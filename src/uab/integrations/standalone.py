"""Standalone integration for development and testing.

This integration provides mock behavior for running UAB outside of a DCC
application. It's useful for UI development, testing, and debugging.
"""

from __future__ import annotations

import logging
from typing import Any

from uab.core.interfaces import HostIntegration
from uab.core.models import StandardAsset

logger = logging.getLogger(__name__)


class StandaloneIntegration(HostIntegration):
    """
    This is only for testing and development.

    Mock host integration for standalone development.

    This integration allows UAB to run outside of a DCC application.
    Import operations are logged to the console instead of creating
    actual scene objects.
    """

    @property
    def uab_supported_renderers(self) -> list[str]:
        """Return mock renderer list for testing."""
        return ["arnold", "redshift", "karma"]

    def import_asset(self, asset: StandardAsset, options: dict[str, Any]) -> None:
        """
        Mock import - logs the operation instead of creating scene objects.

        Args:
            asset: The asset to import
            options: Import options
        """
        logger.info(f"[Standalone] Would import asset: {asset.name}")
        logger.info(f"  Type: {asset.type.value}")
        logger.info(f"  Source: {asset.source}")
        logger.info(f"  Path: {asset.local_path}")
        logger.info(f"  Options: {options}")

        # Print to console for visibility during development
        print(f"\n{'='*50}")
        print(f"IMPORT ASSET (Standalone Mode)")
        print(f"{'='*50}")
        print(f"Name: {asset.name}")
        print(f"Type: {asset.type.value}")
        print(f"Source: {asset.source}")
        print(f"Local Path: {asset.local_path}")
        print(f"Options: {options}")
        print(f"{'='*50}\n")

    def update_selection(self, asset: StandardAsset) -> None:
        """
        Mock update selection - logs the operation.

        Args:
            asset: The asset to select
        """
        logger.info(f"[Standalone] Would update selection to: {asset.name}")
        print(f"[Standalone] Update selection: {asset.name}")

    def get_host_available_renderers(self) -> list[str]:
        """
        Return all renderers as available in standalone mode.

        In standalone mode, we pretend all renderers are available
        so the UI can be fully tested.
        """
        return ["arnold", "redshift", "karma"]

    def get_active_renderer(self) -> str:
        """
        Return the default active renderer for standalone mode.

        Returns:
            "arnold" as the default renderer
        """
        return "arnold"
