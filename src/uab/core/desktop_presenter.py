from typing import List
from uab.core.assets import Asset
from uab.core.base_presenter import Presenter


class DesktopPresenter(Presenter):
    def __init__(self, view):
        super().__init__(view)

    def instantiate_asset(self, asset: Asset):
        self.widget.show_message(
            f"You must be within an application to instantiate an asset.", "info", 3000)

    def replace_texture(self, asset: Asset):
        self.widget.show_message(
            f"You must be within an application to replace a texture.", "info", 3000)

    def set_current_context_menu_options(self, thumbnail_context_menu_event: dict) -> List[dict]:
        options = [
            {"label": "Open Image", "callback": self.on_open_image_requested,
                "shortcut": ""},
            {"label": "Reveal in File System",
                "callback": self.on_reveal_in_file_system_requested,
                "shortcut": ""},
            {"label": "Remove Asset",
                "callback": self.on_delete_asset,
                "shortcut": ""},
        ]
        thumbnail_context_menu_event["object"].create_context_menu_options(
            options, thumbnail_context_menu_event["position"])
        return options
