from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest

from ewp_waveform.ffmpeg.encode import _glow_crop_graph

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg required")


def _frame(
    mask: np.ndarray,
    finish: tuple[float, bool, float, float, float],
    *,
    glow: float = 2.0,
    rgba: bool = False,
    ss: int = 1,
    overscan: int = 0,
) -> np.ndarray:
    h, w = mask.shape
    width, height = w // ss - 2 * overscan, h - 2 * overscan
    data = mask.tobytes()
    if rgba:
        pixels = np.zeros((h, w, 4), dtype=np.uint8)
        pixels[..., :3] = (199, 230, 236)
        pixels[..., 3] = mask
        data = pixels.tobytes()
    graph = _glow_crop_graph(
        glow,
        width,
        height,
        overscan,
        ss,
        pix_fmt="rgba" if rgba else "gray",
        color="#C7E6EC",
        ribbon_finish=finish,
    )
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgba" if rgba else "gray",
            "-s",
            f"{w}x{h}",
            "-i",
            "-",
            "-filter_complex",
            graph,
            "-map",
            "[vout]",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgba",
            "-",
        ],
        input=data,
        capture_output=True,
        check=True,
    )
    assert not result.stderr
    return np.frombuffer(result.stdout, dtype=np.uint8).reshape(height, width, 4)


def _mask() -> np.ndarray:
    mask = np.zeros((32, 64), dtype=np.uint8)
    mask[7:26, 12:52] = 255
    mask[6, 12:52] = 80
    mask[26, 12:52] = 80
    return mask


def test_body_halo_alpha_and_upper_are_independent() -> None:
    mask = _mask()
    neutral = _frame(mask, (1, False, 1, 1, 0.55))
    zero = _frame(mask, (0, False, 1, 1, 0.55))
    half = _frame(mask, (0.5, False, 1, 1, 0.55))
    assert np.array_equal(neutral[:17], half[:17])
    assert np.array_equal(neutral[:17], zero[:17])
    assert not zero[17:, :, 3].any()
    assert np.any(neutral[27:, :, 3] > 0)  # Real intended halo outside body.
    assert np.max(np.abs(half[17:, :, 3].astype(int) * 2 - neutral[17:, :, 3])) <= 2
    visible = half[..., 3] > 0
    assert np.all(half[..., :3][visible] == (199, 230, 236))
    assert not half[..., :3][~visible].any()


def test_single_horizon_silence_opacity_extent_and_thickness() -> None:
    silence = np.zeros((32, 64), dtype=np.uint8)
    for reflection in (0, 0.45, 1):
        off = _frame(silence, (reflection, False, 12, 1, 1))
        assert not off.any()  # No hidden minimum core or halo.
    line = _frame(silence, (0, True, 1, 0.5, 0.5))
    assert np.all(line[16, 16:48, 3] == 127)
    assert np.count_nonzero(line[..., 3]) == 32
    assert np.array_equal(line, _frame(silence, (1, True, 1, 0.5, 0.5)))
    for finish in [(0, True, 12, 0, 1), (0, True, 12, 1, 0)]:
        assert not _frame(silence, finish).any()
    thick = _frame(silence, (0.45, True, 2.5, 0.5, 1))
    assert np.count_nonzero(thick[:, 32, 3]) == 3
    assert thick[16, 32, 3] == 255
    assert thick[15, 32, 3] == thick[17, 32, 3]
    assert np.any(thick != line)


@pytest.mark.parametrize("ss", [1, 2])
def test_mask_and_rgba_paths_share_finish_and_final_pixel_line(ss: int) -> None:
    mask = np.repeat(_mask(), ss, axis=1)
    finish = (0.4, True, 2.5, 0.73, 0.6)
    assert np.array_equal(_frame(mask, finish, ss=ss), _frame(mask, finish, rgba=True, ss=ss))
    silence = np.zeros_like(mask)
    assert np.array_equal(
        _frame(silence, finish, ss=ss), _frame(np.zeros((32, 64), dtype=np.uint8), finish)
    )
