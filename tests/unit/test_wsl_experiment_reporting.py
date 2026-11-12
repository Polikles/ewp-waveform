"""Pure synthetic reporting tests: no media commands or genuine benchmark claims."""

from __future__ import annotations

import copy
import hashlib
import json
from html import unescape
from pathlib import Path
from typing import Any

import pytest

from ewp_waveform.application import experiment_suite as app
from ewp_waveform.application import experiment_suite_reporting as reporting
from ewp_waveform.application import experiment_suite_state as state
from ewp_waveform.application.experiments import save_new


def snapshot() -> dict[str, Any]:
    """Invented unit records, never performance evidence or a qualified session."""
    planned: list[dict[str, Any]] = [
        {"id": ident, "scenario": scenario, "workload": "short", "pair": pair, "role": role}
        for ident, scenario, pair, role in (
            ("cpu", "B", "transfer-1", "control"),
            ("transfer", "C", "transfer-1", "candidate"),
            ("missing-old", "A", None, None),
            ("unsupported", "F1", None, None),
            ("failed", "D", None, None),
            ("pending", "E1", None, None),
        )
    ]
    artifact = {
        "path": "/not-opened/native with space.mov",
        "sha256": "a" * 64,
        "bytes": 123,
        "role": "TESTED_NATIVE_MASTER",
    }
    attempts: dict[str, Any] = {
        "cpu": {
            "status": "SUCCEEDED",
            "actual_action": "PROCESS",
            "throughput_fresh": True,
            "wall_seconds": 10.0,
            "worker_wall_seconds": 12.0,
            "scope": reporting.SERVICE_SCOPE,
            "timer": "synthetic service bounds",
            "output": artifact["path"],
            "artifacts": [artifact],
            "validation": {
                "passed": True,
                "decoded_rgba_sha256": "b" * 64,
                "validation_seconds": 0.5,
            },
        },
        "missing-old": {
            "status": "SKIPPED",
            "actual_action": "NOT_RUN",
            "reason": "OLD_BUILD_NOT_PROVIDED",
            "worker_wall_seconds": 0.1,
        },
        "unsupported": {
            "status": "SKIPPED",
            "actual_action": "NOT_RUN",
            "reason": "CAPABILITY_UNAVAILABLE: encoder absent",
            "worker_wall_seconds": 0.1,
        },
        "failed": {
            "status": "FAILED",
            "actual_action": "UNKNOWN",
            "error": "wrong device",
            "worker_wall_seconds": 1.0,
        },
    }
    attempts["transfer"] = {**copy.deepcopy(attempts["cpu"]), "wall_seconds": 8.0}
    attempts["views-cpu"] = {
        "status": "SUCCEEDED",
        "worker_wall_seconds": 3.0,
        "artifacts": [
            {**artifact, "role": "COMPARISON_MOV_SAME_MASTER"},
            {
                "path": "/not-opened/dark.mp4",
                "sha256": "c" * 64,
                "bytes": 45,
                "role": "OPAQUE_VIEW_DARK",
                "generation_seconds": 0.3,
                "validation": {"passed": True, "validation_seconds": 0.1},
            },
        ],
    }
    return {
        "schema_version": 1,
        "status": "HOLD",
        "source": {
            "git_head_and_tree": ["synthetic-head", "synthetic-tree"],
            "environment": {"VK_ICD_FILENAMES": "synthetic"},
            "dependencies": {},
        },
        "tool_identity": {"new": {"ffmpeg": {"path": "/selected/ffmpeg", "sha256": "d" * 64}}},
        "build": None,
        "device": "requested device, not observation",
        "settings": {
            "cells": planned,
            "workloads": [
                {"id": "short", "kind": "short", "start": 25.0, "duration": 4.0, "frames": 240}
            ],
        },
        "cells": [
            {
                **c,
                "status": attempts.get(c["id"], {}).get("status", "NOT_RUN"),
                "result": attempts.get(c["id"], {}),
            }
            for c in planned
        ],
        "pairs": [
            {
                "id": "transfer-1",
                "control": "cpu",
                "candidate": "transfer",
                "status": "PAIRED",
                "decoded_rgba_equal": True,
            }
        ],
        "attempts": attempts,
        "visual": "PENDING",
        "studio": "PENDING",
        "promotion": "NOT_APPROVED",
        "fresh_measurements_added_by_export": 0,
    }


