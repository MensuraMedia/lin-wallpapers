"""Apply engine: plan, precheck, backup, write, verify, commit or roll back (M4–M5).

No GTK imports — enforced by import-linter. The core never imports a provider module.
"""

from .registry import ProviderRegistry, Surface, SurfaceProvider, registry

__all__ = ["ProviderRegistry", "Surface", "SurfaceProvider", "registry"]
