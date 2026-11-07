"""Zeichnet den Koi im Teich als animiertes SVG.

Die Animation nutzt nur SMIL (<animate>, <animateMotion>, <animateTransform>), weil GitHub
SVGs als <img> einbindet: Skripte und externe Dateien laufen dort nicht, SMIL schon.
Die Form des Fisches und seine Schwimmwelle berechnet `fish.py`; hier entsteht die Szene.

Ebenen von unten nach oben: Teichgrund mit Kieseln und Lichtspiel, Schatten des Koi, Koi,
Wasseroberfläche (Ringe, Seerosen, Blütenblatt, Glitzern), Abdunklung der Ränder, Legende.
"""

import hashlib
import math
import random
from xml.sax.saxutils import escape

from . import fish
from .model import KoiData

# Breitformat: füllt die Inhaltsbreite eines GitHub-READMEs (rund 840 px) ohne Skalierung.
WIDTH, HEIGHT = 840, 270

LABEL = "#d8ebe4"
RIPPLE = "#bfe3dc"
SHADOW = "#001a1d"

# Grundfarbe des Koi: (Körper, Schattierung). Die Schattierung färbt Rückenkamm,
# Schuppen, Barteln und Flossenstrahlen.
BODIES = {
    "white": ("#f8f4ec", "#c9bba5"),
    "gold": ("#f2c14e", "#b8862a"),
    "black": ("#2a2d33", "#5a5f6a"),
    "platinum": ("#e6e9ee", "#a9b0bb"),
}

# Rundkurs durch den Teich als glatte geschlossene Kurve durch diese Wegpunkte, ein langes
# Oval mit leichten Wellen an den Längsseiten.
# Glatt heißt: Die Richtung springt nirgends, sonst zuckt der Koi bei rotate="auto".
SWIM_WAYPOINTS: tuple[fish.Point, ...] = (
    (420, 72),
    (560, 66),
    (676, 92),
    (712, 130),
    (668, 168),
    (540, 180),
    (420, 170),
    (300, 180),
    (172, 168),
    (128, 130),
    (164, 92),
    (280, 66),
)
SWIM_PATH = fish.smooth_closed(SWIM_WAYPOINTS)

# `KoiData.swim_seconds` gilt für eine Runde dieser Länge (die Bahn im früheren, schmaleren
# Teich). Längere Bahn = längere Runde, damit das Tempo des Koi gleich bleibt.
REFERENCE_LAP = 570.0
SWIM_LAP_FACTOR = (
    sum(math.dist(SWIM_WAYPOINTS[i - 1], p) for i, p in enumerate(SWIM_WAYPOINTS)) / REFERENCE_LAP
)

TREND_ARROWS = {1: "↗ wächst", 0: "→ hält sich", -1: "↘ schrumpft"}
FONT = "'Segoe UI', system-ui, -apple-system, Helvetica, Arial, sans-serif"


def _rng_for(*keys: str) -> random.Random:
    """Fester Zufall je Schlüssel: gleiche Eingabe, gleiches Bild – jeden Tag."""
    return random.Random(hashlib.sha256("/".join(keys).lower().encode()).digest())


# --- Koi ---------------------------------------------------------------------------------