def test_report_complete_boundaries_statuses_and_dedup() -> None:
    payload = snapshot()
    before = copy.deepcopy(payload)
    report = reporting.render_report(payload)
    assert payload == before
    for text in (
        "synthetic-head",
        "/selected/ffmpeg",
        "Requested device selector",
        "OLD_BUILD_NOT_PROVIDED",
        "CAPABILITY_UNAVAILABLE",
        "wrong device",
        "pending — E1",
        "NOT_RUN=1",
        "SKIPPED=2",
        "FAILED=1",
        "10.000000 | 8.000000 | -20.000",
        "planned pairs=1, eligible paired observations=1",
        "recorded native bytes=123",
        "Operator visual assessment: PENDING",
        "Resolve Studio native import/alpha/playback: PENDING",
        "Promotion: NOT_APPROVED",
        "File-byte identity",
        "Decoded-frame equality",
        "not an additive total",
        "never sum",
        "External strict verification: 0.500000",
        "Initial host/resources (unavailable in older exports)",
        "fixture preparation is separate",
        "view/proxy generation=0.300000 s; verification=0.100000 s",
        "not pure encoder time",
        "Record",
        "No historical VM-versus-WSL GPU speedup",
        "Recorded unique visual content hashes: 2",
        "native%20with%20space.mov",
    ):
        assert text in unescape(report)
    assert report.count("### SHA-256 " + "a" * 64) == 1
    assert "COMPARISON_MOV_SAME_MASTER" in unescape(report)
    assert "not a new run, ledger verification, artifact readback or acceptance" in report


@pytest.mark.parametrize(
    "mutation",
    [
        "failed",
        "skipped",
        "reused",
        "unvalidated",
        "unknown",
        "zero",
        "negative",
        "bool",
        "scope",
        "decoded",
        "hold",
    ],
)
def test_unqualified_pairs_never_get_change(mutation: str) -> None:
    payload = snapshot()
    result = payload["cells"][1]["result"]
    if mutation in ("failed", "skipped", "unknown"):
        result["status"] = mutation.upper()
        payload["cells"][1]["status"] = result["status"]
    elif mutation == "reused":
        result["throughput_fresh"] = False
    elif mutation == "unvalidated":
        result["validation"]["passed"] = False
    elif mutation in ("zero", "negative", "bool"):
        result["wall_seconds"] = {"zero": 0, "negative": -1, "bool": True}[mutation]
    elif mutation == "scope":
        result["scope"] = reporting.CODEC_SCOPE
    elif mutation == "decoded":
        result["validation"]["decoded_rgba_sha256"] = "e" * 64
    else:
        payload["pairs"][0]["status"] = "HOLD"
    report = reporting.render_report(payload)
    assert "-20.000" not in report
    assert "eligible paired observations=0" in report
    assert "| unavailable |" in report


def test_codec_package_requires_same_fixture_and_stays_separate() -> None:
    payload = snapshot()
    for i, scenario in enumerate(("F0", "F1")):
        for cell in (payload["cells"][i], payload["settings"]["cells"][i]):
            cell["scenario"] = scenario
        payload["cells"][i]["result"].update(
            scope=reporting.CODEC_SCOPE, fixture_rgba_sha256="f" * 64
        )
    payload["attempts"]["fixture-short"] = {
        "status": "SUCCEEDED",
        "preparation_seconds": 7.0,
        "worker_wall_seconds": 9.0,
        "validation": {"passed": True, "validation_seconds": 1.0},
    }
    report = reporting.render_report(payload)
    assert "-20.000" in report
    assert (
        "| fixture-short | SUCCEEDED | 9.000000 | unavailable | 7.000000 | 1.000000 |"
        in unescape(report)
    )
    del payload["cells"][1]["result"]["fixture_rgba_sha256"]
    report = reporting.render_report(payload)
    assert "common decoded fixture identity unavailable or different" in report
    assert "-20.000" not in report


