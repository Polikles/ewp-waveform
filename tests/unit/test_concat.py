from pathlib import Path

from ewp_waveform.ffmpeg.concat import concat_list_line


def test_concat_list_line_quotes_and_escapes(tmp_path: Path) -> None:
    path = tmp_path / "chunk-000.mov"
    path.write_bytes(b"x")
    line = concat_list_line(path)
    assert line.startswith("file '")
    assert line.endswith("'")
    assert str(path.resolve()) in line


def test_concat_list_line_escapes_single_quotes(tmp_path: Path) -> None:
    path = tmp_path / "chunk's.mov"
    path.write_bytes(b"x")
    line = concat_list_line(path)
    assert r"'\''" in line
