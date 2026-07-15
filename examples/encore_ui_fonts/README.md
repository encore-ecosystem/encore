# Encore UI Fonts

Loads a font through SDL3_ttf and renders UTF-8 text. Pass a TrueType,
OpenType, font collection, or another file format supported by the installed
SDL3_ttf/FreeType runtime:

```sh
encore run -- /usr/share/fonts/TTF/DejaVuSans.ttf
```

SDL3_ttf is optional for other `encore_ui` applications. Without it, the UI
renderer continues to use SDL3's small built-in debug font.
