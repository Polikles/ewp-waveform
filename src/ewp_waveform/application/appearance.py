"""Resolve existing fixed-axis controls before identity and output reuse.

Legacy controls remain unchanged unless a named visual profile is explicitly selected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ewp_waveform.config.models import VisualPreset
from ewp_waveform.config.ribbon import DETAIL_SETTINGS, REFINED_RIBBON
from ewp_waveform.ffmpeg.draw import RIBBON_SUPERSAMPLE, parse_rgb
from ewp_waveform.visual.bars import BarStyle
from ewp_waveform.visual.plan import MASK_GEOMETRIES, RenderPlan, resolve_render_plan
from ewp_waveform.visual.style_defaults import BAR_GEOMETRIES, default_bar_style


def spectrum_spatial_sigma(width: int, tau_seconds: float, scale: float) -> float:
    if tau_seconds <= 0.0 or scale <= 0.0:
        return 0.0
    return max(1.0, float(width) / 200.0) * scale


def normalize_spatial_filter(kind: str) -> str:
    return "gaussian" if kind == "gaussian" else "box"


@dataclass(frozen=True)
class FixedAxisAppearance:
    geometry: str
    ribbon_ss: int
    spatial_scale: float = 1.0
    spatial_filter: str = "box"
    spatial_sigma: float = 0.0
    n_bands: int | None = None
    tilt_db: float = 0.0
    compress: float = 1.0
    recenter: bool = False
    taper: float = 0.0
    layout: str = "linear"
    slot_sigma: float = 0.0
    contour: bool = False
    bars: BarStyle | None = None
    field_plan: RenderPlan | None = None
    profile: str | None = None
    detail_level: str | None = None
    baseline_thickness: float | None = None

    def identity(self) -> dict[str, Any]:
        """Only branch-effective values; representation path is execution metadata."""
        recipe: dict[str, Any] = {"version": 1, "visual_geometry": self.geometry}
        if self.geometry != "spectrum":
            return recipe
        if self.profile is not None:
            recipe["profile"] = self.profile
        if self.detail_level is not None:
            recipe.update(
                detail_level=self.detail_level,
                mapping_revision=4,
                baseline_thickness=self.baseline_thickness,
            )
        field = self.field_plan
        banded = self.n_bands is not None or field is not None
        recipe.update(
            layout=self.layout if banded else "linear",
            n_bands=(self.n_bands or 64) if field is not None else self.n_bands,
            spatial_sigma=self.spatial_sigma,
            spatial_filter=self.spatial_filter if self.spatial_sigma > 0.0 else "box",
            tilt_db_per_octave=(self.tilt_db or 0.0) if banded else 0.0,
            compress=min(1.0, max(0.05, self.compress)) if banded else 1.0,
        )
        if field is None:
            recipe.update(
                contour=self.contour,
                recenter=self.recenter if banded and self.layout == "linear" else False,
                edge_taper=self.taper,
                slot_sigma=self.slot_sigma if banded and self.layout == "center_out" else 0.0,
                supersample=self.ribbon_ss,
            )
            return recipe
        recipe.update(field_geometry=field.geometry, supersample=field.supersample)
        # Only ribbon consumes coverage taps. Other geometries currently raster at
        # the plan's SS=1 in that mode; do not invent tap support in an identity fix.
        if field.geometry == "ribbon":
            recipe.update(aa_mode=field.aa_mode, aa_taps=field.aa_taps)
        if field.geometry in BAR_GEOMETRIES:
            assert self.bars is not None
            bars = self.bars
            if bars.align == "slots" or bars.count is not None or bars.align == "count":
                spacing: dict[str, Any] = {
                    "align": "slots" if bars.align == "slots" else "count",
                    "count": bars.count
                    if bars.count is not None
                    else (bars.n_slots if bars.align == "slots" else 1),
                    "fill": min(0.95, max(0.05, bars.fill)),
                }
            else:
                spacing = {
                    "align": "period",
                    "width": max(1.0, bars.width),
                    "gap": max(0.0, bars.gap),
                }
            if field.geometry != "segmented_impulse":
                spacing.update(
                    alternate=bars.alternate,
                    color_b=list(parse_rgb(bars.color_b)) if bars.alternate else None,
                    center_line_width=max(0.0, bars.center_line_width),
                )
            recipe["bars"] = spacing
        return recipe


def resolve_fixed_axis_appearance(
    preset: VisualPreset,
    *,
    spectrum_contour: bool = False,
    spectrum_spatial_scale: float = 1.0,
    spectrum_spatial_filter: str = "box",
    spectrum_n_bands: int | None = None,
    spectrum_tilt_db_per_octave: float = 0.0,
    spectrum_compress: float = 1.0,
    spectrum_recenter: bool = False,
    spectrum_edge_taper: float = 0.0,
    visual_geometry: str = "spectrum",
    spectrum_layout: str = "linear",
    spectrum_slot_sigma: float = 0.0,
    ribbon_supersample: int | None = None,
    render_path: str | None = None,
    render_aa: str | None = None,
    field_geometry: str = "ribbon",
    bar_width: float | None = None,
    bar_gap: float | None = None,
    bar_count: int | None = None,
    bar_fill: float | None = None,
    bar_align: str | None = None,
    bar_alternate: bool | None = None,
    bar_color_b: str | None = None,
    bar_center_line_width: float | None = None,
) -> FixedAxisAppearance:
    # Validation is also repeated here for application callers mutating a resolved copy.
    preset.validate_fixed_axis_profile()
    profile = (
        str(preset.signal["fixed_axis_profile"]) if "fixed_axis_profile" in preset.signal else None
    )
    refined = profile == REFINED_RIBBON
    detail_level = str(preset.signal.get("detail_level", "balanced")) if refined else None
    baseline_thickness = (preset.waveform.stroke_width or 1.0) if refined else None
    if refined:
        unsupported = {
            "spectrum_contour": spectrum_contour,
            "spectrum_spatial_scale": spectrum_spatial_scale != 1.0,
            "spectrum_spatial_filter": spectrum_spatial_filter != "box",
            "spectrum_n_bands": spectrum_n_bands is not None,
            "spectrum_tilt_db_per_octave": spectrum_tilt_db_per_octave != 0.0,
            "spectrum_compress": spectrum_compress != 1.0,
            "spectrum_recenter": spectrum_recenter,
            "spectrum_edge_taper": spectrum_edge_taper != 0.0,
            "spectrum_slot_sigma": spectrum_slot_sigma != 0.0,
            "bar controls": any(
                x is not None
                for x in (
                    bar_width,
                    bar_gap,
                    bar_count,
                    bar_fill,
                    bar_align,
                    bar_color_b,
                    bar_center_line_width,
                )
            ),
        }
        rejected = [key for key, active in unsupported.items() if active]
        if rejected:
            raise ValueError(
                "filled-ribbon-v2 unsupported low-level override(s): " + ", ".join(rejected)
            )
        if render_path not in (None, "mask_fast", "rgba_2d") or render_aa not in (
            None,
            "physical_ss",
            "coverage_taps",
        ):
            raise ValueError("filled-ribbon-v2 unknown render path/AA")
        if ribbon_supersample is not None and (
            type(ribbon_supersample) is not int or not 1 <= ribbon_supersample <= 12
        ):
            raise ValueError("filled-ribbon-v2 supersample must be an integer in [1, 12]")
    if profile is not None:
        if visual_geometry != "spectrum" or field_geometry != "ribbon":
            raise ValueError(f"{profile} only supports spectrum ribbon geometry")
        if spectrum_layout not in {"linear", "field_center_out"}:
            raise ValueError(f"{profile} owns the stationary field_center_out layout")
        if bar_alternate:
            raise ValueError(f"{profile} is monochrome; alternating bars are unsupported")
        # Named visual bundle, not a performance setting or a change to built-in defaults.
        # Render path, AA and supersampling remain independent existing selections.
        spectrum_layout = "field_center_out"
        spectrum_n_bands = 64
        spectrum_tilt_db_per_octave = 3.0
        spectrum_compress = 0.75
        spectrum_spatial_scale = 1.0
        spectrum_spatial_filter = "gaussian"
        spectrum_recenter = False
        spectrum_edge_taper = 0.0
        spectrum_slot_sigma = 0.0
        bar_alternate = False
        if refined:
            assert detail_level is not None
            spectrum_compress = 1.0
            spectrum_spatial_scale = DETAIL_SETTINGS[detail_level][3]
    geometry = (
        visual_geometry if visual_geometry in {"temporal_rms", "temporal_rms_peak"} else "spectrum"
    )
    ribbon_ss = (
        max(1, int(ribbon_supersample)) if ribbon_supersample is not None else RIBBON_SUPERSAMPLE
    )
    if geometry != "spectrum":
        return FixedAxisAppearance(geometry=geometry, ribbon_ss=ribbon_ss)
    raw_smooth = preset.signal.get("smoothing", 0.0)
    tau = 0.0
    if isinstance(raw_smooth, int | float) and not isinstance(raw_smooth, bool):
        tau = max(0.0, float(raw_smooth))
    bars: BarStyle | None = None
    field_plan: RenderPlan | None = None
    spatial_scale = (
        spectrum_spatial_scale
        if isinstance(spectrum_spatial_scale, int | float)
        and not isinstance(spectrum_spatial_scale, bool)
        and spectrum_spatial_scale > 0.0
        else 1.0
    )
    spatial_filter = normalize_spatial_filter(spectrum_spatial_filter)
    spatial_sigma = spectrum_spatial_sigma(preset.canvas.width, tau, float(spatial_scale))
    n_bands = (
        int(spectrum_n_bands)
        if isinstance(spectrum_n_bands, int)
        and not isinstance(spectrum_n_bands, bool)
        and spectrum_n_bands >= 2
        else None
    )
    tilt_db = (
        float(spectrum_tilt_db_per_octave)
        if isinstance(spectrum_tilt_db_per_octave, int | float)
        and not isinstance(spectrum_tilt_db_per_octave, bool)
        else 0.0
    )
    compress = (
        float(spectrum_compress)
        if isinstance(spectrum_compress, int | float)
        and not isinstance(spectrum_compress, bool)
        and spectrum_compress > 0.0
        else 1.0
    )
    recenter = bool(spectrum_recenter)
    taper = (
        float(spectrum_edge_taper)
        if isinstance(spectrum_edge_taper, int | float)
        and not isinstance(spectrum_edge_taper, bool)
        and spectrum_edge_taper > 0.0
        else 0.0
    )
    if taper > 0.0:
        taper = min(taper, 0.49)
    if spectrum_layout == "field_center_out":
        layout = "field_center_out"
    elif spectrum_layout == "center_out":
        layout = "center_out"
    else:
        layout = "linear"
    slot_sigma = (
        float(spectrum_slot_sigma)
        if isinstance(spectrum_slot_sigma, int | float)
        and not isinstance(spectrum_slot_sigma, bool)
        and spectrum_slot_sigma > 0.0
        else 0.0
    )
    if layout == "field_center_out":
        forced_path: Literal["mask_fast", "rgba_2d"] | None = None
        if render_path == "mask_fast":
            forced_path = "mask_fast"
        elif render_path == "rgba_2d":
            forced_path = "rgba_2d"
        aa_mode: Literal["physical_ss", "coverage_taps"] | None = None
        if render_aa == "physical_ss":
            aa_mode = "physical_ss"
        elif render_aa == "coverage_taps":
            aa_mode = "coverage_taps"
        resolved_field_geometry = "ribbon"
        if field_geometry in MASK_GEOMETRIES:
            resolved_field_geometry = field_geometry
        pack = default_bar_style(resolved_field_geometry)
        align = bar_align if bar_align in {"period", "count", "slots"} else pack.align
        bars = BarStyle(
            width=pack.width if bar_width is None else float(bar_width),
            gap=pack.gap if bar_gap is None else float(bar_gap),
            count=None if bar_count is None else max(1, int(bar_count)),
            fill=pack.fill if bar_fill is None else float(bar_fill),
            align=align,
            alternate=pack.alternate if bar_alternate is None else bool(bar_alternate),
            color_b=pack.color_b if bar_color_b is None else str(bar_color_b),
            center_line_width=(
                pack.center_line_width
                if bar_center_line_width is None
                else float(bar_center_line_width)
            ),
        )
        field_plan = resolve_render_plan(
            preset,
            layout=layout,
            field_geometry=resolved_field_geometry,
            ribbon_supersample=ribbon_ss,
            force_path=forced_path,
            aa_mode=aa_mode,
            alternate_bars=bars.alternate,
        )

    return FixedAxisAppearance(
        geometry=geometry,
        ribbon_ss=ribbon_ss,
        spatial_scale=float(spatial_scale),
        spatial_filter=spatial_filter,
        spatial_sigma=spatial_sigma,
        n_bands=n_bands,
        tilt_db=tilt_db,
        compress=compress,
        recenter=recenter,
        taper=taper,
        layout=layout,
        slot_sigma=slot_sigma,
        contour=bool(spectrum_contour),
        bars=bars,
        field_plan=field_plan,
        profile=profile,
        detail_level=detail_level,
        baseline_thickness=baseline_thickness,
    )
