# encore-ui

`encore_ui` is the retained cross-platform UI foundation for native Encore
applications. The public model is independent from the window backend, so
layout, styling, and hit testing can run in tests without a display server.

## Current API

- RGBA colors and two-dimensional geometry;
- immutable style builders for colors, borders, spacing, typography, opacity,
  visibility, pointer events, sizing, positioning, overflow, and scrolling;
- constrained flex layout with grow, shrink, alignment, justification,
  row/column and reverse directions, wrapping, reverse line stacking, and
  independent row/column gaps plus stretch/start/center/end/space line
  distribution through `align-content`;
- grid layout with independent `px`, `%`, and `fr` column/row tracks, grouped
  `repeat()`, explicit line placement, spans, and collision-aware auto-placement;
  repeating `grid-auto-columns` and `grid-auto-rows` create implicit tracks;
  sparse/dense row/column `grid-auto-flow`, `minmax()`, and bounded
  `fit-content()` track sizing with recursive widget `min-content` and
  `max-content` measurement;
  absolute positioning, percentages, min/max constraints,
  and `content-box`/`border-box` sizing;
- retained panel, heading, label, link, button, input, textarea, checkbox,
  radio, switch, select, slider, progress, separator, and spacer widgets;
- caret-visible horizontal input scrolling and measured multiline textarea
  editing with newline insertion, wrapped selection, caret, and pointer mapping;
- deterministic layout trees and ID-based hit testing;
- semantic themes for surfaces, text, buttons, tabs, and status colors;
- eased hover and pressed transitions through `ButtonAnimation`;
- CSS declarations, inheritance, scoped custom properties, cascade specificity,
  pseudo-classes, generic and semantic attribute selectors, and child,
  descendant, adjacent, and general sibling selectors, including child and
  type-relative first/last/only/nth structural matching, compound/functional
  `:root`, and form state selectors such as required, optional, read-only,
  read-write, and placeholder-shown;
- retained color picker triggers and palette swatches;
- cached-layout rendering and a bounded LRU text texture cache;
- keyboard, pointer, scroll, and close events, visibility-aware tab traversal,
  Enter/Space control activation, and validated pointer release targets;
- rectangle, border, line, and text rendering;
- immediate 2D window drawing for custom viewports and engine tooling;
- optional TTF/OpenType loading, UTF-8 rendering, and text measurement through
  SDL3_ttf;
- dynamically loaded SDL3 backend with resizable windows and live content-size
  updates.

The SDL3 runtime must be installed on the target machine. It is loaded at run
time, so building an application does not require SDL headers or linker flags.
`Window::create` returns an unavailable window when SDL3 or a video driver is
missing; `backend_error()` provides the reason.

SDL3_ttf is loaded only when `Window::load_font(path, size)` is called. It
supports TrueType, OpenType, font collections, and other formats enabled by its
FreeType build. `Window::text_width` and `text_height` measure the active font.
Calling `clear_font()` restores SDL3's built-in debug font.

`FontManager::with_bundled(asset_root)` registers Open Sans, Inter, and Roboto
from `assets/fonts`, with Open Sans selected as the default family. Additional
application fonts can be registered individually or discovered from a folder:

```enq
let mut fonts = FontManager::with_bundled("assets/fonts")
fonts.load_directory("fonts")
fonts.register_all(window)
fonts = fonts.activate_default(window, 16.0_f32, 400_u32)
fonts = fonts.activate(window, "JetBrainsMono-Regular.ttf", 16.0_f32, 700_u32)
```

The bundled files remain package assets instead of being copied into every
application executable. Installers and package publishers must preserve the
`assets/fonts` directory next to the `encore_ui` package.

## Features

The base package does not expose font loading and measurement. Enable the
`fonts` feature in the dependency reference:

```toml
dependencies = ["index@encore_ui[fonts]"]
```

The equivalent CLI command is `encore add encore_ui --features fonts`.
Features are additive across a workspace and are recorded separately from the
package source in `encore.lock`. Package authors declare them with a
`[features]` table and can guard functions or methods with
`#cfg(feature = "name")`. A feature can include another feature or an optional
dependency reference:

```toml
[features]
default = []
fonts = []
accessibility = ["workspace@ui_accessibility"]
```

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

See `demo` for style gallery, counter, immediate canvas, font rendering,
animations, and interactive form elements in one executable project.

