"""Pydantic models for TOML configuration domains."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GroupingConfig(BaseModel):
    mode: str = "prefix"
    separator: str = "-"


class InputConfig(BaseModel):
    recursive: bool = False
    follow_symlinks: bool = False
    grouping: GroupingConfig = Field(default_factory=GroupingConfig)


class OutputConfig(BaseModel):
    directory_name: str = "waveform-output"
    formats: list[str] = Field(default_factory=lambda: ["prores4444"])


class WorkdirsConfig(BaseModel):
    persistent: bool = False


class AppDefaults(BaseModel):
    preset: str = "iuris-default"
    performance: str = "balanced"


class ApplicationConfig(BaseModel):
    schema_version: int = 1
    defaults: AppDefaults = Field(default_factory=AppDefaults)
    input: InputConfig = Field(default_factory=InputConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    workdirs: WorkdirsConfig = Field(default_factory=WorkdirsConfig)


class WaveformSection(BaseModel):
    style: str
    color: str
    amplitude: float
    stroke_width: float | None = None
    center_line: bool | None = None
    domain: str = "time"
    time_mode: str | None = None


class CanvasSection(BaseModel):
    width: int
    height: int
    fps: float


class VisualPreset(BaseModel):
    schema_version: int
    name: str
    description: str | None = None
    canvas: CanvasSection
    waveform: WaveformSection
    signal: dict[str, object] = Field(default_factory=dict)
    effects: dict[str, object] = Field(default_factory=dict)
    palette: dict[str, str] = Field(default_factory=dict)


class PerformanceProfile(BaseModel):
    schema_version: int
    name: str
    description: str | None = None
    processing: dict[str, object] = Field(default_factory=dict)
    workdirs: dict[str, object] = Field(default_factory=dict)