def _fish_defs(body: str, beat: float) -> str:
    """Formen und Füllungen des Koi, die mehrfach verwendet werden (Körper, Schwanz).

    Körper und Schwanz stehen einmal hier, ohne eigene Füllung; Koi, Schuppen, Schattierung,
    Schatten und Zuschnitt der Flecken greifen per <use> darauf zu. Das hält die Datei klein
    und garantiert, dass alle Ebenen exakt dieselbe Bewegung machen.
    """
    body_color, shade = BODIES[body]
    return (
        fish.morphing_path(fish.closed_keyframes(fish.body_outline()), beat, 'id="koi-body"')
        + fish.morphing_path(fish.closed_keyframes(fish.tail_outline()), beat, 'id="koi-tail"')
        # Zuschnitt mit eigenem animiertem Pfad statt <use>: Ob jeder Browser (Safari)
        # einen animierten Verweis im clipPath mitbewegt, ist nicht gesichert.
        + '<clipPath id="koi-clip">'
        + fish.morphing_path(fish.closed_keyframes(fish.body_outline()), beat, "")
        + "</clipPath>"
        # Flossen: am Ansatz kräftig, zu den Spitzen hin durchscheinend
        '<linearGradient id="koi-fin" x1="1" y1="0" x2="0" y2="0">'
        f'<stop offset="0" stop-color="{body_color}" stop-opacity="0.95"/>'
        f'<stop offset="1" stop-color="{body_color}" stop-opacity="0.35"/></linearGradient>'
        # Rundung des Körpers: dunkle Flanken, Glanz auf dem Rücken
        '<linearGradient id="koi-shade" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#000" stop-opacity="0.24"/>'
        '<stop offset="0.3" stop-color="#fff" stop-opacity="0.2"/>'
        '<stop offset="0.5" stop-color="#fff" stop-opacity="0"/>'
        '<stop offset="0.8" stop-color="#000" stop-opacity="0.06"/>'
        '<stop offset="1" stop-color="#000" stop-opacity="0.3"/></linearGradient>'
        # Schuppen: versetzte Bögen, nur angedeutet
        '<pattern id="koi-scales" width="6" height="4.6" patternUnits="userSpaceOnUse">'
        f'<path d="M0 4.6A3 3 0 0 1 6 4.6M-3 2.3A3 3 0 0 1 3 2.3M3 2.3A3 3 0 0 1 9 2.3" '
        f'fill="none" stroke="{shade}" stroke-width="0.5"/></pattern>'
    )


def _spots(data: KoiData, beat: float) -> str:
    """Organische Flecken in Sprachfarben, die sich mit dem Körper biegen.

    Jede Sprache hat ihren eigenen Zufall aus Login und Sprachname. So bleiben ihre
    Flecken an derselben Stelle, auch wenn eine andere Sprache dazukommt oder wegfällt.
    """
    parts: list[str] = []
    for lang in data.languages:
        rng = _rng_for(data.login, lang.name)
        size = 6 + 8 * lang.share**0.5
        for _ in range(max(1, round(lang.share * 6))):
            frames = fish.closed_keyframes(fish.spot_blob(rng, size))
            parts.append(fish.morphing_path(frames, beat, f'fill="{lang.color}"'))
    return "".join(parts)


def _pectoral_fins(beat: float) -> str:
    """Brustflossen: fest am Körper, rudern gemächlich im halben Takt des Schwanzes."""
    parts: list[str] = []
    for side in (-1, 1):
        x, y = fish.pectoral_root(side)
        points = fish.pectoral_fin(side)
        a, b = -12 * side, 14 * side
        parts.append(
            f'<g transform="translate({x:.1f} {y:.1f})">'
            f'<path d="{fish.smooth_closed(points)}" fill="url(#koi-fin)">'
            f'<animateTransform attributeName="transform" type="rotate" '
            f'values="{a};{b};{a}" dur="{beat * 2:.2f}s" repeatCount="indefinite"/>'
            f"</path></g>"
        )
    return "".join(parts)


def _head(body: str) -> str:
    """Augen mit Glanzpunkt und zwei Bartelpaare an der Schnauze."""
    _, shade = BODIES[body]
    eye = "#14161a" if body != "black" else "#e8e2d4"
    x = fish.HEAD_X - 8
    parts: list[str] = []
    for side in (-1, 1):
        y = side * (fish.half_width(fish.u_at(x)) - 1.8)
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.3" fill="{eye}"/>'
            f'<circle cx="{x + 0.7:.1f}" cy="{y - 0.6:.1f}" r="0.7" fill="#fff" opacity="0.8"/>'
            f'<path d="M{fish.HEAD_X:.1f} {side * 4:.1f}q4 {side * 1:.1f} 6 {side * 6:.1f}'
            f'M{fish.HEAD_X - 3:.1f} {side * 6.5:.1f}q2 {side * 2:.1f} 2 {side * 6:.1f}" '
            f'fill="none" stroke="{shade}" stroke-width="0.9" stroke-linecap="round"/>'
        )
    return "".join(parts)


