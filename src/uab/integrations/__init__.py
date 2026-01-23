"""Host integrations for Universal Asset Browser.

This package contains integrations for different DCC applications
(Houdini, Maya, etc.) and a standalone integration for development.

Available Integrations:
    - StandaloneIntegration: Mock integration for development/testing
    - HoudiniIntegration: Full Houdini integration with renderer support

Usage:
    # Standalone (development)
    from uab.integrations import StandaloneIntegration
    integration = StandaloneIntegration()

    # Houdini
    from uab.integrations import HoudiniIntegration
    integration = HoudiniIntegration()
"""

from uab.integrations.standalone import StandaloneIntegration

# Houdini integration is imported lazily to avoid hou import errors
# when running outside of Houdini
__all__ = ["StandaloneIntegration", "HoudiniIntegration"]


def __getattr__(name: str):
    """Lazy import for Houdini integration to avoid import errors outside Houdini."""
    if name == "HoudiniIntegration":
        from uab.integrations.houdini import HoudiniIntegration
        return HoudiniIntegration
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
