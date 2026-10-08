"""Sanitized exceptions exposed by persistence ports to application services."""


class PersistenceConflictError(RuntimeError):
    """A transaction conflicts with immutable or optimistic stored state."""
