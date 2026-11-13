"""Read-only presentation of suite snapshots; never execution or acceptance authority."""

from __future__ import annotations

import hashlib
import json
import math
import re
import string
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

SERVICE_SCOPE = "ACTUAL_APPLICATION_SERVICE_RENDER_VALIDATION_PUBLICATION"
CODEC_SCOPE = "SHARED_COMPRESSED_FIXTURE_DECODE_CONVERSION_ENCODE_CONTAINER"
CONTRASTS = {("A", "B"), ("B", "C"), ("C", "D"), ("E0", "E1"), ("F0", "F1")}
VISUAL_ROLES = {
    "TESTED_NATIVE_MASTER",
    "COMPARISON_MOV_SAME_MASTER",
    "COMPARISON_PROXY_NOT_NATIVE_FFV1",
    "OPAQUE_VIEW_DARK",
    "OPAQUE_VIEW_LIGHT",
    "OPAQUE_VIEW_CHECKER",
}


def _text(value: Any) -> str:
    if value is None:
        return "unavailable"
    # Character references keep all inline Markdown/HTML punctuation literal,
    # including backslashes and attacker-supplied entities; never interpret diagnostics.
    return "".join(
        f"&#{ord(char)};" if char in string.punctuation else char
        for char in str(value).replace("\r", " ").replace("\n", " ")
    )


def _number(value: Any, *, positive: bool = False) -> bool:
    return (
        type(value) in (int, float)
        and math.isfinite(value)
        and (value > 0 if positive else value >= 0)
    )


def _seconds(value: Any) -> str:
    return f"{value:.6f}" if _number(value) else "unavailable"


