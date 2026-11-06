"""Why a build fails (Specification 0.1, sections 7.1 and 7.3)."""

from pathlib import Path

REASONS = ("invalid_input", "piece_mismatch", "over_budget", "strict")
"""The reasons of a failed build, as ``build-report.json`` names them (section 7.3)."""


class BuildError(Exception):
    """A build that stops: ``reason`` is one of :data:`REASONS`, the message says what and where."""

    def __init__(self, reason: str, message: str) -> None:
        if reason not in REASONS:
            raise ValueError(f"unknown build failure reason {reason!r}; one of {REASONS}")
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.report: Path | None = None
        """The build report written for this failure (section 7.2), once :func:`build` wrote it."""

    def __str__(self) -> str:
        return f"{self.message} [{self.reason}]"
