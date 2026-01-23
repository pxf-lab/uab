# Universal Asset Browser
The Universal Asset Browser (UAB) is a Python application that allows you to browse your assets regardless of which 3D application you're using. It is designed to be integrated in any digital content creator (DCC) that has a Python API, to work with any render engine, and to access any external asset library.

| DCC  | Renderer | Status |
| - | - | - |
| Houdini | Karma | Done
| Houdini | Redshift | In progress
| Houdini | Arnold | In progress
| Blender | Cycles | Planned
| Unreal Engine 5 | Unreal Engine Renderer | Planned
| Maya | Arnold | Planned

| Asset Library | Status |
| - | - |
| Local | Done
| PolyHaven | Done
| TurboSquid | Depends on TOS
| Fab/Megascans | Depends on TOS
| CGTrader | Depends on TOS

## Key Architectural Concepts

- `MainPresenter`
    - Application shell. Acts as a router between `TabPresenter`s. 

- `TabPresenter`:
    - Handles business logic between a browser, an asset library, and a host.

- Hosts
    - Injected into `TabPresenter`.
    - Handles **renderer-agnostic** functionality for a DCC (e.g., *creating a geometry node in Houdini*).

- Strategies
    - Injected into the Host.
    - Handles **renderer-specific** functionality (e.g., *creating an HDRI specifically for Karma in Houdini*).


## Extension

The application is designed to be easily extensible, allowing anyone to add support for a DCC, a renderer within a DCC, or an external asset library.

* `interfaces.AssetLibraryPlugin`: Add a new asset source.
* `interfaces.HostIntegration`: Add a new DCC support.
* `interfaces.RenderStrategy`: Add a new renderer to a DCC.

> [!IMPORTANT]
> Your implementation must conform to its interface, but note that plugins and strategies both have a `base.py` file that contains a `SharedUtils` class. For those two, your implementation should inherit this class, *not* the interface directly. The `SharedUtils` class contains quite a lot of logic to run everything in the background, minimizing the amount of work your implementation takes. It should hopefully be as simple as implementing a few key methods.