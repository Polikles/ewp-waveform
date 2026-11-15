from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import portable_experiments_reporting as reporting
from ewp_waveform.application.portable_experiments_state import sha
from ewp_waveform.ffmpeg.ribbon import ribbon_graph
from ewp_waveform.ffmpeg.ribbon_lut import GeqSampling, prepare_ribbon_lut, ribbon_lut_argv


def test_report_packaging_io_failure_preserves_original_error(
    tmp_path: Path, monkeypatch: Any
) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise OSError("packet write denied")

    monkeypatch.setattr(reporting, "diagnostic_bundle", fail)
    path = reporting.report(
        tmp_path,
        "FAILED",
        "original encode failed",
        None,
        {"render": {"status": "FAILED", "error": "iterator failed"}},
    )
    full = json.loads(path.with_suffix(".json").read_text())
    assert full["error"] == "original encode failed"
    assert full["results"]["render"]["error"] == "iterator failed"
    assert full["packaging"]["status"] == "FAILED"
    assert "packet write denied" in path.read_text()
    assert "original encode failed" in path.read_text()


@pytest.mark.parametrize("kind", ["report", "diagnostics", "measurements"])
def test_recovery_is_read_only_and_never_renders_or_opens_media(
    tmp_path: Path,
    monkeypatch: Any,
    kind: str,
) -> None:
    records = tmp_path / (kind + ".json")
    original = {
        "status": "FAILED",
        "error": "ModuleNotFoundError: No module named 'numpy'",
        "failure": {
            "stage": "campaign:cuda-combined",
            "interpreter": {"executable": "retained-bootstrap", "version": "retained-version"},
            "traceback": "full retained traceback\n" * 400,
            "failing_frame": {"filename": "retained.py", "lineno": 11},
        },
        "config": {"python": "retained-python", "source": {"sha256": "retained"}},
        "results": {
            "bad-lut": {"status": "FAILED", "error": "original guard"},
            "good": {
                "status": "SUCCEEDED",
                "output": "must-not-open.mov",
                "actual_action": "PROCESS",
                "phase_metrics": {"seconds": {"feed": 1.25}},
            },
        },
    }
    records.write_text(json.dumps(original))
    before = records.read_bytes()
    real_sha = sha

    def sha_only_records(path: Path) -> str:
        assert path == records
        return real_sha(path)

    monkeypatch.setattr(reporting, "sha", sha_only_records)
    output = tmp_path / "recovered"
    path = reporting.regenerate_report(records, output)
    full = json.loads(path.with_suffix(".json").read_text())
    assert full["results"] == original["results"]
    assert full["status"] == original["status"]
    assert full["error"] == original["error"]
    assert full["failure"] == original["failure"]
    measurements = next((output / "reports").glob("measurements-*.json"))
    assert json.loads(measurements.read_text())["failure"] == original["failure"]
    assert "retained-bootstrap" in path.read_text()
    assert not full["fresh_measurements_this_invocation"]
    assert set(full["result_use"].values()) == {"REUSED"}
    assert full["retained_source"]["sha256"] == real_sha(records)
    assert records.read_bytes() == before
    assert (output / "retained-records.json").read_bytes() == before
    assert "not revalidated" in path.read_text()
    with pytest.raises(FileExistsError):
        reporting.regenerate_report(records, output)


def test_recovery_rejects_invalid_input_before_creating_output(tmp_path: Path) -> None:
    records = tmp_path / "bad.json"
    records.write_text('{"status":"COMPLETE","results":[]}')
    with pytest.raises(ValueError, match="retained report"):
        reporting.regenerate_report(records, tmp_path / "not-created")
    assert not (tmp_path / "not-created").exists()


@pytest.mark.parametrize("failure", [[], "damaged", {"interpreter": []}, {"interpreter": None}])
def test_recovery_rejects_malformed_failure_before_creating_output(
    tmp_path: Path, failure: Any
) -> None:
    records = tmp_path / "bad-failure.json"
    records.write_text(json.dumps({"status": "FAILED", "results": {}, "failure": failure}))
    with pytest.raises(ValueError, match="retained report"):
        reporting.regenerate_report(records, tmp_path / "not-created")
    assert not (tmp_path / "not-created").exists()


def test_packaging_outcome_write_failure_keeps_authoritative_records(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    from ewp_waveform.application.portable_experiments_state import save

    def save_except_finalization(path: Path, value: Any) -> None:
        if path.suffix == ".pending":
            raise OSError("outcome disk write denied")
        save(path, value)

    monkeypatch.setattr(reporting, "save", save_except_finalization)
    path = reporting.report(tmp_path, "COMPLETE", None, None, {"kept": {"status": "SUCCEEDED"}})
    assert json.loads(path.with_suffix(".json").read_text())["results"] == {
        "kept": {"status": "SUCCEEDED"}
    }
    assert "Packaging outcome export failed" in path.read_text()
    assert "Status: **COMPLETE**" in path.read_text()


def test_lut_windows_exe_alias_requires_actual_file_identity(
    tmp_path: Path, monkeypatch: Any
) -> None:
    selected = r"C:\qualified\bin\ffmpeg.exe"
    actual = r"C:\qualified\bin\ffmpeg.EXE"
    prepared = prepare_ribbon_lut(
        tmp_path / "mask.pgm",
        width=18,
        height=16,
        finish=(0.45, True, 1.0, 0.96, 0.55),
        sampling=GeqSampling(selected, "smear"),
    )
    graph = ribbon_graph(
        width=18,
        height=16,
        finish=prepared.finish,
        overscan=0,
        supersample=1,
        pix_fmt="gray",
        color="#C7E6EC",
        glow=0,
    )
    argv = [
        actual,
        "-v",
        "verbose",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-s",
        "18x16",
        "-r",
        "60",
        "-i",
        "-",
        "-filter_complex",
        graph,
        "-map",
        "[vout]",
        "-c:v",
        "prores_ks",
        "-profile:v",
        "4444",
        "-pix_fmt",
        "yuva444p10le",
        "native.mov",
    ]
    # Real Linux cannot assert identity of these absent Windows paths.
    with pytest.raises(ValueError, match="qualified FFmpeg"):
        ribbon_lut_argv(argv, prepared)

    def samefile(path: Path, other: str) -> bool:
        return str(path) == actual and other == selected

    monkeypatch.setattr(Path, "samefile", samefile)
    transformed = ribbon_lut_argv(argv, prepared)
    assert transformed[0] == actual and transformed.count("-i") == 2
    assert argv.count("-i") == 1
    for bad in (
        ["C:\\unqualified\\ffmpeg.EXE", *argv[1:]],
        [*argv, "-i", "second"],
        [*argv, "-map", "0:v"],
        [*argv, "-c:v", "png", "second.png"],
    ):
        with pytest.raises(ValueError, match="qualified FFmpeg"):
            ribbon_lut_argv(bad, prepared)


def test_lut_filesystem_alias_not_merely_equal_content(tmp_path: Path) -> None:
    from ewp_waveform.ffmpeg.ribbon_lut import _same_executable

    original = tmp_path / "ffmpeg.exe"
    original.write_bytes(b"fixture, not an executable")
    alias = tmp_path / "ffmpeg.EXE"
    if not alias.exists():  # Case-insensitive Windows may already see the same file.
        alias.hardlink_to(original)
    duplicate = tmp_path / "copied-ffmpeg"
    duplicate.write_bytes(original.read_bytes())
    assert _same_executable(str(alias), str(original))
    assert not _same_executable(str(duplicate), str(original))
