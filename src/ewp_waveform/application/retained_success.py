"""Read-only authentication of retained single-file CPU successes (stdlib only).

This is NOT resume, a render, a decode, or a repair of original status. Hashes
establish consistency with retained self-sealed evidence, not a signed independent
attestation. Historical source/tool/runtime identities are compared within frozen
records, never against today's checkout or a freshly probed environment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
from fractions import Fraction
from pathlib import Path
from typing import Any

# Deliberately narrow: new algorithms/backends require their own admission policy.
CONTROLS = {
    "single-file-direct-lut": "finish_lut",
    "single-file-short-lut": "finish_lut",
    "single-file-lut32": "finish_lut",
    "single-file-jobs32": "jobs",
}
CONTROL_KEYS = (
    "output_mode",
    "batch_size",
    "timing_mode",
    "codec",
    "encoder_threads",
    "filter_threads",
    "async_depth",
    "control",
    "crop",
    "margin",
    "finish_lut",
    "jobs",
    "torch_finish",
)
DIRECT_ROUTE = "EXPLICIT_SERIAL_PRODUCTION_FIXED_PIPELINE_NATIVE_NOT_SERVICE"
DIRECT_TIMER = (
    "selected finishing preparation plus perf_counter around run_fixed_pipeline "
    "including raster hash/feed/finish/encode; excludes planning, imports, external "
    "validation and views; no service publication"
)
SERVICE_TIMER = (
    "perf_counter immediately around actual service.render; external preplan and "
    "strict external validation excluded; imports/initialization/per-encode qualification "
    "inside render and production validation/publication included"
)
MAX_JSON_BYTES = 64 * 1024 * 1024
# Render/service spans are contained in the separately frozen cold worker span.
# Allow only 1ms absolute clock/serialization rounding, never a relative allowance.
TIMER_CONTAINMENT_TOLERANCE_SECONDS = 0.001


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def _json(data: bytes) -> dict[str, Any]:
    def reject(value: str) -> Any:
        raise ValueError("non-finite JSON constant: " + value)

    _require(len(data) <= MAX_JSON_BYTES, "JSON evidence exceeds read bound")
    value = json.loads(data, object_pairs_hook=_object, parse_constant=reject)
    _require(isinstance(value, dict), "expected JSON object")
    return value  # type: ignore[no-any-return]


def _load(path: Path) -> dict[str, Any]:
    _require(path.stat().st_size <= MAX_JSON_BYTES, "JSON evidence exceeds read bound")
    return _json(path.read_bytes())


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _digest(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def _identity_shape(item: dict[str, Any]) -> None:
    _require(
        set(item) == {"path", "resolved", "bytes", "sha256"}
        and isinstance(item["path"], str)
        and Path(item["path"]).is_absolute()
        and isinstance(item["resolved"], str)
        and Path(item["resolved"]).is_absolute()
        and type(item["bytes"]) is int
        and item["bytes"] >= 0
        and _digest(item["sha256"]),
        "malformed frozen file identity",
    )


def _identity(path: Path) -> dict[str, Any]:
    before = path.stat()
    resolved = str(path.resolve(strict=True))
    digest = _sha(path)
    after = path.stat()
    _require(
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        and str(path.resolve(strict=True)) == resolved,
        "evidence changed while hashing",
    )
    return {
        "path": str(path),
        "resolved": resolved,
        "bytes": after.st_size,
        "sha256": digest,
    }


def _verify(item: dict[str, Any]) -> None:
    _identity_shape(item)
    _require(_identity(Path(item["path"])) == item, "retained bytes changed: " + item["path"])


def _chain(run: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Check every byte of the prefix chain; quarantine ambiguous names only."""
    starts: dict[str, Any] = {}
    terminals: dict[str, Any] = {}
    incidents: list[dict[str, Any]] = []
    bad: set[str] = set()
    digest = hashlib.sha256()
    with (run / "events.jsonl").open("rb") as stream:
        for ordinal, line in enumerate(stream, 1):
            _require(line.endswith(b"\n"), "truncated event line")
            row = _json(line)
            _require(
                row.get("previous_sha256") == (digest.hexdigest() if ordinal > 1 else "0" * 64),
                "event hash chain changed",
            )
            digest.update(line)
            name, event = row["name"], row["event"]
            _require(
                isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]+", name) is not None,
                "unsafe event name",
            )
            if event == "STARTED":
                if name in starts or name in terminals:
                    bad.add(name)
                else:
                    starts[name] = {"row": row, "ordinal": ordinal}
            elif event in ("SUCCEEDED", "FAILED", "SKIPPED"):
                if name not in starts or name in terminals:
                    bad.add(name)
                else:
                    terminals[name] = {"row": row, "ordinal": ordinal}
            elif event == "DISPATCH_REFUSED":
                incidents.append(
                    {"name": name, "ordinal": ordinal, "event": event, "value": row.get("value")}
                )
            else:
                raise ValueError("unknown event: " + str(event))
    for name in sorted(bad | (starts.keys() - terminals.keys())):
        incidents.append(
            {
                "name": name,
                "event": "AMBIGUOUS_OR_ORPHAN",
                "reason": "duplicate/orphan event or unterminated STARTED",
            }
        )
        terminals.pop(name, None)
    return starts, terminals, incidents


