from __future__ import annotations

import io
import resource
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ewp_waveform.application import benchmark
from ewp_waveform.application.benchmark import BenchmarkCell
from ewp_waveform.application.evidence import parent_resource_observation, render_measurements
from ewp_waveform.application.timing import PhaseTimes
from ewp_waveform.config.load import load_preset
from ewp_waveform.config.models import BenchmarkManifest, BenchmarkSection
from ewp_waveform.ffmpeg.process import run_argv_stdin


def _payload(status: str = "SUCCEEDED", passed: bool = True) -> dict[str, Any]:
    return {
        "job": {"status": status, "job_id": "test"},
        "validation": {"passed": passed, "frames": 3, "format": "png"},
        "outputs": [{"path": "output", "format": "png"}],
        "execution": {"resumed": False},
        "performance": {
            "extras": {
                "clip_start_seconds": 10.0,
                "effective_audio_seconds": 0.25,
                "expected_frames": 3,
                "reused_output_formats": [],
            }
        },
    }


def test_validated_clip_uses_effective_duration_and_validated_frames() -> None:
    report = render_measurements(_payload(), planned_action="PROCESS", wall_seconds=2, fps=10)
    assert report["throughput_available"] is True
    assert report["render_fps"] == 3 / 2
    assert report["real_time_factor"] == 2 / 0.25
    assert report["output_duration_seconds"] == 3 / 10
    assert report["duration_drift_seconds"] == pytest.approx(3 / 10 - 0.25)
    assert report["speedup"] is None


@pytest.mark.parametrize("status", ["SKIPPED", "FAILED", "BLOCKED", "UNSUPPORTED", "UNKNOWN", ""])
def test_non_success_has_no_throughput(status: str) -> None:
    result = render_measurements(
        _payload(status), planned_action="PROCESS", wall_seconds=0.001, fps=10
    )
    assert result["throughput_available"] is False
    assert all(result[key] is None for key in ["render_fps", "real_time_factor", "speedup"])


@pytest.mark.parametrize(
    "case",
    [
        "unvalidated",
        "planned_skip",
        "resumed",
        "partial_reuse",
        "missing_frames",
        "missing_duration",
        "missing_outputs",
        "zero_wall",
        "nan_wall",
    ],
)
def test_incomplete_or_reused_evidence_cannot_be_throughput(case: str) -> None:
    payload = _payload()
    planned = "PROCESS"
    wall = 2.0
    if case == "unvalidated":
        payload["validation"]["passed"] = False
    elif case == "planned_skip":
        planned = "SKIP"
    elif case == "resumed":
        payload["execution"]["resumed"] = True
    elif case == "partial_reuse":
        payload["performance"]["extras"]["reused_output_formats"] = ["png"]
    elif case == "missing_frames":
        payload["validation"].pop("frames")
    elif case == "missing_duration":
        payload["performance"]["extras"].pop("effective_audio_seconds")
    elif case == "missing_outputs":
        payload["outputs"] = []
    elif case == "zero_wall":
        wall = 0
    elif case == "nan_wall":
        wall = float("nan")
    result = render_measurements(payload, planned_action=planned, wall_seconds=wall, fps=10)
    assert result["render_fps"] is None
    assert result["real_time_factor"] is None


@pytest.mark.parametrize("status", ["SKIPPED", "SUCCEEDED", "FAILED", "UNKNOWN"])
def test_runner_records_planned_and_actual_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    preset = load_preset("iuris-default")
    cell = BenchmarkCell(
        tmp_path / "s0e00-Test.wav",
        "v",
        "ffmpeg",
        "balanced",
        ["png"],
        preset,
        "PROCESS",
        output_dir=tmp_path / "cell" / "output",
        duration_seconds=100,
    )
    manifest = BenchmarkManifest(
        schema_version=1,
        name="unit",
        inputs=[],
        variants=[],
        benchmark=BenchmarkSection(renderers=["ffmpeg"], formats=["png"]),
    )
    monkeypatch.setattr(benchmark, "load_and_expand", lambda *a, **kw: (manifest, [cell]))
    monkeypatch.setattr(benchmark, "probe_media", lambda *a: SimpleNamespace(duration_seconds=100))
    monkeypatch.setattr(benchmark, "render_job", lambda *a, **kw: _payload(status))
    monkeypatch.setattr(
        benchmark, "run_argv", lambda *a: SimpleNamespace(returncode=0, stdout="tool test\n")
    )
    times = iter([10.0, 100.0, 102.0, 110.0])
    monkeypatch.setattr(time, "perf_counter", lambda: next(times))
    summary = benchmark.run_benchmark(tmp_path / "manifest.toml", output_dir=tmp_path / "out")
    record = summary["cells"][0]
    assert record["planned_action"] == "PROCESS"
    assert record["actual_status"] == status
    assert record["wall_seconds"] == 2
    assert summary["benchmark_wall_seconds"] == 100
    assert "excludes" in record["wall_seconds_scope"]
    assert record["throughput_available"] is (status == "SUCCEEDED")
    assert record["source_duration_seconds"] == 100
    assert record["effective_audio_seconds"] == 0.25
    assert record["ffmpeg_threads_observed"] is None
    assert record["resources"]["process_tree_peak_rss_bytes"] is None


