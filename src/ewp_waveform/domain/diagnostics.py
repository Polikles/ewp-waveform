"""Stable warning and error identifiers (FR-CLI-007)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Severity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


class DiagnosticCode(StrEnum):
    W_AUDIO_STEREO_DOWNMIX = "W_AUDIO_STEREO_DOWNMIX"
    W_CHANNEL_SPLIT_ASSUMPTION = "W_CHANNEL_SPLIT_ASSUMPTION"
    W_PROJECT_DURATION_MISMATCH = "W_PROJECT_DURATION_MISMATCH"
    W_JOB_RESUMED = "W_JOB_RESUMED"
    E_INPUT_UNSUPPORTED = "E_INPUT_UNSUPPORTED"
    E_PROJECT_TIMELINE_MISMATCH = "E_PROJECT_TIMELINE_MISMATCH"
    E_RENDERER_CAPABILITY = "E_RENDERER_CAPABILITY"
    E_OUTPUT_VALIDATION = "E_OUTPUT_VALIDATION"
    E_PRESET_ALREADY_EXISTS = "E_PRESET_ALREADY_EXISTS"
    E_CONFIG_INVALID = "E_CONFIG_INVALID"
    E_CHECKPOINT_INCOMPATIBLE = "E_CHECKPOINT_INCOMPATIBLE"
    E_FFMPEG_MISSING = "E_FFMPEG_MISSING"


class Diagnostic(BaseModel):
    code: DiagnosticCode
    severity: Severity
    message: str
    path: str | None = None


class ExitCode(StrEnum):
    """Frozen numeric categories for the first identifiable CLI (docs/09)."""

    SUCCESS = "0"
    CONFIG = "2"
    INPUT = "3"
    CAPABILITY = "4"
    RENDER = "5"
    PARTIAL = "6"


EXIT_CODE_VALUES: dict[ExitCode, int] = {
    ExitCode.SUCCESS: 0,
    ExitCode.CONFIG: 2,
    ExitCode.INPUT: 3,
    ExitCode.CAPABILITY: 4,
    ExitCode.RENDER: 5,
    ExitCode.PARTIAL: 6,
}


class CapabilityLevel(StrEnum):
    FULL = "full"
    LIMITED = "limited"
    EXPERIMENTAL = "experimental"
    UNSUPPORTED = "unsupported"


class CapabilityItem(BaseModel):
    name: str
    level: CapabilityLevel
    notes: str = Field(default="")
