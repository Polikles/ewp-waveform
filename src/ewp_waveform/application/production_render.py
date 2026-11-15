"""Reuse-only launcher for the ordinary full-file CPU refined-ribbon CLI.

Stdlib bootstrap only. Rendering stays behind the public CLI/application service;
there are no experimental adapters, dependency installers, or recovery changes.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ewp_waveform.application.portable_experiments_dependencies import (
    prepared_environment,
    prepared_ffmpeg_root,
    require_process_safe,
)
from ewp_waveform.application.portable_experiments_process import run_command
from ewp_waveform.application.portable_experiments_state import (
    check_budget,
    environment_details,
    identity,
    outside_git,
    save,
    verify,
)

ROOT = Path(__file__).resolve().parents[3]
DRIVER = ROOT / "scripts/render_refined_ribbon.py"
PRESET = ROOT / "presets/iuris-ribbon-refined-production.toml"
PERFORMANCE = ROOT / "performance/ribbon-lut.toml"
CONFIG = ROOT / "examples/production/refined-ribbon.toml"
PREPARATIONS = Path.home() / ".local/state/ewp-portable-experiments"
GIB = 1024**3


def child_environment(media: Path) -> dict[str, str]:
    """Use current source and private scratch, without activating any environment."""
    env = {key: value for key, value in os.environ.items() if key != "PYTHONHOME"}
    env.update(
        PYTHONPATH=str(ROOT / "src"),
        PYTHONDONTWRITEBYTECODE="1",
        TMPDIR=str(media / "tmp"),
        TMP=str(media / "tmp"),
        TEMP=str(media / "tmp"),
    )
    return env


def cli_command(python: Path, audio: Path, media: Path, performance: Path) -> list[str]:
    """Exactly one ordinary full-file render; no --full campaign or clip bounds."""
    return [
        str(python),
        "-m",
        "ewp_waveform",
        "render",
        str(audio),
        "--config",
        str(CONFIG),
        "--preset",
        str(PRESET),
        "--performance",
        str(performance),
        "--format",
        "prores4444",
        "--output-dir",
        str(media / "output"),
    ]


def performance_text(media: Path) -> str:
    # Keep all committed serial/LUT policies; change only scratch placement.
    return PERFORMANCE.read_text(encoding="utf-8").replace(
        "[workdirs]", "[workdirs]\nroot = " + json.dumps((media / "work").as_posix())
    )


def publication_summary(output: Path) -> dict[str, Any]:
    """Read back the ordinary service's published schema-valid result and asset."""
    from ewp_waveform.application.results import result_payload_errors

    results = list(output.glob("*/*_results.json"))
    if len(results) != 1:
        raise ValueError(f"expected exactly one published result, observed {len(results)}")
    payload = json.loads(results[0].read_text(encoding="utf-8"))
    errors = result_payload_errors(payload)
    if errors or payload["job"]["status"] != "SUCCEEDED":
        raise ValueError(f"ordinary CLI publication did not succeed: {errors}: {payload['job']}")
    outputs = payload["outputs"]
    if len(outputs) != 1 or outputs[0]["format"] != "prores4444":
        raise ValueError("expected one published ProRes MOV")
    mov = Path(outputs[0]["path"])
    if not mov.resolve().is_relative_to(output.resolve()) or not mov.is_file():
        raise ValueError("published asset missing or outside owned output")
    diagnostic = payload["performance"]["extras"]["ribbon_finish_lut"]
    if diagnostic["status"] != "succeeded" or not diagnostic["qualification"]["passed"]:
        raise ValueError("per-encode CPU LUT qualification did not pass")
    if payload["analysis"]["encode_workers"] != 1:
        raise ValueError("ordinary production render was not serial")
    return {
        "status": "SUCCEEDED",
        "result_json": str(results[0]),
        "output": identity(mov),
        "lut_qualified": True,
        "encode_workers": 1,
        "scope": "ordinary service validated/published; no new performance or NLE qualification",
    }


