from pathlib import Path

from ewp_waveform.application.render import output_is_complete, publish_path


def test_publish_path_skips_nonempty_file(tmp_path: Path) -> None:
    dest = tmp_path / "out.mov"
    dest.write_bytes(b"not-empty")
    path, skip = publish_path(dest, force=False)
    assert path == dest
    assert skip is True


def test_publish_path_does_not_skip_empty_file(tmp_path: Path) -> None:
    dest = tmp_path / "out.mov"
    dest.write_bytes(b"")
    path, skip = publish_path(dest, force=False)
    assert path == dest
    assert skip is False
    assert output_is_complete(dest) is False


def test_publish_path_force_versions_complete_file(tmp_path: Path) -> None:
    dest = tmp_path / "out.mov"
    dest.write_bytes(b"not-empty")
    path, skip = publish_path(dest, force=True)
    assert path == tmp_path / "out_v002.mov"
    assert skip is False


def test_publish_path_skips_png_dir_with_frames(tmp_path: Path) -> None:
    dest = tmp_path / "out_png"
    dest.mkdir()
    (dest / "frame_000001.png").write_bytes(b"png")
    path, skip = publish_path(dest, force=False)
    assert path == dest
    assert skip is True


def test_publish_path_does_not_skip_empty_png_dir(tmp_path: Path) -> None:
    dest = tmp_path / "out_png"
    dest.mkdir()
    _path, skip = publish_path(dest, force=False)
    assert skip is False
