"""Validate complete effective output selections without changing their semantics."""

from __future__ import annotations

from collections.abc import Sequence

from ewp_waveform.application.errors import AppError
from ewp_waveform.domain.diagnostics import Diagnostic, DiagnosticCode, ExitCode, Severity

SUPPORTED_OUTPUT_FORMATS = ("png", "prores4444")


class UnsupportedOutputFormatError(AppError):
    """An output request contains tokens unsupported by the application (exit 2)."""

    def __init__(self, unsupported: Sequence[str]) -> None:
        message = (
            f"Unsupported output format(s): {', '.join(repr(token) for token in unsupported)}. "
            f"Supported formats: {', '.join(SUPPORTED_OUTPUT_FORMATS)}."
        )
        super().__init__(
            ExitCode.CONFIG,
            message,
            Diagnostic(
                code=DiagnosticCode.E_CONFIG_INVALID, severity=Severity.ERROR, message=message
            ),
        )


def validate_output_formats(formats: Sequence[str]) -> None:
    """Reject every unknown token; leave empty/default and repeated selections intact."""
    unsupported = list(
        dict.fromkeys(token for token in formats if token not in SUPPORTED_OUTPUT_FORMATS)
    )
    if unsupported:
        raise UnsupportedOutputFormatError(unsupported)
