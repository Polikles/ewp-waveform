"""Pydantic models for TOML configuration domains."""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


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

    @model_validator(mode="before")
    @classmethod
    def _validate_refined_data(cls, data: Any) -> Any:
        from ewp_waveform.config.ribbon import validate_refined_data

        return validate_refined_data(data)

    def validate_fixed_axis_profile(self) -> Self:
        """A named visual profile must never silently select an unrelated path."""
        from ewp_waveform.config.ribbon import REFINED_RIBBON, validate_refined_data

        validate_refined_data(self.model_dump())
        if self.signal.get("fixed_axis_profile") == REFINED_RIBBON:
            return self
        if "fixed_axis_profile" not in self.signal:
            return self
        if self.signal["fixed_axis_profile"] != "filled-ribbon-v1":
            raise ValueError("Unsupported signal.fixed_axis_profile; expected filled-ribbon-v1/v2")
        if self.waveform.domain != "frequency" or self.waveform.style != "filled":
            raise ValueError("filled-ribbon-v1 requires waveform.domain=frequency and style=filled")
        return self

    @model_validator(mode="after")
    def _validate_fixed_axis_profile(self) -> Self:
        return self.validate_fixed_axis_profile()


class PerformanceProfile(BaseModel):
    schema_version: int
    name: str
    description: str | None = None
    processing: dict[str, object] = Field(default_factory=dict)
    workdirs: dict[str, object] = Field(default_factory=dict)


class BenchmarkInput(BaseModel):
    # Input-only strictness prevents misspelled/coerced bounds becoming full-source jobs.
    model_config = ConfigDict(extra="forbid")

    path: str
    start: float | None = Field(default=None, strict=True, allow_inf_nan=False, ge=0)
    duration: float | None = Field(default=None, strict=True, allow_inf_nan=False, gt=0)


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
