"""Opt-in WSL CPU/GPU suite application; all media commands live in FFmpeg adapters."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from ewp_waveform.application.experiment_suite_models import GPU, read_manifest
from ewp_waveform.application.experiment_suite_state import (
    Ledger,
    artifact,
    build_receipt,
    check_envelope,
    execute,
    lock,
    resources,
    source_identity,
    tool,
    tree_bytes,
    validate_roots,
    verify_session,
)
from ewp_waveform.application.experiments import load, save_new, sha


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    manifest = read_manifest(args.manifest)
    if args.run.exists() or args.media_root.exists():
        raise ValueError("prepare requires fresh run and media namespaces")
    audio = artifact(args.audio.resolve(), "SOURCE_AUDIO")
    if audio["sha256"] != manifest.input_sha256:
        raise ValueError("source WAV hash mismatch")
    roots = validate_roots([args.run, args.media_root, *args.account_root])
    for path in roots:
        if Path(audio["path"]).is_relative_to(path):
            raise ValueError("audio must not be inside an output/accounting root")
    tools: dict[str, Any] = {
        "new": {"ffmpeg": tool(args.ffmpeg), "ffprobe": tool(args.ffprobe)},
        "old": None,
    }
    if (args.old_ffmpeg is None) != (args.old_ffprobe is None):
        raise ValueError("both old build tools required")
    if args.old_ffmpeg:
        tools["old"] = {"ffmpeg": tool(args.old_ffmpeg), "ffprobe": tool(args.old_ffprobe)}
    for selected in tools.values():
        if selected is not None and (
            Path(selected["ffmpeg"]["path"]).name != "ffmpeg"
            or Path(selected["ffprobe"]["path"]).name != "ffprobe"
            or Path(selected["ffmpeg"]["path"]).parent != Path(selected["ffprobe"]["path"]).parent
        ):
            raise ValueError("tool pair must be real ffmpeg/ffprobe in one selected bin directory")
    reference = load(args.reference)
    if any(c.scenario in ("FULL", "PRODUCTION32") for c in manifest.cells):
        identity = reference["source_input"]
        if (
            manifest.input_sha256 != identity["sha256"]
            or manifest.source_duration_seconds != identity["source_seconds"]
        ):
            raise ValueError("full/production32 require the authenticated reference input")
    source = source_identity()
    if source["git_head_and_tree"][0] != args.source_commit or source["git_status"]:
        raise ValueError("clean exact final source commit required; do not use a historical pin")
    build = build_receipt(args.build_receipt, tools["new"]) if args.build_receipt else None
    if any(c.scenario in GPU for c in manifest.cells) and build is None:
        raise ValueError("GPU matrix requires pinned clean-source FFmpeg build receipt")
    session = {
        "schema_version": 1,
        "manifest": manifest.model_dump(mode="json"),
        "manifest_input": artifact(args.manifest.resolve(), "MANIFEST"),
        "source": source,
        "audio": audio,
        "tools": tools,
        "build": build,
        "vm_reference": reference,
        "reference_artifact": artifact(args.reference.resolve()),
        "build_qualification": "PINNED" if build else "CPU_SUPPLEMENTAL_UNPINNED",
        "device": args.device,
        "expect_device_regex": args.expect_device_regex,
        "media_root": str(args.media_root.resolve()),
        "base_path": os.environ["PATH"],
        "growth_baseline": {str(p): tree_bytes(p) for p in roots},
        "initial_resources": resources(roots),
        "settings_context": (
            "balanced jobs2, ffmpeg_threads0, chunk60; short serial; "
            "full/32 stock pool; requested threads not observed count"
        ),
    }
    # Validate every option and resource before creating output namespaces.
    from ewp_waveform.ffmpeg.experiment_suite import SuiteEncoding

    SuiteEncoding("TRANSFER", Path("unused"), args.device, args.expect_device_regex)
    check_envelope(session, manifest.limits.estimates["probe"].model_dump())
    args.run.mkdir(parents=True, exist_ok=False)
    args.media_root.mkdir(parents=True, exist_ok=False)
    save_new(args.run / "session.json", session)
    save_new(args.run / "session-seal.json", artifact(args.run / "session.json"))
    return {
        "status": "PREPARED_NOT_RUN",
        "run": str(args.run),
        "cells": [c.id for c in manifest.cells],
        "source_commit": args.source_commit,
        "next": "preflight",
    }


def session_at(run: Path) -> dict[str, Any]:
    from ewp_waveform.application.experiment_suite_state import verify_artifact

    verify_artifact(load(run / "session-seal.json"))
    session = load(run / "session.json")
    verify_session(session)
    # Detect edited manifest (the frozen session remains authoritative regardless).
    from ewp_waveform.application.experiment_suite_state import verify_artifact

    verify_artifact(session["manifest_input"])
    return session


def capability_skip(
    session: dict[str, Any], preflight: dict[str, Any], cell: dict[str, Any]
) -> str | None:
    name = cell["scenario"]
    if name == "A" and session["tools"]["old"] is None:
        return "OLD_BUILD_NOT_PROVIDED"
    if name not in GPU:
        return None
    gpu = preflight["runtime"]
    if gpu["gpu_status"] in ("API_UNAVAILABLE", "CAPABILITY_UNAVAILABLE", "NOT_TARGET"):
        return str(gpu["gpu_status"]) + ": " + str(gpu["evidence"])
    if gpu["gpu_status"] != "PASS":
        raise ValueError("GPU runtime qualification absent/failed")
    capability = {"D": "blur", "E1": "prores", "F1": "ffv1"}.get(name)
    if capability:
        for geometry in gpu["capabilities"].values():
            value = geometry[capability]
            if value["status"] == "CAPABILITY_UNAVAILABLE":
                return capability + ": " + str(value["evidence"])
            if value["status"] != "PASS":
                raise ValueError("actual capability probe failed")
    return None


def dispatch(run: Path, command: str, cell_id: str | None = None) -> dict[str, Any]:
    with lock(run):
        session = session_at(run)
        results = Ledger(run).results()
        if command == "preflight":
            return execute(run, session, "preflight", {"operation": "preflight"}, "probe")
        if "preflight" not in results or results["preflight"]["status"] != "SUCCEEDED":
            raise ValueError("successful real preflight required before timed cells")
        preflight = results["preflight"]
        cells = session["manifest"]["cells"]
        if cell_id is not None and cell_id not in {c["id"] for c in cells}:
            raise ValueError("unknown exact prepared cell ID")
        if command == "views":
            if any(c["id"] not in results for c in cells):
                raise ValueError("views require terminal timed matrix")
            for cell in cells:
                current = results[cell["id"]]
                w = next(w for w in session["manifest"]["workloads"] if w["id"] == cell["workload"])
                if current["status"] != "SUCCEEDED" or (
                    w["kind"] == "full" and not session["manifest"]["full_views"]
                ):
                    continue
                comparison = next(
                    (
                        results.get(c["id"], {}).get("output")
                        for c in cells
                        if cell["pair"]
                        and c["pair"] == cell["pair"]
                        and c["role"] == "control"
                        and cell["role"] == "candidate"
                    ),
                    None,
                )
                value = execute(
                    run,
                    session,
                    "views-" + cell["id"],
                    {
                        "operation": "views",
                        "cell": cell,
                        "workload": w,
                        "master": current["output"],
                        "comparison_reference": comparison,
                    },
                    "views",
                )
                if value["status"] == "FAILED":
                    break
            return export_results(run)
        # Failed attempts are immutable. Resume never runs past an unresolved failure.
        # An optional failed old-build probe is retained, but does not prevent B on the new build.
        if any(r["status"] == "FAILED" for ident, r in results.items() if ident != "old-preflight"):
            raise ValueError(
                "retained failure blocks dispatch; inspect and prepare a fresh namespace"
            )
        for cell in cells:
            if cell_id is not None and cell["id"] != cell_id:
                continue
            if cell["id"] in results:
                continue
            w = next(w for w in session["manifest"]["workloads"] if w["id"] == cell["workload"])
            skip = capability_skip(session, preflight, cell)
            if cell["scenario"] == "A" and skip is None:
                old = execute(
                    run,
                    session,
                    "old-preflight",
                    {"operation": "old-preflight", "cell": cell},
                    "probe",
                )
                if old["status"] != "SUCCEEDED":
                    skip = "OLD_BUILD_PROBE_FAILED; A NOT_RUN, diagnostics retained; B independent"
            fixture_result = None
            if cell["scenario"] in ("F0", "F1") and skip is None:
                fid = "fixture-" + cell["workload"]
                fixture_result = execute(
                    run,
                    session,
                    fid,
                    {
                        "operation": "fixture",
                        "workload": w,
                        "configuration": preflight["configurations"][w["id"]],
                    },
                    "fixture",
                )
                if fixture_result["status"] != "SUCCEEDED":
                    break
            reference = None
            if cell["pair"]:
                other = next(
                    c for c in cells if c["pair"] == cell["pair"] and c["id"] != cell["id"]
                )
                if other["role"] == "control" and other["id"] in results:
                    reference = results[other["id"]]
                    if reference["status"] != "SUCCEEDED":
                        reference = None
            value = execute(
                run,
                session,
                cell["id"],
                {
                    "operation": "cell",
                    "cell": cell,
                    "workload": w,
                    "configuration": preflight["configurations"][w["id"]],
                    "fixture": fixture_result,
                    "reference": reference,
                    "skip_reason": skip,
                },
                w["kind"],
            )
            results[cell["id"]] = value
            if value["status"] == "FAILED":
                break
        return export_results(run)


def worker(request_path: Path) -> None:
    request = load(request_path)
    run, attempt, root = Path(request["run"]), Path(request["attempt"]), Path(request["media"])
    result: dict[str, Any]
    try:
        if sha(run / "session.json") != request["session_sha256"]:
            raise ValueError("frozen session mutation")
        session = session_at(run)
        tools = session["tools"]["new"]
        os.environ["PATH"] = (
            str(Path(tools["ffmpeg"]["path"]).parent) + os.pathsep + session["base_path"]
        )
        operation = request["operation"]
        if operation == "old-preflight":
            from ewp_waveform.ffmpeg.experiment_suite_probes import runtime_preflight

            old_tools = session["tools"]["old"]
            os.environ["PATH"] = (
                str(Path(old_tools["ffmpeg"]["path"]).parent) + os.pathsep + session["base_path"]
            )
            runtime = runtime_preflight(
                old_tools["ffmpeg"]["path"],
                old_tools["ffprobe"]["path"],
                attempt,
                session["device"],
                session["expect_device_regex"],
                False,
            )
            if not runtime["advertised_cpu"]["prores_ks"]:
                raise ValueError("optional old build lacks CPU ProRes encoder")
            result = {
                "status": "SUCCEEDED",
                "runtime": runtime,
                "actual_action": "OLD_BUILD_PROBE",
                "throughput_fresh": False,
            }
        elif operation == "preflight":
            from ewp_waveform.application.experiment_suite_render import effective
            from ewp_waveform.ffmpeg.experiment_suite_probes import runtime_preflight

            runtime = runtime_preflight(
                tools["ffmpeg"]["path"],
                tools["ffprobe"]["path"],
                attempt,
                session["device"],
                session["expect_device_regex"],
                any(c["scenario"] in GPU for c in session["manifest"]["cells"]),
            )
            configs = {
                w["id"]: effective(session, w, root) for w in session["manifest"]["workloads"]
            }
            result = {
                "status": "SUCCEEDED",
                "runtime": runtime,
                "configurations": configs,
                "actual_action": "PROBE",
                "throughput_fresh": False,
            }
        elif request.get("skip_reason"):
            result = {
                "status": "SKIPPED",
                "reason": request["skip_reason"],
                "actual_action": "NOT_RUN",
                "throughput_fresh": False,
            }
        elif operation == "fixture":
            from ewp_waveform.application.experiment_suite_render import fixture

            result = fixture(session, request["workload"], root, attempt, request["configuration"])
        elif operation == "cell":
            from ewp_waveform.application.experiment_suite_render import run_cell

            result = run_cell(
                session,
                request["cell"],
                request["workload"],
                root,
                attempt,
                request["configuration"],
                request["fixture"],
                request["reference"],
            )
        elif operation == "views":
            from ewp_waveform.ffmpeg.experiment_suite_validation import make_views

            items = make_views(
                tools["ffmpeg"]["path"],
                tools["ffprobe"]["path"],
                Path(request["master"]),
                root,
                width=1400,
                height=280,
                frames=request["workload"]["frames"],
                log=attempt / "commands.jsonl",
            )
            metrics = None
            if request.get("comparison_reference"):
                from ewp_waveform.ffmpeg.experiment_suite_validation import inspect

                metrics = inspect(
                    tools["ffmpeg"]["path"],
                    tools["ffprobe"]["path"],
                    Path(request["master"]),
                    width=1400,
                    height=280,
                    frames=request["workload"]["frames"],
                    log=attempt / "compare.jsonl",
                    codec="ffv1" if request["master"].endswith(".mkv") else "prores",
                    reference=Path(request["comparison_reference"]),
                )
            result = {
                "comparison_validation": metrics,
                "status": "SUCCEEDED",
                "actual_action": "DERIVATIVES",
                "throughput_fresh": False,
                "artifacts": [
                    dict(item, **artifact(Path(item["path"]), item["role"])) for item in items
                ],
            }
        else:
            raise ValueError("unknown worker operation")
        verify_session(session)
    except Exception as exc:
        traceback.print_exc()
        result = {"status": "FAILED", "error": str(exc), "throughput_fresh": False}
    save_new(attempt / "worker-result.json", result)


def export_results(run: Path) -> dict[str, Any]:
    # Export/readback never invokes media tools or creates new throughput observations.
    session = session_at(run)
    ledger = Ledger(run)
    results = ledger.results()
    rows = []
    for c in session["manifest"]["cells"]:
        value = results.get(c["id"], {})
        valid = (
            value.get("status") == "SUCCEEDED"
            and value.get("actual_action") == "PROCESS"
            and value.get("throughput_fresh") is True
            and value.get("validation", {}).get("passed") is True
        )
        w = next(w for w in session["manifest"]["workloads"] if w["id"] == c["workload"])
        wall = value.get("wall_seconds") if valid else None
        rows.append(
            {
                **c,
                "status": value.get("status", "NOT_RUN"),
                "wall_seconds": wall,
                "fps": w["frames"] / wall if wall else None,
                "rtf": wall / (w["frames"] / 60) if wall else None,
                "measurement_scope": value.get("scope"),
                "result": value,
            }
        )
    pairs = []
    for name in sorted({c["pair"] for c in session["manifest"]["cells"] if c["pair"]}):
        members = [r for r in rows if r["pair"] == name]
        a = next(r for r in members if r["role"] == "control")
        b = next(r for r in members if r["role"] == "candidate")
        paired = all(r["wall_seconds"] is not None for r in (a, b))
        equality = None
        if paired and (a["scenario"], b["scenario"]) in (("B", "C"), ("F0", "F1")):
            equality = (
                a["result"]["validation"]["decoded_rgba_sha256"]
                == b["result"]["validation"]["decoded_rgba_sha256"]
            )
        pairs.append(
            {
                "id": name,
                "control": a["id"],
                "candidate": b["id"],
                "status": "HOLD" if equality is False else "PAIRED" if paired else "NOT_COMPARABLE",
                "decoded_rgba_equal": equality,
                "wall_ratio_control_over_candidate": a["wall_seconds"] / b["wall_seconds"]
                if paired and equality is not False
                else None,
                "claim": "build-factor"
                if a["scenario"] == "A"
                else "same-host same-build backend/topology factor",
            }
        )
    status = (
        "TECHNICAL_COMPLETE"
        if all(r["status"] in ("SUCCEEDED", "SKIPPED") for r in rows)
        else "INCOMPLETE"
    )
    if any(r["status"] == "SKIPPED" for r in rows) and status == "TECHNICAL_COMPLETE":
        status = "COMPLETE_WITH_SKIPS"
    if any(r["status"] == "FAILED" for r in results.values()) or any(
        p["status"] == "HOLD" for p in pairs
    ):
        status = "HOLD"
    payload = {
        "schema_version": 1,
        "status": status,
        "source": session["source"],
        "tool_identity": session["tools"],
        "build": session["build"],
        "settings": session["manifest"],
        "device": session["device"],
        "cells": rows,
        "pairs": pairs,
        "attempts": results,
        "ledger_head": ledger.previous,
        "visual": "PENDING",
        "studio": "PENDING",
        "promotion": "NOT_APPROVED",
        "fresh_measurements_added_by_export": 0,
        "unavailable_gpu_cells": [r["id"] for r in rows if r["status"] == "SKIPPED"],
        "views_pending": [
            r["id"]
            for r in rows
            if r["status"] == "SUCCEEDED" and "views-" + r["id"] not in results
        ],
    }
    # Admit each export's actual serialized size, not an inherited multi-GiB floor.
    payload_size = len(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False).encode())
    index_items = [a for r in results.values() for a in r.get("artifacts", [])]
    index_size = len(json.dumps({"artifacts": index_items}, indent=2, sort_keys=True).encode())
    csv_bound = (
        sum(len(json.dumps({k: v for k, v in row.items() if k != "result"})) for row in rows) * 2
        + 8192
    )
    check_envelope(
        session,
        {"growth_bytes": payload_size + index_size + csv_bound, "memory_bytes": 0, "seconds": 0},
        spent=sum(r["worker_wall_seconds"] for r in results.values()),
    )
    # Numbered immutable snapshots; prior exports never overwritten.
    folder = run / "exports"
    folder.mkdir(exist_ok=True)
    index = len(list(folder.glob("results-*.json"))) + 1
    stem = f"results-{index:04d}"
    save_new(folder / (stem + ".json"), payload)
    with (folder / (stem + ".csv")).open("x", newline="") as stream:
        fields = [
            "id",
            "scenario",
            "workload",
            "pair",
            "role",
            "status",
            "wall_seconds",
            "fps",
            "rtf",
            "measurement_scope",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    save_new(
        folder / (stem + "-artifact-index.json"),
        {"artifacts": [a for r in results.values() for a in r.get("artifacts", [])]},
    )
    return {
        "status": status,
        "json": str(folder / (stem + ".json")),
        "cells": len(rows),
        "not_run": sum(r["status"] == "NOT_RUN" for r in rows),
        "visual": "PENDING",
        "studio": "PENDING",
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser(
        "prepare", help="freeze source/input/settings/tools; no media execution"
    )
    for name in ("run", "media-root", "manifest", "audio", "ffmpeg", "ffprobe"):
        prepare_parser.add_argument("--" + name, type=Path, required=True)
    prepare_parser.add_argument(
        "--reference",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "examples/experiments/vm-reference.json",
    )
    prepare_parser.add_argument("--source-commit", required=True)
    prepare_parser.add_argument("--build-receipt", type=Path)
    prepare_parser.add_argument("--old-ffmpeg", type=Path)
    prepare_parser.add_argument("--old-ffprobe", type=Path)
    prepare_parser.add_argument("--device", default="RTX 3090")
    prepare_parser.add_argument("--expect-device-regex", default=r"RTX\s*3090")
    prepare_parser.add_argument("--account-root", type=Path, action="append", default=[])
    for name in ("preflight", "batch", "resume", "one", "views", "results", "export"):
        child = sub.add_parser(name)
        child.add_argument("--run", type=Path, required=True)
        if name == "one":
            child.add_argument("--cell", required=True)
    worker_parser = sub.add_parser("_worker", help=argparse.SUPPRESS)
    worker_parser.add_argument("--request", type=Path, required=True)
    a = p.parse_args(argv)
    try:
        if a.command == "prepare":
            result = prepare(a)
        elif a.command == "_worker":
            worker(a.request)
            return 0
        elif a.command in ("results", "export"):
            with lock(a.run):
                result = export_results(a.run)
        else:
            result = dispatch(a.run, a.command, getattr(a, "cell", None))
        print(json.dumps(result, indent=2))
        return 2 if result.get("status") in ("HOLD", "FAILED") else 0
    except Exception as exc:
        print(json.dumps({"status": "HOLD", "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
