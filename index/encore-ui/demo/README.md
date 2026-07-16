# Encore UI Demo

This single project contains every `encore_ui` demonstration. Run it from this
directory and switch screens with the toolbar:

```sh
encore run
```

Place TTF, OTF, TTC, WOFF, or WOFF2 files in `fonts/`. The Fonts screen lists
them in its font selector. Available toolbar screens:

- `gallery` is the default interactive style catalog with primary, secondary,
  outline, danger, ghost, compact, regular, and large buttons. It also contains
  badges, metric cards, a toolbar, and a status bar.
- `counter` demonstrates application state, widget IDs, and pointer hit
  testing.
- `canvas` demonstrates immediate drawing for CAD and Graphene viewports.
- `fonts` loads TTF, OTF, TTC, or another SDL3_ttf-supported format and renders
  measured UTF-8 text.

SDL3 is required at runtime. The Fonts screen additionally requires SDL3_ttf.
Press Escape to close the demo.
