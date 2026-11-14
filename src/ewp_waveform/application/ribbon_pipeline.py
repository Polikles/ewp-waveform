"""Bounded one-frame lookahead for the serial refined-ribbon CPU route only."""

from __future__ import annotations

import sys
from collections.abc import Generator, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import cast


@contextmanager
def ribbon_frame_pipeline(frames: Iterable[bytes]) -> Iterator[Iterator[bytes]]:
    """Overlap exactly one next() with the consumer's blocking frame write.

    There is one producer, one pending future and one consumer-owned frame.
    Production frames are immutable bytes, not borrowed/reused array buffers.
    Cancellation joins the bounded in-flight production step before closing its
    source. This cannot interrupt arbitrary user code; only the finite CPU
    generator is admitted by the calling route. Unconsumed future failures are
    discarded on cancellation, never substituted for a primary encoder failure.
    """
    source = iter(frames)
    end = object()
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ribbon-frame")

    def ordered() -> Generator[bytes, None, None]:
        # Lazy: no production during FFmpeg/LUT setup or a pre-feed refusal.
        pending = pool.submit(next, source, end)
        try:
            while True:
                frame = pending.result()
                if frame is end:
                    return
                pending = pool.submit(next, source, end)
                yield cast(bytes, frame)
        finally:
            pending.cancel()

    iterator = ordered()
    try:
        yield iterator
    finally:
        primary = sys.exception()
        iterator.close()
        pool.shutdown(wait=True, cancel_futures=True)
        close = getattr(source, "close", None)
        if close is not None:
            try:
                close()
            except BaseException as error:
                if primary is None:
                    raise
                primary.add_note(f"ribbon frame source cleanup failed: {error}")
