"""Static compliance checks for the non-intrusiveness promise."""

from aiduvo.lint.nonintrusive import (
    ComplianceReport,
    Violation,
    check_files,
    check_repo,
)

__all__ = ["ComplianceReport", "Violation", "check_repo", "check_files"]
