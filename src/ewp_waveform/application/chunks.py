"""Logical chunk ranges and overlap windows (ADR-0006, docs/22).

Chunk size is a performance concern. Frame partitioning is exact so concat
neither drops nor duplicates canonical frames.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LogicalChunk:
    index: int
    first_frame: int
    n_frames: int
    fps: float

    @property
    def start_seconds(self) -> float:
        return self.first_frame / self.fps

    @property
    def end_seconds(self) -> float:
        return (self.first_frame + self.n_frames) / self.fps


@dataclass(frozen=True)
class ProcessingWindow:
    """Decode more context than the logical chunk publishes."""

    chunk: LogicalChunk
    decode_start: float
    decode_duration: float


def plan_chunks(duration: float, fps: float, chunk_seconds: float) -> list[LogicalChunk]:
    """Partition ``duration`` into contiguous frame ranges.

    Non-positive ``chunk_seconds`` means a single chunk covering the whole job.
    """
    if fps <= 0:
        msg = "fps must be positive"
        raise ValueError(msg)
    total = max(1, round(max(duration, 0.0) * fps))
    per = total if chunk_seconds <= 0 else min(total, max(1, round(chunk_seconds * fps)))
    chunks: list[LogicalChunk] = []
    start = 0
    index = 0
    while start < total:
        n_frames = min(per, total - start)
        chunks.append(LogicalChunk(index=index, first_frame=start, n_frames=n_frames, fps=fps))
        start += n_frames
        index += 1
    return chunks


def processing_window(
    chunk: LogicalChunk,
    *,
    source_duration: float,
    preroll: float,
    postroll: float,
) -> ProcessingWindow:
    """Map a logical chunk to a decode window clamped to the source clip."""
    decode_start = max(0.0, chunk.start_seconds - max(preroll, 0.0))
    decode_end = min(source_duration, chunk.end_seconds + max(postroll, 0.0))
    duration = max(0.0, decode_end - decode_start)
    return ProcessingWindow(chunk=chunk, decode_start=decode_start, decode_duration=duration)


def bin_origin(decode_start: float, sample_rate: int, hop: float) -> float:
    """Dense-bin index of decoded sample 0 on the clip timeline."""
    if hop <= 0.0:
        msg = "hop must be positive"
        raise ValueError(msg)
    return decode_start * float(sample_rate) / hop
