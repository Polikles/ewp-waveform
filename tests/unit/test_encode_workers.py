from ewp_waveform.application.render import (
    _FIELD_POOL_MIN_FRAMES,
    _encode_worker_threads,
    _field_frame_ranges,
    _job_workers,
)
from ewp_waveform.config.load import load_performance
from ewp_waveform.config.models import PerformanceProfile


def _profile(jobs: object) -> PerformanceProfile:
    return PerformanceProfile(schema_version=1, name="x", processing={"jobs": jobs})


def test_job_workers_is_positive_int() -> None:
    assert _job_workers(_profile(4)) == 4
    assert _job_workers(_profile(0)) == 1
    assert _job_workers(_profile(2.5)) == 1
    assert _job_workers(_profile(True)) == 1
    assert _job_workers(_profile("2")) == 1


def test_balanced_profile_requests_two_workers() -> None:
    assert _job_workers(load_performance("balanced")) == 2
    assert _job_workers(load_performance("maximum")) == 4


def test_encode_worker_threads_pin_auto_when_parallel() -> None:
    assert _encode_worker_threads(0, 1) == 0
    assert _encode_worker_threads(0, 2) == 1
    assert _encode_worker_threads(8, 4) == 8


def test_field_frame_ranges_cover_every_frame_without_gaps() -> None:
    ranges = _field_frame_ranges(480, 4)
    assert ranges == [(0, 120), (120, 120), (240, 120), (360, 120)]
    assert _field_frame_ranges(10, 4) == [(0, 3), (3, 3), (6, 2), (8, 2)]
    assert _field_frame_ranges(3, 8) == [(0, 1), (1, 1), (2, 1)]
    assert _FIELD_POOL_MIN_FRAMES == 1800