def test_derived_overflow_is_unavailable_not_infinite_speedup() -> None:
    payload = snapshot()
    payload["cells"][0]["result"]["wall_seconds"] = 1e-300
    payload["cells"][1]["result"]["wall_seconds"] = 1e300
    report = reporting.render_report(payload)
    assert "nonfinite derived wall-time change" in unescape(report)
    assert "eligible paired observations=0" in report


def test_unlike_factor_and_workload_do_not_get_rankings() -> None:
    payload = snapshot()
    for cell in (payload["cells"][1], payload["settings"]["cells"][1]):
        cell["scenario"] = "F1"
    assert "unlike workload or unsupported factor" in reporting.render_report(payload)


def test_repeat_counts_are_not_export_count() -> None:
    payload = snapshot()
    for i, role in enumerate(("candidate", "control")):
        original = payload["cells"][1 if i == 0 else 0]
        row = copy.deepcopy(original)
        row.update(id=role + "2", pair="transfer-2")
        payload["cells"].append(row)
        payload["settings"]["cells"].append(
            {k: row[k] for k in ("id", "scenario", "workload", "pair", "role")}
        )
        payload["attempts"][row["id"]] = row["result"]
    payload["pairs"].append(
        {"id": "transfer-2", "control": "control2", "candidate": "candidate2", "status": "PAIRED"}
    )
    a = reporting.render_report(payload)
    b = reporting.render_report(payload)
    assert a == b
    assert (
        "planned pairs=2, eligible paired observations=2; control/candidate observations=2/2" in a
    )
    assert "Small sequential samples" in a


def test_retained_helper_pins_bytes_never_opens_media_or_checks_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = snapshot()
    # Model a historical test's mutated/deleted media: JSON survives unchanged.
    media = tmp_path / "retained-synthetic.txt"
    media.write_text("corrupted after export")
    path = tmp_path / "export.json"
    path.write_text(json.dumps(payload))
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("live authority must not be used by diagnostic presentation")

    monkeypatch.setattr(app, "session_at", forbidden)
    monkeypatch.setattr(state, "verify_artifact", forbidden)
    before = {p: p.read_bytes() for p in tmp_path.iterdir()}
    report = reporting.render_retained_export(path, expected_sha256=digest)
    assert "HISTORICAL / UNVERIFIED-MEDIA DIAGNOSTIC" in unescape(report)
    assert "NOT fresh verification or session approval" in report
    assert "linked files are not rehashed here" in report
    assert {p: p.read_bytes() for p in tmp_path.iterdir()} == before
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        reporting.render_retained_export(path, expected_sha256=digest)


