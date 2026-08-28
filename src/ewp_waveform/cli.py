"""Thin CLI adapter. No FFmpeg command construction here."""

# Typer requires Option/Argument defaults; ruff B008 does not apply.

from __future__ import annotations

from pathlib import Path

import typer

from ewp_waveform import __version__
from ewp_waveform.application import service as app_service
from ewp_waveform.application.service import AppError
from ewp_waveform.domain.diagnostics import EXIT_CODE_VALUES, ExitCode

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
) -> None:
    """Resolve discovery, grouping, and effective config without rendering."""
    try:
        _cfg, visual, jobs, diagnostics = app_service.dry_run(
            input_path,
            recursive=recursive,
            config_path=config,
            preset_name=preset,
            performance_name=performance,
            fps_override=fps,
        )
    except AppError as exc:
        _fail(exc)
    typer.echo(
        f"preset: {visual.name}  style: {visual.waveform.style}  domain: {visual.waveform.domain}"
    )
    typer.echo(f"jobs: {len(jobs)}")
    for job in jobs:
        typer.echo(
            f"  {job.path.name} -> {job.project_id}/{job.track_id}  "
            f"{job.status.value}  capability={job.capability.value}"
        )
        if job.capability_notes:
            typer.echo(f"    {job.capability_notes}")
    for diag in diagnostics:
        color = typer.colors.YELLOW if diag.severity.value == "warning" else typer.colors.RED
        typer.secho(f"{diag.code.value}: {diag.message}", fg=color)
    if any(d.severity.value == "error" for d in diagnostics):
        raise typer.Exit(EXIT_CODE_VALUES[ExitCode.INPUT])


@app.command()
def render(
    input_path: Path = typer.Argument(..., metavar="INPUT"),
) -> None:
    """Render is not product-faithful yet. Use doctor/inspect/dry-run/capabilities."""
    typer.secho(
        "E_RENDERER_CAPABILITY: render is not implemented. "
        "Scrolling envelope and fixed-axis spectrum looks are not brand-faithful in FFmpeg yet. "
        "See `waveform capabilities`.",
        fg=typer.colors.RED,
        err=True,
    )
    raise typer.Exit(EXIT_CODE_VALUES[ExitCode.CAPABILITY])


def main() -> None:
    app()
