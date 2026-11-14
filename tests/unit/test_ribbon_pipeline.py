from __future__ import annotations

import threading
from collections.abc import Generator
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from ewp_waveform.application.render_fixed import validate_ribbon_frame_prefetch
from ewp_waveform.application.ribbon_pipeline import ribbon_frame_pipeline
from ewp_waveform.config.models import PerformanceProfile


def _threads() -> set[int | None]:
    return {t.ident for t in threading.enumerate() if t.name.startswith("ribbon-frame")}


@pytest.mark.parametrize("count", [0, 1, 2, 3, 17])
def test_order_odd_empty_single_and_one_producer(count: int) -> None:
    before = _threads()
    producers = set()
    closed = []

    def frames() -> Generator[bytes, None, None]:
        try:
            for i in range(count):
                producers.add(threading.get_ident())
                yield bytes([i])
        finally:
            closed.append(True)

    with ribbon_frame_pipeline(frames()) as feed:
        assert list(feed) == [bytes([i]) for i in range(count)]
    assert len(producers) == min(count, 1)
    assert threading.get_ident() not in producers
    assert closed == [True] and _threads() == before


def test_lazy_and_bounded_one_pending_frame() -> None:
    produced = []
    second = threading.Event()

    def frames() -> Generator[bytes, None, None]:
        for i in range(10):
            produced.append(i)
            if i == 1:
                second.set()
            yield bytes([i])

    before = _threads()
    with ribbon_frame_pipeline(frames()) as feed:
        assert produced == []
        assert next(feed) == b"\x00"
        assert second.wait(2)
        assert produced == [0, 1]  # no third request until consumer advances
    assert produced == [0, 1] and _threads() == before


def test_pending_step_drained_before_close_on_early_consumer_failure() -> None:
    before = _threads()
    started = threading.Event()
    release = threading.Event()
    closed = threading.Event()
    joined = threading.Event()
    errors: list[BaseException] = []

    def frames() -> Generator[bytes, None, None]:
        try:
            yield b"first"
            started.set()
            assert release.wait(2)
            raise ValueError("unconsumed producer failure")
        finally:
            closed.set()

    primary = RuntimeError("encoder failed")

    def consume() -> None:
        try:
            with ribbon_frame_pipeline(frames()) as feed:
                assert next(feed) == b"first"
                assert started.wait(2)
                raise primary
        except BaseException as error:
            errors.append(error)
        finally:
            joined.set()

    consumer = threading.Thread(target=consume)
    consumer.start()
    try:
        assert started.wait(2)
        assert not joined.is_set() and not closed.is_set()
    finally:
        release.set()
        consumer.join(3)
    assert not consumer.is_alive()
    assert errors == [primary] and closed.is_set() and _threads() == before


def test_iterator_failure_is_original_and_no_thread_leaks() -> None:
    before = _threads()
    primary = LookupError("field failed")

    def frames() -> Generator[bytes, None, None]:
        yield b"frame"
        raise primary

    with pytest.raises(LookupError) as caught, ribbon_frame_pipeline(frames()) as feed:
        assert next(feed) == b"frame"
        next(feed)
    assert caught.value is primary and _threads() == before


@pytest.mark.parametrize("consume", [False, True])
def test_source_closed_even_on_pre_feed_failure_and_cleanup_cannot_mask_primary(
    consume: bool,
) -> None:
    class Source:
        closed = False

        def __iter__(self) -> Source:
            return self

        def __next__(self) -> bytes:
            return b"frame"

        def close(self) -> None:
            self.closed = True
            raise OSError("close failed")

    source = Source()
    primary = RuntimeError("encode failed")
    before = _threads()
    with pytest.raises(RuntimeError) as caught, ribbon_frame_pipeline(source) as feed:
        if consume:
            assert next(feed) == b"frame"
        raise primary
    assert caught.value is primary and source.closed
    assert "close failed" in primary.__notes__[0]
    assert _threads() == before


@pytest.mark.parametrize("value", [0, 1, "true", "false", None, [], {}, 1.0])
def test_setting_strict_bool(value: object) -> None:
    with pytest.raises(ValidationError, match="ribbon_frame_prefetch"):
        PerformanceProfile(
            schema_version=1, name="bad", processing={"ribbon_frame_prefetch": value}
        )


@pytest.mark.parametrize(
    "change",
    [
        {"appearance": None},
        {"profile": "moving-mouth-v1"},
        {"ribbon_finish": None},
        {"geometry": "temporal"},
        {"field_plan": None},
        {"producing_mov": False},
        {"producing_png": True},
        {"experiment": True},
        {"jobs": 2},
        {"jobs": True},
        {"jobs": "1"},
    ],
)
def test_unsupported_refused_explicitly(change: dict[str, Any]) -> None:
    processing = {"jobs": change.get("jobs", 1), "ribbon_frame_prefetch": True}
    profile = PerformanceProfile(schema_version=1, name="test", processing=processing)
    appearance = SimpleNamespace(
        profile=change.get("profile", "filled-ribbon-v2"),
        ribbon_finish=change.get("ribbon_finish", ()),
        field_plan=change.get("field_plan", object()),
        geometry=change.get("geometry", "spectrum"),
    )
    with pytest.raises(ValueError, match="serial jobs=1 refined-ribbon"):
        validate_ribbon_frame_prefetch(
            profile,
            change.get("appearance", appearance),
            producing_mov=change.get("producing_mov", True),
            producing_png=change.get("producing_png", False),
            experiment=change.get("experiment", False),
        )


def test_default_disabled_accepts_unrelated_routes() -> None:
    profile = PerformanceProfile(schema_version=1, name="default")
    assert not validate_ribbon_frame_prefetch(
        profile, None, producing_mov=False, producing_png=True, experiment=True
    )