def select_tools(
    explicit_ffmpeg: Path | None,
    explicit_ffprobe: Path | None,
    preparations: Path,
    store: Path,
) -> tuple[Path, Path]:
    """Prefer retained pinned Windows tools; never acquire or repair anything."""
    if bool(explicit_ffmpeg) != bool(explicit_ffprobe):
        raise ValueError("supply both --ffmpeg and --ffprobe, or neither")
    if explicit_ffmpeg is not None and explicit_ffprobe is not None:
        pair = explicit_ffmpeg, explicit_ffprobe
    elif os.name == "nt":
        from ewp_waveform.ffmpeg.portable_tools import read_lock, verify_install

        tool_lock = ROOT / "src/ewp_waveform/ffmpeg/portable_ffmpeg_lock.json"
        base = prepared_ffmpeg_root(
            preparations, store / "ffmpeg" / identity(tool_lock)["sha256"], []
        )
        directory = base / read_lock()["archive_root"]
        if directory.exists():
            info = verify_install(directory)
            pair = Path(info["ffmpeg"]), Path(info["ffprobe"])
        else:
            pair = Path(shutil.which("ffmpeg") or ""), Path(shutil.which("ffprobe") or "")
    else:
        pair = Path(shutil.which("ffmpeg") or ""), Path(shutil.which("ffprobe") or "")
    ffmpeg, ffprobe = (p.expanduser().absolute() for p in pair)
    expected = ("ffmpeg.exe", "ffprobe.exe") if os.name == "nt" else ("ffmpeg", "ffprobe")
    if (
        not ffmpeg.is_file()
        or not ffprobe.is_file()
        or (ffmpeg.name.lower(), ffprobe.name.lower()) != expected
        or ffmpeg.parent.resolve() != ffprobe.parent.resolve()
    ):
        raise ValueError(
            "existing same-bin ffmpeg/ffprobe required; supply --ffmpeg PATH --ffprobe PATH; "
            "no install/download attempted"
        )
    return ffmpeg, ffprobe


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--audio", type=Path, required=True, help="one file; rendered in full")
    result.add_argument("--python", type=Path, help="existing locked Python 3.12 (never installed)")
    result.add_argument("--ffmpeg", type=Path)
    result.add_argument("--ffprobe", type=Path)
    result.add_argument("--preparations-root", type=Path, default=PREPARATIONS)
    result.add_argument("--managed-root", type=Path, help="existing preparation registry/tools")
    result.add_argument(
        "--output-root", type=Path, help="must be NEW; default ~/Videos/ewp-waveform/ID"
    )
    result.add_argument("--evidence-root", type=Path, help="must be NEW; default OUTPUT_ROOT/logs")
    result.add_argument("--max-growth-gib", type=float, default=8.0)
    result.add_argument("--reserve-gib", type=float, default=10.0)
    result.add_argument("--timeout-seconds", type=float, default=86400.0)
    return result


