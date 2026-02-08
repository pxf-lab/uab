"""Maya launcher for Universal Asset Browser (UAB).

Usage (in Maya Script Editor, Python tab):

```python
import uab_maya
uab_maya.show()
```

This file is meant to live somewhere on Maya's PYTHONPATH (e.g. inside your
Maya scripts folder) OR you can import it via an absolute path.
"""

from __future__ import annotations

from typing import Optional


WORKSPACE_CONTROL = "UABWorkspaceControl"
WORKSPACE_LABEL = "Universal Asset Browser"


def _get_workspace_qwidget(control_name: str):
    """Return the Qt widget backing a Maya workspaceControl."""
    from maya import OpenMayaUI as omui  # type: ignore
    from shiboken6 import wrapInstance  # type: ignore
    from PySide6 import QtWidgets

    ptr = omui.MQtUtil.findControl(control_name)
    if ptr is None:
        ptr = omui.MQtUtil.findLayout(control_name)
    if ptr is None:
        ptr = omui.MQtUtil.findMenuItem(control_name)
    if ptr is None:
        raise RuntimeError(f"Could not find Qt control for workspaceControl: {control_name}")

    return wrapInstance(int(ptr), QtWidgets.QWidget)


def _clear_layout(layout) -> None:
    """Remove all widgets from a Qt layout."""
    from PySide6 import QtWidgets

    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        else:
            child_layout = item.layout()
            if child_layout is not None:
                _clear_layout(child_layout)
                child_layout.setParent(None)


def build_ui(control_name: str = WORKSPACE_CONTROL):
    """Build the UAB UI inside an existing workspaceControl."""
    from PySide6 import QtWidgets

    host = _get_workspace_qwidget(control_name)

    layout = host.layout()
    if layout is None:
        layout = QtWidgets.QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
    else:
        _clear_layout(layout)

    from uab.main import create_panel_widget
    from uab.integrations.maya import MayaIntegration

    uab_widget = create_panel_widget(host_integration=MayaIntegration())
    layout.addWidget(uab_widget)

    return uab_widget


def show(*, floating: bool = False) -> Optional[object]:
    """Create/show the docked UAB workspaceControl and build its UI."""
    import maya.cmds as cmds  # type: ignore

    if cmds.workspaceControl(WORKSPACE_CONTROL, query=True, exists=True):
        # Re-show existing control
        cmds.workspaceControl(WORKSPACE_CONTROL, edit=True, visible=True)
        try:
            return build_ui(WORKSPACE_CONTROL)
        except Exception:
            # If something went wrong with the existing control, recreate it.
            cmds.deleteUI(WORKSPACE_CONTROL)

    ui_script = (
        "python(\"import uab_maya; uab_maya.build_ui('"
        + WORKSPACE_CONTROL
        + "')\")"
    )

    cmds.workspaceControl(
        WORKSPACE_CONTROL,
        label=WORKSPACE_LABEL,
        uiScript=ui_script,
        retain=False,
        floating=floating,
    )

    return build_ui(WORKSPACE_CONTROL)

