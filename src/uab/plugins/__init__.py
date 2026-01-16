"""Asset library plugins for Universal Asset Browser.

This package contains plugins that provide access to different asset sources:
- mock: Mock plugin for development and testing
- local: Local library plugin for managing downloaded assets (Phase 4)
- polyhaven: Poly Haven cloud asset plugin (Phase 4)

Plugins auto-register via __init_subclass__ when imported.
"""

# Import plugins to trigger auto-registration
from uab.plugins.mock import MockPlugin

__all__ = ["MockPlugin"]
