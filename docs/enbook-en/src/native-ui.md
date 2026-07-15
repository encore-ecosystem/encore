# Native UI

`encore_ui` is Encore's retained toolkit for cross-platform native
applications. Application code builds a widget tree, the toolkit computes a
deterministic layout tree, and the same tree is used for rendering and hit
testing.

```toml
dependencies = [
    "index@encore_ui",
]
```

```enq
import encore_ui::{Insets, Style, Widget, Window, vertical}

fn view() -> Widget {
    let mut root = Widget::panel("root")
        .with_direction(vertical())
        .with_style(Style::panel().with_padding(Insets::all(16.0_f32)))
    root.push(Widget::label("Project"))
    root.push(Widget::button("open", "Open"))
    ret root
}

fn main() -> u32 {
    let window = Window::create("Application", 960_u32, 640_u32)
    if !window.available() { ret 1_u32 }
    while window.is_open() {
        let event = window.poll()
        let layout = window.draw(view())
        // Use layout.hit(event.x(), event.y()) for pointer actions.
    }
    window.destroy()
    ret 0_u32
}
```

## Package Structure

`color` and `geometry` are independent reusable packages. The SDL3 FFI backend
is an implementation detail embedded as `workspace@ui_native` in the
`encore_ui` distribution.

SDL3 is loaded dynamically. Applications therefore compile without SDL
headers, but the target machine must provide the SDL3 shared library. Linux,
macOS, and Windows library names are recognized. A missing runtime or video
driver makes `Window::create` unavailable and exposes a message through
`backend_error()`.

## Styling And Layout

`Style` values are immutable builders. They define colors, borders, padding,
gaps, corner radius, and font size. `Widget::with_style` applies a style to one
widget without mutating a shared global theme.

Containers use horizontal or vertical flex layout. Children can have a fixed
basis, consume remaining space with a grow factor, or be constrained with
`FlexItem`. Layout and hit testing do not require a native window, which keeps
component tests deterministic in CI.

Custom viewports can bypass widgets for a frame with `Window::begin`,
`fill_rect`, `stroke_rect`, `line`, `text`, and `present`. This is the intended
integration point for Graphene editors and CAD canvases; application chrome can
remain retained while the central scene uses a specialized renderer.

The first renderer provides panels, labels, buttons, spacers, lines, keyboard
and pointer events, scrolling, and debug text. Full typography, IME editing,
accessibility trees, GPU scene caching, and native menus are higher-level work;
they do not belong in the language `core` runtime.
