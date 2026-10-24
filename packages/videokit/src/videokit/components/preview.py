"""A component as a web page, for a browser to show without rendering anything."""

from typing import Any, Final

from videokit.components.registry import Component
from videokit.components.render import component_clip
from videokit.layout import DESIGN_SHORT_SIDE
from videokit.models import Brand, Zone

_LENGTH: Final = 4.0
_STILL: Final = (
    "(()=>{const t={from(){return t},to(){return t},fromTo(){return t},"
    "set(){return t},add(){return t},call(){return t},play(){return t},"
    "pause(){return t},seek(){return t},progress(){return t}};"
    "window.gsap={timeline(){return t},from(){return t},to(){return t},"
    "fromTo(){return t},set(){return t}};"
    "const fit=()=>{document.documentElement.style.zoom="
    f"String(window.innerWidth/{DESIGN_SHORT_SIDE})}};"
    "fit();window.addEventListener('resize',fit)})();"
)


def preview_page(
    item: Component, *, props: dict[str, Any], brand: Brand, zone: Zone
) -> str:
    """A whole HTML document drawing ``item``'s settled frame over ``zone``."""
    asset = component_clip(
        item,
        props=props,
        brand=brand,
        zone=zone,
        start=0,
        length=_LENGTH,
        resolution="1080",
        aspect_ratio="9:16",
    )["asset"]
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<style>{asset['css']}</style></head><body>{asset['html']}"
        f"<script>{_STILL}</script><script>{asset['js']}</script></body></html>"
    )
