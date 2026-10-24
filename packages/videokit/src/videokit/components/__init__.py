"""Components: graphics a montage puts over the footage, one folder each."""

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
