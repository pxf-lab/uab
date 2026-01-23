"""Houdini integration for Universal Asset Browser.

This package provides the HoudiniIntegration class and renderer-specific
strategies for importing assets into Houdini.

Usage in Houdini Python Panel:
    from uab.integrations.houdini import HoudiniIntegration
    integration = HoudiniIntegration()

The integration auto-detects the active renderer and delegates material
creation to the appropriate RenderStrategy (Arnold, Redshift, etc.).
"""

from uab.integrations.houdini.integration import HoudiniIntegration

__all__ = ["HoudiniIntegration"]
