# Ignore failed import on desktop
try:
    import hou
except ImportError:
    pass
from typing import List

from PySide6.QtCore import Slot
from uab.core.base_presenter import Presenter
from uab.core.utils import get_modifier_key


class HoudiniPresenter(Presenter):
    def __init__(self, view):
        super().__init__(view)

    def instantiate_asset(self, asset: dict):
        self.create_light_with_texture(
            "domelight", asset["path"], f"instantiated_dome_light")
        self.widget.show_message(
            f"Instantiated: {asset['name']}", "info", 3000)

    def replace_texture(self, asset: dict):
        self._set_dome_light_texture(asset)
        self.widget.show_message(
            f"Texture replaced with: {asset['name']}", "info", 3000)

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
            {"label": "Instantiate", "callback": self.on_instantiate_requested,
                "shortcut": f"{modifier_key}+LMB"},
            {"label": "Open Image", "callback": self.on_open_image_requested,
                "shortcut": ""},
            {"label": "Reveal in File System",
                "callback": self.on_reveal_in_file_system_requested,
                "shortcut": ""},
            {"label": "Remove Asset",
                "callback": self.on_delete_asset,
                "shortcut": ""},
        ]
        if self._is_dome_light_currently_selected():
            set_texture_option = {
                "label": "Set Texture",
                "callback": self._set_dome_light_texture,
                "shortcut": "Alt+LMB"
            }
            options.insert(0, set_texture_option)
        context["object"].create_context_menu_options(
            options, context["position"])
        return options

    def _get_currently_selected_node(self):
        nodes = hou.selectedNodes()
        return nodes[0] if nodes else None

    def _is_dome_light_currently_selected(self) -> bool:
        current_node = self._get_currently_selected_node()
        if not current_node:
            return False
        return current_node.type().name() == "domelight::3.0"

    def _set_dome_light_texture(self, asset: dict):
        light = self._get_currently_selected_node()
        if not light:
            return
        tex = light.parm("xn__inputstexturefile_r3ah")
        tex.set(asset["path"])
        return light
