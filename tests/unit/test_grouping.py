from pathlib import Path

from ewp_waveform.domain.grouping import ids_for_path, split_project_track


def test_split_on_first_separator() -> None:
    assert split_project_track("s0e00-Szymon-Kowalski") == ("s0e00", "Szymon-Kowalski")


def test_ungrouped_filename_is_valid() -> None:
    assert split_project_track("interview") == ("interview", "interview")


def test_ids_for_path_uses_stem() -> None:
    assert ids_for_path(Path("s0e00-Damian.wav")) == ("s0e00", "Damian")
