# Ignore failed import on desktop
try:
    import hou
except ImportError:
    pass
from typing import List

from PySide6.QtCore import Slot
from uab.core.base_presenter import Presenter


class HoudiniPresenter(Presenter):
    def __init__(self, view):
        super().__init__(view)

    def instantiate_asset(self, asset: dict):
        self.create_light_with_texture(
            "domelight", asset["directory_path"], f"dome_light_{asset['name']}")

    def create_light_with_texture(self, light_type: str, directory_path: str, light_name: str):
        stage = hou.node("/stage")
        light = stage.createNode(light_type, node_name=light_name)
        tex = light.parm("xn__inputstexturefile_r3ah")
        tex.set(directory_path)
        light.moveToGoodPosition()
        return light

    @Slot(object)
    def set_current_context_menu_options(self, context: object) -> List[dict]:
        if self._is_dome_light_currently_selected():
            options = [
                {"label": "Open Image", "callback": self.on_open_image_requested},
                {"label": "Reveal in File System",
                    "callback": self.on_reveal_in_file_system_requested},
                {"label": "Instantiate", "callback": self.on_instantiate_requested},
                {"label": "Set Texture", "callback": self._set_dome_light_texture},
            ]
        else:
            options = [
                {"label": "Open Image", "callback": self.on_open_image_requested},
                {"label": "Reveal in File System",
                    "callback": self.on_reveal_in_file_system_requested},
                {"label": "Instantiate", "callback": self.on_instantiate_requested},
            ]
        context["object"].create_context_menu_options(
            options, context["position"])
        return options

    def _get_currently_selected_node(self) -> hou.Node:
        return hou.selectedNodes()[0] if hou.selectedNodes() else None

    def _is_dome_light_currently_selected(self) -> bool:
        if not self._get_currently_selected_node():
            return False
        print(
            f"Currently selected node: {self._get_currently_selected_node().name()} of type {self._get_currently_selected_node().type().name()}")
        return self._get_currently_selected_node().type().name() == "domelight::3.0"

    def _set_dome_light_texture(self, asset: dict):
        print(f"Setting texture for dome light: {asset['name']}")
        light = self._get_currently_selected_node()
        if not light:
            return
        tex = light.parm("xn__inputstexturefile_r3ah")
        tex.set(asset["directory_path"])
        return light
