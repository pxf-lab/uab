from uab.core.base_presenter import Presenter


class DesktopPresenter(Presenter):
    def __init__(self, view):
        super().__init__(view)

    def instantiate_asset(self, asset: dict):
        self.widget.show_message(
            f"You must be within an application to instantiate an asset.", "info", 3000)