def _fish(data: KoiData, body: str) -> str:
    """Der Koi in Originalgröße, skaliert nach Wachstum; Flossen unter dem Körper."""
    body_color, shade = BODIES[body]
    beat = data.tail_beat_seconds
    rays = fish.morphing_path(
        fish.ray_keyframes(fish.tail_rays()),
        beat,
        f'fill="none" stroke="{shade}" stroke-width="0.6" opacity="0.55"',
    )
    pelvic = "".join(
        fish.morphing_path(
            fish.closed_keyframes(fish.pelvic_fin(side)), beat, 'fill="url(#koi-fin)"'
        )
        for side in (-1, 1)
    )
    ridge = fish.morphing_path(
        fish.closed_keyframes(fish.dorsal_ridge()), beat, f'fill="{shade}" opacity="0.5"'
    )
    return (
        f'<g transform="scale({data.scale:.3f})">'
        f"{_pectoral_fins(beat)}{pelvic}"
        f'<use href="#koi-body" fill="{body_color}"/>'
        # Schwanz über dem Körper, damit er das abgerundete Ende des Stiels verdeckt
        f'<use href="#koi-tail" fill="url(#koi-fin)"/>{rays}'
        f'<g clip-path="url(#koi-clip)" opacity="{data.spot_opacity:.2f}">'
        f"{_spots(data, beat)}</g>"
        '<use href="#koi-body" fill="url(#koi-scales)" opacity="0.35"/>'
        '<use href="#koi-body" fill="url(#koi-shade)"/>'
        f"{ridge}{_head(body)}"
        "</g>"
    )


def _koi_layers(data: KoiData, body: str) -> tuple[str, str]:
    """Liefert (defs, Szene) für Schatten und Koi, beide auf derselben Schwimmbahn."""
    defs = _fish_defs(body, data.tail_beat_seconds)
    motion = (
        f'<animateMotion dur="{data.swim_seconds * SWIM_LAP_FACTOR:.1f}s" repeatCount="indefinite" '
        f'rotate="auto" path="{SWIM_PATH}"/>'
    )
    scene = (
        # Schatten am Teichgrund, leicht versetzt und unscharf
        f'<g transform="translate(8 11)" opacity="0.4" filter="url(#blur-4)"><g>{motion}'
        f'<g transform="scale({data.scale:.3f})" fill="{SHADOW}">'
        '<use href="#koi-body"/><use href="#koi-tail"/></g></g></g>'
        f"<g>{motion}{_fish(data, body)}</g>"
    )
    return defs, scene


# --- Teich -------------------------------------------------------------------------------