@pytest.mark.parametrize(
    "platform,unit", [("linux", "KiB"), ("darwin", "bytes"), ("other", "platform-defined")]
)
def test_rss_is_lifetime_parent_not_per_cell(
    monkeypatch: pytest.MonkeyPatch, platform: str, unit: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(resource, "getrusage", lambda who: SimpleNamespace(ru_maxrss=987))
    report = parent_resource_observation()
    assert report["parent_lifetime_ru_maxrss"] == 987
    assert report["parent_lifetime_ru_maxrss_unit"] == unit
    assert "process-lifetime" in report["scope"]
    assert report["per_cell_peak_rss_bytes"] is None
    assert report["child_cpu_seconds"] is None
    assert report["disk_io_bytes"] is None


def test_phase_metadata_and_stream_instrumentation_do_not_consume_or_mutate() -> None:
    expected = [b"first", b"", b"second\x00", b"third"]
    seen: list[bytes] = []

    def frames() -> Iterator[bytes]:
        for item in expected:
            seen.append(item)
            yield item

    argv = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"]
    phases = PhaseTimes()
    measured = run_argv_stdin(argv, frames(), phases=phases)
    plain = run_argv_stdin(argv, iter(expected))
    assert measured.returncode == plain.returncode == 0
    assert measured.stdout == plain.stdout == b"".join(expected)
    assert seen == expected
    snapshot = phases.snapshot()
    assert snapshot["semantics"]["additive"] is False
    assert "not encoder CPU" in snapshot["semantics"]["ffmpeg_feed"]
    assert snapshot["semantics"]["worker_phase_seconds"] is None
    assert snapshot["counts"]["generator"] == len(expected)
    assert phases.extras["raw_feed_bytes"] == sum(map(len, expected))
    assert phases.extras["rgba_bytes"] == sum(map(len, expected))


def test_dual_output_frame_disagreement_is_visible_not_common_throughput() -> None:
    payload = _payload()
    payload["validation"] = {
        "passed": True,
        "frames": 3,
        "png_frames": 4,
        "codec": "prores",
        "duration_seconds": 0.3,
    }
    result = render_measurements(payload, planned_action="PROCESS", wall_seconds=1, fps=10)
    assert result["validated_output_frames_by_format"] == {"prores4444": 3, "png": 4}
    assert result["throughput_available"] is False
    assert result["render_fps"] is None
    assert result["real_time_factor"] is None


def test_nested_phase_times_are_explicitly_non_additive() -> None:
    phases = PhaseTimes()
    phases.add("generator", 3.0)
    phases.add("visual_field", 1.0)
    phases.add("raster", 1.5)
    report = phases.snapshot()
    assert report["seconds"] == {"generator": 3.0, "visual_field": 1.0, "raster": 1.5}
    assert report["semantics"]["additive"] is False
    assert "nested" in report["semantics"]["generator"]


def test_feed_bytes_distinguish_successful_writes_from_broken_pipe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Sink:
        calls = 0

        def write(self, data: bytes) -> int:
            self.calls += 1
            if self.calls == 2:
                raise BrokenPipeError
            return len(data)

        def close(self) -> None:
            pass

    class Child:
        stdin = Sink()
        stdout = io.BytesIO(b"")
        stderr = io.BytesIO(b"broken")
        returncode = 1

        def wait(self) -> int:
            return 1

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: Child())
    phases = PhaseTimes()
    result = run_argv_stdin(["fake"], iter([b"abc", b"de", b"not-consumed"]), phases=phases)
    assert result.returncode == 1
    assert phases.extras["raw_feed_bytes"] == 3
    assert phases.extras["rgba_bytes"] == 5
    assert phases.counts["generator"] == 1
    assert phases.counts["ffmpeg_wait"] == 1


def test_planned_skip_is_not_a_terminal_render_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    preset = load_preset("iuris-default")
    cell = BenchmarkCell(tmp_path / "a.wav", "v", "ffmpeg", "balanced", ["png"], preset, "SKIP")
    manifest = BenchmarkManifest(
        schema_version=1,
        name="skip",
        inputs=[],
        variants=[],
        benchmark=BenchmarkSection(renderers=["ffmpeg"], formats=["png"]),
    )
    monkeypatch.setattr(benchmark, "load_and_expand", lambda *a, **kw: (manifest, [cell]))
    monkeypatch.setattr(
        benchmark, "run_argv", lambda *a: SimpleNamespace(returncode=0, stdout="tool test\n")
    )
    summary = benchmark.run_benchmark(tmp_path / "manifest", output_dir=tmp_path / "out")
    cell_report = summary["cells"][0]
    assert summary["counts"]["skipped"] == 1
    assert cell_report["planned_action"] == "SKIP"
    assert cell_report["actual_status"] == "NOT_RUN"
    assert cell_report["wall_seconds"] is None
    assert cell_report["render_fps"] is None
    assert cell_report["resources"] is None
