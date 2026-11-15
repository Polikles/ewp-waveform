"""Tiny synthetic protocol witnesses, not historical media/pixel qualification."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import retained_success as recovery


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def ident(path: Path) -> dict[str, Any]:
    return recovery._identity(path)


def append(run: Path, row: dict[str, Any]) -> None:
    p = run / "events.jsonl"
    previous = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "0" * 64
    with p.open("a") as stream:
        stream.write(json.dumps({**row, "previous_sha256": previous}, sort_keys=True) + "\n")


def rewrite_events(run: Path, rows: list[dict[str, Any]]) -> None:
    (run / "events.jsonl").unlink()
    for row in rows:
        append(run, {k: v for k, v in row.items() if k != "previous_sha256"})


def events(run: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]


def freeze(
    run: Path, name: str, request: dict[str, Any], raw: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    root = run / "steps" / name
    if raw.get("actual_action") == "PROCESS":
        output = raw["output"]
        raw["commands"] = [
            {
                "phase": "complete-frame-metadata-outcome",
                "argv": [request["ffprobe"], "-of", "json", output],
                "returncode": 0,
                "stderr": "",
                "stdout": json.dumps(
                    {
                        "streams": [raw["validation"]["stream"]],
                        "frames": [
                            {"best_effort_timestamp": i * 256}
                            for i in range(raw["validation"]["frames"])
                        ],
                    }
                ),
            },
            {
                "phase": "strict-complete-software-decode",
                "argv": [
                    request["ffmpeg"],
                    "-nostdin",
                    "-v",
                    "error",
                    "-xerror",
                    "-err_detect",
                    "explode",
                    "-hwaccel",
                    "none",
                    "-i",
                    output,
                    "-map",
                    "0:v:0",
                    "-an",
                    "-c:v",
                    "rawvideo",
                    "-pix_fmt",
                    "rgba",
                    "-f",
                    "rawvideo",
                    "pipe:1",
                ],
            },
        ]
        root.mkdir(parents=True)
        (root / "commands.jsonl").write_text("".join(json.dumps(c) + "\n" for c in raw["commands"]))
        (root / (Path(output).name + ".rgba.decode.stderr")).write_bytes(b"")
    write(root / "request.json", request)
    write(root / "value.json", raw)
    if request["operation"] == "service":
        write(root / "service-result.json", raw["service_result"])
    argv = [
        config["python"],
        str(Path(config["source"]["root"]) / "scripts/run_experiments.py"),
        "--_worker",
        str(root / "request.json"),
    ]
    observed = {
        "argv": argv,
        "returncode": 0,
        "error": None,
        "shutdown_verified": True,
        "resource_refused": False,
        "storage_observation_failed": False,
        "monitor_failed": False,
        "wall_seconds": 3.0,
    }
    write(root / "process/command.json", {"argv": argv})
    write(root / "process/result.json", observed)
    (root / "process/stdout.txt").write_bytes(b"")
    (root / "process/stderr.txt").write_bytes(b"")
    value = {
        **raw,
        "command": observed,
        "execution_settings": {
            **{k: request.get(k) for k in ("ffmpeg", "ffprobe", "visual_overrides", "workload")},
            "python": config["python"],
        },
        "experimental_controls": {k: request.get(k) for k in recovery.CONTROL_KEYS},
    }
    if request.get("pair"):
        value["pair"] = request["pair"]
    append(run, {"name": name, "event": "STARTED", "request": ident(root / "request.json")})
    artifacts = [ident(p) for p in sorted(root.rglob("*")) if p.is_file()]
    artifacts.extend(raw.get("artifacts", []))
    append(run, {"name": name, "event": "SUCCEEDED", "value": value, "artifacts": artifacts})
    return value


def fixture_run(tmp_path: Path, *, operation: str = "direct") -> tuple[Path, Path, dict[str, Any]]:
    run = tmp_path / "old"
    run.mkdir()
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"synthetic source, not decodable audio")
    original = run / "original-environment.json"
    observations = run / "original-observations.json"
    write(original, {"old": "environment"})
    write(observations, {"old": "tools"})
    files = {"src/old.py": "1" * 64}
    # No historical source, binary, or tools exist: today's environment is irrelevant.
    binary = {"path": "/old/python", "resolved": "/old/python", "bytes": 17, "sha256": "a" * 64}
    config: dict[str, Any] = {
        "run": str(run),
        "media": str(tmp_path / "media"),
        "audio": ident(audio),
        "original": ident(original),
        "original_observations": ident(observations),
        "python": "/old/python",
        "environment": {"python": "/old/python", "binary": binary},
        "source": {
            "root": "/old/source",
            "files": files,
            "sha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
        },
        "selected": {
            "tools": {
                k: {**binary, "path": "/old/" + k, "resolved": "/old/" + k}
                for k in ("ffmpeg", "ffprobe")
            }
        },
        "original_path": "/old/path",
        "visual_overrides": {"noise_seed": 17},
        "repeats": 2,
    }
    write(run / "config.json", config)
    write(run / "config-seal.json", ident(run / "config.json"))
    results = {}
    group = "single-file-direct-lut" if operation == "direct" else "single-file-short-lut"
    workload = {"id": "speech", "kind": "short", "start": 25.0, "duration": 4.0, "frames": 240}
    first_output = None
    for repeat in (1, 2):
        order = "AB" if repeat == 1 else "BA"
        for side in order:
            name = f"{group}-r{repeat:02d}-{side}"
            media = tmp_path / "media" / name
            media.mkdir(parents=True)
            output = media / "native.mov"
            output.write_bytes(b"synthetic exact retained native bytes")
            request = {
                "operation": operation,
                "audio": str(audio),
                "original_path": "/old/path",
                "visual_overrides": config["visual_overrides"],
                "media": str(media),
                "evidence": str(run / "steps" / name),
                "result_path": str(run / "steps" / name / "value.json"),
                "ffmpeg": "/old/ffmpeg",
                "ffprobe": "/old/ffprobe",
                "workload": workload,
                "pair": {
                    "id": group,
                    "repeat": repeat,
                    "side": side,
                    "order": order,
                    "comparison": "synthetic matched control",
                },
            }
            if operation == "direct":
                request["codec"] = "prores"
            else:
                request["jobs"] = 1
            if side == "B":
                request["finish_lut"] = True
            if first_output:
                request.update(reference=first_output, reference_lossless=True)
                if operation == "direct":
                    request["expected_raster_sha256"] = "b" * 64
            value: dict[str, Any] = {
                "status": "SUCCEEDED",
                "actual_action": "PROCESS",
                "throughput_fresh": True,
                "workload": workload,
                "wall_seconds": 2.0 if side == "A" else 1.0,
                "timer": recovery.DIRECT_TIMER if operation == "direct" else recovery.SERVICE_TIMER,
                "route": recovery.DIRECT_ROUTE if operation == "direct" else "STOCK_SERVICE",
                "output": str(output),
                "artifacts": [ident(output)],
                "source": config["audio"],
                "original_raster_sha256": "b" * 64,
                "effective_preset": {"same": "preset"},
                "validation": {
                    "passed": True,
                    "frames": 240,
                    "fps": "60/1",
                    "alpha_min": 0,
                    "alpha_max": 255,
                    "alpha_association_contract": "straight",
                    "frame_grid_seconds": "4",
                    "time_base": "1/15360",
                    "lossless_against_reference_master": bool(first_output),
                    "max_pts_error_seconds": "0",
                    "decoded_rgba_sha256": "c" * 64,
                    "decoded_alpha_sha256": "d" * 64,
                    "stream": {
                        "avg_frame_rate": "60/1",
                        "codec_name": "prores",
                        "profile": "4444",
                        "pix_fmt": "yuva444p12le",
                        "width": 1400,
                        "height": 280,
                        "time_base": "1/15360",
                    },
                },
            }
            if operation == "service":
                value["service_result"] = {
                    "job": {"status": "SUCCEEDED"},
                    "validation": {"passed": True, "frames": 240},
                    "execution": {"resumed": False},
                    "resume_history": [],
                    "performance": {"extras": {"reused_output_formats": []}},
                    "outputs": [{"format": "prores4444", "path": str(output)}],
                    "inputs": [
                        {
                            "path": str(audio),
                            "sha256": config["audio"]["sha256"],
                            "size_bytes": config["audio"]["bytes"],
                        }
                    ],
                    "analysis": {"encode_workers": 1},
                }
            results[name] = freeze(run, name, request, value, config)
            if first_output is None:
                first_output = str(output)
    diagnostic = tmp_path / "diagnostics.json"
    write(
        diagnostic,
        {
            "status": "FAILED",
            "error": "later bootstrap failure",
            "config": config,
            "results": {
                n: {**v, "evidence_status": "SALVAGED_UNVERIFIED"} for n, v in results.items()
            },
        },
    )
    (run / "status.txt").write_text("FAILED\n")
    return run, diagnostic, config


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("operation", ["direct", "service"])
def test_valid_reused_validation_and_originals_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    run, diagnostic, _ = fixture_run(tmp_path, operation=operation)
    before = snapshot(tmp_path)
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **k: pytest.fail("must not launch a process")
    )
    result = recovery.recover(run, tmp_path / "new", diagnostic)
    assert result["status"] == "AUTHENTICATED"
    assert result["authenticated_success_count"] == 4
    stats = next(p for p in result["pair_statistics"] if p["recovered_paired_n"])
    assert stats["recovered_paired_n"] == 2
    assert stats["orders"] == ["AB", "BA"]
    assert stats["sides"]["A"]["median_seconds"] == 2
    assert stats["sides"]["B"]["median_seconds"] == 1
    assert stats["speedup"] is None
    assert result["fresh_measurements_this_invocation"] is False
    assert result["original_status"] == "FAILED"
    assert "not new pixels" in result["validation_scope"]
    after = snapshot(tmp_path)
    assert all(after[n] == value for n, value in before.items())
    assert all(
        v["evidence_status"] == "SALVAGED_UNVERIFIED"
        for v in json.loads(diagnostic.read_text())["results"].values()
    )


@pytest.mark.parametrize(
    "target", ["media", "request", "value", "process", "chain", "config", "input"]
)
def test_tampered_bytes_fail_closed(tmp_path: Path, target: str) -> None:
    run, diagnostic, _ = fixture_run(tmp_path)
    first = "single-file-direct-lut-r01-A"
    paths = {
        "media": tmp_path / "media" / first / "native.mov",
        "request": run / "steps" / first / "request.json",
        "value": run / "steps" / first / "value.json",
        "process": run / "steps" / first / "process/result.json",
        "chain": run / "events.jsonl",
        "config": run / "config.json",
        "input": tmp_path / "input.wav",
    }
    with paths[target].open("ab") as stream:
        stream.write(b"tampered")
    result = recovery.authenticate(run, diagnostic)
    assert first not in result["qualified"]
    stats = result["pair_statistics"]
    assert (
        not stats
        or next(p for p in stats if p["id"] == "single-file-direct-lut")["recovered_paired_n"] == 0
    )
    assert result["errors"] or result["ineligible"]


def test_missing_media_and_partial_packet_never_qualify(tmp_path: Path) -> None:
    run, _, _ = fixture_run(tmp_path)
    for media in (tmp_path / "media").rglob("*.mov"):
        media.unlink()
    report = recovery.authenticate(run)
    assert report["authenticated_success_count"] == 0
    assert all(p["recovered_paired_n"] == 0 for p in report["pair_statistics"])
    (run / "events.jsonl").unlink()
    assert recovery.authenticate(run)["status"] == "INELIGIBLE"


@pytest.mark.parametrize(
    "mutation",
    [
        "shutdown",
        "returncode",
        "frames",
        "order",
        "source",
        "tool",
        "controls",
        "grid",
        "decoded",
        "route",
        "raw",
    ],
)
def test_consistent_frozen_bad_provenance_excluded(tmp_path: Path, mutation: str) -> None:
    run, _, _ = fixture_run(tmp_path)
    rows = events(run)
    v = rows[1]["value"]
    if mutation == "shutdown":
        v["command"]["shutdown_verified"] = False
    elif mutation == "returncode":
        v["command"]["returncode"] = 1
    elif mutation == "frames":
        v["validation"]["frames"] = 1
    elif mutation == "order":
        v["pair"]["order"] = "BA"
    elif mutation == "source":
        v["source"] = {**v["source"], "sha256": "e" * 64}
    elif mutation == "tool":
        v["execution_settings"]["ffmpeg"] = "/wrong/ffmpeg"
    elif mutation == "controls":
        v["experimental_controls"]["jobs"] = 17
    elif mutation == "grid":
        v["validation"]["max_pts_error_seconds"] = "1"
    elif mutation == "decoded":
        v["validation"]["decoded_rgba_sha256"] = "f" * 64
    elif mutation == "route":
        v["route"] = "CUDA"
    elif mutation == "raw":
        v["wall_seconds"] = 99
    if mutation != "raw":
        root = run / "steps" / rows[0]["name"]
        request = json.loads((root / "request.json").read_text())
        if mutation == "order":
            request["pair"] = v["pair"]
        elif mutation == "tool":
            request["ffmpeg"] = v["execution_settings"]["ffmpeg"]
        elif mutation == "controls":
            request["jobs"] = 17
        write(root / "request.json", request)
        rows[0]["request"] = ident(root / "request.json")
        raw = json.loads((root / "value.json").read_text())
        write(root / "value.json", {k: v[k] for k in raw})
        write(root / "process/result.json", v["command"])
        rows[1]["artifacts"] = [ident(Path(a["path"])) for a in rows[1]["artifacts"]]
    rewrite_events(run, rows)
    report = recovery.authenticate(run)
    stats = next(p for p in report["pair_statistics"] if p["id"] == "single-file-direct-lut")
    assert stats["recovered_paired_n"] == 0


def test_unrelated_failed_and_orphan_do_not_become_successes(tmp_path: Path) -> None:
    run, diagnostic, _ = fixture_run(tmp_path)
    append(run, {"name": "cuda-bootstrap", "event": "STARTED", "request": {"missing": True}})
    append(
        run,
        {
            "name": "cuda-bootstrap",
            "event": "FAILED",
            "value": {"status": "FAILED"},
            "artifacts": [],
        },
    )
    append(
        run,
        {"name": "orphan", "event": "SUCCEEDED", "value": {"status": "SUCCEEDED"}, "artifacts": []},
    )
    append(run, {"name": "interrupted", "event": "STARTED", "request": {"missing": True}})
    report = recovery.authenticate(run, diagnostic)
    assert report["authenticated_success_count"] == 4
    assert {r["name"] for r in report["unrelated"]} == {"cuda-bootstrap", "orphan", "interrupted"}
    assert "cuda-bootstrap" not in report["qualified"]


def test_duplicate_start_quarantines_only_ambiguous_name(tmp_path: Path) -> None:
    run, _, _ = fixture_run(tmp_path)
    rows = events(run)
    append(run, rows[0])
    report = recovery.authenticate(run)
    assert report["authenticated_success_count"] == 0
    assert rows[0]["name"] not in report["qualified"]


@pytest.mark.parametrize("mutation", ["wall", "excerpt"])
def test_diagnostics_must_match_frozen_results(tmp_path: Path, mutation: str) -> None:
    run, diagnostic, _ = fixture_run(tmp_path)
    d = json.loads(diagnostic.read_text())
    first = next(iter(d["results"].values()))
    if mutation == "wall":
        first["wall_seconds"] = 777
    else:
        first["commands"][0]["stdout"] = {"excerpt": "not the full retained metadata"}
    write(diagnostic, d)
    report = recovery.authenticate(run, diagnostic)
    assert report["authenticated_success_count"] == 0
    assert any("diagnostics/terminal" in r["reason"] for r in report["ineligible"])


def test_fresh_output_collision_and_overlap_refused(tmp_path: Path) -> None:
    run, diagnostic, _ = fixture_run(tmp_path)
    output = tmp_path / "new"
    output.mkdir()
    before = snapshot(tmp_path)
    with pytest.raises(ValueError, match="already exists"):
        recovery.recover(run, output, diagnostic)
    with pytest.raises(ValueError, match="overlaps"):
        recovery.recover(run, run / "new", diagnostic)
    with pytest.raises(ValueError, match="overlaps"):
        recovery.recover(run, tmp_path / "media" / "new", diagnostic)
    assert snapshot(tmp_path) == before


def test_no_heavy_import_or_subprocess_in_entrypoint(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[2] / "scripts/authenticate_retained_success.py"
    code = (
        "import runpy,sys; "
        "sys.argv=[sys.argv[1], '--run', sys.argv[2], '--output', sys.argv[3]]; "
        "runpy.run_path(sys.argv[0],run_name='__main__')"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            code,
            str(script),
            str(tmp_path / "missing"),
            str(tmp_path / "new"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stderr
    assert json.loads(result.stdout)["authenticated_success_count"] == 0
    assert (tmp_path / "new/authentication.json").is_file()


def test_json_duplicate_keys_refused() -> None:
    with pytest.raises(ValueError, match="duplicate JSON key"):
        recovery._json(b'{"status":"FAILED","status":"SUCCEEDED"}')
    with pytest.raises(ValueError, match="non-finite"):
        recovery._json(b'{"wall":NaN}')


def test_complete_other_repeat_survives_late_missing_media(tmp_path: Path) -> None:
    run, _, _ = fixture_run(tmp_path)
    (tmp_path / "media/single-file-direct-lut-r02-B/native.mov").unlink()
    report = recovery.authenticate(run)
    assert report["authenticated_success_count"] == 3
    stats = next(p for p in report["pair_statistics"] if p["id"] == "single-file-direct-lut")
    assert stats["recovered_paired_n"] == 1
    assert stats["orders"] == ["AB"]


def test_frozen_frame_reordering_is_rejected_without_decode(tmp_path: Path) -> None:
    run, _, _ = fixture_run(tmp_path)
    rows = events(run)
    value = rows[1]["value"]
    metadata = json.loads(value["commands"][0]["stdout"])
    metadata["frames"][0], metadata["frames"][1] = metadata["frames"][1], metadata["frames"][0]
    value["commands"][0]["stdout"] = json.dumps(metadata)
    root = run / "steps" / rows[0]["name"]
    raw = json.loads((root / "value.json").read_text())
    raw["commands"] = value["commands"]
    write(root / "value.json", raw)
    rows[1]["artifacts"] = [ident(Path(a["path"])) for a in rows[1]["artifacts"]]
    rewrite_events(run, rows)
    report = recovery.authenticate(run)
    assert report["authenticated_success_count"] == 0
    assert any("frame order/timeline" in row["reason"] for row in report["ineligible"])


def test_candidate_failed_and_duplicate_terminal_not_promoted(tmp_path: Path) -> None:
    run, _, _ = fixture_run(tmp_path)
    rows = events(run)
    rows[1]["event"] = "FAILED"
    rewrite_events(run, rows)
    report = recovery.authenticate(run)
    assert report["authenticated_success_count"] == 0
    assert report["ineligible"][0]["event"] == "FAILED"
    append(run, rows[1])
    assert recovery.authenticate(run)["authenticated_success_count"] == 0


def test_foreign_config_seal_cannot_substitute_config(tmp_path: Path) -> None:
    run, _, _ = fixture_run(tmp_path)
    foreign = tmp_path / "foreign.json"
    foreign.write_bytes((run / "config.json").read_bytes())
    write(run / "config-seal.json", ident(foreign))
    report = recovery.authenticate(run)
    assert report["authenticated_success_count"] == 0
    assert "another namespace" in report["errors"][0]


def test_owner_lock_requires_quiescent_evidence(tmp_path: Path) -> None:
    run, _, _ = fixture_run(tmp_path)
    (run / "owner.lock").write_text("retained owner, do not remove")
    before = snapshot(tmp_path)
    report = recovery.authenticate(run)
    assert report["authenticated_success_count"] == 0
    assert "owner lock" in report["errors"][0]
    assert snapshot(tmp_path) == before


def test_original_failed_reports_preserved_without_diagnostics(tmp_path: Path) -> None:
    run, _, _ = fixture_run(tmp_path)
    original = run / "reports/report-old.json"
    write(original, {"status": "FAILED", "error": "later bootstrap"})
    report = recovery.authenticate(run)
    assert report["authenticated_success_count"] == 4
    assert report["original_reports"] == [
        {"identity": ident(original), "status": "FAILED", "error": "later bootstrap"}
    ]


def test_valid_cli_is_stdlib_only_and_writes_separate_report(tmp_path: Path) -> None:
    run, diagnostic, _ = fixture_run(tmp_path)
    script = Path(__file__).resolve().parents[2] / "scripts/authenticate_retained_success.py"
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            str(script),
            "--run",
            str(run),
            "--output",
            str(tmp_path / "new"),
            "--diagnostics",
            str(diagnostic),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["authenticated_success_count"] == 4
    persisted = json.loads((tmp_path / "new/authentication.json").read_text())
    assert persisted["original_status"] == "FAILED"
    assert persisted["new_renders"] == persisted["new_decodes"] == 0


def reseal_terminal(run: Path, rows: list[dict[str, Any]], index: int) -> None:
    """Consistently freeze only new synthetic fixtures, never historical records."""
    value = rows[index]["value"]
    root = run / "steps" / rows[index]["name"]
    raw = json.loads((root / "value.json").read_text())
    write(root / "value.json", {key: value[key] for key in raw})
    write(root / "process/result.json", value["command"])
    rows[index]["artifacts"] = [ident(Path(a["path"])) for a in rows[index]["artifacts"]]
    rewrite_events(run, rows)


@pytest.mark.parametrize("operation", ["direct", "service"])
@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("render", 100000.0),
        ("worker", 0.0),
        ("worker", -1.0),
        ("worker", True),
        ("worker", "3"),
        ("cold_alias", 100000.0),
    ],
)
def test_contained_render_timer_must_agree_with_worker(
    tmp_path: Path, operation: str, field: str, bad: Any
) -> None:
    run, _, _ = fixture_run(tmp_path, operation=operation)
    rows = events(run)
    value = rows[3]["value"]
    if field == "render":
        value["wall_seconds"] = bad
    elif field == "worker":
        value["command"]["wall_seconds"] = bad
    else:
        value["cold_process_wall_seconds"] = bad
    reseal_terminal(run, rows, 3)
    before = snapshot(tmp_path)
    report = recovery.authenticate(run)
    assert rows[3]["name"] not in report["qualified"]
    group = value["pair"]["id"]
    stats = next(s for s in report["pair_statistics"] if s["id"] == group)
    assert stats["recovered_paired_n"] == 1
    assert stats["orders"] == ["BA"]
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("operation", ["direct", "service"])
@pytest.mark.parametrize("inside", [True, False])
def test_timer_rounding_allowance_is_absolute_and_bounded(
    tmp_path: Path, operation: str, inside: bool
) -> None:
    run, _, _ = fixture_run(tmp_path, operation=operation)
    rows = events(run)
    rows[3]["value"]["wall_seconds"] = 3.0 + recovery.TIMER_CONTAINMENT_TOLERANCE_SECONDS * (
        0.5 if inside else 2.0
    )
    reseal_terminal(run, rows, 3)
    report = recovery.authenticate(run)
    assert (rows[3]["name"] in report["qualified"]) is inside


@pytest.mark.parametrize("operation", ["direct", "service"])
def test_exact_rgba_reference_requires_matching_alpha_evidence(
    tmp_path: Path, operation: str
) -> None:
    run, _, _ = fixture_run(tmp_path, operation=operation)
    rows = events(run)
    rows[3]["value"]["validation"]["decoded_alpha_sha256"] = "e" * 64
    reseal_terminal(run, rows, 3)
    before = snapshot(tmp_path)
    report = recovery.authenticate(run)
    assert rows[3]["name"] not in report["qualified"]
    assert any("alpha mismatch" in r["reason"] for r in report["ineligible"])
    stats = next(s for s in report["pair_statistics"] if s["id"] == rows[3]["value"]["pair"]["id"])
    assert stats["recovered_paired_n"] == 1
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("operation", ["direct", "service"])
def test_pair_admission_also_reconciles_alpha(tmp_path: Path, operation: str) -> None:
    run, _, _ = fixture_run(tmp_path, operation=operation)
    report = recovery.authenticate(run)
    name = events(run)[3]["name"]
    report["qualified"][name]["value"]["validation"]["decoded_alpha_sha256"] = "e" * 64
    stats = recovery._statistics(report["qualified"], report["config"])
    group = report["qualified"][name]["value"]["pair"]["id"]
    assert next(s for s in stats if s["id"] == group)["recovered_paired_n"] == 1