POND_DEFS = (
    '<radialGradient id="pond" cx="45%" cy="38%" r="80%">'
    '<stop offset="0" stop-color="#2b7a72"/><stop offset="0.55" stop-color="#14505a"/>'
    '<stop offset="1" stop-color="#0a2f37"/></radialGradient>'
    '<radialGradient id="vignette" cx="50%" cy="45%" r="75%">'
    '<stop offset="0.55" stop-color="#021417" stop-opacity="0"/>'
    '<stop offset="1" stop-color="#021417" stop-opacity="0.5"/></radialGradient>'
    '<radialGradient id="glow"><stop offset="0" stop-color="#e8fff8" stop-opacity="0.11"/>'
    '<stop offset="1" stop-color="#e8fff8" stop-opacity="0"/></radialGradient>'
    '<radialGradient id="pebble" cx="35%" cy="30%">'
    '<stop offset="0" stop-color="#4a7d78"/><stop offset="1" stop-color="#0b2b30"/>'
    "</radialGradient>"
    '<radialGradient id="pad" cx="40%" cy="40%">'
    '<stop offset="0" stop-color="#6fae5f"/><stop offset="1" stop-color="#3c7536"/>'
    "</radialGradient>"
    '<linearGradient id="petal" x1="0" y1="1" x2="0" y2="0">'
    '<stop offset="0" stop-color="#ef9dbb"/><stop offset="1" stop-color="#fff5f8"/>'
    "</linearGradient>"
    '<linearGradient id="band" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0" stop-color="#021a1d" stop-opacity="0"/>'
    '<stop offset="1" stop-color="#021a1d" stop-opacity="0.6"/></linearGradient>'
    '<filter id="blur-1" x="-20%" y="-20%" width="140%" height="140%">'
    '<feGaussianBlur stdDeviation="0.9"/></filter>'
    '<filter id="blur-4" x="-50%" y="-50%" width="200%" height="200%">'
    '<feGaussianBlur stdDeviation="4"/></filter>'
    f'<clipPath id="pond-clip"><rect width="{WIDTH}" height="{HEIGHT}" rx="20"/></clipPath>'
)


def _pebbles(rng: random.Random) -> str:
    """Kiesel am Teichgrund, leicht unscharf, weil tief unter Wasser."""
    stones = "".join(
        f'<ellipse cx="{rng.uniform(16, WIDTH - 16):.0f}" cy="{rng.uniform(16, HEIGHT - 16):.0f}" '
        f'rx="{rng.uniform(4, 12):.1f}" ry="{rng.uniform(3, 7):.1f}" fill="url(#pebble)"/>'
        for _ in range(32)
    )
    return f'<g opacity="0.4" filter="url(#blur-1)">{stones}</g>'


def _caustics(rng: random.Random) -> str:
    """Lichtflecken am Grund, die langsam wandern, wie Sonne durch bewegtes Wasser."""
    parts: list[str] = []
    for i in range(9):
        cx, cy = rng.uniform(60, WIDTH - 60), rng.uniform(40, HEIGHT - 60)
        dx, dy = rng.uniform(-18, 18), rng.uniform(-10, 10)
        dur = rng.uniform(11, 19)
        parts.append(
            f'<ellipse cx="{cx:.0f}" cy="{cy:.0f}" rx="{rng.uniform(50, 90):.0f}" '
            f'ry="{rng.uniform(26, 44):.0f}" fill="url(#glow)">'
            f'<animateTransform attributeName="transform" type="translate" '
            f'values="0 0;{dx:.0f} {dy:.0f};0 0" dur="{dur:.1f}s" begin="-{i * 2.3:.1f}s" '
            f'repeatCount="indefinite"/></ellipse>'
        )
    return "".join(parts)


def _ripples(rng: random.Random) -> str:
    """Ringe auf der Wasseroberfläche, die sich ausbreiten und verblassen."""
    parts: list[str] = []
    count = 7
    for i in range(count):
        x, y = rng.uniform(60, WIDTH - 60), rng.uniform(40, HEIGHT - 80)
        # Starts gleichmäßig über die Dauer verteilt, damit immer etwa gleich viele Ringe laufen
        timing = f'dur="6.8s" begin="{i * 6.8 / count:.1f}s" repeatCount="indefinite"'
        parts.append(
            f'<circle cx="{x:.0f}" cy="{y:.0f}" r="0" fill="none" '
            f'stroke="{RIPPLE}" stroke-width="1">'
            f'<animate attributeName="r" values="0;26" {timing}/>'
            f'<animate attributeName="opacity" values="0.4;0" {timing}/>'
            f"</circle>"
        )
    return "".join(parts)


