# Exception types shared by the JAS import skills.
from __future__ import annotations


# Raised when a requested job reference number has no matching JAS records page.
class JobNotFoundError(ValueError):
    """Indicates the requested refno does not exist on the JAS system."""


__all__ = ["JobNotFoundError"]
