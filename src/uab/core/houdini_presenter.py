# Ignore failed import on desktop
try:
    import hou
except ImportError:
    pass
from typing import List

import sys
from PySide6.QtCore import Slot
from uab.core.assets import Asset
from uab.core.base_presenter import Presenter
from uab.core.utils import get_modifier_key


class HoudiniPresenter(Presenter):
    def __init__(self, view):
        super().__init__(view)

    def instantiate_asset(self, asset: Asset):
        self.create_light_with_texture(
            "domelight", asset.path, f"instantiated_dome_light")
        self.widget.show_message(
            f"Instantiated: {asset.name}", "info", 3000)

    def replace_texture(self, asset: Asset):
        self._set_dome_light_texture(asset)
        self.widget.show_message(
            f"Texture replaced with: {asset.name}", "info", 3000)

    def create_light_with_texture(self, light_type: str, path: str, light_name: str):
        stage = hou.node("/stage")
        light = stage.createNode(light_type, node_name=light_name)
        tex = light.parm("xn__inputstexturefile_r3ah")
        tex.set(path)
        light.moveToGoodPosition()
        return light

    @Slot(object)
    def set_current_context_menu_options(self, context: object) -> List[dict]:
        modifier_key = get_modifier_key()

        options = [
            {"label": "New Light", "callback": self.on_instantiate_requested,
                "shortcut": f"{modifier_key}+LMB"},
            {"label": "Open Image", "callback": self.on_open_image_requested,
                "shortcut": ""},
            {"label": "Open File Location",
                "callback": self.on_reveal_in_file_system_requested,
                "shortcut": ""},
            {"label": "Remove Asset",
                "callback": self.on_delete_asset,
                "shortcut": ""},
        ]
        update_shortcut = "Opt+LMB" if sys.platform == "darwin" else "Alt+LMB"
        if self._is_dome_light_currently_selected():
            set_texture_option = {
                "label": "Update Light",
                "callback": self._set_dome_light_texture,
                "shortcut": update_shortcut
            }
            options.insert(0, set_texture_option)
        context["object"].create_context_menu_options(
            options, context["position"])
        return options

    def _get_first_selected_node(self):
        nodes = hou.selectedNodes()
        return nodes[0] if nodes else None

    def _get_currently_selected_nodes(self) -> List[hou.Node]:
        nodes = hou.selectedNodes()
        return nodes if nodes else []

    def _is_dome_light_currently_selected(self) -> bool:
        nodes = self._get_currently_selected_nodes()
        for node in nodes:
            if node.type().name() == "domelight::3.0":
                return True
        return False

    def _set_dome_light_texture(self, asset: Asset):
        nodes = self._get_currently_selected_nodes()
        lights = []
        for node in nodes:
            if node.type().name() != "domelight::3.0":
                continue
            tex = node.parm("xn__inputstexturefile_r3ah")
            tex.set(asset.path)
            lights.append(node)
        return lights
