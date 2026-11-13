"""Human diagnostics and bounded text-only export for portable experiments."""

from __future__ import annotations

import json
import uuid
import zipfile
from pathlib import Path
from typing import Any

from ewp_waveform.application.portable_experiments_state import load, save, sha

ROOT = Path(__file__).resolve().parents[3]


def diagnostic_bundle(run: Path, destination: Path) -> dict[str, Any]:
    """Small text/JSON only. No media, arrays, raw video, or database payloads."""
    cap, total, members = 2 * 1024**2, 0, []
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(run.rglob("*")):
            if any(
                part in ("python-env", "python-managed", "uv-cache", "cuda-env", "cuda-cache")
                for part in path.relative_to(run).parts
            ):
                continue
            if (
                path.is_symlink()
                or not path.is_file()
                or path.suffix not in (".json", ".jsonl", ".txt", ".md", ".toml", ".stderr")
            ):
                continue
            name = path.relative_to(run).as_posix()
            size = path.stat().st_size
            with path.open("rb") as source:
                data = source.read(32768)
                if size > 32768:
                    source.seek(size - 16384)
                    data = (
                        data[:16384]
                        + b"\n[DIAGNOSTIC BUNDLE EXCERPT; see original for full bytes]\n"
                        + source.read(16384)
                    )
                    if path.suffix in (".json", ".jsonl"):
                        name += ".excerpt.txt"  # Never disguise truncated data as valid JSON.
            if total + len(data) > cap - 1024:
                continue
            archive.writestr(name, data)
            total += len(data)
            members.append(name)
        archive.writestr(
            "BUNDLE-SCOPE.txt",
            "Text/JSON excerpts only; 2MiB uncompressed cap. "
            "Original retained run is authoritative. No media included.\n",
        )
    return {"path": str(destination), "members": members, "uncompressed_bytes": total}


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
    value = {
        "status": status,
        "error": error,
        "results": results,
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
    lines = [
        "# Portable waveform experiments",
        "",
        f"Status: **{status}**",
        "",
        f"Run: `{run}`",
        "",
        "Visual / native NLE acceptance: PENDING. Promotion: NOT_APPROVED.",
        "",
        "No speedup claimed. Installed-versus-selected tools are a **build contrast**, "
        "not isolated GPU acceleration. Reused records are not new measurements.",
        "",
        "Timers include only their stated scopes; serial short renders are not proof "
        "of the production32 multiprocessing route. "
        "Quiet selection is observed or explicitly unverified.",
        "",
    ]
    if error:
        lines += ["## Failure / refusal", "", "```text", error.replace("```", "'''"), "```", ""]
    for title, filename in (
        ("Operator-reported WSL history (not locally remeasured)", "operator-wsl-history.json"),
        (
            "VM.1 environment reference (different source; not retimed)",
            "vm1-current-reference.json",
        ),
    ):
        reference = ROOT / "examples/experiments" / filename
        if reference.is_file():
            lines += [
                f"## {title}",
                "",
                "```json",
                reference.read_text(encoding="utf-8").replace("```", "~~~"),
                "```",
                "",
            ]
    original_file = (
        Path(config["original"]["path"]) if config else run / "original-environment.json"
    )
    if original_file.is_file():
        lines += [
            "## Original environment before selection",
            "",
            "```json",
            json.dumps(load(original_file), indent=2).replace("```", "~~~"),
            "```",
            "",
        ]
    observations_file = original_file.with_name("original-observations.json")
    if observations_file.is_file():
        lines += [
            "## Original tool/device observations before selection",
            "",
            "```json",
            observations_file.read_text(encoding="utf-8").replace("```", "~~~"),
            "```",
            "",
        ]
    if config:
        lines += [
            f"Selected Python: `{config['python']}`",
            "",
            f"Source content SHA-256: `{config['source']['sha256']}`",
            "",
            f"Media: `{config['media']}` (not in diagnostic bundle).",
            "",
            "Frozen tool/runtime selections:",
            "",
            "```json",
            json.dumps(
                {
                    key: config.get(key)
                    for key in (
                        "installed",
                        "selected",
                        "cuda_setup",
                        "cuda_error",
                        "tool_acquisition",
                    )
                },
                indent=2,
            ).replace("```", "~~~"),
            "```",
            "",
            "Mode: "
            + (
                "CPU smoke (six frames; no full/pool2/GPU claims)."
                if config["smoke"]
                else "short-first production recipe."
            ),
            "",
        ]
    previews: dict[str, dict[str, Any]] = {}
    for name, result in results.items():
        lines += [f"## {name}: {result.get('status', 'UNKNOWN')}", ""]
        if result.get("workload"):
            lines += ["Workload: `" + json.dumps(result["workload"], sort_keys=True) + "`", ""]
        for key in ("reason", "error", "process_error", "route", "timer"):
            if result.get(key):
                lines += [f"{key}: {result[key]}", ""]
        if result.get("wall_seconds") is not None:
            lines += [
                f"Retained wall seconds: {result['wall_seconds']:.6f}; "
                f"fresh this invocation: {name in fresh_names}.",
                "",
            ]
        # Full backend JSON embeds concrete independent reasons/commands/stderr,
        # not a generic label that sends an operator hunting through raw files.
        if name == "backend-qualification":
            lines += [
                "```json",
                json.dumps(result.get("backends", result), indent=2).replace("```", "'''"),
                "```",
                "",
            ]
        for command in [result.get("command"), *result.get("commands", [])]:
            if not isinstance(command, dict):
                continue
            lines += [
                "Exact command (argv, no shell):",
                "",
                "```json",
                json.dumps(command.get("argv", [])),
                "```",
                "",
                f"Exit: {command.get('returncode')}; error: {command.get('error')}",
                "",
            ]
            if command.get("stderr"):
                lines += [
                    "stderr excerpt:",
                    "",
                    "```text",
                    command["stderr"][-4000:].replace("```", "'''"),
                    "```",
                    "",
                ]
        for diagnostic_path, excerpt in result.get("diagnostic_excerpts", {}).items():
            if excerpt:
                lines += [
                    f"Retained stderr: `{diagnostic_path}`",
                    "",
                    "```text",
                    excerpt.replace("```", "~~~"),
                    "```",
                    "",
                ]
        if result.get("output") and result.get("status") == "SUCCEEDED":
            output = Path(result["output"])
            if output.is_file():
                fingerprint = sha(output)
                item = previews.setdefault(fingerprint, {"path": str(output), "aliases": []})
                item["aliases"].append(name)
                lines += [f"Native transparent output: `{output}`; SHA-256 `{fingerprint}`.", ""]
    lines += [
        "## Deduplicated native preview navigation",
        "",
        "Equal file hashes grouped; original artifacts retained. MOVs are native transparent "
        "short previews, not opaque MP4 surrogates. MKV is an FFV1 experiment, not NLE acceptance.",
        "",
    ]
    for digest, item in previews.items():
        uri = Path(item["path"]).absolute().as_uri()
        lines += [f"- [Native preview]({uri}) — {', '.join(item['aliases'])}; `{digest}`"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    bundle = diagnostic_bundle(run, folder / ("diagnostics-" + token + ".zip"))
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"\nSmall text-only diagnostics: `{bundle['path']}`. No media included.\n")
    return path
