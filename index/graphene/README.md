# Graphene

Graphene is the native GUI/game-engine experiment for Encore.

The package is intentionally split into layers:

- `gui_core`: platform-independent value types.
- `gui_native`: native window backend and platform library declarations.
- `graphene`: public engine-facing API built on those layers.
- `gui_window`: executable smoke test using Graphene as a dependency.

On Linux the current native backend uses X11/XWayland through the EHIR runtime ABI and declares `X11` in `encore.toml` through the native-library manifest.
