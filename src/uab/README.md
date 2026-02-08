## UAB Python package (`src/uab`)

This folder contains the importable Python package (`uab`) plus the standalone entrypoint (`main.py`).

### Run (standalone)

```bash
cd src/uab
uv run python main.py
```

### Run tests

```bash
cd src/uab
uv run --group dev pytest -q ../../tests
```

## Key architectural concepts (quick map)

- **`MainPresenter`**: application shell + plugin discovery + tab routing
- **`TabPresenter`**: per-tab coordinator (plugin ↔ view ↔ host)
- **Assets**:
  - `Asset`: single file (resolution/format/LOD variant)
  - `CompositeAsset`: recursive grouping of Assets and/or other composites
  - `Browsable`: UI-facing protocol implemented by both
- **Host integrations** (`HostIntegration`): DCC-specific import behavior
- **Render strategies** (`RenderStrategy`): renderer-specific material/light creation
