# cad_ui

Native GUI bridge used by the CAD example. On Linux it dynamically loads X11;
on unsupported/headless platforms the window API returns `0` and callers can
fall back to textual output.

