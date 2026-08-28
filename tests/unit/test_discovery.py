from pathlib import Path

import pytest

from ewp_waveform.discovery.scan import DiscoveryError, discover_paths


def test_single_wav(tmp_path: Path) -> None:
    wav = tmp_path / "s0e00-Szymon.wav"
    wav.write_bytes(b"RIFF")
    assert discover_paths(wav) == [wav.resolve()]


def test_rejects_non_mvp_suffix(tmp_path: Path) -> None:
    flac = tmp_path / "x.flac"
    flac.write_bytes(b"fLaC")
    with pytest.raises(DiscoveryError) as exc:
        discover_paths(flac)
    assert exc.value.diagnostic.code.value == "E_INPUT_UNSUPPORTED"


def test_directory_non_recursive(tmp_path: Path) -> None:
    (tmp_path / "a.wav").write_bytes(b"RIFF")
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "b.wav").write_bytes(b"RIFF")
    found = discover_paths(tmp_path)
    assert [p.name for p in found] == ["a.wav"]


def test_directory_recursive(tmp_path: Path) -> None:
    (tmp_path / "a.mp3").write_bytes(b"ID3")
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "b.wav").write_bytes(b"RIFF")
    found = discover_paths(tmp_path, recursive=True)
    assert sorted(p.name for p in found) == ["a.mp3", "b.wav"]
