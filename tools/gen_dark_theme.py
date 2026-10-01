"""Erzeugt static/dark.css aus dem hellen Design in static/app.css.

Ausgangspunkt ist die helle Ebene ab «CKO Light UI» (sie bestimmt das heutige Aussehen). Jede Regel mit
Farbwerten wird unter :root[data-theme="dark"] mit umgerechneten Farben wiederholt: helle Flächen werden
dunkel (Navy-Ton), dunkle Schrift hell, Akzentfarben bleiben im Farbton und werden für dunklen Grund
aufgehellt. Handkorrekturen und die Farbvariablen stehen in static/dark-overrides.css (wird angehängt).

Aufruf: python tools/gen_dark_theme.py
"""

from __future__ import annotations

import colorsys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "static" / "app.css"
TARGET = ROOT / "static" / "dark.css"
OVERRIDES = ROOT / "static" / "dark-overrides.css"
MARKER = "/* CKO Light UI"
PREFIX = ':root[data-theme="dark"]'
COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|\b(?:white|black|transparent)\b")
COLOR_PROPS = ("color", "background", "border", "outline", "box-shadow", "text-shadow", "fill", "stroke",
               "caret-color", "accent-color")
SHADOW_PROPS = ("box-shadow", "text-shadow")
TEXT_PROPS = ("color", "fill", "caret-color")
NAVY_HUE = 207 / 360


def parse_color(token: str) -> tuple[float, float, float, float] | None:
    token = token.strip().lower()
    if token == "transparent":
        return None
    if token == "white":
        return 1, 1, 1, 1
    if token == "black":
        return 0, 0, 0, 1
    if token.startswith("#"):
        value = token[1:]
        if len(value) in (3, 4):
            value = "".join(ch * 2 for ch in value)
        r, g, b = (int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
        return r, g, b, int(value[6:8], 16) / 255 if len(value) == 8 else 1
    numbers = [part.strip() for part in token[token.index("(") + 1:-1].replace("/", ",").split(",")]
    r, g, b = (float(x) / 255 for x in numbers[:3])
    return r, g, b, float(numbers[3]) if len(numbers) > 3 else 1


def fmt(r: float, g: float, b: float, a: float) -> str:
    rgb = tuple(max(0, min(255, round(x * 255))) for x in (r, g, b))
    if a >= 0.999:
        return "#{:02x}{:02x}{:02x}".format(*rgb)
    return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {round(a, 3)})"


def is_accent(token: str) -> bool:
    parsed = parse_color(token)
    if parsed is None:
        return False
    _hue, light, s = colorsys.rgb_to_hls(*parsed[:3])
    return s > 0.35 and 0.3 <= light <= 0.75 and parsed[3] > 0.5


