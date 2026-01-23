"""Asset library plugins for Universal Asset Browser.

This package contains plugins that provide access to different asset sources:
- mock: Mock plugin for development and testing
- local: Local library plugin for managing downloaded assets
- polyhaven: Poly Haven cloud asset plugin

Plugins auto-register via __init_subclass__ when imported.
"""

# Import plugins to trigger auto-registration
from uab.plugins.base import SharedAssetLibraryUtils
from uab.plugins.mock import MockPlugin
from uab.plugins.local import LocalLibraryPlugin
from uab.plugins.polyhaven import PolyHavenPlugin

__all__ = [
    "SharedAssetLibraryUtils",
    "MockPlugin",
    "LocalLibraryPlugin",
    "PolyHavenPlugin",
]