def _digest(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _fresh(result: dict[str, Any]) -> bool:
    return (
        result.get("status") == "SUCCEEDED"
        and result.get("actual_action") == "PROCESS"
        and result.get("throughput_fresh") is True
        and result.get("validation", {}).get("passed") is True
        and _number(result.get("wall_seconds"), positive=True)
    )


def _link(path: str) -> str:
    # Absolute recorded paths only; do not stat, resolve, hash or open linked media.
    return (
        f"[open](<{quote('file://' + path, safe='/:')}>)"
        if path.startswith("/")
        else "no absolute link"
    )


def _artifact_groups(attempts: dict[str, Any]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for ident, result in attempts.items():
        for item in result.get("artifacts", []):
            digest = item.get("sha256")
            if item.get("role") not in VISUAL_ROLES or not _digest(digest):
                continue
            group = groups.setdefault(digest, {"sha256": digest, "entries": []})
            entry = {"attempt": ident, **item}
            if entry not in group["entries"]:
                group["entries"].append(entry)
    return list(groups.values())


def _pair_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    cells = {c["id"]: c for c in payload["cells"]}
    pairs = []
    for pair in payload["pairs"]:
        a, b = cells[pair["control"]], cells[pair["candidate"]]
        av, bv = a["result"], b["result"]
        contrast = (a["scenario"], b["scenario"])
        reason = None
        if contrast not in CONTRASTS or a["workload"] != b["workload"]:
            reason = "unlike workload or unsupported factor"
        elif not all(_fresh(v) for v in (av, bv)):
            reason = "requires two fresh successful validated positive-time PROCESS observations"
        elif av.get("scope") != bv.get("scope") or av.get("scope") != (
            CODEC_SCOPE if contrast == ("F0", "F1") else SERVICE_SCOPE
        ):
            reason = "missing or unlike timer scopes"
        elif contrast == ("F0", "F1") and not (
            _digest(av.get("fixture_rgba_sha256"))
            and av.get("fixture_rgba_sha256") == bv.get("fixture_rgba_sha256")
        ):
            reason = "common decoded fixture identity unavailable or different"
        hashes = [v.get("validation", {}).get("decoded_rgba_sha256") for v in (av, bv)]
        equality = hashes[0] == hashes[1] if all(_digest(h) for h in hashes) else None
        if contrast in (("B", "C"), ("F0", "F1")) and equality is not True:
            reason = "required decoded equality missing or different"
        if pair.get("status") != "PAIRED":
            reason = "recorded pair " + str(pair.get("status", "unavailable"))
        change = None if reason else 100 * (bv["wall_seconds"] / av["wall_seconds"] - 1)
        if change is not None and not math.isfinite(change):
            reason, change = "nonfinite derived wall-time change", None
        pairs.append(
            {
                "id": pair["id"],
                "control": a,
                "candidate": b,
                "reason": reason,
                "change": change,
                "equality": equality,
                "scope": av.get("scope"),
                "contrast": contrast,
            }
        )
    return pairs


def _native_bytes(result: dict[str, Any]) -> Any:
    for item in result.get("artifacts", []):
        if item.get("path") == result.get("output") and item.get("role") == "TESTED_NATIVE_MASTER":
            return item.get("bytes")
    return None


def _overview(payload: dict[str, Any]) -> list[str]:
    lines = [
        "## At a glance",
        "",
        "Every planned cell; wall is recorded attempted time, not necessarily eligible throughput.",
        "Native size is recorded bytes for the output master; missing is unavailable, not zero.",
        "Scopes: SERVICE = service render/validation/publication; CODEC = shared-fixture",
        "decode/conversion/encode/container. External verification and views are separate costs.",
        "",
        "| Cell (scenario / workload) | Status | Scope | Wall s | "
        "Native bytes | Validation passed |",
        "|---|---|---|---:|---:|---|",
    ]
    for cell in payload["cells"]:
        result = cell["result"]
        scope = {SERVICE_SCOPE: "SERVICE", CODEC_SCOPE: "CODEC"}.get(
            result.get("scope"), result.get("scope")
        )
        lines.append(
            f"| {_text(cell['id'])} ({_text(cell['scenario'])} / {_text(cell['workload'])}) | "
            f"{_text(cell['status'])} | {_text(scope)} | "
            f"{_seconds(result.get('wall_seconds'))} | {_text(_native_bytes(result))} | "
            f"{_text(result.get('validation', {}).get('passed'))} |"
        )
    source = payload.get("source") or {}
    identity = source.get("git_head_and_tree") or []
    lines.extend(
        [
            "",
            "### Identity summary — recorded, not reverified",
            "",
            f"- Source HEAD / tree: {_text(identity[0] if identity else None)} / "
            f"{_text(identity[1] if len(identity) > 1 else None)}.",
            "- Product / installed distribution: "
            f"{_text(source.get('imported_product_version'))} / "
            f"{_text(source.get('installed_distribution_version'))}; "
            f"interpreter: {_text(source.get('interpreter'))}.",
            f"- Host: {_text(source.get('platform'))}; "
            f"CPU: {_text(source.get('cpu_model_observed'))}.",
            f"- Requested device selector (not observed use): {_text(payload.get('device'))}.",
        ]
    )
    tools = payload.get("tool_identity") or {}
    for build, selected in tools.items():
        if selected:
            for name, tool in selected.items():
                lines.append(
                    f"- {_text(build)} / {_text(name)}: {_text(tool.get('path'))}; "
                    f"SHA-256 {_text(tool.get('sha256'))}."
                )
    if not tools:
        lines.append("- Selected tool identities: unavailable.")
    lines.append("Full source/environment/tool/build provenance is in the appendix.")
    return lines


def render_report(payload: dict[str, Any], *, snapshot: str = "in-memory snapshot") -> str:
    """Format recorded data only; no live source/tool/media checks or status changes."""
    _validate_snapshot(payload)
    attempts = payload["attempts"]
    pairs = _pair_rows(payload)
    lines = [
        "# WSL experiment report",
        "",
        f"Snapshot: {_text(snapshot)}",
        f"Recorded technical matrix status: **{_text(payload['status'])}**.",
        "Presentation only: not a new run, ledger verification, artifact readback or acceptance.",
        "Export adds **0 fresh measurements**. Missing costs are unavailable, never zero.",
        "",
        *_overview(payload),
        "",
        "## Independent acceptance axes",
        "",
        "- Technical validity: per-cell recorded validation below; not visual acceptance.",
        "- File-byte identity: recorded artifact SHA-256 only; linked files are not rehashed here.",
        "- Decoded-frame equality: paired decoded RGBA hashes below, not container byte identity.",
        f"- Operator visual assessment: {_text(payload.get('visual'))} "
        "(not inferred from metrics).",
        f"- Resolve Studio native import/alpha/playback: {_text(payload.get('studio'))}.",
        f"- Promotion: {_text(payload.get('promotion'))}; this report grants no approval.",
    ]
    appendix = [
        "",
        "## Appendix — frozen source, environment, tools and device",
        "",
        f"Requested device selector (not an observation): {_text(payload.get('device'))}.",
        "Observed device evidence remains in retained preflight/command artifacts; a selector or",
        "advertised encoder alone does not prove the device actually used.",
    ]
    for name, value in (
        ("Source/interpreter/dependencies/environment", payload.get("source")),
        ("Initial host/resources (unavailable in older exports)", payload.get("environment")),
        ("Selected tool identities", payload.get("tool_identity")),
        ("Build provenance", payload.get("build")),
        (
            "Installed provenance (observations, not a source-build receipt)",
            payload.get("installed_provenance"),
        ),
        ("Tool qualification", payload.get("build_qualification")),
        (
            "VM.1 environment reference (not an isolated GPU comparison)",
            payload.get("vm_reference"),
        ),
        ("Recorded preflight runtime", attempts.get("preflight", {}).get("runtime")),
    ):
        appendix.extend(
            [
                "",
                f"### {name}",
                "",
                "```json",
                json.dumps(value, indent=2, sort_keys=True, allow_nan=False),
                "```",
            ]
        )
    counts = Counter(c["status"] for c in payload["cells"])
    cell_details = [
        "",
        "## Every planned cell",
        "",
        "Status counts: " + ", ".join(f"{_text(k)}={v}" for k, v in sorted(counts.items())),
        "NOT_RUN includes pending/unattempted cells; skip reasons distinguish unsupported",
        "capabilities from absent optional tools. Failures are not reclassified as unsupported.",
    ]
    workloads = {w["id"]: w for w in payload["settings"]["workloads"]}
    for cell in payload["cells"]:
        result = cell["result"]
        w = workloads[cell["workload"]]
        validation = result.get("validation", {})
        verification_seconds = result.get(
            "external_verification_seconds", validation.get("validation_seconds")
        )
        output = result.get("output")
        size = _native_bytes(result)
        eligible_wall = result.get("wall_seconds") if _fresh(result) else None
        views_status = attempts.get("views-" + cell["id"], {}).get("status")
        if views_status is None:
            views_status = (
                "NOT_REQUESTED (full_views=false)"
                if w.get("kind") == "full" and not payload["settings"].get("full_views", False)
                else "PENDING/NOT_RUN"
                if result.get("status") == "SUCCEEDED"
                else "NOT_RUN (cell not succeeded)"
            )
        cell_details.extend(
            [
                "",
                f"### {_text(cell['id'])} — {_text(cell['scenario'])} / {_text(cell['workload'])}",
                f"- Status: {_text(cell['status'])}; action: {_text(result.get('actual_action'))}; "
                f"fresh PROCESS eligible: {_fresh(result)}.",
                f"- Reason/error: {_text(result.get('reason', result.get('error')))}.",
                f"- Workload: kind={_text(w.get('kind'))}, start={_text(w.get('start'))} s, "
                f"requested duration={_text(w.get('duration'))} s, "
                f"frames={_text(w.get('frames'))}.",
                f"- Route/scope: {_text(result.get('route'))} / {_text(result.get('scope'))}.",
                f"- Timer boundaries: {_text(result.get('timer'))}.",
                f"- Recorded attempted wall: {_seconds(result.get('wall_seconds'))} s; "
                f"eligible wall: {_seconds(eligible_wall)} s.",
                f"- Service CPU accounting: {_text(result.get('cpu_seconds'))}.",
                f"- Output: {_text(output)}; recorded native bytes={_text(size)}.",
                f"- Technical validation passed: {_text(validation.get('passed'))}; "
                f"decoded RGBA SHA-256: {_text(validation.get('decoded_rgba_sha256'))}.",
                "- External strict verification: "
                f"{_seconds(verification_seconds)} s; "
                f"views attempt: {_text(views_status)}.",
                "- Validation detail (metrics are descriptive, not acceptance):",
                "",
                "```json",
                json.dumps(validation, indent=2, sort_keys=True, allow_nan=False),
                "```",
            ]
        )
    lines.extend(
        [
            "",
            "## Explicit paired comparisons only",
            "",
            "Change = 100 * (candidate/control - 1); negative means less wall time.",
            "No historical VM-versus-WSL GPU speedup, service-versus-codec or ProRes-versus-FFV1",
            "ranking is calculated. E/F are backend packages including conversion/upload, "
            "not pure encoder time.",
            "Decoded equality below is derived only from recorded cell RGBA hashes. "
            "Late views comparison status/passed is separate; neither establishes visual "
            "acceptance or promotion. Full comparison evidence follows in attempt details.",
            "",
            "| Pair | Control seconds | Candidate seconds | Change % | "
            "Decoded RGBA equal | Views status / comparison passed | Eligibility |",
            "|---|---:|---:|---:|---|---|---|",
        ]
    )
    repetitions: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for pair in pairs:
        a, b = pair["control"], pair["candidate"]
        av, bv = a["result"], b["result"]
        views = attempts.get("views-" + b["id"], {})
        comparison = views.get("comparison_validation") or {}
        change = "unavailable" if pair["change"] is None else f"{pair['change']:+.3f}"
        lines.append(
            f"| {_text(pair['id'])} ({_text(a['id'])} → {_text(b['id'])}) | "
            f"{_seconds(av.get('wall_seconds'))} | {_seconds(bv.get('wall_seconds'))} | "
            f"{change} | {_text(pair['equality'])} | "
            f"{_text(views.get('status'))} / {_text(comparison.get('passed'))} | "
            f"{_text(pair['reason'] or 'comparable recorded pair')} |"
        )
        repetitions[(*pair["contrast"], a["workload"], str(pair["scope"]))].append(pair)
    if not pairs:
        lines.append("No planned paired comparisons.")
    lines.extend(["", "### Repetitions and limits", ""])
    for group, values in repetitions.items():
        eligible = sum(v["change"] is not None for v in values)
        lines.append(
            f"- {_text(' / '.join(group))}: planned pairs={len(values)}, "
            f"eligible paired observations={eligible}; control/candidate observations="
            f"{sum(_fresh(v['control']['result']) for v in values)}/"
            f"{sum(_fresh(v['candidate']['result']) for v in values)}."
        )
    lines.extend(
        [
            "Counts refer to unique planned cells, not exports/resume/readback. "
            "Small sequential samples",
            "are descriptive only: no significance, confidence interval, universal GPU claim "
            "or automatic promotion.",
            *cell_details,
            "",
            "## Costs — separate scopes, not an additive total",
            "",
            "Service wall includes service validation/publication but excludes setup, "
            "external strict checks and views.",
            "Codec wall includes common fixture decode/conversion/encode/container; "
            "fixture preparation is separate.",
            "Worker envelopes include orchestration/validation; accounted time may include "
            "reserved receipt allowance.",
            "Inclusive production phase spans overlap: never sum them or subtract envelopes "
            "into guessed costs.",
            "",
            "| Attempt | Status | Worker envelope s | Accounted s | "
            "Fixture prep s | External verification s |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for ident, result in attempts.items():
        verification_seconds = result.get(
            "external_verification_seconds", result.get("validation", {}).get("validation_seconds")
        )
        lines.append(
            f"| {_text(ident)} | {_text(result.get('status'))} | "
            f"{_seconds(result.get('worker_wall_seconds'))} | "
            f"{_seconds(result.get('accounted_wall_seconds'))} | "
            f"{_seconds(result.get('preparation_seconds'))} | "
            f"{_seconds(verification_seconds)} |"
        )
    lines.extend(["", "### Attempt details — separate from the costs table", ""])
    for ident, result in attempts.items():
        if result.get("reason") or result.get("error"):
            lines.append(
                f"\n{_text(ident)} reason/error: "
                f"{_text(result.get('reason', result.get('error')))}\n"
            )
        if result.get("comparison_validation") is not None:
            related = next(
                (p for p in payload["pairs"] if "views-" + p["candidate"] == ident), None
            )
            association = (
                f"pair={_text(related['id'])}; candidate={_text(related['candidate'])}; "
                f"control={_text(related['control'])}; "
                f"recorded pair status={_text(related.get('status'))}; "
                f"recorded decoded RGBA equal={_text(related.get('decoded_rgba_equal'))}"
                if related
                else "no planned candidate/control association recorded"
            )
            lines.extend(
                [
                    "",
                    f"#### {_text(ident)} — recorded comparison validation",
                    "",
                    f"{association}.",
                    f"Attempt status: {_text(result.get('status'))}; "
                    f"comparison passed: {_text(result['comparison_validation'].get('passed'))}.",
                    "Full recorded comparison evidence; metrics/equality are descriptive, "
                    "not visual acceptance, a threshold verdict or promotion.",
                    "",
                    "```json",
                    json.dumps(
                        result["comparison_validation"], indent=2, sort_keys=True, allow_nan=False
                    ),
                    "```",
                ]
            )
        seen = set()
        for item in result.get("artifacts", []):
            key = (item.get("path"), item.get("sha256"), item.get("role"))
            if key in seen or item.get("role") not in VISUAL_ROLES:
                continue
            seen.add(key)
            lines.append(
                f"\n{_text(ident)} / {_text(item.get('role'))}: view/proxy generation="
                f"{_seconds(item.get('generation_seconds'))} s; verification="
                f"{_seconds(item.get('validation', {}).get('validation_seconds'))} s.\n"
            )
    groups = _artifact_groups(attempts)
    lines.extend(
        [
            "",
            "## Visual assessment navigation — recorded artifacts only",
            "",
            "One content group per recorded SHA-256, with all path/role aliases retained below.",
            "Comparison MOV may be the same native master; MKV comparison proxies do not prove",
            "native FFV1 Resolve acceptance. "
            "Opaque views do not prove transparent-master acceptance.",
            "No missing derivative is invented; use views status above. Links may be stale.",
            f"Recorded unique visual content hashes: {len(groups)}.",
        ]
    )
    for content in groups:
        lines.extend(["", f"### SHA-256 {content['sha256']}"])
        for item in content["entries"]:
            lines.append(
                f"- {_text(item['attempt'])}: {_text(item['role'])}; "
                f"bytes={_text(item.get('bytes'))}; {_text(item.get('path'))} "
                f"{_link(item['path'])}"
            )
    if not groups:
        lines.append("No hashed visual artifacts recorded.")
    lines.extend(appendix)
    return "\n".join(lines) + "\n"


def _validate_snapshot(payload: dict[str, Any]) -> None:
    """Reject malformed/inconsistent snapshots, without authenticating live state."""
    try:
        if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
            raise ValueError("unsupported schema")
        if not isinstance(payload["status"], str) or not isinstance(payload["attempts"], dict):
            raise ValueError("invalid status/attempts")
        if payload.get("fresh_measurements_added_by_export") != 0:
            raise ValueError("not a read-only export")
        cells, settings = payload["cells"], payload["settings"]
        if not isinstance(cells, list) or not cells or len(cells) != len(settings["cells"]):
            raise ValueError("incomplete planned cell list")
        ids = [c["id"] for c in cells]
        workloads = {w["id"] for w in settings["workloads"]}
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate cell")
        for cell, planned in zip(cells, settings["cells"], strict=True):
            if any(
                cell.get(k) != planned.get(k)
                for k in ("id", "scenario", "workload", "pair", "role")
            ):
                raise ValueError("cell/plan mismatch")
            if cell["workload"] not in workloads or not isinstance(cell["result"], dict):
                raise ValueError("unknown workload/result")
            result = payload["attempts"].get(cell["id"], {})
            if cell["result"] != result or cell["status"] != result.get("status", "NOT_RUN"):
                raise ValueError("cell/attempt mismatch")
        pair_ids = set()
        by_id = {c["id"]: c for c in cells}
        for pair in payload["pairs"]:
            if pair["id"] in pair_ids:
                raise ValueError("duplicate pair")
            pair_ids.add(pair["id"])
            members = [c["id"] for c in cells if c.get("pair") == pair["id"]]
            if len(members) != 2 or set(members) != {pair["control"], pair["candidate"]}:
                raise ValueError("pair must contain exactly its control and candidate")
            for role in ("control", "candidate"):
                member = by_id[pair[role]]
                if member.get("role") != role or member.get("pair") != pair["id"]:
                    raise ValueError("pair/member mismatch")
        if pair_ids != {c["pair"] for c in cells if c.get("pair")}:
            raise ValueError("incomplete pairs")
        # Also rejects NaN/Infinity from permissive JSON parsers, even in unused fields.
        json.dumps(payload, allow_nan=False)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("malformed suite export snapshot") from exc


def render_retained_export(export: Path, *, expected_sha256: str) -> str:
    """Read checksum-pinned historical JSON into text; no session guard bypass/write.

    The caller supplies a separately retained trusted digest and admits/writes the
    returned UTF-8 text to a fresh report path. This only checks snapshot bytes and
    structure, NOT ledger ancestry, current source identity, or linked artifacts.
    """
    if not _digest(expected_sha256):
        raise ValueError("literal lowercase SHA-256 required")
    if export.is_symlink() or not export.is_file():
        raise ValueError("regular retained JSON export required")
    raw = export.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("retained export SHA-256 mismatch")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate JSON key")
            obj[key] = value
        return obj

    payload = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(payload, dict):
        raise ValueError("suite export JSON object required")
    return render_report(
        cast(dict[str, Any], payload),
        snapshot=f"HISTORICAL / UNVERIFIED-MEDIA DIAGNOSTIC: {export}; "
        f"SHA-256 {expected_sha256}; checksum/structure only; "
        "recorded evidence, NOT fresh verification or session approval",
    )
