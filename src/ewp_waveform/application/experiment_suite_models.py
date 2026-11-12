"""Strict finite suite inputs and explicit A-F comparisons, not a generic scheduler."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCENARIOS = ("FULL", "PRODUCTION32", "A", "B", "C", "D", "E0", "E1", "F0", "F1")
GPU = {"C", "D", "E1", "F1"}
Name = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")]
Positive = Annotated[int, Field(strict=True, gt=0)]
Seconds = Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Estimate(Strict):
    growth_bytes: Positive
    memory_bytes: Positive
    seconds: Seconds


class Limits(Strict):
    attempts: Positive
    seconds: Seconds
    growth_bytes: Positive
    reserve_bytes: Positive
    memory_floor_bytes: Positive
    attempt_seconds: Seconds
    estimates: dict[Literal["full", "production32", "short", "fixture", "probe", "views"], Estimate]

    @model_validator(mode="after")
    def complete(self) -> Self:
        if set(self.estimates) != {"full", "production32", "short", "fixture", "probe", "views"}:
            raise ValueError("all six finite per-kind estimates are required")
        return self


class Workload(Strict):
    id: Name
    kind: Literal["full", "production32", "short"]
    start: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None
    duration: Seconds | None
    frames: Positive

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if self.kind == "full":
            if self.start is not None or self.duration is not None:
                raise ValueError("full must use stock unbounded source interval")
        elif self.start is None or self.duration is None:
            raise ValueError("explicit start and duration required")
        elif (self.kind == "short" and self.duration > 4) or (
            self.kind == "production32" and self.duration != 32
        ):
            raise ValueError("short <=4s and production32 exactly32s")
        if self.duration is not None and self.frames != math.ceil(self.duration * 60):
            raise ValueError("declared frames do not match canonical 60fps interval")
        return self


class Cell(Strict):
    id: Name
    scenario: Literal["FULL", "PRODUCTION32", "A", "B", "C", "D", "E0", "E1", "F0", "F1"]
    workload: Name
    pair: Name | None = None
    role: Literal["control", "candidate"] | None = None


class Manifest(Strict):
    schema_version: Literal[1]
    input_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    source_duration_seconds: Seconds
    visual_overrides: dict[str, object]
    workloads: list[Workload]
    cells: list[Cell]
    limits: Limits
    full_views: bool = False

    @model_validator(mode="after")
    def validate_matrix(self) -> Self:
        from ewp_waveform.application.experiments import VISUAL

        if self.visual_overrides != VISUAL:
            raise ValueError("suite freezes the authenticated full dark appearance recipe")
        if not self.cells or not self.workloads:
            raise ValueError("nonempty workloads and cells required")
        if len({w.id for w in self.workloads}) != len(self.workloads):
            raise ValueError("duplicate workload ID")
        if len({c.id for c in self.cells}) != len(self.cells):
            raise ValueError("duplicate cell ID")
        workloads = {w.id: w for w in self.workloads}
        pairs: dict[str, list[Cell]] = {}
        for c in self.cells:
            if c.id in ("preflight", "old-preflight") or c.id.startswith(("fixture-", "views-")):
                raise ValueError("reserved lifecycle ID prefix")
            if c.workload not in workloads:
                raise ValueError("unknown workload")
            w = workloads[c.workload]
            expected = {"FULL": "full", "PRODUCTION32": "production32"}.get(c.scenario, "short")
            if w.kind != expected:
                raise ValueError("scenario/workload kind mismatch")
            if w.kind == "full" and w.frames != math.ceil(self.source_duration_seconds * 60):
                raise ValueError("full source frame count mismatch")
            if (
                w.start is not None
                and w.duration is not None
                and w.start + w.duration > self.source_duration_seconds
            ):
                raise ValueError("interval exceeds source; no silent EOF truncation")
            if (c.pair is None) != (c.role is None):
                raise ValueError("pair and role must be declared together")
            if c.pair:
                pairs.setdefault(c.pair, []).append(c)
        allowed = {("A", "B"), ("B", "C"), ("C", "D"), ("E0", "E1"), ("F0", "F1")}
        for pair in pairs.values():
            roles = {c.role: c for c in pair}
            if len(pair) != 2 or set(roles) != {"control", "candidate"}:
                raise ValueError("each paired observation needs exactly two explicit roles")
            a, b = roles["control"], roles["candidate"]
            if a.workload != b.workload or (a.scenario, b.scenario) not in allowed:
                raise ValueError("unsupported/multifactor comparison")
        self.validate_attempt_budget()
        return self

    def lifecycle_attempts(self, *, old_tools: bool = False) -> int:
        fixtures = {c.workload for c in self.cells if c.scenario in ("F0", "F1")}
        views = sum(self.workload(c.workload).kind != "full" or self.full_views for c in self.cells)
        old_probe = old_tools and any(c.scenario == "A" for c in self.cells)
        return 1 + int(old_probe) + len(self.cells) + len(fixtures) + views

    def validate_attempt_budget(self, *, old_tools: bool = False) -> None:
        required = self.lifecycle_attempts(old_tools=old_tools)
        if self.limits.attempts < required:
            raise ValueError(f"attempt budget must cover complete frozen lifecycle: {required}")

    def workload(self, ident: str) -> Workload:
        return next(w for w in self.workloads if w.id == ident)


def read_manifest(path: Path) -> Manifest:
    return Manifest.model_validate_json(path.read_text())
