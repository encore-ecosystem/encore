# encore-ui

`encore_ui` is the retained cross-platform UI foundation for native Encore
applications. The public model is independent from the window backend, so
layout, styling, and hit testing can run in tests without a display server.

## Current API

- RGBA colors and two-dimensional geometry;
- immutable style builders with background, foreground, border, padding, gap,
  radius, and font-size properties;
- horizontal and vertical flex layout with fixed and growing items;
- retained panel, label, button, and spacer widgets;
- deterministic layout trees and ID-based hit testing;
- keyboard, pointer, scroll, and close events;
- rectangle, border, line, and text rendering;
- immediate 2D window drawing for custom viewports and engine tooling;
- dynamically loaded SDL3 backend on Linux, macOS, and Windows.

The SDL3 runtime must be installed on the target machine. It is loaded at run
time, so building an application does not require SDL headers or linker flags.
`Window::create` returns an unavailable window when SDL3 or a video driver is
missing; `backend_error()` provides the reason.

## Example

```enq
import encore_ui::{Color, Insets, Style, Widget, Window, vertical}

fn view() -> Widget {
    let mut root = Widget::panel("root").with_direction(vertical()).with_style(
        Style::panel()
            .with_background(Color::rgb(242_u8, 245_u8, 248_u8))
            .with_padding(Insets::all(16.0_f32))
            .with_gap(8.0_f32)
    )
    root.push(Widget::label("Hello from Encore"))
    root.push(Widget::button("continue", "Continue"))
    ret root
}
```

See `examples/encore_ui_hello`, `encore_ui_counter`, `encore_ui_canvas`, and
`encore_ui_demo` for complete retained and immediate rendering loops.

## Package Boundaries

`color` and `geometry` are reusable public packages. `ui_native` is private to
this distribution and is resolved through `workspace@ui_native`; consumers do
not depend on it directly.

The initial renderer intentionally uses SDL's debug text to keep the bootstrap
dependency small. Production typography, accessibility adapters, IME state,
GPU scene caching, and platform-native menus belong to subsequent layers built
on this API rather than to `core`.
