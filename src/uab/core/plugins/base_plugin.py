from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Set, Type


class BasePlugin(ABC):
    """Abstract base class for all plugins.

    automatically registers concrete subclasses via __init_subclass__.
    """

    _plugin_types: Set[Type[BasePlugin]] = set()

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)

        # Only register non abstract classes
        if not getattr(cls, "__abstractmethods__", None):
            cls._plugin_types.add(cls)

    @classmethod
    def get_plugin_types(cls) -> Set[Type[BasePlugin]]:
        return cls._plugin_types.copy()

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique internal identifier of the plugin.
        Use the convention organization_name.plugin_name, ex. pxf.local_assets_browser."""
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """User-facing name of the plugin."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Brief description of the plugin's functionality."""
        pass

    @property
    @abstractmethod
    def is_enabled(self) -> bool:
        """Return True if the plugin is currently active."""
        pass

    @abstractmethod
    def enable(self) -> None:
        """Activate the plugin (initialization, event connection)."""
        pass

    @abstractmethod
    def disable(self) -> None:
        """Deactivate the plugin (cleanup, event disconnection)."""
        pass
