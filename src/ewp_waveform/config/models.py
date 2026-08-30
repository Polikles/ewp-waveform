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
    window_seconds: float = 5.0


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


class BenchmarkInput(BaseModel):
    path: str


class BenchmarkVariant(BaseModel):
    name: str
    preset: str | None = None
    preset_file: str | None = None
    overrides: dict[str, object] = Field(default_factory=dict)


class BenchmarkSection(BaseModel):
    renderers: list[str]
    formats: list[str]
    performance_profiles: list[str] = Field(default_factory=lambda: ["balanced"])
    dry_run_estimates: bool = False


class BenchmarkManifest(BaseModel):
    schema_version: int
    name: str
    inputs: list[BenchmarkInput]
    variants: list[BenchmarkVariant]
    benchmark: BenchmarkSection
