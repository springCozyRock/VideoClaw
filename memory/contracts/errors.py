"""Failures that stop promotion of an unverified candidate into memory."""


class QualityBlocked(RuntimeError):
    """No candidate satisfies the configured selection and state requirements."""


class PendingAction(RuntimeError):
    """An external operation has no confirmed completion receipt."""
