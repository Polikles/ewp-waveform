"""Human diagnostics and bounded text-only export for portable experiments."""

from __future__ import annotations

import uuid
import zipfile
from pathlib import Path
from typing import Any

from ewp_waveform.application.portable_experiments_state import save, sha

ROOT = Path(__file__).resolve().parents[3]


def diagnostic_bundle(
    run: Path,
    destination: Path,
    *,
    media: Path | None = None,
) -> dict[str, Any]:
    """2MiB text-only return packet, prioritizing complete Vulkan device JSON.

    Only the named backend-qualification subtree is read under media. Native
    controls, outputs, arrays, caches and other media directories are never scanned.
    """
    import json

    cap, total = 2 * 1024**2, 0
    members: list[str] = []
    omissions: list[dict[str, Any]] = []
    candidates: list[tuple[Path, str, int, bool]] = []
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
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, name, limit, intact_json in candidates:
            if path.is_symlink() or not path.is_file():
                continue
            size = path.stat().st_size
            if intact_json and size > limit:
                omissions.append(
                    {
                        "path": name,
                        "bytes": size,
                        "reason": "device JSON exceeds 512KiB; original retained",
                    }
                )
                continue
            with path.open("rb") as source:
                data = source.read(limit)
                if size > limit:
                    source.seek(size - limit // 2)
                    data = (
                        data[: limit // 2]
                        + b"\n[DIAGNOSTIC EXCERPT; original retained]\n"
                        + source.read(limit // 2)
                    )
                    omissions.append({"path": name, "bytes": size, "reason": "head/tail excerpt"})
                    if path.suffix in (".json", ".jsonl"):
                        name += ".excerpt.txt"
            if total + len(data) > cap - 128 * 1024:
                omissions.append({"path": name, "bytes": size, "reason": "2MiB packet cap"})
                continue
            archive.writestr(name, data)
            total += len(data)
            members.append(name)
        manifest: dict[str, Any] = {
            "scope": "text only; complete device JSON <=512KiB prioritized; no native media",
            "omissions": omissions,
            "excluded_subtrees": sorted(excluded),
            "media_scope": "backend-qualification/device JSON, command and stderr/stdout text only",
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
    commands = {
        name: {
            "worker": result.get("command"),
            "commands": result.get("commands", []),
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
        f"Fresh this invocation: **{value['fresh_measurements_this_invocation']}**. "
        "Reused records are retained observations, not new measurements.",
        "",
    ]
    if error:
        lines += [f"Failure / refusal: {clean(error, 1000)}", ""]
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
                "CPU six-frame usability validation; no full/pool2/GPU claims."
                if config["smoke"]
                else "short-first production recipe."
            ),
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
        reason = result.get("reason") or result.get("error") or result.get("process_error")
        use = "FRESH" if name in fresh_names else "REUSED"
        if result.get("evidence_status") == "SALVAGED_UNVERIFIED":
            use += "/SALVAGED_UNVERIFIED"
        lines.append(
            f"| {clean(name)} | {clean(result.get('status', 'UNKNOWN'))} | {wall_text} | "
            f"{validation} | {use}; {clean(reason or '')} |"
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
        backends = result.get("backends")
        if isinstance(backends, dict):
            for backend, item in backends.items():
                if isinstance(item, dict):
                    detail = item.get("reason") or item.get("error") or item.get("classification")
                    lines.append(
                        f"- {backend}: **{clean(item.get('status', 'UNKNOWN'))}** — "
                        f"{clean(detail or '')}"
                    )
        else:
            lines.append(
                f"- {name}: **{clean(result.get('status'))}** — "
                f"{clean(result.get('scope') or result.get('error') or result.get('claim') or '')}"
            )
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
