"""Host integrations for Universal Asset Browser.

This package contains integrations for different DCC applications
(Houdini, Maya, etc.) and a standalone integration for development.
"""

from uab.integrations.standalone import StandaloneIntegration

__all__ = ["StandaloneIntegration"]
