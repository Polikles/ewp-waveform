"""Deterministic analysis cache. Mapping/style/glow changes must not invalidate."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from ewp_waveform.analysis.frames import AnalysisFrame, AnalysisSequence
from ewp_waveform.analysis.spectrum import FFT_SIZE, FrequencySpan, frequency_config_from_signal

CACHE_VERSION = 1
ENV_CACHE_DIR = "EWP_ANALYSIS_CACHE"


def analysis_cache_dir() -> Path:
    raw = os.environ.get(ENV_CACHE_DIR, "").strip()
    if raw:
        return Path(raw)
    return Path(tempfile.gettempdir()) / "ewp-waveform-analysis"


def analysis_cache_payload(
    *,
    source_sha256: str,
    clip_start: float,
    clip_duration: float,
    fps: float,
    n_frames: int,
    n_bands: int,
    scale: str,
    tilt_db_per_octave: float,
    compress: float,
    signal: dict[str, object],
) -> dict[str, Any]:
    mode, explicit_min, explicit_max = frequency_config_from_signal(signal)
    return {
        "cache_version": CACHE_VERSION,
        "fft_size": FFT_SIZE,
        "source_sha256": source_sha256,
        "clip_start": round(float(clip_start), 9),
        "clip_duration": round(float(clip_duration), 9),
        "fps": float(fps),
        "n_frames": int(n_frames),
        "n_bands": int(n_bands),
        "scale": str(scale),
        "tilt_db_per_octave": float(tilt_db_per_octave),
        "compress": float(compress),
        "frequency_range": mode,
        "fmin_hz": explicit_min,
        "fmax_hz": explicit_max,
    }


def analysis_cache_digest(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _cache_path(digest: str, directory: Path | None = None) -> Path:
    root = directory if directory is not None else analysis_cache_dir()
    return root / f"{digest}.npz"


def load_analysis_cache(
    digest: str, *, directory: Path | None = None
) -> tuple[AnalysisSequence, FrequencySpan] | None:
    path = _cache_path(digest, directory)
    if not path.is_file():
        return None
    try:
        data = np.load(path, allow_pickle=False)
        bands = np.asarray(data["bands"], dtype=np.float64)
        fmin = float(data["fmin_hz"])
        fmax = float(data["fmax_hz"])
        source = str(data["span_source"])
    except (OSError, KeyError, ValueError):
        return None
    if bands.ndim != 2:
        return None
    frames = tuple(AnalysisFrame.from_bands(row.tolist()) for row in bands)
    return AnalysisSequence(frames=frames), FrequencySpan(fmin, fmax, source)


def store_analysis_cache(
    digest: str,
    sequence: AnalysisSequence,
    span: FrequencySpan,
    *,
    directory: Path | None = None,
) -> Path:
    path = _cache_path(digest, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not sequence.frames:
        bands = np.zeros((0, 0), dtype=np.float64)
    else:
        bands = np.asarray([frame.bands for frame in sequence.frames], dtype=np.float64)
    tmp = path.with_suffix(".tmp.npz")
    np.savez(
        tmp,
        bands=bands,
        fmin_hz=np.float64(span.fmin_hz),
        fmax_hz=np.float64(span.fmax_hz),
        span_source=np.asarray(span.source),
    )
    tmp.replace(path)
    return path
