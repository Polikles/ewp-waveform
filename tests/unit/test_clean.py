from pathlib import Path

from ewp_waveform.application.clean import clean_workdirs, list_workdirs


def test_clean_workdirs_only_touches_ewp_prefix(tmp_path: Path) -> None:
    keep = tmp_path / "other"
    keep.mkdir()
    (keep / "file.txt").write_text("x", encoding="utf-8")
    target = tmp_path / "ewp-abcd1234ef00"
    target.mkdir()
    (target / "checkpoint.json").write_text("{}", encoding="utf-8")
    found = list_workdirs(tmp_path)
    assert found == [target]
    removed = clean_workdirs(root=tmp_path, dry_run=True)
    assert removed == [target]
    assert target.is_dir()
    removed = clean_workdirs(root=tmp_path, dry_run=False)
    assert removed == [target]
    assert not target.exists()
    assert keep.is_dir()
