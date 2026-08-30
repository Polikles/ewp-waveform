from ewp_waveform.application.chunks import bin_origin, plan_chunks, processing_window


def test_plan_chunks_covers_every_frame_once() -> None:
    chunks = plan_chunks(duration=2.5, fps=60.0, chunk_seconds=1.0)
    frames: list[int] = []
    for chunk in chunks:
        frames.extend(range(chunk.first_frame, chunk.first_frame + chunk.n_frames))
    assert frames == list(range(150))
    assert [chunk.n_frames for chunk in chunks] == [60, 60, 30]


def test_plan_chunks_single_when_shorter_than_chunk() -> None:
    chunks = plan_chunks(0.5, 60.0, 60.0)
    assert len(chunks) == 1
    assert chunks[0].n_frames == 30
    assert chunks[0].first_frame == 0


def test_plan_chunks_nonpositive_is_one_window() -> None:
    chunks = plan_chunks(10.0, 60.0, 0.0)
    assert len(chunks) == 1
    assert chunks[0].n_frames == 600


def test_processing_window_clamps_file_start() -> None:
    chunk = plan_chunks(120.0, 60.0, 60.0)[0]
    window = processing_window(chunk, source_duration=120.0, preroll=5.1, postroll=0.1)
    assert window.decode_start == 0.0
    assert window.decode_duration == 60.0 + 0.1


def test_processing_window_prerolls_later_chunks() -> None:
    chunk = plan_chunks(180.0, 60.0, 60.0)[1]
    window = processing_window(chunk, source_duration=180.0, preroll=5.1, postroll=0.08)
    assert abs(window.decode_start - (60.0 - 5.1)) < 1e-12
    assert abs(window.decode_duration - (5.1 + 60.0 + 0.08)) < 1e-12


def test_bin_origin_is_decode_start_in_hops() -> None:
    assert abs(bin_origin(1.5, 48000, 48.0) - 1500.0) < 1e-12
