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
        self.create_dome_light(asset["directory_path"])

    def create_dome_light(self, directory_path: str, light_name: str = "dome_light"):
        stage = hou.node("/stage")
        dome = stage.createNode("domelight", node_name=light_name)
        tex = dome.parm("xn__inputstexturefile_r3ah")
        tex.set(directory_path)
        dome.moveToGoodPosition()
        return dome

    @Slot(object)
    def set_current_context_menu_options(self, context: object) -> List[dict]:
        options = [
            {"label": "Open Image", "callback": self.on_open_image_requested},
            {"label": "Reveal in File System",
                "callback": self.on_reveal_in_file_system_requested},
            {"label": "Instantiate", "callback": self.on_instantiate_requested},
        ]
        context["object"].create_context_menu_options(
            options, context["position"])
        return options
