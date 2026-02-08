"""Host integrations for Universal Asset Browser.

This package contains integrations for different DCC applications
(Houdini, Maya, etc.) and a standalone integration for development.

Available Integrations:
    - StandaloneIntegration: Mock integration for development/testing
    - HoudiniIntegration: Houdini 21+
    - MayaIntegration: Maya 2025+

Usage:
    # Standalone (development)
    from uab.integrations import StandaloneIntegration
    integration = StandaloneIntegration()

    # Houdini
    from uab.integrations import HoudiniIntegration
    integration = HoudiniIntegration()

    # Maya
    from uab.integrations import MayaIntegration
    integration = MayaIntegration()
"""

from uab.integrations.standalone import StandaloneIntegration

__all__ = ["StandaloneIntegration", "HoudiniIntegration", "MayaIntegration"]


def __getattr__(name: str):
    """Lazy imports for DCC integrations to avoid import errors outside hosts."""
    if name == "HoudiniIntegration":
        from uab.integrations.houdini import HoudiniIntegration
        return HoudiniIntegration
    if name == "MayaIntegration":
        from uab.integrations.maya import MayaIntegration
        return MayaIntegration
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
