"""The motion every component shares: how things come in, land, and go."""

import json
import re
from typing import Final

TOKENS: Final[dict[str, float | str]] = {
    "enter": 0.4,
    "pop": "back.out(2)",
    "slide": "power3.out",
    "slamFrom": 2.4,
    "slam": 0.28,
    "shake": 10,
    "stagger": 0.08,
    "type": 0.4,
    "leave": 0.3,
    "leaveEase": "power2.in",
}

HELPERS: Final[dict[str, str]] = {
    "enter": (
        "const enter=(tl,t,at,v)=>tl.from(t,Object.assign({opacity:0,y:40,"
        "duration:M.enter,ease:M.slide},v||{}),at);"
    ),
    "pop": (
        "const pop=(tl,t,at,v)=>tl.from(t,Object.assign({opacity:0,scale:0,"
        "duration:M.enter*.9,ease:M.pop},v||{}),at);"
    ),
    "slam": (
        "const slam=(tl,t,at,hold)=>{tl.fromTo(t,{scale:M.slamFrom,opacity:0},"
        "{scale:1,opacity:1,duration:M.slam,ease:'power4.in'},at);"
        "tl.fromTo(hold||t,{y:0},{y:M.shake,duration:.05,yoyo:true,repeat:3,"
        "ease:'none'},at+M.slam);};"
    ),
    "burst": (
        "const burst=(tl,t,at,grow,v)=>{tl.set(t,{opacity:1,scale:.3},at);"
        "tl.to(t,Object.assign({opacity:0,scale:grow||2.4,duration:.45,"
        "ease:'power2.out'},v||{}),at);};"
    ),
    "leave": (
        "const leave=(tl,t,v)=>tl.to(t,Object.assign({opacity:0,y:-60,"
        "duration:M.leave,ease:M.leaveEase,stagger:.04},v||{}),"
        "Math.max(0,P.length-M.leave-.05));"
    ),
    "typeIn": (
        "const typeIn=(tl,el,at,d)=>{const s=el.textContent;el.textContent='';"
        "[...s].forEach(ch=>{const c=document.createElement('span');"
        "c.textContent=ch;c.style.opacity=0;el.appendChild(c);});"
        "tl.to(el.children,{opacity:1,duration:.01,"
        "stagger:(d||M.type)/Math.max(1,s.length)},at);};"
    ),
    "twinkle": (
        "const twinkle=(tl,t,at)=>{tl.fromTo(t,{scale:0,rotation:-90,opacity:0},"
        "{scale:1,rotation:0,opacity:1,duration:.35,ease:'back.out(3)',"
        "stagger:.06},at);tl.to(t,{scale:.55,opacity:.55,duration:.35,yoyo:true,"
        "repeat:5,ease:'sine.inOut',stagger:.09},at+.4);};"
    ),
}

_CALL: Final = re.compile(r"\b(" + "|".join(HELPERS) + r")\(")


def prelude(js: str) -> str:
    """``M`` and the helpers ``js`` calls, to go before it; nothing when it
    calls none and never reads ``M``."""
    used = sorted({found.group(1) for found in _CALL.finditer(js)})
    if not used and "M." not in js:
        return ""
    tokens = json.dumps(TOKENS, separators=(",", ":"))
    return f"const M={tokens};" + "".join(HELPERS[name] for name in used)
