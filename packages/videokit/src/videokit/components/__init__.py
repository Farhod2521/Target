"""Components: graphics a montage puts over the footage, one folder each.

See :mod:`videokit.components.registry` for what a folder holds and the
rules it keeps, and :mod:`videokit.components.render` for how one becomes
a clip.
"""

from videokit.components.preview import preview_page
from videokit.components.registry import (
    Component,
    ComponentError,
    PropSpec,
    component,
    components,
)
from videokit.components.render import component_clip, fill, font_css

__all__ = [
    "Component",
    "ComponentError",
    "PropSpec",
    "component",
    "component_clip",
    "components",
    "fill",
    "font_css",
    "preview_page",
]