@pytest.mark.parametrize("raw", [b"{}", b"[]", b'{"schema_version":1,"schema_version":1}', b"{bad"])
def test_retained_rejects_malformed_bytes(tmp_path: Path, raw: bytes) -> None:
    path = tmp_path / "bad.json"
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        reporting.render_retained_export(path, expected_sha256=hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize("mutation", ["duplicate", "mismatch", "pair", "nan", "infinity"])
def test_snapshot_corruption_refused(mutation: str) -> None:
    payload = snapshot()
    if mutation == "duplicate":
        payload["cells"][1]["id"] = "cpu"
    elif mutation == "mismatch":
        payload["cells"][0]["result"] = {}
    elif mutation == "pair":
        payload["pairs"] = []
    else:
        payload["arbitrary"] = float("nan" if mutation == "nan" else "inf")
    with pytest.raises(ValueError):
        reporting.render_report(payload)


def live_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    payload = snapshot()
    manifest = payload["settings"]
    manifest["cells"] = [manifest["cells"][0]]
    manifest["cells"][0].update(pair=None, role=None)
    session = {
        "manifest": manifest,
        "source": payload["source"],
        "tools": payload["tool_identity"],
        "build": None,
        "device": "synthetic 请求",
        "initial_resources": {"platform": "test"},
    }
    monkeypatch.setattr(app, "session_at", lambda _: session)
    result = copy.deepcopy(payload["attempts"]["cpu"])
    # Real ledger has only real tiny text artifacts, not invented media records.
    output = tmp_path / "synthetic-text-not-media.txt"
    output.write_text('synthetic "text", 请求\n')
    result.update(output=str(output), artifacts=[state.artifact(output, "TESTED_NATIVE_MASTER")])
    result["scope"] += ', "quoted" 请求'
    save_new(tmp_path / "request.json", {})
    save_new(tmp_path / "terminal.json", result)
    ledger = state.Ledger(tmp_path)
    ledger.append("STARTED", "cpu", request=state.artifact(tmp_path / "request.json"))
    ledger.append("FINISHED", "cpu", result=state.artifact(tmp_path / "terminal.json"))
    return session


def test_live_export_exact_byte_admission_immutable_and_zero_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_fixture(tmp_path, monkeypatch)
    estimates: list[dict[str, Any]] = []

    def admission(session: Any, estimate: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        assert not (tmp_path / "exports").exists() or len(estimates) > 0
        estimates.append(estimate)
        return {}

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("export must not execute media")

    monkeypatch.setattr(app, "check_envelope", admission)
    monkeypatch.setattr(app, "execute", forbidden)
    before = (tmp_path / "ledger.jsonl").read_bytes()
    first = app.export_results(tmp_path)
    files = {p: p.read_bytes() for p in (tmp_path / "exports").iterdir()}
    assert len(files) == 4
    assert estimates[0]["growth_bytes"] == sum(len(v) for v in files.values())
    assert Path(first["report"]).is_file()
    assert (
        json.loads(Path(first["json"]).read_text())["environment"]["initial_resources"]["platform"]
        == "test"
    )
    second = app.export_results(tmp_path)
    assert first["report"] != second["report"]
    assert all(p.read_bytes() == content for p, content in files.items())
    new = [p for p in (tmp_path / "exports").iterdir() if p not in files]
    assert estimates[1]["growth_bytes"] == sum(p.stat().st_size for p in new)
    assert (tmp_path / "ledger.jsonl").read_bytes() == before


def test_refused_export_creates_no_partial_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live_fixture(tmp_path, monkeypatch)

    def refused(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("growth admission/monitor limit")

    monkeypatch.setattr(app, "check_envelope", refused)
    before = {p: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(RuntimeError, match="growth admission"):
        app.export_results(tmp_path)
    assert not (tmp_path / "exports").exists()
    assert {p: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_live_artifact_mutation_still_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_fixture(tmp_path, monkeypatch)
    (tmp_path / "synthetic-text-not-media.txt").write_text("changed after ledger seal")
    with pytest.raises(ValueError, match="artifact mutation"):
        app.export_results(tmp_path)
    assert not (tmp_path / "exports").exists()


def test_views_disabled_is_not_pending() -> None:
    payload = snapshot()
    payload["settings"]["workloads"][0]["kind"] = "full"
    del payload["attempts"]["views-cpu"]
    assert "NOT_REQUESTED (full_views=false)" in unescape(reporting.render_report(payload))


@pytest.mark.parametrize("digest", ["", "A" * 64, "a" * 63, " a" * 32])
def test_retained_requires_literal_digest(tmp_path: Path, digest: str) -> None:
    with pytest.raises(ValueError, match="literal lowercase SHA-256"):
        reporting.render_retained_export(tmp_path / "missing.json", expected_sha256=digest)


def test_live_source_drift_not_bypassed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def drift(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("source/interpreter/dependency/environment/host identity drift")

    monkeypatch.setattr(app, "session_at", drift)
    with pytest.raises(ValueError, match="identity drift"):
        app.export_results(tmp_path)
    assert not list(tmp_path.iterdir())


class _RenderedTables:
    """Inspect rendered Markdown tables, not merely pipe-delimited source lines."""

    @staticmethod
    def parse(report: str) -> list[list[list[str]]]:
        from html.parser import HTMLParser

        from markdown_it import MarkdownIt

        class Reader(HTMLParser):
            def __init__(self) -> None:
                super().__init__(convert_charrefs=True)
                self.tables: list[list[list[str]]] = []
                self.row: list[str] | None = None
                self.cell: list[str] | None = None

            def handle_starttag(self, tag: str, attrs: Any) -> None:
                if tag == "table":
                    self.tables.append([])
                elif tag == "tr":
                    self.row = []
                elif tag in ("th", "td"):
                    self.cell = []

            def handle_data(self, data: str) -> None:
                if self.cell is not None:
                    self.cell.append(data)

            def handle_endtag(self, tag: str) -> None:
                if tag in ("th", "td") and self.row is not None and self.cell is not None:
                    self.row.append("".join(self.cell))
                    self.cell = None
                elif tag == "tr" and self.row is not None:
                    self.tables[-1].append(self.row)
                    self.row = None

        reader = Reader()
        reader.feed(MarkdownIt("commonmark").enable("table").render(report))
        return reader.tables


def test_costs_render_every_attempt_before_details() -> None:
    payload = snapshot()
    payload["attempts"]["views-transfer"] = {
        "status": "SUCCEEDED",
        "comparison_validation": {
            "passed": True,
            "validation_seconds": 0.125,
            "synthetic_edge_abs_delta": 123456789,
        },
        "artifacts": [],
    }
    # Masters, skip/failure reasons and comparison details must not terminate rows.
    payload["attempts"]["later-attempt"] = {"status": "NOT_RUN", "reason": "synthetic later"}
    report = reporting.render_report(payload)
    tables = _RenderedTables.parse(report)
    costs = next(table for table in tables if table[0][0] == "Attempt")
    assert [row[0] for row in costs[1:]] == list(payload["attempts"])
    assert all(len(row) == 6 for row in costs)
    details = report.index("### Attempt details")
    assert report.index("| later&#45;attempt |") < details
    assert report.index("reason/error:", details) > details
    assert report.index('"synthetic_edge_abs_delta": 123456789', details) > details
    assert "view/proxy generation=" in report[details:]


@pytest.mark.parametrize("order", ["control-first", "candidate-first"])
@pytest.mark.parametrize("passed", [True, False])
def test_comparison_evidence_visible_in_both_orders(order: str, passed: bool) -> None:
    payload = snapshot()
    for where in (payload["cells"], payload["settings"]["cells"]):
        where[0]["scenario"], where[1]["scenario"] = "C", "D"
    candidate = payload["attempts"]["transfer"]
    candidate["validation"]["decoded_rgba_sha256"] = "c" * 64
    payload["pairs"][0]["decoded_rgba_equal"] = False
    metric = {
        "passed": passed,
        "validation_seconds": 0.125,
        "decoded_rgba_sha256": "c" * 64,
        "lossless_against_preencode": False,
        "edge_halo_composite_integer_metrics": {"synthetic_edge_abs_delta": 123456789},
        "temporal_alpha_absolute_delta_sum": 456789,
        "visual": "PENDING",
        "studio": "PENDING",
    }
    if order == "control-first":
        candidate["validation"].update(metric)
    else:
        for where in (payload["cells"], payload["settings"]["cells"]):
            where[:2] = where[:2][::-1]
        payload["attempts"]["views-transfer"] = {
            "status": "SUCCEEDED" if passed else "FAILED",
            "comparison_validation": metric,
            "artifacts": [],
        }
    before = copy.deepcopy(payload)
    report = reporting.render_report(payload)
    assert payload == before
    assert '"synthetic_edge_abs_delta": 123456789' in report
    assert '"temporal_alpha_absolute_delta_sum": 456789' in report
    assert '"lossless_against_preencode": false' in report
    assert f'"passed": {str(passed).lower()}' in report
    assert '"decoded_rgba_sha256": "' + "c" * 64 + '"' in report
    if order == "candidate-first":
        assert "candidate=transfer; control=cpu" in report
        assert "recorded pair status=PAIRED; recorded decoded RGBA equal=False" in report
        assert f"comparison passed: {passed}" in report
        assert "Attempt status: " + ("SUCCEEDED" if passed else "FAILED") in report
    pair_table = next(t for t in _RenderedTables.parse(report) if t[0][0] == "Pair")
    assert pair_table[1][4] == "False"  # Equality is not inferred from passed.
    assert pair_table[1][5] == (
        ("SUCCEEDED / True" if passed else "FAILED / False")
        if order == "candidate-first"
        else "unavailable / unavailable"
    )
    assert "this report grants no approval" in report
    assert "Promotion: " + reporting._text("NOT_APPROVED") in report
    assert payload["visual"] == payload["studio"] == "PENDING"


def test_front_overview_all_planned_cells_identity_and_pairs_before_json() -> None:
    payload = snapshot()
    payload["source"].update(
        imported_product_version="0.4.1",
        installed_distribution_version="0.4.1",
        interpreter="/synthetic/python",
        platform="synthetic host",
        cpu_model_observed="test CPU",
    )
    report = reporting.render_report(payload)
    front = report.split("## Every planned cell", 1)[0]
    assert "```json" not in front
    assert front.index("## At a glance") < front.index("### Identity summary")
    assert front.index("### Identity summary") < front.index("## Explicit paired comparisons only")
    assert reporting._text("synthetic-head") in front
    assert reporting._text("synthetic-tree") in front
    assert reporting._text("/synthetic/python") in front
    assert reporting._text("/selected/ffmpeg") in front
    assert "d" * 64 in front
    assert "-20.000" in front
    overview = _RenderedTables.parse(front)[0]
    assert overview[0] == [
        "Cell (scenario / workload)",
        "Status",
        "Scope",
        "Wall s",
        "Native bytes",
        "Validation passed",
    ]
    assert len(overview) == len(payload["cells"]) + 1
    assert [row[0].split(" (", 1)[0] for row in overview[1:]] == [c["id"] for c in payload["cells"]]
    assert overview[1][1:] == ["SUCCEEDED", "SERVICE", "10.000000", "123", "True"]
    assert overview[-1][1:] == ["NOT_RUN"] + ["unavailable"] * 4
    assert [row[1] for row in overview[1:]] == [c["status"] for c in payload["cells"]]
    assert report.index("## Appendix") > report.index("## Visual assessment navigation")


def test_diagnostic_inline_markdown_and_html_are_literal() -> None:
    import string
    from html.parser import HTMLParser

    from markdown_it import MarkdownIt

    diagnostic = (
        r"file [review](https://invalid.example/) **APPROVED** _accept_ ![image](bad) "
        r"<script>alert(1)</script> `code` ~~strike~~ \\ &#42; " + string.punctuation + "\nnext"
    )

    class Reader(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.tags: list[str] = []
            self.data: list[str] = []

        def handle_starttag(self, tag: str, attrs: Any) -> None:
            self.tags.append(tag)

        def handle_data(self, text: str) -> None:
            self.data.append(text)

    reader = Reader()
    reader.feed(MarkdownIt("commonmark").render(reporting._text(diagnostic)))
    assert reader.tags == ["p"]
    assert "".join(reader.data).strip() == diagnostic.replace("\n", " ")
    payload = snapshot()
    payload["attempts"]["failed"]["error"] = diagnostic
    html = MarkdownIt("commonmark").enable("table").render(reporting.render_report(payload))
    assert 'href="https://invalid.example/"' not in html
    assert "<strong>APPROVED</strong>" not in html
    assert "<script>" not in html


@pytest.mark.parametrize("role", ["control", "candidate", None])
def test_retained_refuses_extra_pair_member(tmp_path: Path, role: str | None) -> None:
    payload = snapshot()
    extra = copy.deepcopy(payload["cells"][0])
    extra.update(id="extra", role=role)
    payload["cells"].append(extra)
    payload["settings"]["cells"].append(
        {k: extra[k] for k in ("id", "scenario", "workload", "pair", "role")}
    )
    payload["attempts"]["extra"] = extra["result"]
    path = tmp_path / "checksum-valid-but-inconsistent.json"
    raw = json.dumps(payload).encode()
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="exactly its control and candidate"):
        reporting.render_retained_export(path, expected_sha256=hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize("mutation", ["same-reference", "missing-member", "wrong-role"])
def test_pair_requires_exact_referenced_role_members(mutation: str) -> None:
    payload = snapshot()
    if mutation == "same-reference":
        payload["pairs"][0]["candidate"] = "cpu"
    elif mutation == "missing-member":
        for where in (payload["cells"], payload["settings"]["cells"]):
            where[1]["pair"] = None
    else:
        for where in (payload["cells"], payload["settings"]["cells"]):
            where[1]["role"] = "control"
    with pytest.raises(ValueError, match="pair"):
        reporting.render_report(payload)
