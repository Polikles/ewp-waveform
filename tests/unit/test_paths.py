from pathlib import Path

from ewp_waveform.paths import normalize_user_path


def test_windows_drive_path_maps_to_mnt() -> None:
    assert normalize_user_path(r"D:\podkast\s0e00.wav") == Path("/mnt/d/podkast/s0e00.wav")
    assert normalize_user_path("D:/podkast/s0e00.wav") == Path("/mnt/d/podkast/s0e00.wav")


def test_posix_path_is_unchanged() -> None:
    assert normalize_user_path("/mnt/d/podkast/s0e00.wav") == Path("/mnt/d/podkast/s0e00.wav")


def test_quoted_windows_path() -> None:
    assert normalize_user_path('"C:\\Users\\me\\a.wav"') == Path("/mnt/c/Users/me/a.wav")
