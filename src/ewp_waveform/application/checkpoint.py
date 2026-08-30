"""Workdir checkpoints for chunk resume (ADR-0006, FR-RESUME-006/007)."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ValidationError

from ewp_waveform.application.chunks import ProcessingWindow
from ewp_waveform.config.models import PerformanceProfile
from ewp_waveform.identity import sha256_file, short_signature

CHECKPOINT_SCHEMA_VERSION = 1
CHECKPOINT_NAME = "checkpoint.json"


class ChunkRecord(BaseModel):
    index: int
    first_frame: int
    n_frames: int
    start_seconds: float
    end_seconds: float
    mov_name: str | None = None
    mov_sha256: str | None = None
    png_count: int | None = None


class Checkpoint(BaseModel):
    schema_version: int
    source_sha256: str
    render_signature: str
    visual_contract_version: int | str
    renderer: str
    fps: float
    clip_start: float
    clip_duration: float
    chunk_seconds: float
    expected_frames: int
    want_mov: bool
    want_png: bool
    peak: float | None = None
    preroll_seconds: float = 0.0
    postroll_seconds: float = 0.0
    completed_chunks: list[ChunkRecord] = []


def workdir_key(
    *,
    render_signature: str,
    clip_start: float,
    clip_duration: float,
    want_mov: bool,
    want_png: bool,
) -> str:
    payload = {
        "sig": render_signature,
        "clip_start": round(clip_start, 9),
        "clip_duration": round(clip_duration, 9),
        "want_mov": want_mov,
        "want_png": want_png,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


DEFAULT_WORK_PARENT = "ewp-waveform-work"


def default_work_root() -> Path:
    return Path(tempfile.gettempdir()) / DEFAULT_WORK_PARENT


def resolve_workdir(performance: PerformanceProfile, key: str) -> Path:
    """Deterministic workdir so a later run can find kept failure state."""
    raw_root = performance.workdirs.get("root")
    base = Path(raw_root) if isinstance(raw_root, str) and raw_root.strip() else default_work_root()
    return base / f"ewp-{short_signature(key) if len(key) > 12 else key}"


def checkpoint_path(work: Path) -> Path:
    return work / CHECKPOINT_NAME


def write_checkpoint(path: Path, checkpoint: Checkpoint) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(checkpoint.model_dump_json(indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_checkpoint(path: Path) -> Checkpoint | None:
    """Return a schema-valid checkpoint or None. Invalid files are not reused."""
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        checkpoint = Checkpoint.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError, TypeError, ValueError):
        return None
    if checkpoint.schema_version != CHECKPOINT_SCHEMA_VERSION:
        return None
    return checkpoint


def identity_matches(
    checkpoint: Checkpoint,
    *,
    source_sha256: str,
    render_signature: str,
    visual_contract_version: int | str,
    renderer: str,
    fps: float,
    clip_start: float,
    clip_duration: float,
    chunk_seconds: float,
    expected_frames: int,
    want_mov: bool,
    want_png: bool,
) -> bool:
    return (
        checkpoint.source_sha256 == source_sha256
        and checkpoint.render_signature == render_signature
        and checkpoint.visual_contract_version == visual_contract_version
        and checkpoint.renderer == renderer
        and abs(checkpoint.fps - fps) < 1e-9
        and abs(checkpoint.clip_start - clip_start) < 1e-9
        and abs(checkpoint.clip_duration - clip_duration) < 1e-9
        and abs(checkpoint.chunk_seconds - chunk_seconds) < 1e-9
        and checkpoint.expected_frames == expected_frames
        and checkpoint.want_mov == want_mov
        and checkpoint.want_png == want_png
    )


def reset_workdir(work: Path) -> None:
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)


def png_frame_path(png_dir: Path, frame_number: int) -> Path:
    return png_dir / f"frame_{frame_number:06d}.png"


def png_chunk_complete(png_dir: Path, *, first_frame: int, n_frames: int) -> bool:
    if n_frames < 1:
        return False
    for number in range(first_frame + 1, first_frame + n_frames + 1):
        frame = png_frame_path(png_dir, number)
        if not frame.is_file() or frame.stat().st_size <= 0:
            return False
    return True


def chunk_record_reusable(
    work: Path,
    record: ChunkRecord,
    *,
    want_mov: bool,
    want_png: bool,
) -> bool:
    """True when checkpointed artifacts are still the files we hashed/counted."""
    if want_mov:
        if not record.mov_name or not record.mov_sha256:
            return False
        mov = work / record.mov_name
        if not mov.is_file() or mov.stat().st_size <= 0:
            return False
        if sha256_file(mov) != record.mov_sha256:
            return False
    if want_png:
        if record.png_count != record.n_frames:
            return False
        if not png_chunk_complete(
            work / "png", first_frame=record.first_frame, n_frames=record.n_frames
        ):
            return False
    return True


def reusable_chunk_indices(
    work: Path,
    checkpoint: Checkpoint,
    windows: Sequence[ProcessingWindow],
    *,
    want_mov: bool,
    want_png: bool,
) -> list[int]:
    """Completed records whose plan row and artifacts still match."""
    by_index = {window.chunk.index: window for window in windows}
    reused: list[int] = []
    for record in checkpoint.completed_chunks:
        window = by_index.get(record.index)
        if window is None:
            continue
        if (
            record.first_frame != window.chunk.first_frame
            or record.n_frames != window.chunk.n_frames
        ):
            continue
        if chunk_record_reusable(work, record, want_mov=want_mov, want_png=want_png):
            reused.append(record.index)
    return reused
