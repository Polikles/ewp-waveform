from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from ewp_waveform.application.portable_experiments_reporting import diagnostic_bundle, report

PAYLOAD_CAP = 2 * 1024**2 - 128 * 1024


@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_critical_measurement_uses_actual_packet_payload_budget(tmp_path: Path, delta: int) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "report-boundary-diagnostics.json").write_text("{}")
    path = reports / "measurements-boundary.json"
    prefix_size = len(json.dumps({"phase_bytes": ""}).encode())
    data = json.dumps({"phase_bytes": "x" * (PAYLOAD_CAP + delta - prefix_size)}).encode()
    assert len(data) == PAYLOAD_CAP + delta
    path.write_bytes(data)
    packet = tmp_path / "diagnostics.zip"
    if delta > 0:
        with pytest.raises(ValueError, match="critical measurements"):
            diagnostic_bundle(tmp_path, packet)
        assert not packet.exists()
    else:
        result = diagnostic_bundle(tmp_path, packet)
        with zipfile.ZipFile(packet) as archive:
            assert archive.read("reports/measurements-boundary.json") == data
        assert result["uncompressed_bytes"] <= 2 * 1024**2


def test_report_to_packet_refuses_oversized_critical_export_without_truncation(
    tmp_path: Path,
) -> None:
    value = {"fixture": {"status": "SUCCEEDED", "phase_evidence": "x" * (PAYLOAD_CAP + 1)}}
    path = report(tmp_path, "COMPLETE", None, None, value)
    full = json.loads(path.with_suffix(".json").read_text())
    assert full["status"] == "COMPLETE" and full["error"] is None
    assert full["results"] == value
    assert full["packaging"]["status"] == "REFUSED"
    assert "critical measurements" in full["packaging"]["error"]
    assert "Status: **REFUSED** (separate from render status)" in path.read_text()
    measurements = list((tmp_path / "reports").glob("measurements-*.json"))
    assert len(measurements) == 1
    assert json.loads(measurements[0].read_text())["results"] == value
    assert not list((tmp_path / "reports").glob("*.zip"))
