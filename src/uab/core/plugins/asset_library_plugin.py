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
