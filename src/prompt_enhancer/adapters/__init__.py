"""Read-only provider adapters."""

from .base import AdapterHealth, AdapterProbe, ProviderAdapter
from .synthetic import SyntheticAdapter

__all__ = ["AdapterHealth", "AdapterProbe", "ProviderAdapter", "SyntheticAdapter"]
