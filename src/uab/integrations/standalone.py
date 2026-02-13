"""Standalone integration for development and testing.

This integration provides mock behavior for running UAB outside of a DCC
application. It's useful for UI development, testing, and debugging.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from uab.core.interfaces import HostIntegration, RenderStrategy
from uab.core.models import CompositeAsset, StandardAsset

logger = logging.getLogger(__name__)


class _NoopStrategy(RenderStrategy):
    """RenderStrategy stub for standalone mode (never executed)."""

    def get_required_texture_maps(self) -> set[str]:
        return set()

    def create_environment_light(
        self, composite: CompositeAsset, options: dict[str, Any]
    ) -> Any:  # noqa: ANN401
        raise NotImplementedError

    def update_environment_light(
        self, asset: StandardAsset, options: dict[str, Any]
    ) -> None:
        raise NotImplementedError

    def create_material_from_textures(
        self, name: str, textures: dict[str, Path], options: dict[str, Any]
    ) -> Any:  # noqa: ANN401
        raise NotImplementedError

    def create_material(
        self, composite: CompositeAsset, options: dict[str, Any]
    ) -> Any:  # noqa: ANN401
        raise NotImplementedError

    def update_material(self, asset: StandardAsset, options: dict[str, Any]) -> None:
        raise NotImplementedError


class StandaloneIntegration(HostIntegration):
    """
    This is only for testing and development.

    Mock host integration for standalone development.

    This integration allows UAB to run outside of a DCC application.
    Import operations are logged to the console instead of creating
    actual scene objects.
    """

    _SUPPORTED_RENDERERS = ["arnold", "redshift", "karma"]

    def __init__(self) -> None:
        self._strategies: dict[str, RenderStrategy] = {}
        self._load_strategies()

    def _load_strategies(self) -> None:
        # In standalone mode we register placeholder strategies so the UI can
        # exercise renderer selection logic consistently across integrations.
        self._strategies = {r: _NoopStrategy()
                            for r in self._SUPPORTED_RENDERERS}

    @property
    def uab_supported_renderers(self) -> list[str]:
        """Return renderer identifiers that have a registered strategy."""
        return [r for r in self._SUPPORTED_RENDERERS if r in self._strategies]

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
        return self._SUPPORTED_RENDERERS.copy()

    def get_active_renderer(self) -> str:
        """
        Return the default active renderer for standalone mode.

        Returns:
            "arnold" as the default renderer
        """
        return "arnold"

    @property
    def supports_replace_selection(self) -> bool:
        """
        Standalone mode does not support node replacement.

        The "Replace" context menu action will not be shown in standalone mode.
        """
        return False

    @property
    def supports_import(self) -> bool:
        """
        Standalone mode does not support importing into a host scene.
        """
        return False
