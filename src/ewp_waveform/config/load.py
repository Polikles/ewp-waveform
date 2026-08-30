"""Load application config, visual presets, and performance profiles."""

from __future__ import annotations

import tomllib
from pathlib import Path

from ewp_waveform.config.models import ApplicationConfig, PerformanceProfile, VisualPreset
from ewp_waveform.paths import builtin_performance_dir, builtin_presets_dir, project_root


def _read_toml(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data, dict):
        msg = f"TOML root must be a table: {path}"
        raise ValueError(msg)
    return data


def load_application_config(path: Path | None = None) -> ApplicationConfig:
    if path is None:
        return ApplicationConfig()
    return ApplicationConfig.model_validate(_read_toml(path))


def resolve_named_toml(name_or_path: str, builtin_dir: Path) -> Path:
    candidate = Path(name_or_path)
    if candidate.suffix == ".toml" and candidate.is_file():
        return candidate
    builtin = builtin_dir / f"{name_or_path}.toml"
    if builtin.is_file():
        return builtin
    msg = f"Unknown config '{name_or_path}' (looked at path and {builtin_dir})"
    raise FileNotFoundError(msg)


def load_preset(name_or_path: str) -> VisualPreset:
    path = resolve_named_toml(name_or_path, builtin_presets_dir())
    return VisualPreset.model_validate(_read_toml(path))


def load_performance(name_or_path: str) -> PerformanceProfile:
    path = resolve_named_toml(name_or_path, builtin_performance_dir())
    return PerformanceProfile.model_validate(_read_toml(path))


def list_named_toml(builtin_dir: Path) -> list[tuple[str, Path]]:
    return sorted((path.stem, path) for path in builtin_dir.glob("*.toml"))


def list_presets() -> list[tuple[str, Path]]:
    return list_named_toml(builtin_presets_dir())


def list_performance_profiles() -> list[tuple[str, Path]]:
    return list_named_toml(builtin_performance_dir())


def example_config_path() -> Path:
    return project_root() / "examples" / "config.example.toml"