def main(argv: list[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list == ["--_environment"]:
        print(json.dumps(environment_details(ROOT)))
        return 0
    if len(args_list) == 2 and args_list[0] == "--_verify":
        print(json.dumps(publication_summary(Path(args_list[1]))))
        return 0
    args = parser().parse_args(args_list)
    failure_root: Path | None = None
    try:
        for name in ("max_growth_gib", "reserve_gib", "timeout_seconds"):
            value = getattr(args, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"--{name.replace('_', '-')} must be finite and positive")
        audio = args.audio.expanduser().resolve(strict=True)
        if not audio.is_file():
            raise ValueError("--audio must be one file, not a directory")
        if bool(args.ffmpeg) != bool(args.ffprobe):
            raise ValueError("supply both --ffmpeg and --ffprobe, or neither")
        identifier = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12]
        media = args.output_root or Path.home() / "Videos/ewp-waveform" / identifier
        media = media.expanduser().resolve()
        requested_evidence = (args.evidence_root or media / "logs").expanduser().resolve()
        if media.exists() or requested_evidence.exists():
            raise FileExistsError(
                "output/evidence root already exists; use NEW paths; never overwrite"
            )
        if media.is_relative_to(requested_evidence):
            raise ValueError("output root must not be inside evidence root")
        outside_git([media, requested_evidence], audio)
        media.mkdir(parents=True, exist_ok=False)
        requested_evidence.mkdir(parents=True, exist_ok=False)
        evidence = requested_evidence
        failure_root = evidence
        for folder in (media / "tmp", media / "work"):
            folder.mkdir()
        limits = {
            "growth_bytes": args.max_growth_gib * GIB,
            "reserve_bytes": args.reserve_gib * GIB,
            "memory_floor_bytes": 128 * 1024**2,
            "accounting_roots": [str(media), str(evidence)],
            "baseline_bytes": 0,
            "budget_scope": "new ordinary-render output, work, scratch and logs; no setup",
        }
        env = child_environment(media)

        def monitor() -> dict[str, Any]:
            return check_budget(evidence, media, limits)

        def command(command_argv: list[str], folder: Path, timeout: float) -> dict[str, Any]:
            record = run_command(
                command_argv,
                folder,
                timeout=timeout,
                env=env,
                cwd=ROOT,
                monitor=monitor,
                final_monitor=monitor,
            )
            require_process_safe(record)
            if record["returncode"] != 0 or record["error"]:
                raise ValueError(
                    f"command failed; see {folder}: {record['error']}\n{record['stderr']}"
                )
            return record

        def probe(python: Path, folder: Path, *, optional: bool = False) -> dict[str, Any]:
            if optional:
                raise ValueError("ordinary CPU production never requests an optional runtime")
            command([str(python), str(DRIVER), "--_environment"], folder, 120)
            value: dict[str, Any] = json.loads((folder / "stdout.txt").read_text(encoding="utf-8"))
            return value

        save(evidence / "admission.json", monitor())
        before = identity(audio)
        source_mtime = audio.stat().st_mtime_ns
        store = (args.managed_root or args.preparations_root / "managed-dependencies").expanduser()
        candidates = (
            [args.python.expanduser().absolute()]
            if args.python
            else [ROOT / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")]
        )
        python = candidates[0]
        if python.is_file():
            environment = probe(python, evidence / "runtime")
        elif args.python:
            raise ValueError(f"explicit --python missing: {python}; no install attempted")
        else:
            reused = prepared_environment(store, ROOT, "runtime", evidence, probe)
            if reused is None:
                raise ValueError(
                    "no verified prepared Python 3.12; use --python PATH; no install attempted"
                )
            python, environment, receipt = reused
            save(evidence / "runtime-reuse.json", receipt)
        save(evidence / "environment.json", environment)
        ffmpeg, ffprobe = select_tools(
            args.ffmpeg, args.ffprobe, args.preparations_root.expanduser(), store
        )
        tools = {"ffmpeg": identity(ffmpeg), "ffprobe": identity(ffprobe)}
        env["PATH"] = str(ffmpeg.parent) + os.pathsep + env.get("PATH", "")
        if any(
            not os.path.samefile(shutil.which(name, path=env["PATH"]) or "", path)
            for name, path in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe))
        ):
            raise ValueError("selected PATH does not resolve the exact requested tools")
        for name, path in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)):
            command([str(path), "-version"], evidence / (name + "-version"), 30)
        performance = media / "performance.toml"
        with performance.open("x", encoding="utf-8") as stream:
            stream.write(performance_text(media))
        render_argv = cli_command(python, audio, media, performance)
        save(
            evidence / "request.json",
            {
                "audio": before,
                "tools": tools,
                "preset": identity(PRESET),
                "base_performance": identity(PERFORMANCE),
                "performance": identity(performance),
                "config": identity(CONFIG),
                "argv": render_argv,
                "limits": limits,
                "mode": "ordinary full-file CPU serial/LUT; no experimental --full",
            },
        )
        print(f"Output root: {media}\nLogs: {evidence}", flush=True)
        command(render_argv, evidence / "ordinary-cli", args.timeout_seconds)
        command(
            [str(python), str(DRIVER), "--_verify", str(media / "output")],
            evidence / "publication-readback",
            120,
        )
        summary = json.loads(
            (evidence / "publication-readback/stdout.txt").read_text(encoding="utf-8")
        )
        verify(before)
        if audio.stat().st_mtime_ns != source_mtime:
            raise ValueError("source modification time changed")
        for item in tools.values():
            verify(item)
        save(evidence / "publication.json", {**summary, "source_unchanged": True})
        save(evidence / "final-storage.json", monitor())
        monitor()  # Include final evidence serialization in admission.
        print(f"SUCCEEDED: {summary['output']['path']}\nResult: {summary['result_json']}")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        if failure_root is not None:
            save(failure_root / "failure.json", {"status": "FAILED", "error": str(exc)})
        print(f"REFUSED/FAILED: {exc}", file=sys.stderr)
        return 2
