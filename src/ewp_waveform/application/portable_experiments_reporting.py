"""Human diagnostics and bounded text-only export for portable experiments."""

from __future__ import annotations

import json
import uuid
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ewp_waveform.application.portable_experiments_state import save, sha

ROOT = Path(__file__).resolve().parents[3]


# Only verbose diagnostic payloads are excerpted. Never truncate result/config
# trees as byte strings: a metric or failure in their middle is still essential.
_VERBOSE = {"stderr", "stdout", "stderr_excerpt", "excerpts", "diagnostic_excerpts"}
_CHECKS = ("transfer", "blur", "prores", "ffv1", "same_build_control")


def _compact_diagnostics(
    value: Any, source: str, pointer: str = "", *, verbose: bool = False
) -> Any:
    """Copy semantics intact, replacing only long log payloads with linked excerpts."""
    if isinstance(value, dict):
        return {
            key: _compact_diagnostics(
                item,
                source,
                pointer + "/" + str(key).replace("~", "~0").replace("/", "~1"),
                verbose=verbose or key in _VERBOSE,
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        # A diagnostic list is one payload; do not retain thousands of short lines.
        if verbose and len(json.dumps(value, ensure_ascii=False)) > 1200:
            value = "\n".join(str(line) for line in value)
        else:
            return [
                _compact_diagnostics(item, source, pointer + f"/{i}", verbose=verbose)
                for i, item in enumerate(value)
            ]
    if verbose and isinstance(value, str) and len(value) > 1200:
        return {
            "excerpt": value[:600] + "\n[DIAGNOSTIC EXCERPT; original retained]\n" + value[-600:],
            "characters": len(value),
            "full_evidence": source + "#" + pointer,
        }
    return value


def _checks(backends: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Only execution checks; paths, bounds, inventory and devices are observations."""
    for name in _CHECKS:
        item = backends.get(name)
        if isinstance(item, dict):
            yield name, item
    controls = backends.get("cpu_controls", {})
    if isinstance(controls, dict):
        for name, item in controls.items():
            if isinstance(item, dict):
                yield "cpu_controls/" + name, item


def _cases(value: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    cases = value.get("cases", {})
    if isinstance(cases, dict):
        for name, item in cases.items():
            if isinstance(item, dict):
                yield name, item
    elif isinstance(cases, list):
        for i, item in enumerate(cases):
            if isinstance(item, dict) and any(
                key in item for key in ("name", "case", "status", "passed")
            ):
                name = str(item.get("name", item.get("case", i)))
                geometry = item.get("geometry")
                if isinstance(geometry, list):
                    name = "x".join(map(str, geometry)) + "/" + name
                yield name, item


def _reason(value: dict[str, Any]) -> str:
    if "ffmpeg_version_and_configuration" in value and value.get("status") != "PASS":
        return (
            "Same-build control failed: observed FFmpeg/ffprobe version/configuration "
            "identities are unavailable or unequal"
        )
    for key in ("reason", "error", "process_error", "explanation", "classification"):
        if value.get(key):
            return str(value[key])
    failures = [
        name + ": " + (_reason(case) or str(case.get("status", "failed")))
        for name, case in _cases(value)
        if case.get("status") not in (None, "PASS", "SUCCEEDED") or case.get("passed") is False
    ]
    if failures:
        return "; ".join(failures)
    if value.get("attempt_failures"):
        return "Failed checks: " + ", ".join(value["attempt_failures"])
    return ""


def diagnostic_bundle(
    run: Path,
    destination: Path,
    *,
    media: Path | None = None,
) -> dict[str, Any]:
    """2MiB text-only packet with intact semantics and linked bounded log excerpts.

    Only the named backend-qualification subtree is read under media. Native
    controls, outputs, arrays, caches and other media directories are never scanned.
    """
    cap, total = 2 * 1024**2, 0
    payload_cap = cap - 128 * 1024  # The same reserved scope budget governs admission/packing.
    critical_name: str | None = None
    members: list[str] = []
    omissions: list[dict[str, Any]] = []
    candidates: list[tuple[Path, str, int, bool]] = []
    # The newest report's semantic snapshot/settings precede bulky duplicated logs
    # and historical reports. Its full JSON/commands remain authoritative on disk.
    snapshots = sorted(
        (run / "reports").glob("report-*-diagnostics.json"),
        key=lambda p: p.stat().st_mtime_ns,
        reverse=True,
    )
    if snapshots:
        snapshot = snapshots[0]
        measurements = snapshot.with_name(
            snapshot.name.replace("report-", "measurements-", 1).replace(
                "-diagnostics.json", ".json"
            )
        )
        if measurements.is_file():
            # Essential totals/settings precede duplicated logs and raw call rows.
            if measurements.stat().st_size > payload_cap:
                raise ValueError(
                    "critical measurements exceed diagnostic packet cap; full file retained: "
                    + str(measurements)
                )
            critical_name = measurements.relative_to(run).as_posix()
            candidates.append((measurements, critical_name, payload_cap, True))
        candidates.extend(
            (p, p.relative_to(run).as_posix(), 256 * 1024, False)
            for p in (
                snapshot,
                snapshot.with_name(snapshot.name.replace("-diagnostics.json", ".md")),
            )
        )
    if (run / "config.json").is_file():
        candidates.append((run / "config.json", "config.json", 32768, False))
    if media is not None:
        qualifier = media / "backend-qualification"
        device = qualifier / "device"
        if device.is_dir():
            candidates.extend(
                (
                    p,
                    "backend-qualification/" + p.relative_to(qualifier).as_posix(),
                    512 * 1024,
                    True,
                )
                for p in sorted(device.rglob("*.json"))
            )
        if qualifier.is_dir():
            candidates.append(
                (
                    qualifier / "qualification.json",
                    "backend-qualification/qualification.json",
                    256 * 1024,
                    False,
                )
            )
            # The small qualifier subtree contains no user controls. JSON device
            # inventory precedes verbose duplicated command/stderr diagnostics.
            for pattern in ("commands.jsonl", "*.stderr", "*.stdout.txt"):
                candidates.extend(
                    (
                        p,
                        "backend-qualification/" + p.relative_to(qualifier).as_posix(),
                        128 * 1024,
                        False,
                    )
                    for p in sorted(qualifier.rglob(pattern))
                )
    excluded = {"python-env", "python-managed", "uv-cache", "cuda-env", "cuda-cache"}
    for path in sorted(run.rglob("*")):
        if excluded.intersection(path.relative_to(run).parts):
            continue
        if path.suffix in (".json", ".jsonl", ".txt", ".md", ".toml", ".stderr"):
            candidates.append((path, path.relative_to(run).as_posix(), 32768, False))
    seen: set[str] = set()
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, name, limit, intact_json in candidates:
            if name in seen or path.is_symlink() or not path.is_file():
                if name == critical_name and name not in members:
                    raise ValueError("critical measurements unavailable; full report retained")
                continue
            seen.add(name)
            size = path.stat().st_size
            if intact_json and size > limit:
                if name == critical_name:
                    raise ValueError("critical measurements exceed diagnostic payload budget")
                omissions.append(
                    {
                        "path": name,
                        "bytes": size,
                        "reason": "device JSON exceeds 512KiB; original retained",
                    }
                )
                continue
            structured = size > limit and path.suffix in (".json", ".jsonl")
            data = b""
            if structured:
                try:
                    uri = path.absolute().as_uri()
                    with path.open(encoding="utf-8") as source:
                        if path.suffix == ".json":
                            compact = _compact_diagnostics(json.load(source), uri)
                            data = json.dumps(compact, ensure_ascii=False).encode()
                        else:
                            # JSONL stays parseable. If the structured prefix itself
                            # reaches the packet cap, disclose that boundary explicitly.
                            chunks = bytearray()
                            for ordinal, line in enumerate(source, 1):
                                compact = _compact_diagnostics(
                                    json.loads(line), uri + f"?line={ordinal}"
                                )
                                row = (json.dumps(compact, ensure_ascii=False) + "\n").encode()
                                if len(chunks) + len(row) > cap - 128 * 1024:
                                    omissions.append(
                                        {
                                            "path": name,
                                            "reason": "structured JSONL prefix ends before line "
                                            + str(ordinal),
                                        }
                                    )
                                    break
                                chunks.extend(row)
                            data = bytes(chunks)
                    omissions.append(
                        {
                            "path": name,
                            "bytes": size,
                            "reason": "structural log compaction; original retained",
                            "full_evidence": uri,
                        }
                    )
                    name = Path(name).with_suffix(".compact" + path.suffix).as_posix()
                except (ValueError, UnicodeError):
                    structured = False  # A damaged/partial log is text, not valid JSON.
            if not structured:
                with path.open("rb") as source:
                    data = source.read(limit)
                    if size > limit:
                        marker = b"\n[DIAGNOSTIC EXCERPT; original retained]\n"
                        half = (limit - len(marker)) // 2
                        source.seek(size - half)
                        data = data[:half] + marker + source.read(half)
                        omissions.append(
                            {
                                "path": name,
                                "bytes": size,
                                "reason": "head/tail excerpt",
                                "full_evidence": path.absolute().as_uri(),
                            }
                        )
                        if path.suffix in (".json", ".jsonl"):
                            name += ".excerpt.txt"
            if total + len(data) > payload_cap:
                if name == critical_name:
                    raise ValueError("critical measurements cannot fit diagnostic payload budget")
                omissions.append(
                    {
                        "path": name,
                        "bytes": size,
                        "reason": "2MiB packet cap",
                        "full_evidence": path.absolute().as_uri(),
                    }
                )
                continue
            archive.writestr(name, data)
            total += len(data)
            members.append(name)
        if critical_name is not None and critical_name not in members:
            raise ValueError("critical measurements missing from diagnostic packet")
        manifest: dict[str, Any] = {
            "scope": "text only; latest semantic report and complete device JSON <=512KiB "
            "prioritized; long embedded logs structurally excerpted; no native media",
            "omissions": omissions,
            "excluded_subtrees": sorted(excluded),
            "media_scope": "backend-qualification/device and qualification JSON, "
            "command and stderr/stdout text only",
        }
        data = json.dumps(manifest, indent=2).encode()
        # Preserve valid JSON even for unusually large retained metadata trees.
        dropped = 0
        while len(data) > cap - total - 1024:
            omissions.pop()
            dropped += 1
            manifest["additional_omissions_not_enumerated"] = dropped
            data = json.dumps(manifest, indent=2).encode()
        archive.writestr("BUNDLE-SCOPE.json", data)
        members.append("BUNDLE-SCOPE.json")
        total += len(data)
        scope = (
            "Text/JSON only; 2MiB uncompressed cap. Original run is authoritative. "
            "Only targeted qualifier text is included from media. No binary media.\n"
        )
        archive.writestr("BUNDLE-SCOPE.txt", scope)
        members.append("BUNDLE-SCOPE.txt")
        total += len(scope.encode())
    return {"path": str(destination), "members": members, "uncompressed_bytes": total}


def pair_statistics(results: dict[str, Any]) -> list[dict[str, Any]]:
    """Descriptive paired observations, never a ratio between unrelated scopes."""
    import math
    import statistics

    groups: dict[str, dict[int, dict[str, Any]]] = {}
    for name, result in results.items():
        pair = result.get("pair")
        if pair:
            groups.setdefault(pair["id"], {}).setdefault(pair["repeat"], {})[pair["side"]] = (
                name,
                result,
            )
    summaries = []
    for group, repeats in groups.items():
        samples: dict[str, list[float]] = {"A": [], "B": []}
        excluded: list[dict[str, Any]] = []
        orders, comparison = [], ""
        for ordinal, sides in sorted(repeats.items()):
            if set(sides) != {"A", "B"}:
                excluded.append({"repeat": ordinal, "reason": "missing pair member"})
                continue
            a, b = sides["A"][1], sides["B"][1]
            comparison = a["pair"]["comparison"]
            orders.append(a["pair"]["order"])
            reason = None
            for r in (a, b):
                wall = r.get("wall_seconds")
                if (
                    r.get("status") != "SUCCEEDED"
                    or r.get("actual_action") != "PROCESS"
                    or r.get("throughput_fresh") is not True
                    or r.get("evidence_status") == "SALVAGED_UNVERIFIED"
                    or r.get("validation", {}).get("passed") is not True
                    or not isinstance(wall, (int, float))
                    or not math.isfinite(wall)
                    or wall <= 0
                ):
                    reason = "failed, unvalidated, reused or unavailable measurement"
            for key in ("timer", "route", "workload", "execution_settings"):
                if not a.get(key) or a.get(key) != b.get(key):
                    reason = "unmatched " + key
            ac, bc = a.get("experimental_controls", {}), b.get("experimental_controls", {})
            changed_controls = {k for k in ac.keys() | bc.keys() if ac.get(k) != bc.get(k)}
            allowed_controls = {
                "opt-fir-host-reuse": {"output_mode"},
                "opt-fir-device-rgba": {"output_mode"},
                "opt-fir-device-alpha8": {"output_mode"},
                "opt-fir-batch2": {"batch_size"},
                "opt-fir-ordinary": {"timing_mode"},
                "opt-crop-output": {"control"},
                "opt-crop-working": {"control"},
                "opt-direct-ffv1": {"codec"},
                "opt-ffv1-encoder": {"encoder_threads"},
                "opt-prores-filter": {"filter_threads"},
                "opt-prores-async": {"async_depth"},
                "opt-prores-lut": {"finish_lut"},
            }.get(group, set())
            if changed_controls - allowed_controls:
                reason = "undeclared experimental control changes"
            frames = a.get("validation", {}).get("frames")
            if (
                type(frames) is not int
                or frames <= 0
                or frames != b.get("validation", {}).get("frames")
            ):
                reason = "unmatched or unavailable validated frame count"
            for key in ("source", "reference"):
                if (a.get(key) or b.get(key)) and a.get(key) != b.get(key):
                    reason = "unmatched " + key
            custom = a.get("original_raster_sha256") or b.get("original_raster_sha256")
            if custom and (
                not a.get("original_raster_sha256")
                or a.get("original_raster_sha256") != b.get("original_raster_sha256")
                or a.get("spec") != b.get("spec")
                or a.get("effective_preset") != b.get("effective_preset")
            ):
                reason = "original raster/config mismatch"
            if reason:
                excluded.append({"repeat": ordinal, "reason": reason})
                continue
            for side, r in (("A", a), ("B", b)):
                samples[side].append(r["wall_seconds"])
        stats = {
            side: {
                "n": len(values),
                "median_seconds": statistics.median(values) if values else None,
                "min_seconds": min(values) if values else None,
                "max_seconds": max(values) if values else None,
            }
            for side, values in samples.items()
        }
        summaries.append(
            {
                "id": group,
                "comparison": comparison,
                "orders": orders,
                "validated_paired_n": len(samples["A"]),
                "sides": stats,
                "excluded": excluded,
                "speedup": None,
                "claim": "descriptive only; no speedup or visual/NLE acceptance",
            }
        )
    return summaries


def report(
    run: Path,
    status: str,
    error: str | None,
    config: dict[str, Any] | None,
    results: dict[str, Any],
    *,
    reused: bool = False,
    fresh_names: set[str] | None = None,
) -> Path:
    folder = run / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex[:12]
    path = folder / ("report-" + token + ".md")
    fresh_names = set(results) if fresh_names is None and not reused else (fresh_names or set())
    pairs = pair_statistics(results)
    value = {
        "status": status,
        "error": error,
        "results": results,
        "pair_statistics": pairs,
        "result_use": {name: "FRESH" if name in fresh_names else "REUSED" for name in results},
        "reused": reused,
        "fresh_measurements_this_invocation": any(
            name in fresh_names
            and result.get("actual_action") == "PROCESS"
            and result.get("status") == "SUCCEEDED"
            for name, result in results.items()
        ),
        "config": config,
        "visual": "PENDING",
        "studio": "PENDING",
        "promotion": "NOT_APPROVED",
    }
    save(path.with_suffix(".json"), value)
    from ewp_waveform.application.portable_experiments_metrics import compact_metrics

    save(
        path.with_name("measurements-" + token + ".json"),
        {
            "status": status,
            "error": error,
            "results": compact_metrics(results),
            "pair_statistics": pairs,
            "result_use": value["result_use"],
            "config": compact_metrics(
                {
                    k: v
                    for k, v in (config or {}).items()
                    if k
                    in {
                        "source",
                        "python",
                        "cuda_python",
                        "selected",
                        "installed",
                        "audio",
                        "limits",
                        "repeats",
                        "optimization",
                        "visual_overrides",
                    }
                }
            ),
            "scope": "critical compact comparison data; "
            "ordered raw calls/commands remain in full JSON",
        },
    )
    compact_path = path.with_name(path.stem + "-diagnostics.json")
    save(compact_path, _compact_diagnostics(value, path.with_suffix(".json").as_uri()))
    commands = {
        name: {
            "worker": result.get("command"),
            "commands": result.get("commands", []),
            "backend_commands": result.get("backends", {}).get("commands", []),
            "diagnostics": result.get("diagnostic_excerpts", {}),
        }
        for name, result in results.items()
    }
    appendix = path.with_name(path.stem + "-commands.json")
    save(appendix, commands)

    def clean(text: Any, limit: int = 180) -> str:
        return str(text).replace("|", "/").replace("\n", " ")[:limit]

    lines = [
        "# Portable waveform experiments",
        "",
        f"Status: **{status}**",
        "",
        f"Run: `{run}`",
        "",
        "Visual / native NLE acceptance: PENDING. Promotion: NOT_APPROVED.",
        "",
        "No speedup claimed. Installed/selected tools are a build contrast, "
        "not isolated GPU acceleration. "
        "Stock service versus the custom FIR pipeline also changes wrapper/publication scope.",
        "",
        "## Summary",
        "",
        "Fresh rendered measurements this invocation: "
        f"**{value['fresh_measurements_this_invocation']}**. "
        "Reused records are retained observations, not new measurements.",
        "",
    ]
    if error:
        lines += [f"Failure / refusal: {clean(error, 1000)}", ""]
    if status == "FAILED_STORAGE_OBSERVATION":
        lines += [
            "Storage accounting could not obtain a complete observation. This is an "
            "infrastructure failure, not evidence of disk-capacity or budget exhaustion. "
            "Dispatch is stopped; attempts and incomplete samples are retained. "
            "A new bounded setup/preflight can be used after reconciliation; do not resume "
            "or rewrite the failed run.",
            "",
        ]
    if config and config.get("cuda_error"):
        lines += [
            "Optional CUDA environment/setup failed; "
            "independent CPU/Vulkan controls remain admitted:",
            "",
            "```text",
            str(config["cuda_error"])[-1200:].replace("```", "'''"),
            "```",
            "",
            "This failed attempt is retained; a fixed/changed environment requires a new campaign.",
            "",
        ]
    first_diagnostic = None
    for result in results.values():
        records = [
            *result.get("backends", {}).get("commands", []),
            *result.get("commands", []),
            result.get("command"),
        ]
        for command in records:
            if not isinstance(command, dict):
                continue
            if command.get("returncode") not in (None, 0) or command.get("error"):
                diagnostic = command.get("excerpts") or command.get("stderr")
                if diagnostic:
                    first_diagnostic = (
                        "\n".join(diagnostic) if isinstance(diagnostic, list) else diagnostic
                    )
                    break
        if first_diagnostic:
            break
    if first_diagnostic:
        lines += [
            "First concrete command failure (full diagnostics in appendix):",
            "",
            "```text",
            str(first_diagnostic)[-1200:].replace("```", "'''"),
            "```",
            "",
        ]
    if config:
        lines += [
            f"Selected Python: `{config['python']}`",
            "",
            f"Source content SHA-256: `{config['source']['sha256']}`",
            "",
            f"Media: `{config['media']}` (excluded from diagnostic bundle).",
            "",
            f"Frozen --repeats: **{config.get('repeats', 2)}**; AB/BA on speech shortlist "
            "(six frames in smoke). Other baseline intervals run once.",
            "",
            "Mode: "
            + (
                "preflight only; no waveform rendering or throughput measurements."
                if config.get("preflight_only")
                else "CPU six-frame usability validation; no full/pool2/GPU claims."
                if config["smoke"]
                else "short-first production recipe."
            ),
            "",
            "Selected scope: "
            + "; ".join(
                f"{key}={config.get(key, 'not recorded')}"
                for key in (
                    "preflight_only",
                    "smoke",
                    "production32",
                    "full",
                    "reference_only",
                    "cuda",
                    "optimize",
                )
            )
            + ".",
            "",
            "Selected limits (not resource observations): `"
            + json.dumps(config.get("limits", {}), sort_keys=True)
            + "`.",
            "",
        ]
    lines += [
        "## Results",
        "",
        "| Step | Status | Wall s | Validation | Use / reason |",
        "|---|---|---:|---|---|",
    ]
    for name, result in results.items():
        if name.endswith("-views"):
            continue
        wall = result.get("wall_seconds")
        wall_text = f"{wall:.3f}" if isinstance(wall, (float, int)) else "—"
        valid = result.get("validation", {})
        validation = f"{valid.get('frames')} frames PASS" if valid.get("passed") else "—"
        reason = _reason(result)
        use = "FRESH" if name in fresh_names else "REUSED"
        if result.get("evidence_status") == "SALVAGED_UNVERIFIED":
            use += "/SALVAGED_UNVERIFIED"
        for key in ("failure_scope", "independent_dispatch_allowed"):
            if key in result:
                use += f"; {key}={clean(result[key])}"
        lines.append(
            f"| {clean(name)} | {clean(result.get('status', 'UNKNOWN'))} | {wall_text} | "
            f"{validation} | {use}; {clean(reason or '')} |"
        )
    if config and config.get("optimize"):
        lines += [
            "",
            "## Optimization shortlist",
            "",
            "One speech interval (six synthetic frames in smoke); stock service is a separate "
            "wrapper control. Codec/thread pairs run the real serial production fixed pipeline "
            "with identical cache-disabled analysis and raster hashing. Native FFV1 MKV is "
            "direct output, not a ProRes transcode; Resolve support remains unverified.",
            "",
            "Optional shared-master FFV1 prefix diagnostics are different: only6/60 frames, "
            "one CPU/GPU observation each, at most60s per worker including validation. "
            "They include process startup, MOV decode/conversion and encoding; differences "
            "across lengths are not pure startup or waveform render savings. Historical "
            "240-frame operator observations remain separate and unchanged.",
            "",
            "Encoder and complex-filter thread settings change individually; omitted options "
            "mean FFmpeg defaults, not observed runtime counts. Inclusive phase spans are "
            "non-additive; feed is blocking write time, not encoder CPU. Cold worker envelopes "
            "include launch/import overhead; validation/views remain outside pipeline timers.",
            "",
            "| Step | Encoder / filter / async requested | Cold worker s "
            "| Generator / feed / wait s | External validation s |",
            "|---|---|---:|---|---:|",
        ]
        for name, result in results.items():
            if not result.get("output"):
                continue
            phase = result.get("phase_metrics", {})
            seconds = phase.get("seconds", {})
            settings = result.get("experimental_settings", {})
            lines.append(
                f"| {clean(name)} | "
                + " / ".join(
                    str(settings.get(k))
                    for k in ("encoder_threads", "filter_threads", "async_depth")
                )
                + " | "
                + clean(result.get("cold_process_wall_seconds"))
                + " | "
                + " / ".join(
                    clean(seconds.get(k)) for k in ("generator", "ffmpeg_feed", "ffmpeg_wait")
                )
                + " | "
                + clean(result.get("external_verification_seconds"))
                + " |"
            )
    lines += [
        "",
        "## Independent qualification",
        "",
        "Each optional backend gate precedes its timed workloads; Torch gates have a 120s maximum. "
        "Transfer-only is a compute-free byte roundtrip, not a CUDA finishing claim.",
        "",
    ]
    for name, result in results.items():
        if "qualif" not in name:
            continue
        lines += [f"### {clean(name)}", ""]
        backends = result.get("backends")
        if isinstance(backends, dict):
            lines += [
                "Observations — not execution qualification: tool paths/hashes, component "
                "inventory and loader/device enumeration. "
                "A successful listing is not a runtime PASS.",
                "",
                "- Tools: `" + clean(json.dumps(backends.get("tool_paths", {})), 1000) + "`",
                "- Selected qualification bounds: `"
                + clean(json.dumps(backends.get("bounds", {})), 1000)
                + "`",
                "- Scope: " + clean(backends.get("qualification_scope", "not recorded"), 1000),
                "",
            ]
            checks = list(_checks(backends))
        else:
            checks = [(name, result)]
        lines += [
            "Actual checks (a successful process can still fail its numerical oracle):",
            "",
            "| Check / case | Status | Failure / scope | Metrics / tolerance |",
            "|---|---|---|---|",
        ]
        for backend, item in checks:
            rows = [
                (backend, item),
                *((backend + "/" + case_name, case) for case_name, case in _cases(item)),
            ]
            for label, case in rows:
                check_status = case.get("status")
                if check_status is None:
                    check_status = (
                        "PASS"
                        if case.get("passed") is True
                        else "FAILED"
                        if case.get("passed") is False
                        else "OBSERVED (no per-case verdict)"
                    )
                detail = _reason(case) or case.get("scope") or case.get("claim") or ""
                metrics = {
                    key: val
                    for key, val in case.items()
                    if key.endswith("_oracle")
                    or key in ("metrics", "tolerance", "checks", "timing", "geometry")
                    or ("error" in key and isinstance(val, (float, int)))
                    or key.endswith("_equal")
                }
                # Metrics and fixed tolerances are never character-truncated.
                metric_text = json.dumps(metrics, ensure_ascii=False) if metrics else "—"
                evidence = case.get("command", {}).get("stderr_path")
                detail_text = clean(detail, 1000)
                if evidence:
                    detail_text += f"; [full stderr]({Path(evidence).absolute().as_uri()})"
                lines.append(
                    f"| {clean(label)} | {clean(check_status)} | {detail_text} | "
                    + metric_text.replace("|", "/").replace("\n", " ")
                    + " |"
                )
        lines.append("")
    lines += [
        "",
        "## Counterbalanced descriptive observations",
        "",
        "Only complete fresh validated pairs with identical input/config/timer/route "
        "enter these statistics. "
        "Custom pairs require identical original-raster SHA-256 and finishing geometry. "
        "n is retained pairs, not fresh work on resume. Ranges are min-max, "
        "not confidence intervals.",
        "",
        "| Pair | Orders | Paired n | A median [range] s | B median [range] s | "
        "Comparison / exclusions |",
        "|---|---|---:|---|---|---|",
    ]

    def fmt(stats: dict[str, Any]) -> str:
        if not stats["n"]:
            return "unavailable"
        return (
            f"{stats['median_seconds']:.3f} [{stats['min_seconds']:.3f}-{stats['max_seconds']:.3f}]"
        )

    for pair in pairs:
        reasons = "; ".join(sorted({item["reason"] for item in pair["excluded"]}))
        lines.append(
            f"| {clean(pair['id'])} | {','.join(pair['orders'])} | {pair['validated_paired_n']} | "
            f"{fmt(pair['sides']['A'])} | {fmt(pair['sides']['B'])} | "
            f"{clean(pair['comparison'])}; {clean(reasons)} |"
        )
    lines += [
        "",
        "## Distinct useful viewing outputs",
        "",
        "Native transparent files retained. MP4s are opaque straight-alpha views, not masters. "
        "Exact decoded-RGBA duplicates share views; lossless MKV uses the existing equal CPU MOV "
        "for comparison, not a duplicate transcode. FFV1 is not NLE acceptance.",
        "",
    ]
    navigation: dict[str, dict[str, Any]] = {}
    for name, result in results.items():
        if result.get("status") != "SUCCEEDED":
            continue
        if result.get("output"):
            output = Path(result["output"])
            if output.is_file():
                fingerprint = sha(output)
                item = navigation.setdefault(
                    fingerprint, {"path": output, "role": "NATIVE", "aliases": []}
                )
                item["aliases"].append(name)
        for view in result.get("views", []):
            output = Path(view["path"])
            if output.is_file():
                fingerprint = sha(output)
                item = navigation.setdefault(
                    fingerprint, {"path": output, "role": view["role"], "aliases": []}
                )
                item["aliases"].append(name)
    for digest, item in navigation.items():
        uri = item["path"].absolute().as_uri()
        aliases = ", ".join(item["aliases"])
        lines.append(
            f"- [{clean(item['role'])}]({uri}) — {clean(aliases, 500)}; SHA-256 `{digest}`"
        )
    lines += [
        "",
        "## Appendix / exact evidence",
        "",
        f"- [Compact complete semantics / bounded diagnostic excerpts]({compact_path.as_uri()})",
        f"- [Structured report / settings / diagnostics]({path.with_suffix('.json').as_uri()})",
        f"- [Exact worker and FFmpeg argv, exit status and stderr]({appendix.as_uri()})",
        "- Original environment, runtime fingerprints and setup receipts are in structured config; "
        "all per-step request/result/command logs remain under the retained run.",
        "- Historical WSL and VM.1 references are operator context, not local remeasurement: "
        "`examples/experiments/operator-wsl-history.json`, `vm1-current-reference.json`.",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    bundle = diagnostic_bundle(
        run,
        folder / ("diagnostics-" + token + ".zip"),
        media=Path(config["media"]) if config else None,
    )
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"\nSmall text-only diagnostics: `{bundle['path']}`. No media included.\n")
    return path
