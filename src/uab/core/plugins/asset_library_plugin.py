from __future__ import annotations
from abc import abstractmethod
from typing import List, Set, Type, Optional, final
from weakref import WeakValueDictionary
import uuid

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