def convert(token: str, prop: str, on_accent: bool = False) -> str:
    parsed = parse_color(token)
    if parsed is None:
        return token
    r, g, b, a = parsed
    h, light, s = colorsys.rgb_to_hls(r, g, b)
    if prop in SHADOW_PROPS:
        # Schatten auf dunklem Grund: schwarz und etwas kräftiger
        return fmt(0, 0, 0, min(0.6, a * 3 + 0.12))
    if on_accent and prop in TEXT_PROPS and light > 0.75:
        return fmt(1, 1, 1, a)  # Schrift auf Vollfarb-Buttons bleibt weiss
    if s > 0.35 and 0.3 <= light <= 0.75:
        # Akzent: Farbton halten. Schrift hell, Flächen leicht aufgehellt, Rahmen gedämpft
        if prop in TEXT_PROPS:
            new_light = max(0.62, min(0.74, light + 0.22))
        elif prop.startswith(("border", "outline")):
            new_light = 0.42
        else:
            new_light = max(0.4, min(0.55, light + 0.04))
        return fmt(*colorsys.hls_to_rgb(h, new_light, min(1, s)), a)
    if light > 0.82:
        if prop in TEXT_PROPS:
            return fmt(*colorsys.hls_to_rgb(h, 0.95, min(s, 0.3)), a)
        # helle (oft leicht getönte) Fläche → dunkle Navy-Fläche; Tönung farbiger Flächen bleibt erhalten
        tint = s > 0.2
        hue = h if tint else NAVY_HUE
        new_light = 0.075 + (1 - light) * (0.9 if tint else 0.75)
        new_s = min(0.6, s * 0.8) if tint else 0.42
        if a < 0.999:
            return fmt(*colorsys.hls_to_rgb(hue, 0.75, 0.3), round(a * 0.5, 3))
        return fmt(*colorsys.hls_to_rgb(hue, new_light, new_s), a)
    if light < 0.35:
        if prop in TEXT_PROPS:
            # dunkle Schrift → helle Schrift
            return fmt(*colorsys.hls_to_rgb(h, 0.93 - light * 0.25, min(s, 0.35)), a)
        if a < 0.999:
            # dunkle, halbtransparente Tönung → helle Tönung
            return fmt(*colorsys.hls_to_rgb(h, 0.8, min(s, 0.4)), round(a * 0.9, 3))
        return fmt(*colorsys.hls_to_rgb(h, 0.88 - light * 0.3, min(s, 0.35)), a)
    # mittlere, graue Töne: spiegeln (Rahmen werden dunkler, Hilfstexte heller)
    if prop in TEXT_PROPS:
        return fmt(*colorsys.hls_to_rgb(h, max(0.62, 1 - light), min(s, 0.3)), a)
    return fmt(*colorsys.hls_to_rgb(h if s > 0.15 else NAVY_HUE, max(0.16, min(0.32, 1 - light)), min(max(s, 0.25), 0.4)), a)


def blocks(css: str):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    i, n = 0, len(css)
    while i < n:
        start = css.find("{", i)
        if start < 0:
            return
        prelude = css[i:start].strip()
        depth, j = 1, start + 1
        while j < n and depth:
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        yield prelude, css[start + 1:j - 1]
        i = j


def prefix_selectors(prelude: str) -> str:
    return ", ".join(PREFIX if sel.strip() in (":root", "html") else f"{PREFIX} {sel.strip()}" for sel in prelude.split(","))


def convert_rule(prelude: str, body: str) -> str | None:
    pairs = [d.split(":", 1) for d in body.split(";") if ":" in d]
    on_accent = any(p.strip().lower().startswith("background") and any(is_accent(m.group(0)) for m in COLOR.finditer(v))
                    for p, v in pairs)
    declarations = []
    for prop, value in pairs:
        prop = prop.strip().lower()
        if prop.startswith("--") or not prop.startswith(COLOR_PROPS) or not COLOR.search(value):
            continue  # Variablen setzt dark-overrides.css von Hand
        converted = COLOR.sub(lambda match, prop=prop: convert(match.group(0), prop, on_accent), value.strip())
        declarations.append(f"{prop}:{converted}")
    if not declarations:
        return None
    return f"{prefix_selectors(prelude)}{{{';'.join(declarations)}}}"


def convert_css(css: str) -> list[str]:
    out = []
    for prelude, body in blocks(css):
        if prelude.startswith("@media"):
            inner = [rule for rule in (convert_rule(p, b) for p, b in blocks(body)) if rule]
            if not inner:
                continue
            if "prefers-color-scheme" in prelude:
                out.extend(inner)  # im dunklen Design immer gültig, unabhängig von der Windows-Einstellung
            else:
                out.append(f"{prelude}{{{''.join(inner)}}}")
        elif not prelude.startswith("@"):
            rule = convert_rule(prelude, body)
            if rule:
                out.append(rule)
    return out


def main() -> None:
    css = SOURCE.read_text(encoding="utf-8")
    light_layer = css[css.index(MARKER):]
    lines = ["/* Automatisch erzeugt mit tools/gen_dark_theme.py – nicht von Hand bearbeiten. */"]
    lines.extend(convert_css(light_layer))
    if OVERRIDES.exists():
        lines.append("/* dark-overrides.css */")
        lines.append(OVERRIDES.read_text(encoding="utf-8").strip())
    TARGET.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"dark.css: {len(lines)} Zeilen")


if __name__ == "__main__":
    main()