`Window::draw(root)` is the convenient path for a changing tree. Applications
that only change after input can retain the calculated layout and render only
when their state is dirty:

```enq
let theme = Theme::light()
let root = Widget::button("save", "Save").with_style(theme.primary_button())
let layout = window.layout(root)
window.draw_layout(layout)
```

## CSS styles and transitions

Visual styles can be created and overridden with CSS declarations. The current
model includes colors, border, outline, and box-shadow shorthands, radius, padding and margin shorthands,
gap, font family/size/weight, text alignment, opacity, visibility, pointer
events, width/height constraints, percentage sizing, box sizing, flex, grid
column/row templates, overflow clipping, scrolling offsets, absolute positioning, and stable
`z-index` stacking shared by painting and hit testing.
Static, relative, and absolute positioning accept explicit or `auto`
insets; relative offsets preserve the element's original flow allocation and
negative inset values remain distinct from an unset property.
Colors accept short and long hex notation with optional alpha, legacy comma
and modern space/slash RGB syntax, and HSL hue values in degrees, gradians,
radians, or turns.
Text decoration supports underline, overline, and line-through combinations,
an independent color and thickness, and transition interpolation.

`StyleSheet` supports type, class, ID, universal, compound, descendant, child,
adjacent-sibling, and general-sibling selectors. Supported pseudo-classes
include interaction and form states, structural child selectors, `:is`,
`:where`, `:not`, and descendant/direct-child forms of `:has`. Custom
properties are scoped, inherited, and resolved through `var()` fallbacks.

```enq
let normal = css_style("background-color: #12997e; color: #fff; border-radius: 4px; padding: 10px;")
let hovered = apply_css(normal, "border-width: 3px; border-radius: 8px; font-size: 16px;")
let active = apply_css(normal, "background-color: #cf4848; opacity: 0.82;")
let style = animation.style(normal, hovered, active)
```

`ButtonAnimation` supports configurable duration and `linear`, `ease-in`,
`ease-out`, and `ease-in-out` timing. Numeric and color values interpolate;
discrete properties switch between endpoints. Border, radius, and outline
width/color/offset interpolate independently; outlines do not affect layout.
Outer and inset shadows support offsets, bounded blur, spread, color, and
transition interpolation.
`Widget::color_picker`, `Widget::color_channel`, and `Widget::color_swatch`
provide retained controls for complete RGBA pickers and CSS editors. The demo's
CSS Playground sends edited declarations through the public CSS parser and
updates its preview and selected color immediately.

## SVG icons

`SvgDocument` parses SVG directly in Encore and flattens paths, cubic and
quadratic curves, smooth curves, and elliptical arcs into portable vector
geometry. The parser supports the SVG primitives used by Lucide: `path`,
`line`, `polyline`, `polygon`, `circle`, `ellipse`, and rounded `rect`, including
absolute and relative path commands. No librsvg, resvg, browser engine, or
platform SVG runtime is required.

Vector strokes and rounded widget geometry are rendered as anti-aliased SDL3
triangles with transparent edge fringes. Curve flattening uses higher-detail
segments for large previews, avoiding point chains and stair-stepped corners.

`IconManager` discovers bundled or application-provided `.svg` files and loads
documents lazily. Icons inherit the widget foreground color and remain sharp at
different layout sizes.

```enq
let icons = IconManager::with_bundled("assets/icons")
let save = icons.document("save")
let glyph = Widget::icon("save-glyph", save)
let action = Widget::icon_button("save", "Save", save)
```

The demo includes an Icon Browser covering the complete bundled Lucide catalog,
large previews, icon buttons, CSS coloring, and pagination.

## Package Boundaries

`color` and `geometry` are reusable public packages. `ui_native` is private to
this distribution and is resolved through `workspace@ui_native`; consumers do
not depend on it directly.

The base renderer uses SDL's debug text when the `fonts` feature is disabled.
Production typography uses dynamically loaded SDL3_ttf. Accessibility adapters,
IME composition state, and platform-native menus remain separate future layers
rather than additions to `core`.

Windows request a high-pixel-density framebuffer. Layout and pointer events use
logical coordinates, while primitives and SDL3_ttf text are rendered at the
display's physical density. `Window::pixel_density()` exposes the current scale
for application-owned render targets.
