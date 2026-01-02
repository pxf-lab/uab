from __future__ import annotations
import asyncio
from abc import abstractmethod
from typing import Dict, List, Set, Type, Optional, final
from weakref import WeakValueDictionary
import uuid

from uab.core.assets import Asset
from uab.core.plugins.base_plugin import BasePlugin


class AssetLibraryPlugin(BasePlugin):
    # WeakValueDictionary automatically removes the entry if the object is deleted elsewhere
    _instances: WeakValueDictionary[str,
                                    AssetLibraryPlugin] = WeakValueDictionary()

    @final
    def __init__(self) -> None:
        super().__init__()
        self.on_init()
        # Generate a unique ID for this specific run instance
        self._instance_id = f"{self.name}_{str(uuid.uuid4())}"

        AssetLibraryPlugin._instances[self._instance_id] = self

    def on_init(self) -> None:
        """
        Optional lifecycle hook for plugin setup.

        Override this to initialize instance variables, connect signals, or
        perform setup logic. Don't override __init__.

        The method is called here since `name` etc. are properties. As such, they
        may need to run init logic to set them, which has to happen before 
        instance_id is generated.
        """
        pass

    @classmethod
    def get_all_instances(cls) -> List[AssetLibraryPlugin]:
        return list(cls._instances.values())

    @classmethod
    def get_by_id(cls, instance_id: str) -> Optional[AssetLibraryPlugin]:
        return cls._instances.get(instance_id)

    @classmethod
    def get_registered_libraries(cls) -> Set[Type[AssetLibraryPlugin]]:
        """
        Dynamically filters the master list for Asset Libraries only.
        """
        all_plugins = BasePlugin.get_plugin_types()

        # Filter for subclasses of this class
        return {
            p for p in all_plugins
            if issubclass(p, cls) and p is not cls
        }

    @classmethod
    async def fetch_all_assets_async(cls) -> Dict[str, List[Asset]]:
        """
        Fetch assets from all registered plugin instances.

        Returns:
            Dict mapping instance_id to list of assets from that plugin.
        """
        instances = cls.get_all_instances()
        if not instances:
            return {}

        tasks = [inst.fetch_assets_async() for inst in instances]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output: Dict[str, List[Asset]] = {}
        for inst, result in zip(instances, results):
            if isinstance(result, Exception):
                # Log or handle error; return empty list for this plugin
                output[inst._instance_id] = []
            else:
                output[inst._instance_id] = result

        return output

    @classmethod
    async def search_all_async(cls, query: str) -> Dict[str, List[Asset]]:
        """
        Search across all registered plugin instances.

        Args:
            query: Search query string.

        Returns:
            Dict mapping instance_id to list of matching assets from that plugin.
        """
        instances = cls.get_all_instances()
        if not instances:
            return {}

        tasks = [inst.search_assets_async(query) for inst in instances]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output: Dict[str, List[Asset]] = {}
        for inst, result in zip(instances, results):
            if isinstance(result, Exception):
                output[inst._instance_id] = []
            else:
                output[inst._instance_id] = result

        return output

    @abstractmethod
    async def fetch_assets_async(self) -> List[Asset]:
        """Fetch all assets from this library."""
        pass

    @abstractmethod
    async def search_assets_async(self, query: str) -> List[Asset]:
        """Search assets in this library matching the query."""
        pass

    @abstractmethod
    async def get_asset_by_id_async(self, asset_id: str) -> Optional[Asset]:
        """Get a single asset by its ID."""
        pass
