"""Thin CLI adapter. No FFmpeg command construction here."""

# Typer requires Option/Argument defaults; ruff B008 does not apply.

from __future__ import annotations

from pathlib import Path

import typer

from ewp_waveform import __version__
from ewp_waveform.application import service as app_service
from ewp_waveform.application.service import AppError
from ewp_waveform.config.load import load_performance, load_preset
from ewp_waveform.domain.diagnostics import EXIT_CODE_VALUES, ExitCode
from ewp_waveform.identity import short_signature

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="ewp-waveform — deterministic transparent waveform assets.",
)


def _fail(exc: AppError) -> None:
    typer.secho(
        exc.diagnostic.code.value if exc.diagnostic else "ERROR", fg=typer.colors.RED, err=True
    )
    typer.echo(str(exc), err=True)
    raise typer.Exit(exc.numeric_exit)


@app.callback()
def _root() -> None:
    """ewp-waveform CLI."""


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


@app.command()
def doctor() -> None:
    """Check FFmpeg/ffprobe, encoders, and required filters. GPU checks are deferred."""
    problems = app_service.doctor()
    if not problems:
        typer.echo("doctor: ok")
        raise typer.Exit(EXIT_CODE_VALUES[ExitCode.SUCCESS])
    for item in problems:
        typer.secho(item, fg=typer.colors.RED, err=True)
    raise typer.Exit(EXIT_CODE_VALUES[ExitCode.CAPABILITY])


@app.command()
def capabilities() -> None:
    """Report renderer/style/domain/effect/output support honestly."""
    for item in app_service.capabilities():
        typer.echo(f"{item.level.value:13} {item.name}")
        if item.notes:
            typer.echo(f"              {item.notes}")


@app.command("inspect")
def inspect_cmd(
    input_path: Path = typer.Argument(..., metavar="INPUT"),
    recursive: bool = typer.Option(False, "--recursive"),
    config: Path | None = typer.Option(None, "--config", exists=True, dir_okay=False),
) -> None:
    """Report source and grouping metadata without rendering."""
    try:
        rows = app_service.inspect_input(input_path, recursive=recursive, config_path=config)
    except AppError as exc:
        _fail(exc)
    for media, project_id, track_id in rows:
        typer.echo(f"path: {media.path}")
        typer.echo(f"  project: {project_id}  track: {track_id}")
        typer.echo(
            f"  duration_s: {media.duration_seconds:.3f}  rate: {media.sample_rate}  "
            f"channels: {media.channels}  codec: {media.codec}"
        )