def _config(run: Path) -> dict[str, Any]:
    seal = _load(run / "config-seal.json")
    _require(seal.get("path") == str(run / "config.json"), "config seal names another namespace")
    _verify(seal)
    config = _load(run / "config.json")
    _require(config["run"] == str(run), "config namespace identity mismatch")
    source = config["source"]
    _require(
        source["files"] and all(_digest(v) for v in source["files"].values()),
        "source manifest missing or malformed",
    )
    _require(
        hashlib.sha256(json.dumps(source["files"], sort_keys=True).encode()).hexdigest()
        == source["sha256"],
        "frozen source manifest digest mismatch",
    )
    for item in (
        config["audio"],
        config["environment"]["binary"],
        *config["selected"]["tools"].values(),
    ):
        _identity_shape(item)
    _require(
        config["environment"]["python"]
        == config["python"]
        == config["environment"]["binary"]["path"],
        "frozen interpreter identity mismatch",
    )
    # Inputs and retained inventory snapshots must still exist. Tool/runtime/source
    # payloads are historical identities, not requirements on the current install.
    for key in ("audio", "original", "original_observations"):
        _verify(config[key])
    return config


def _terminal(
    run: Path, name: str, start: dict[str, Any], terminal: dict[str, Any], config: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = run / "steps" / name
    request_identity = start["row"]["request"]
    _require(request_identity["path"] == str(root / "request.json"), "request path mismatch")
    _verify(request_identity)
    request = _load(root / "request.json")
    row = terminal["row"]
    _require(row["event"] == "SUCCEEDED", "not a successful terminal")
    artifacts: dict[str, Any] = {}
    for item in row["artifacts"]:
        _require(item["path"] not in artifacts, "duplicate terminal artifact path")
        _verify(item)
        artifacts[item["path"]] = item
    for required in (
        root / "request.json",
        root / "value.json",
        root / "process/command.json",
        root / "process/result.json",
        root / "process/stdout.txt",
        root / "process/stderr.txt",
    ):
        _require(str(required) in artifacts, "unfrozen required evidence: " + str(required))
    _require(
        artifacts[str(root / "request.json")] == request_identity,
        "STARTED/terminal request identity mismatch",
    )
    value = row["value"]
    raw = _load(root / "value.json")
    _require(
        raw.get("status") == value.get("status") == "SUCCEEDED", "worker/terminal status mismatch"
    )
    _require(
        all(key in value and value[key] == v for key, v in raw.items()),
        "worker result disagrees with terminal",
    )
    observed = _load(root / "process/result.json")
    _require(value["command"] == observed, "process result disagrees with terminal")
    argv = [
        config["python"],
        str(Path(config["source"]["root"]) / "scripts/run_experiments.py"),
        "--_worker",
        str(root / "request.json"),
    ]
    _require(
        observed["argv"] == argv == _load(root / "process/command.json")["argv"],
        "worker executable/request argv identity mismatch",
    )
    _require(
        type(observed["returncode"]) is int
        and observed["returncode"] == 0
        and observed["error"] is None
        and observed["shutdown_verified"] is True,
        "process return/shutdown not authenticated",
    )
    _require(
        not any(
            observed.get(k)
            for k in (
                "resource_refused",
                "storage_observation_failed",
                "monitor_failed",
                "failure_scope",
            )
        )
        and not value.get("attempt_failures")
        and not value.get("diagnostic_parse_errors"),
        "terminal carries a failure/refusal",
    )
    _require(
        request["audio"] == config["audio"]["path"]
        and request["original_path"] == config["original_path"]
        and request["visual_overrides"] == config["visual_overrides"]
        and request["evidence"] == str(root)
        and request["result_path"] == str(root / "value.json")
        and request["media"] == str(Path(config["media"]) / name),
        "request/config identity mismatch",
    )
    settings = {k: request.get(k) for k in ("ffmpeg", "ffprobe", "visual_overrides", "workload")}
    settings["python"] = config["python"]
    _require(value["execution_settings"] == settings, "execution settings/request mismatch")
    for tool in ("ffmpeg", "ffprobe"):
        _require(
            request[tool] == config["selected"]["tools"][tool]["path"],
            "request/frozen tool mismatch",
        )
    for item in value.get("artifacts", []):
        _require(artifacts.get(item["path"]) == item, "result artifact not frozen by terminal")
    if value.get("actual_action") == "PROCESS":
        decode_errors = root / (Path(value["output"]).name + ".rgba.decode.stderr")
        _require(
            str(root / "commands.jsonl") in artifacts
            and str(decode_errors) in artifacts
            and artifacts[str(decode_errors)]["bytes"] == 0,
            "required frozen command/decode diagnostics unavailable",
        )
        if request["operation"] == "service":
            _require(
                str(root / "service-result.json") in artifacts
                and _load(root / "service-result.json") == value["service_result"],
                "frozen service result mismatch/unavailable",
            )
    return request, value


def _measurement(request: dict[str, Any], value: dict[str, Any], config: dict[str, Any]) -> None:
    pair = request["pair"]
    group, side, repeat = pair["id"], pair["side"], pair["repeat"]
    _require(
        group in CONTROLS
        and side in ("A", "B")
        and type(repeat) is int
        and 1 <= repeat <= config["repeats"]
        and value["pair"] == pair,
        "unsupported pair identity",
    )
    _require(pair["order"] == ("AB" if repeat % 2 else "BA"), "pair order mismatch")
    direct = group == "single-file-direct-lut"
    _require(
        request["operation"] == ("direct" if direct else "service")
        and not request.get("torch_finish")
        and not request.get("variant")
        and not request.get("backend"),
        "unsupported CPU route selectors",
    )
    for key in CONTROL_KEYS:
        expected: Any = None
        if key == "codec" and direct:
            expected = "prores"
        elif key == "jobs" and not direct:
            expected = 2 if group == "single-file-jobs32" and side == "A" else 1
        elif key == "finish_lut" and group != "single-file-jobs32" and side == "B":
            expected = True
        _require(request.get(key) == expected, "unsupported CPU control: " + key)
    workload, valid = request["workload"], value["validation"]
    frames = workload["frames"]
    _require(
        type(frames) is int
        and frames > 0
        and valid["frames"] == frames
        and value["workload"] == workload
        and valid["passed"] is True,
        "required validation/workload/frame count mismatch",
    )
    _require(
        value["actual_action"] == "PROCESS" and value["throughput_fresh"] is True,
        "historical result was not fresh PROCESS",
    )
    _require(
        type(value["wall_seconds"]) in (int, float)
        and math.isfinite(value["wall_seconds"])
        and value["wall_seconds"] > 0,
        "invalid historical wall time",
    )
    worker_wall = value["command"]["wall_seconds"]
    _require(
        type(worker_wall) in (int, float)
        and math.isfinite(worker_wall)
        and worker_wall > 0
        and value["wall_seconds"] <= worker_wall + TIMER_CONTAINMENT_TOLERANCE_SECONDS,
        "historical render wall exceeds/contradicts frozen worker envelope",
    )
    if "cold_process_wall_seconds" in value:
        _require(
            type(value["cold_process_wall_seconds"]) in (int, float)
            and value["cold_process_wall_seconds"] == worker_wall,
            "cold worker timer disagrees with frozen process result",
        )
    _require(
        valid["fps"] == valid["stream"]["avg_frame_rate"] == "60/1"
        and valid["stream"]["codec_name"] == "prores"
        and valid["stream"]["profile"] == "4444"
        and valid["stream"]["pix_fmt"].startswith("yuva444p")
        and (valid["stream"]["width"], valid["stream"]["height"]) == (1400, 280)
        and valid["max_pts_error_seconds"] == "0"
        and valid["alpha_min"] == 0
        and 0 < valid["alpha_max"] <= 255
        and valid["alpha_association_contract"] == "straight"
        and Fraction(valid["frame_grid_seconds"]) == Fraction(frames, 60)
        and 0 < Fraction(valid["time_base"]) < Fraction(1, 60)
        and valid["stream"]["time_base"] == valid["time_base"]
        and _digest(valid["decoded_rgba_sha256"])
        and _digest(valid["decoded_alpha_sha256"]),
        "required frozen frame-grid/decoded validation unavailable",
    )
    output = value["output"]
    _require(
        Path(request["evidence"]).name == f"{group}-r{repeat:02d}-{side}", "pair/name mismatch"
    )
    _require(any(i["path"] == output for i in value["artifacts"]), "output not authenticated")
    _require(Path(output).is_relative_to(Path(request["media"])), "output outside stage media")
    commands = value["commands"]
    _require(isinstance(commands, list) and bool(commands), "frozen commands unavailable")
    for command in commands:
        _require(
            command["argv"] and command["argv"][0] in (request["ffmpeg"], request["ffprobe"]),
            "command/frozen tool identity mismatch",
        )
    outcomes = [
        c
        for c in commands
        if c.get("phase") == "complete-frame-metadata-outcome"
        and c["argv"][0] == request["ffprobe"]
        and c["argv"][-1] == output
    ]
    _require(
        len(outcomes) == 1
        and outcomes[0].get("returncode") == 0
        and not outcomes[0].get("stderr")
        and isinstance(outcomes[0].get("stdout"), str),
        "successful full frozen output frame metadata unavailable",
    )
    metadata = _json(outcomes[0]["stdout"].encode("utf-8"))
    _require(
        metadata["streams"] == [valid["stream"]] and len(metadata["frames"]) == frames,
        "frozen metadata stream/frame count mismatch",
    )
    tb = Fraction(valid["time_base"])
    _require(
        all(
            Fraction(frame["best_effort_timestamp"]) * tb == Fraction(i, 60)
            for i, frame in enumerate(metadata["frames"])
        ),
        "frozen metadata frame order/timeline mismatch",
    )
    decode = [
        request["ffmpeg"],
        "-nostdin",
        "-v",
        "error",
        "-xerror",
        "-err_detect",
        "explode",
        "-hwaccel",
        "none",
        "-i",
        output,
        "-map",
        "0:v:0",
        "-an",
        "-c:v",
        "rawvideo",
        "-pix_fmt",
        "rgba",
        "-f",
        "rawvideo",
        "pipe:1",
    ]
    _require(
        any(
            c.get("phase") == "strict-complete-software-decode" and c["argv"] == decode
            for c in commands
        ),
        "complete frozen exact-output software validation unavailable",
    )
    _require(
        value["experimental_controls"] == {k: request.get(k) for k in CONTROL_KEYS},
        "controls/request mismatch",
    )
    if request["operation"] == "direct":
        _require(
            value["route"] == DIRECT_ROUTE
            and value["timer"] == DIRECT_TIMER
            and value["source"] == config["audio"]
            and _digest(value["original_raster_sha256"])
            and request.get("codec") == "prores",
            "direct provenance mismatch",
        )
    elif request["operation"] == "service":
        service = value["service_result"]
        _require(
            value["route"] == "STOCK_SERVICE"
            and value["timer"] == SERVICE_TIMER
            and service["job"]["status"] == "SUCCEEDED"
            and service["validation"]["passed"] is True
            and service["validation"]["frames"] == frames
            and service["execution"]["resumed"] is False
            and not service.get("resume_history")
            and not service["performance"]["extras"].get("reused_output_formats"),
            "service freshness/validation mismatch",
        )
        _require(
            service["outputs"] == [{"format": "prores4444", "path": output}]
            and len(service["inputs"]) == 1,
            "service input/output mismatch",
        )
        source = service["inputs"][0]
        _require(
            (source["path"], source["sha256"], source["size_bytes"])
            == (config["audio"]["path"], config["audio"]["sha256"], config["audio"]["bytes"]),
            "service/frozen input identity mismatch",
        )
        _require(
            service["analysis"]["encode_workers"] == request.get("jobs", 2),
            "service worker policy mismatch",
        )
    else:
        raise ValueError("unsupported measurement operation")


def _statistics(qualified: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    summaries = []
    repeats = config.get("repeats")
    _require(type(repeats) is int and 0 < repeats <= 1000, "invalid frozen repeat count")
    assert isinstance(repeats, int)
    for group, control in CONTROLS.items():
        samples: dict[str, list[float]] = {"A": [], "B": []}
        excluded = []
        orders = []
        for repeat in range(1, repeats + 1):
            names = [f"{group}-r{repeat:02d}-{side}" for side in "AB"]
            try:
                _require(all(n in qualified for n in names), "missing/ineligible pair member")
                a, b = [qualified[n] for n in names]
                av, bv = a["value"], b["value"]
                order = "AB" if repeat % 2 else "BA"
                for side, member in zip("AB", (a, b), strict=True):
                    pair = member["request"]["pair"]
                    _require(
                        pair == member["value"]["pair"]
                        and pair["id"] == group
                        and pair["repeat"] == repeat
                        and pair["side"] == side
                        and pair["order"] == order,
                        "pair identity/order mismatch",
                    )
                ordered = [a, b] if order == "AB" else [b, a]
                _require(
                    ordered[0]["terminal_ordinal"] < ordered[1]["start_ordinal"],
                    "pair order/serial execution mismatch",
                )
                for key in (
                    "timer",
                    "route",
                    "workload",
                    "execution_settings",
                    "source",
                    "original_raster_sha256",
                    "effective_preset",
                    "spec",
                ):
                    _require(av.get(key) == bv.get(key), "unmatched " + key)
                _require(
                    av["pair"]["comparison"] == bv["pair"]["comparison"],
                    "unmatched pair comparison",
                )
                ac, bc = av["experimental_controls"], bv["experimental_controls"]
                changed = {k for k in ac.keys() | bc.keys() if ac.get(k) != bc.get(k)}
                _require(changed == {control}, "undeclared/missing experimental control change")
                expected = (2, 1) if control == "jobs" else (None, True)
                _require((ac[control], bc[control]) == expected, "unexpected control contrast")
                _require(
                    av["validation"]["frames"] == bv["validation"]["frames"]
                    and av["validation"]["decoded_rgba_sha256"]
                    == bv["validation"]["decoded_rgba_sha256"]
                    and av["validation"]["decoded_alpha_sha256"]
                    == bv["validation"]["decoded_alpha_sha256"],
                    "unmatched validated output/alpha",
                )
                for side, v in (("A", av), ("B", bv)):
                    samples[side].append(v["wall_seconds"])
                orders.append(order)
            except (KeyError, TypeError, ValueError) as exc:
                excluded.append({"repeat": repeat, "reason": str(exc)})
        summaries.append(
            {
                "id": group,
                "recovered_paired_n": len(samples["A"]),
                "orders": orders,
                "sides": {
                    side: {
                        "n": len(values),
                        "median_seconds": statistics.median(values) if values else None,
                        "min_seconds": min(values) if values else None,
                        "max_seconds": max(values) if values else None,
                    }
                    for side, values in samples.items()
                },
                "excluded": excluded,
                "speedup": None,
                "claim": "descriptive retained historical samples; "
                "not new throughput or acceptance",
            }
        )
    return summaries


def authenticate(run: Path, diagnostics: Path | None = None) -> dict[str, Any]:
    """Read only; absent evidence yields explicit ineligibility, never a retry."""
    report: dict[str, Any] = {
        "schema_version": 1,
        "action": "AUTHENTICATE_RETAINED_SUCCESS",
        "run": str(run),
        "status": "INELIGIBLE",
        "fresh_measurements_this_invocation": False,
        "new_renders": 0,
        "new_decodes": 0,
        "original_status_modified": False,
        "qualified": {},
        "ineligible": [],
        "unrelated": [],
        "pair_statistics": [],
        "errors": [],
        "visual": "PENDING",
        "studio": "PENDING",
        "promotion": "NOT_APPROVED",
        "validation_scope": "reuse of frozen prior validation for authenticated exact "
        "retained bytes; not new pixels; no current source/tool/runtime probe; "
        "self-sealed consistency, not signature",
    }
    try:
        _require(
            not (run / "owner.lock").exists(), "run has an owner lock; require quiescent evidence"
        )
        snapshot = _load(diagnostics) if diagnostics else None
        if diagnostics:
            report["diagnostics_identity"] = _identity(diagnostics)
            report["original_status"] = snapshot["status"] if snapshot else None
        config = _config(run)
        report["config"] = config
        report["sealed_config_identity"] = _load(run / "config-seal.json")
        report["config_seal"] = _identity(run / "config-seal.json")
        report["original_reports"] = []
        for path in sorted((run / "reports").glob("report-*.json")):
            original = _load(path)
            report["original_reports"].append(
                {
                    "identity": _identity(path),
                    "status": original.get("status"),
                    "error": original.get("error"),
                }
            )
        event_identity = _identity(run / "events.jsonl")
        starts, terminals, incidents = _chain(run)
        _verify(event_identity)
        report["unrelated"].extend(incidents)
        if diagnostics:
            _require(
                snapshot is not None and snapshot["config"] == config,
                "diagnostics/sealed config mismatch",
            )
        for name, terminal in terminals.items():
            row = terminal["row"]
            candidate = any(name.startswith(group + "-r") for group in CONTROLS)
            if not candidate:
                report["unrelated"].append(
                    {
                        "name": name,
                        "event": row["event"],
                        "status": row["value"].get("status"),
                        "qualification": "NOT_REQUESTED",
                    }
                )
                continue
            try:
                request, value = _terminal(run, name, starts[name], terminal, config)
                _measurement(request, value, config)
                if request.get("reference"):
                    providers = [
                        q
                        for q in report["qualified"].values()
                        if q["value"]["output"] == request["reference"]
                    ]
                    _require(
                        len(providers) == 1, "reference success/bytes unavailable or ineligible"
                    )
                    reference = providers[0]
                    _require(
                        reference["terminal_ordinal"] < starts[name]["ordinal"]
                        and request.get("reference_lossless") is True
                        and value["validation"].get("lossless_against_reference_master") is True
                        and reference["value"]["validation"]["decoded_rgba_sha256"]
                        == value["validation"]["decoded_rgba_sha256"]
                        and reference["value"]["validation"]["decoded_alpha_sha256"]
                        == value["validation"]["decoded_alpha_sha256"],
                        "reference validation/provenance/alpha mismatch",
                    )
                    if request["operation"] == "direct":
                        _require(
                            request.get("expected_raster_sha256")
                            == reference["value"]["original_raster_sha256"]
                            == value["original_raster_sha256"],
                            "reference original raster mismatch",
                        )
                if snapshot is not None:
                    comparison = dict(snapshot["results"][name])
                    # This one known reporting-only annotation is not worker evidence.
                    if comparison.get("evidence_status") == "SALVAGED_UNVERIFIED":
                        comparison.pop("evidence_status")
                    _require(comparison == value, "diagnostics/terminal result mismatch")
                report["qualified"][name] = {
                    "authentication": "RETAINED_SUCCESS_AUTHENTICATED",
                    "validation_reused": True,
                    "throughput_fresh_this_invocation": False,
                    "start_ordinal": starts[name]["ordinal"],
                    "terminal_ordinal": terminal["ordinal"],
                    "request": request,
                    "value": value,
                }
            except (
                OSError,
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                ArithmeticError,
            ) as exc:
                report["ineligible"].append(
                    {"name": name, "event": row["event"], "reason": str(exc)}
                )
        _verify(event_identity)
        _verify(report["sealed_config_identity"])
        _verify(report["config_seal"])
        _require(not (run / "owner.lock").exists(), "run became active during authentication")
        report["events_identity"] = event_identity
        report["pair_statistics"] = _statistics(report["qualified"], config)
        report["status"] = "AUTHENTICATED" if report["qualified"] else "INELIGIBLE"
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ArithmeticError) as exc:
        report["qualified"] = {}
        report["pair_statistics"] = []
        report["errors"].append(str(exc))
    report["authenticated_success_count"] = len(report["qualified"])
    return report


def recover(run: Path, output: Path, diagnostics: Path | None = None) -> dict[str, Any]:
    """Write only a fresh external directory; never open original bytes writable."""
    run, output = run.expanduser().absolute(), output.expanduser().absolute()
    _require(not output.exists(), "output already exists; use a fresh directory")
    protected = [run]
    if (run / "config.json").is_file():
        protected.append(Path(_load(run / "config.json")["media"]))
    if diagnostics:
        protected.append(diagnostics.absolute())
    for path in protected:
        _require(
            not output.resolve().is_relative_to(path.resolve())
            and not path.resolve().is_relative_to(output.resolve()),
            "output overlaps evidence",
        )
    _require(
        not any((p / ".git").exists() for p in (output, *output.parents)),
        "recovery output must be outside Git",
    )
    report = authenticate(run, diagnostics)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    with (output / "authentication.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    lines = [
        "# Retained-success authentication",
        "",
        f"Status: {report['status']}",
        f"Authenticated historical CPU successes: {report['authenticated_success_count']}",
        "",
        report["validation_scope"],
        "",
        "Original FAILED/status and SALVAGED labels "
        "are unchanged. This separate report is not resume or visual/NLE acceptance.",
        "",
        "| Pair | Recovered paired n | A median s | B median s |",
        "|---|---:|---:|---:|",
    ]
    for pair in report["pair_statistics"]:
        lines.append(
            f"| {pair['id']} | {pair['recovered_paired_n']} | "
            f"{pair['sides']['A']['median_seconds']} | "
            f"{pair['sides']['B']['median_seconds']} |"
        )
    lines.extend(
        [
            "",
            "## Errors/ineligible",
            "",
            *report["errors"],
            *(f"{r['name']}: {r['reason']}" for r in report["ineligible"]),
        ]
    )
    with (output / "authentication.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path, help="old run, read-only")
    parser.add_argument(
        "--output", required=True, type=Path, help="fresh external report directory"
    )
    parser.add_argument(
        "--diagnostics",
        type=Path,
        help="optional exact full report JSON compare; compact/excerpted records refuse",
    )
    args = parser.parse_args(argv)
    try:
        report = recover(args.run, args.output, args.diagnostics)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"authentication refused: {exc}\n")
    print(json.dumps({k: report[k] for k in ("status", "authenticated_success_count", "errors")}))
    return 0 if report["status"] == "AUTHENTICATED" and not report["ineligible"] else 2
