"""Native monochrome alpha finishing for filled ribbon; no RGB darkening.

Mask AA/downsampling -> body+halo alpha union -> lower attenuation -> independent
horizon -> constant unassociated color. Other styles keep their existing graph.
"""

from __future__ import annotations

from ewp_waveform.ffmpeg.draw import parse_rgb


def ribbon_graph(
    *,
    width: int,
    height: int,
    overscan: int,
    supersample: int,
    pix_fmt: str,
    color: str,
    glow: float,
    finish: tuple[float, bool, float, float, float],
) -> str:
    reflection, enabled, thickness, extent, opacity = finish
    padded_w, padded_h = width + 2 * overscan, height + 2 * overscan
    head = "[0:v]format=gray" if pix_fmt == "gray" else "[0:v]alphaextract"
    if supersample > 1:
        head += f",scale={padded_w}:{padded_h}:flags=area"
    if glow > 0:
        head += (
            f",split=2[body][halo];[halo]gblur=sigma={glow}:steps=3[blur];"
            "[body][blur]blend=all_expr='A+B*(1-A/255)':shortest=1"
        )
    if overscan:
        head += f",crop={width}:{height}:{overscan}:{overscan}"
    # Coordinates and coverage are final output pixels, centered horizontally.
    left, right = width * (1 - extent) / 2, width * (1 + extent) / 2
    cy = height // 2 + 0.5
    top, bottom = cy - thickness / 2, cy + thickness / 2
    line = "0"
    if enabled and extent > 0 and opacity > 0:
        line = (
            f"({opacity}*clip(min(X+1,{right})-max(X,{left}),0,1)"
            f"*clip(min(Y+1,{bottom})-max(Y,{top}),0,1))"
        )
    body = f"lum(X,Y)*if(gt(Y,{height // 2}),{reflection},1)"
    expression = f"255*{line}+({body})*(1-{line})"
    # geq evaluates a gray mask; no per-pixel Python or RGB multiplied by alpha.
    head += f",geq=lum='{expression}',split=2[alpha][luma];"
    r, g, b = parse_rgb(color)
    return (
        head + f"[luma]format=gbrp,lut=c0='if(val\\,{r}\\,0)':"
        f"c1='if(val\\,{g}\\,0)':c2='if(val\\,{b}\\,0)'[rgb];"
        "[rgb][alpha]alphamerge,format=rgba[vout]"
    )
