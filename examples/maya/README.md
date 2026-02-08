# Maya example (UAB dock)

This folder contains a minimal launcher script (`uab_maya.py`) that docks UAB in a Maya `workspaceControl`.

## Option A: Maya module file (recommended)

1. Pick a folder on your `MAYA_MODULE_PATH` (for example, your Maya `modules/` folder).
2. Create a file named `UAB.mod` with contents like:

```text
+ UAB 0.1 /absolute/path/to/uab-refactor
PYTHONPATH +:= src
PYTHONPATH +:= examples/maya
```

Restart Maya.

Then, in the Script Editor (Python tab):

```python
import uab_maya
uab_maya.show()
```

## Option B: Copy launcher into your scripts folder

Copy `examples/maya/uab_maya.py` into your Maya scripts directory (so Maya can `import uab_maya`), and separately ensure the repo `src/` directory is on `PYTHONPATH` so Maya can `import uab`.

