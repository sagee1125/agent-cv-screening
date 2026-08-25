# Compatibility shim: hash cache lives in screening_core.
from screening_core.hash_cache import HashCache

__all__ = ["HashCache"]
