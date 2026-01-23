"""Presenter layer for Universal Asset Browser.

This package contains the MVP presenters that coordinate between
the view (UI) layer and the plugin/integration layers.

Imports are lazy to avoid forcing PySide6 dependency at import time.
Use explicit imports from submodules:
    from uab.presenters.main_presenter import MainPresenter
    from uab.presenters.tab_presenter import TabPresenter
"""

__all__ = ["MainPresenter", "TabPresenter"]


def __getattr__(name: str):
    """Lazy import of presenter classes."""
    if name == "MainPresenter":
        from uab.presenters.main_presenter import MainPresenter
        return MainPresenter
    if name == "TabPresenter":
        from uab.presenters.tab_presenter import TabPresenter
        return TabPresenter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
