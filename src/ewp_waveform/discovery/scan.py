"""Discover WAV/MP3 inputs. Directory processing is non-recursive by default."""

from __future__ import annotations

from pathlib import Path

from ewp_waveform.domain.diagnostics import Diagnostic, DiagnosticCode, Severity

MVP_SUFFIXES = {".wav", ".mp3"}


class DiscoveryError(Exception):
    def __init__(self, diagnostic: Diagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


def discover_paths(
    input_path: Path,
    *,
    recursive: bool = False,
    follow_symlinks: bool = False,
) -> list[Path]:
    path = input_path.expanduser().resolve(strict=False)
    if not path.exists():
        raise DiscoveryError(
            Diagnostic(
                code=DiagnosticCode.E_INPUT_UNSUPPORTED,
                severity=Severity.ERROR,
                message=f"Input does not exist: {input_path}",
                path=str(input_path),
            )
        )
    if path.is_file():
        if path.suffix.lower() not in MVP_SUFFIXES:
            raise DiscoveryError(
                Diagnostic(
                    code=DiagnosticCode.E_INPUT_UNSUPPORTED,
                    severity=Severity.ERROR,
                    message=f"MVP inputs are WAV and MP3; got {path.suffix or 'no suffix'}",
                    path=str(path),
                )
            )
        return [path]
    if not path.is_dir():
        raise DiscoveryError(
            Diagnostic(
                code=DiagnosticCode.E_INPUT_UNSUPPORTED,
                severity=Severity.ERROR,
                message=f"Input is neither a file nor a directory: {path}",
                path=str(path),
            )
        )
    if recursive:
        return _scan_recursive(path, follow_symlinks=follow_symlinks)
    return [
        child
        for child in sorted(path.iterdir())
        if child.is_file() and child.suffix.lower() in MVP_SUFFIXES
    ]


def _scan_recursive(root: Path, *, follow_symlinks: bool) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in root.walk(follow_symlinks=follow_symlinks):
        if not follow_symlinks:
            dirnames[:] = [name for name in dirnames if not (dirpath / name).is_symlink()]
        for name in filenames:
            candidate = dirpath / name
            if candidate.suffix.lower() in MVP_SUFFIXES and candidate.is_file():
                found.append(candidate)
    return sorted(found)