def _lily_pad(x: float, y: float, r: float, angle: float, flower: bool = False) -> str:
    """Seerosenblatt mit Kerbe und Blattadern, wiegt sanft; auf Wunsch mit Blüte."""
    veins = "".join(
        f"M0 0L{-r * 0.85 * c:.1f} {r * 0.85 * s:.1f}"
        for c, s in ((1, 0), (0.7, 0.7), (0.7, -0.7), (0, 1), (0, -1), (-0.6, 0.75), (-0.6, -0.75))
    )
    pad = (
        f'<path d="M0 0L{r * 0.985:.1f} {-r * 0.17:.1f}'
        f'A{r} {r} 0 1 0 {r * 0.985:.1f} {r * 0.17:.1f}Z" fill="url(#pad)"/>'
        f'<path d="{veins}" stroke="#2f5f2b" stroke-width="0.8" opacity="0.6"/>'
    )
    blossom = _water_lily(-r * 0.25, 0, r * 0.03) if flower else ""
    return (
        f'<g transform="translate({x} {y})"><g>'
        f'<animateTransform attributeName="transform" type="rotate" '
        f'values="{angle - 3};{angle + 3};{angle - 3}" dur="{8 + r / 4:.1f}s" '
        f'repeatCount="indefinite"/>{pad}{blossom}</g></g>'
    )


PETAL_PATH = "M0 0C3.4-3 3.4-9 0-12.5C-3.4-9-3.4-3 0 0Z"


def _water_lily(x: float, y: float, size: float) -> str:
    """Seerosenblüte: zwei Kränze spitzer Blütenblätter um eine gelbe Mitte."""
    outer = "".join(
        f'<path d="{PETAL_PATH}" fill="url(#petal)" transform="rotate({i * 45})"/>'
        for i in range(8)
    )
    inner = "".join(
        f'<path d="{PETAL_PATH}" fill="url(#petal)" transform="rotate({i * 60 + 22}) scale(0.65)"/>'
        for i in range(6)
    )
    return (
        f'<g transform="translate({x:.1f} {y:.1f}) scale({size:.2f})">'
        f'<g opacity="0.95">{outer}</g>{inner}'
        '<circle r="3" fill="#f4c430"/><circle r="1.4" fill="#e09a1a"/></g>'
    )


def _drifting_petal() -> str:
    """Ein einzelnes Blütenblatt treibt langsam über den Teich."""
    path = (
        f"M -20 {HEIGHT * 0.35:.0f} C {WIDTH * 0.25:.0f} 60, {WIDTH * 0.54:.0f} 190, "
        f"{WIDTH + 20} {HEIGHT * 0.55:.0f}"
    )
    # Treibt gleich langsam, egal wie breit der Teich ist: 48 s je 480 px
    return (
        '<path d="M0 0C2-2 6-2 8 0C6 2 2 2 0 0Z" fill="#f6bfd0" opacity="0.9">'
        f'<animateMotion dur="{48 * WIDTH / 480:.0f}s" repeatCount="indefinite" rotate="auto" '
        f'path="{path}"/>'
        "</path>"
    )


def _glints(rng: random.Random) -> str:
    """Kurzes Glitzern auf der Oberfläche."""
    return "".join(
        f'<ellipse cx="{rng.uniform(40, WIDTH - 40):.0f}" cy="{rng.uniform(30, HEIGHT - 80):.0f}" '
        f'rx="2.2" ry="0.9" fill="#fff" opacity="0">'
        f'<animate attributeName="opacity" values="0;0.75;0" dur="{rng.uniform(2.5, 4.5):.1f}s" '
        f'begin="{i * 1.3:.1f}s" repeatCount="indefinite"/></ellipse>'
        for i in range(10)
    )


# --- Legende -----------------------------------------------------------------------------


def _text_width(text: str, size: float, bold: bool = False) -> float:
    """Grobe Breitenschätzung, da SVG-Text ohne Layout-Engine erzeugt wird."""
    widths = {"upper": 0.66, "lower": 0.53, "digit": 0.56, "other": 0.32}
    total = 0.0
    for ch in text:
        if ch.isupper():
            kind = "upper"
        elif ch.islower():
            kind = "lower"
        elif ch.isdigit():
            kind = "digit"
        else:
            kind = "other"
        total += widths[kind]
    return total * size * (1.06 if bold else 1.0)


