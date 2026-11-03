"""Application errors shared by service and direct job entrypoints."""

from __future__ import annotations

from ewp_waveform.domain.diagnostics import EXIT_CODE_VALUES, Diagnostic, ExitCode


class AppError(Exception):
    def __init__(
        self, exit_code: ExitCode, message: str, diagnostic: Diagnostic | None = None
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.diagnostic = diagnostic

    @property
    def numeric_exit(self) -> int:
        return EXIT_CODE_VALUES[self.exit_code]
