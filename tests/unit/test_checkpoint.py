from pathlib import Path

from ewp_waveform.application.checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    Checkpoint,
    ChunkRecord,
    chunk_record_reusable,
    identity_matches,
    load_checkpoint,
    png_chunk_complete,
    resolve_workdir,
    reusable_chunk_indices,
    workdir_key,
    write_checkpoint,
)
from ewp_waveform.application.chunks import LogicalChunk, ProcessingWindow
from ewp_waveform.config.models import PerformanceProfile
from ewp_waveform.identity import sha256_file


def _checkpoint(**overrides: object) -> Checkpoint:
    payload: dict[str, object] = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "source_sha256": "abc",
        "render_signature": "sig",
        "visual_contract_version": 12,
        "renderer": "ffmpeg",
        "fps": 10.0,
        "clip_start": 0.0,
        "clip_duration": 0.6,
        "chunk_seconds": 0.25,
        "expected_frames": 6,
        "want_mov": True,
        "want_png": False,
        "peak": 0.4,
        "completed_chunks": [],
    }
    payload.update(overrides)
    return Checkpoint.model_validate(payload)


def test_workdir_key_is_stable_and_excludes_unrelated_paths() -> None:
    a = workdir_key(
        render_signature="sig",
        clip_start=0.0,
        clip_duration=1.0,
        want_mov=True,
        want_png=False,
    )
    b = workdir_key(
        render_signature="sig",
        clip_start=0.0,
        clip_duration=1.0,
        want_mov=True,
        want_png=False,
    )
    other = workdir_key(
        render_signature="sig",
        clip_start=0.0,
        clip_duration=2.0,
        want_mov=True,
        want_png=False,
    )
    assert a == b
    assert a != other
    assert len(a) == 12


def test_resolve_workdir_uses_performance_root(tmp_path: Path) -> None:
    profile = PerformanceProfile(
        schema_version=1,
        name="t",
        processing={},
        workdirs={"root": str(tmp_path / "work")},
    )
    path = resolve_workdir(profile, "abcdefghijkl")
    assert path == tmp_path / "work" / "ewp-abcdefghijkl"


def test_load_checkpoint_rejects_stale_schema(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    write_checkpoint(path, _checkpoint(schema_version=CHECKPOINT_SCHEMA_VERSION))
    raw = path.read_text(encoding="utf-8").replace(
        f'"schema_version": {CHECKPOINT_SCHEMA_VERSION}',
        '"schema_version": 99',
    )
    path.write_text(raw, encoding="utf-8")
    assert load_checkpoint(path) is None


def test_load_checkpoint_rejects_garbage(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    path.write_text("{not-json", encoding="utf-8")
    assert load_checkpoint(path) is None


def test_identity_matches_requires_signature_and_source() -> None:
    checkpoint = _checkpoint()
    assert (
        identity_matches(
            checkpoint,
            source_sha256="abc",
            render_signature="sig",
            visual_contract_version=12,
            renderer="ffmpeg",
            fps=10.0,
            clip_start=0.0,
            clip_duration=0.6,
            chunk_seconds=0.25,
            expected_frames=6,
            want_mov=True,
            want_png=False,
        )
        is True
    )
    assert (
        identity_matches(
            checkpoint,
            source_sha256="abc",
            render_signature="other",
            visual_contract_version=12,
            renderer="ffmpeg",
            fps=10.0,
            clip_start=0.0,
            clip_duration=0.6,
            chunk_seconds=0.25,
            expected_frames=6,
            want_mov=True,
            want_png=False,
        )
        is False
    )
    assert (
        identity_matches(
            checkpoint,
            source_sha256="zzz",
            render_signature="sig",
            visual_contract_version=12,
            renderer="ffmpeg",
            fps=10.0,
            clip_start=0.0,
            clip_duration=0.6,
            chunk_seconds=0.25,
            expected_frames=6,
            want_mov=True,
            want_png=False,
        )
        is False
    )
    assert (
        identity_matches(
            checkpoint,
            source_sha256="abc",
            render_signature="sig",
            visual_contract_version=11,
            renderer="ffmpeg",
            fps=10.0,
            clip_start=0.0,
            clip_duration=0.6,
            chunk_seconds=0.25,
            expected_frames=6,
            want_mov=True,
            want_png=False,
        )
        is False
    )


def test_chunk_record_reusable_checks_hash_and_size(tmp_path: Path) -> None:
    mov = tmp_path / "chunk-0000.mov"
    mov.write_bytes(b"segment")
    record = ChunkRecord(
        index=0,
        first_frame=0,
        n_frames=3,
        start_seconds=0.0,
        end_seconds=0.3,
        mov_name="chunk-0000.mov",
        mov_sha256=sha256_file(mov),
    )
    assert chunk_record_reusable(tmp_path, record, want_mov=True, want_png=False) is True
    mov.write_bytes(b"tampered")
    assert chunk_record_reusable(tmp_path, record, want_mov=True, want_png=False) is False
    mov.write_bytes(b"")
    assert chunk_record_reusable(tmp_path, record, want_mov=True, want_png=False) is False


def test_reusable_chunk_indices_require_matching_plan(tmp_path: Path) -> None:
    mov = tmp_path / "chunk-0000.mov"
    mov.write_bytes(b"segment")
    record = ChunkRecord(
        index=0,
        first_frame=0,
        n_frames=3,
        start_seconds=0.0,
        end_seconds=0.3,
        mov_name="chunk-0000.mov",
        mov_sha256=sha256_file(mov),
    )
    checkpoint = _checkpoint(completed_chunks=[record.model_dump()])
    window = ProcessingWindow(
        chunk=LogicalChunk(index=0, first_frame=0, n_frames=3, fps=10.0),
        decode_start=0.0,
        decode_duration=0.3,
    )
    assert reusable_chunk_indices(
        tmp_path, checkpoint, [window], want_mov=True, want_png=False
    ) == [0]
    shifted = ProcessingWindow(
        chunk=LogicalChunk(index=0, first_frame=3, n_frames=3, fps=10.0),
        decode_start=0.3,
        decode_duration=0.3,
    )
    assert (
        reusable_chunk_indices(tmp_path, checkpoint, [shifted], want_mov=True, want_png=False) == []
    )


def test_png_chunk_complete_requires_contiguous_nonempty_frames(tmp_path: Path) -> None:
    png = tmp_path / "png"
    png.mkdir()
    (png / "frame_000001.png").write_bytes(b"a")
    (png / "frame_000002.png").write_bytes(b"b")
    assert png_chunk_complete(png, first_frame=0, n_frames=2) is True
    (png / "frame_000002.png").write_bytes(b"")
    assert png_chunk_complete(png, first_frame=0, n_frames=2) is False