def _legend(data: KoiData) -> str:
    """Beschriftung unten: Lebensphase, Trend, Jahreszahl, Sprachen (so viele passen)."""
    count = f"{data.month_contributions:,}".replace(",", ".")
    head = f"{data.stage} · {TREND_ARROWS[data.trend]}"
    noun = "Contribution" if data.month_contributions == 1 else "Contributions"
    sub = f"{count} {noun} in den letzten 30 Tagen"
    y = HEIGHT - 16
    items = [
        f'<rect y="{HEIGHT - 66}" width="{WIDTH}" height="66" fill="url(#band)"/>',
        f'<text x="18" y="{y - 16}" font-size="13" fill="{LABEL}" font-weight="600">'
        f"{escape(head)}</text>",
        f'<text x="18" y="{y}" font-size="11" fill="{LABEL}" opacity="0.85">{escape(sub)}</text>',
    ]
    x = 18 + _text_width(sub, 11) + 16
    if not data.languages:
        items.append(
            f'<text x="{x:.0f}" y="{y}" font-size="11" fill="{LABEL}" opacity="0.6" '
            f'font-style="italic">Farben folgen mit den ersten Commits</text>'
        )
    for lang in data.languages:
        width = 8 + _text_width(lang.name, 11)
        if x + width > WIDTH - 18:
            break
        items.append(
            f'<circle cx="{x:.0f}" cy="{y - 4}" r="4" fill="{lang.color}"/>'
            f'<text x="{x + 8:.0f}" y="{y}" font-size="11" fill="{LABEL}" opacity="0.85">'
            f"{escape(lang.name)}</text>"
        )
        x += width + 12
    return f'<g font-family="{FONT}">' + "".join(items) + "</g>"


# --- Gesamtbild --------------------------------------------------------------------------


def render_svg(data: KoiData, body: str = "white", label: bool = True) -> str:
    """Erzeugt das komplette SVG.

    Args:
        data: Kennzahlen des Koi.
        body: Grundfarbe, ein Schlüssel aus `BODIES`.
        label: Beschriftung mit Lebensphase und Sprachen unten im Teich.

    Raises:
        ValueError: bei unbekannter Grundfarbe.
    """
    if body not in BODIES:
        raise ValueError(f"Unbekannter Körper '{body}'. Möglich: {', '.join(BODIES)}")
    scene_rng = _rng_for(data.login, "teich")
    koi_defs, koi_scene = _koi_layers(data, body)
    noun = "Contribution" if data.month_contributions == 1 else "Contributions"
    # Steht auch im Attribut aria-label="…", deshalb zusätzlich " maskieren.
    title = escape(
        f"Koi von {data.login}: {data.stage}, "
        f"{data.month_contributions} {noun} in den letzten 30 Tagen",
        {'"': "&quot;"},
    )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'width="{WIDTH}" height="{HEIGHT}" role="img" aria-label="{title}">'
        f"<title>{title}</title>"
        f"<defs>{POND_DEFS}{koi_defs}</defs>"
        '<g clip-path="url(#pond-clip)">'
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="url(#pond)"/>'
        f"{_pebbles(scene_rng)}{_caustics(scene_rng)}"
        f"{koi_scene}"
        f"{_ripples(scene_rng)}"
        f"{_lily_pad(WIDTH - 42, 42, 30, 200, flower=True)}"
        f"{_lily_pad(WIDTH - 92, 18, 16, 120)}{_lily_pad(34, 48, 21, 330)}"
        f"{_lily_pad(round(WIDTH * 0.38), 12, 13, 60)}"
        f"{_drifting_petal()}{_glints(scene_rng)}"
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="url(#vignette)"/>'
        f"{_legend(data) if label else ''}"
        "</g></svg>"
    )
