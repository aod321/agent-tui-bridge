"""Errors shared by the atb modules."""


class TargetError(RuntimeError):
    """The session, block, or log the caller named cannot be used as given."""
