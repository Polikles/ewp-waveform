"""Typed job and inspection models."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from ewp_waveform.domain.diagnostics import CapabilityLevel, Diagnostic


class JobStatus(StrEnum):
    PLANNED = "PLANNED"
    SKIPPED = "SKIPPED"
    RUNNING = "RUNNING"
    RESUMED = "RESUMED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class VisualizationDomain(StrEnum):
    TIME = "time"
    FREQUENCY = "frequency"


class TimeMode(StrEnum):
    SCROLL = "scroll"
    PLAYHEAD = "playhead"


class SourceMedia(BaseModel):
    path: Path
    duration_seconds: float
    sample_rate: int
    channels: int
    codec: str
    format_name: str
    size_bytes: int


class PlannedJob(BaseModel):
    path: Path
    project_id: str
    track_id: str
    preset: str
    domain: VisualizationDomain
    time_mode: TimeMode | None
    style: str
    fps: float
    status: JobStatus = JobStatus.PLANNED
    capability: CapabilityLevel
    capability_notes: str = ""
    diagnostics: list[Diagnostic] = Field(default_factory=list)
