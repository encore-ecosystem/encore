# Encore UI Demo

This single project contains every `encore_ui` demonstration. Run it from this
directory and select a screen after `--`:

```sh
encore run
encore run -- gallery
encore run -- counter
encore run -- canvas
encore run -- fonts /usr/share/fonts/TTF/DejaVuSans.ttf
```

Available screens:

- `gallery` is the default interactive style catalog with primary, secondary,
  outline, danger, ghost, compact, regular, and large buttons. It also contains
  badges, metric cards, a toolbar, and a status bar.
- `counter` demonstrates application state, widget IDs, and pointer hit
  testing.
- `canvas` demonstrates immediate drawing for CAD and Graphene viewports.
- `fonts` loads TTF, OTF, TTC, or another SDL3_ttf-supported format and renders
  measured UTF-8 text.

SDL3 is required at runtime. The `fonts` screen additionally requires SDL3_ttf.
Press Escape to close any screen.