@app.command("dry-run")
def dry_run_cmd(
    input_path: Path = typer.Argument(..., metavar="INPUT"),
    recursive: bool = typer.Option(False, "--recursive"),
    config: Path | None = typer.Option(None, "--config", exists=True, dir_okay=False),
    preset: str | None = typer.Option(None, "--preset"),
    performance: str | None = typer.Option(None, "--performance"),
    fps: float | None = typer.Option(None, "--fps"),
    output_dir: Path | None = typer.Option(None, "--output-dir"),
    format_name: list[str] | None = typer.Option(None, "--format"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Resolve discovery, grouping, signatures, dests, and SKIP/PROCESS without rendering."""
    try:
        _cfg, visual, perf, plans, diagnostics = app_service.plan_jobs(
            input_path,
            recursive=recursive,
            config_path=config,
            preset_name=preset,
            performance_name=performance,
            fps_override=fps,
            output_dir=output_dir,
            formats=format_name,
            force=force,
        )
    except AppError as exc:
        _fail(exc)
    typer.echo(
        f"preset: {visual.name}  style: {visual.waveform.style}  domain: {visual.waveform.domain}"
    )
    typer.echo(
        f"performance: {perf.name}  chunk_seconds: {perf.processing.get('chunk_seconds', 60)}"
    )
    typer.echo(f"jobs: {len(plans)}")
    for planned in plans:
        job = planned.job
        sig = planned.render_signature
        short = short_signature(sig) if sig else "-"
        typer.echo(
            f"  {planned.action:8} {job.path.name} -> {job.project_id}/{job.track_id}  "
            f"sig={short}  capability={job.capability.value}"
        )
        if planned.mov_path is not None:
            typer.echo(f"    mov: {planned.mov_path}")
        if planned.png_path is not None:
            typer.echo(f"    png: {planned.png_path}")
        if job.capability_notes:
            typer.echo(f"    {job.capability_notes}")
    for diag in diagnostics:
        color = typer.colors.YELLOW if diag.severity.value == "warning" else typer.colors.RED
        typer.secho(f"{diag.code.value}: {diag.message}", fg=color)
    if any(d.severity.value == "error" for d in diagnostics):
        raise typer.Exit(EXIT_CODE_VALUES[ExitCode.INPUT])


def _run_render(
    input_path: Path,
    *,
    recursive: bool,
    config: Path | None,
    preset: str | None,
    performance: str | None,
    fps: float | None,
    output_dir: Path | None,
    formats: list[str] | None,
    force: bool,
    start: float | None,
    duration: float | None,
    keep_temp: bool,
) -> None:
    try:
        results = app_service.render(
            input_path,
            recursive=recursive,
            config_path=config,
            preset_name=preset,
            performance_name=performance,
            fps_override=fps,
            output_dir=output_dir,
            formats=formats or None,
            force=force,
            start=start,
            duration=duration,
            keep_temp=keep_temp,
        )
    except AppError as exc:
        _fail(exc)
    failed = 0
    run_json = None
    for payload in results:
        job_obj = payload.get("job")
        status = "UNKNOWN"
        if isinstance(job_obj, dict):
            status = str(job_obj.get("status", "UNKNOWN"))
        typer.echo(f"{status}: {payload.get('result_json', '')}")
        outputs = payload.get("outputs")
        if isinstance(outputs, list):
            for item in outputs:
                if isinstance(item, dict):
                    typer.echo(f"  {item.get('format')}: {item.get('path')}")
        if run_json is None:
            run_json = payload.get("run_json")
        if status == "FAILED":
            failed += 1
    if run_json:
        typer.echo(f"run: {run_json}")
    if failed and failed == len(results):
        raise typer.Exit(EXIT_CODE_VALUES[ExitCode.RENDER])
    if failed:
        raise typer.Exit(EXIT_CODE_VALUES[ExitCode.PARTIAL])


@app.command()
def render(
    input_path: Path = typer.Argument(..., metavar="INPUT"),
    recursive: bool = typer.Option(False, "--recursive"),
    config: Path | None = typer.Option(None, "--config", exists=True, dir_okay=False),
    preset: str | None = typer.Option(None, "--preset"),
    performance: str | None = typer.Option(None, "--performance"),
    fps: float | None = typer.Option(None, "--fps"),
    output_dir: Path | None = typer.Option(None, "--output-dir"),
    format_name: list[str] | None = typer.Option(None, "--format"),
    force: bool = typer.Option(False, "--force"),
    keep_temp: bool = typer.Option(False, "--keep-temp"),
) -> None:
    """Render waveform assets (scrolling envelope or experimental spectrum)."""
    _run_render(
        input_path,
        recursive=recursive,
        config=config,
        preset=preset,
        performance=performance,
        fps=fps,
        output_dir=output_dir,
        formats=format_name,
        force=force,
        start=None,
        duration=None,
        keep_temp=keep_temp,
    )


@app.command()
def preview(
    input_path: Path = typer.Argument(..., metavar="INPUT"),
    start: float = typer.Option(0.0, "--start"),
    duration: float = typer.Option(8.0, "--duration"),
    recursive: bool = typer.Option(False, "--recursive"),
    config: Path | None = typer.Option(None, "--config", exists=True, dir_okay=False),
    preset: str | None = typer.Option(None, "--preset"),
    fps: float | None = typer.Option(None, "--fps"),
    output_dir: Path | None = typer.Option(None, "--output-dir"),
    format_name: list[str] | None = typer.Option(None, "--format"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Render a short interval using the real production path."""
    _run_render(
        input_path,
        recursive=recursive,
        config=config,
        preset=preset,
        performance=None,
        fps=fps,
        output_dir=output_dir,
        formats=format_name,
        force=force,
        start=start,
        duration=duration,
        keep_temp=False,
    )


preset_app = typer.Typer(help="List and show visual presets.")
performance_app = typer.Typer(help="List and show performance profiles.")
benchmark_app = typer.Typer(help="Expand and run benchmark manifests.")
app.add_typer(preset_app, name="preset")
app.add_typer(performance_app, name="performance")
app.add_typer(benchmark_app, name="benchmark")


@preset_app.command("list")
def preset_list() -> None:
    """List builtin visual presets."""
    for name, path in app_service.catalog_presets():
        typer.echo(f"{name}\tbuiltin\t{path}")


@preset_app.command("show")
def preset_show(name: str = typer.Argument(..., metavar="NAME_OR_PATH")) -> None:
    """Show a visual preset (builtin name or .toml path)."""
    try:
        preset = load_preset(name)
    except FileNotFoundError as exc:
        _fail(AppError(ExitCode.CONFIG, str(exc)))
    except ValueError as exc:
        _fail(AppError(ExitCode.CONFIG, str(exc)))
    typer.echo(f"name: {preset.name}")
    typer.echo(f"style: {preset.waveform.style}  domain: {preset.waveform.domain}")
    typer.echo(f"time_mode: {preset.waveform.time_mode}  fps: {preset.canvas.fps}")
    typer.echo(f"canvas: {preset.canvas.width}x{preset.canvas.height}")
    if preset.description:
        typer.echo(f"description: {preset.description}")


@performance_app.command("list")
def performance_list() -> None:
    """List builtin performance profiles."""
    for name, path in app_service.catalog_performance():
        typer.echo(f"{name}\tbuiltin\t{path}")


@performance_app.command("show")
def performance_show(name: str = typer.Argument(..., metavar="NAME_OR_PATH")) -> None:
    """Show a performance profile (builtin name or .toml path)."""
    try:
        profile = load_performance(name)
    except FileNotFoundError as exc:
        _fail(AppError(ExitCode.CONFIG, str(exc)))
    except ValueError as exc:
        _fail(AppError(ExitCode.CONFIG, str(exc)))
    typer.echo(f"name: {profile.name}")
    typer.echo(f"processing: {profile.processing}")
    typer.echo(f"workdirs: {profile.workdirs}")
    if profile.description:
        typer.echo(f"description: {profile.description}")


@app.command()
def clean(
    workdirs: bool = typer.Option(False, "--workdirs", help="Remove abandoned ewp-* workdirs."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="List matching workdirs without deleting."
    ),
    root: Path | None = typer.Option(None, "--root", help="Workdir parent (default: system temp)."),
) -> None:
    """Remove intermediate workdirs. Never touches published outputs."""
    if not workdirs:
        typer.echo("specify --workdirs", err=True)
        raise typer.Exit(EXIT_CODE_VALUES[ExitCode.CONFIG])
    found = app_service.clean(root=root, dry_run=dry_run)
    if not found:
        typer.echo("clean: no workdirs")
        return
    verb = "would remove" if dry_run else "removed"
    for path in found:
        typer.echo(f"{verb}: {path}")


@benchmark_app.command("dry-run")
def benchmark_dry_run_cmd(
    manifest: Path = typer.Argument(..., metavar="MANIFEST", exists=True, dir_okay=False),
    output_dir: Path = typer.Option(Path("benchmark-output"), "--output-dir"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Expand a benchmark matrix without rendering."""
    try:
        loaded, cells = app_service.benchmark_dry_run(manifest, output_dir=output_dir, force=force)
    except AppError as exc:
        _fail(exc)
    typer.echo(f"manifest: {loaded.name}  cells: {len(cells)}")
    estimated = 0.0
    has_estimate = False
    for cell in cells:
        dest = cell.mov_path or cell.png_path or "-"
        typer.echo(
            f"  {cell.action:12} {cell.input_path.name}  {cell.variant_name}  "
            f"{cell.renderer}/{cell.performance_name}  {dest}"
        )
        if cell.notes:
            typer.echo(f"               {cell.notes}")
        if cell.estimated_output_mb is not None:
            estimated += cell.estimated_output_mb
            has_estimate = True
    if has_estimate:
        typer.echo(f"estimated_output_mb: {estimated:.1f}  ({_ESTIMATE_NOTE})")


_ESTIMATE_NOTE = "labelled spike extrapolation; not a profile default"


@benchmark_app.command("run")
def benchmark_run_cmd(
    manifest: Path = typer.Argument(..., metavar="MANIFEST", exists=True, dir_okay=False),
    output_dir: Path = typer.Option(Path("benchmark-output"), "--output-dir"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Render every PROCESS cell in a benchmark manifest."""
    try:
        summary = app_service.benchmark_run(manifest, output_dir=output_dir, force=force)
    except AppError as exc:
        _fail(exc)
    counts = summary.get("counts")
    typer.echo(f"manifest: {summary.get('manifest')}  result: {summary.get('result_json')}")
    if isinstance(counts, dict):
        typer.echo(
            "counts: "
            f"cells={counts.get('cells')} succeeded={counts.get('succeeded')} "
            f"skipped={counts.get('skipped')} failed={counts.get('failed')} "
            f"blocked={counts.get('blocked')}"
        )
    failed = int(counts.get("failed") or 0) if isinstance(counts, dict) else 0
    cells = int(counts.get("cells") or 0) if isinstance(counts, dict) else 0
    if failed and failed == cells:
        raise typer.Exit(EXIT_CODE_VALUES[ExitCode.RENDER])
    if failed:
        raise typer.Exit(EXIT_CODE_VALUES[ExitCode.PARTIAL])


def main() -> None:
    app()
