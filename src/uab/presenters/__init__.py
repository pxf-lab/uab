"""Presenter layer for Universal Asset Browser.

This package contains the MVP presenters that coordinate between
the view (UI) layer and the plugin/integration layers.
"""

from uab.presenters.main_presenter import MainPresenter
from uab.presenters.tab_presenter import TabPresenter

__all__ = ["MainPresenter", "TabPresenter"]
