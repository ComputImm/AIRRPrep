# app/singlecell/errors.py
"""
Exceptions for the single-cell preprocessing module.

SingleCellAdapterError is the umbrella type routers/tasks catch to turn into
a clean 400 / job "FAILED"+error — never a 500, since these are all
user-actionable (bad/missing input files, unsupported format) or ops-actionable
(SingleCellConfigError) conditions, not bugs.
"""


class SingleCellAdapterError(Exception):
    """Base error for anything wrong with a single-cell input/adapter."""


class SingleCellConfigError(SingleCellAdapterError):
    """Raised when a required external tool (e.g. TRUST4) isn't configured."""


class SingleCellValidationError(SingleCellAdapterError):
    """Raised when no valid unified records remain after validation."""
