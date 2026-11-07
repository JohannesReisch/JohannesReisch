"""Geometrie des Koi: Körper, Flossen und Flecken als Schlüsselbilder einer Schwimmwelle.

Der Fisch liegt mit dem Kopf in +x-Richtung um den Ursprung (animateMotion mit
rotate="auto" dreht ihn später in Schwimmrichtung). Die Bewegung ist eine Welle, die vom
Kopf zum Schwanz läuft und nach hinten stärker wird, wie bei echten Fischen.

Jede Form wird in Ruhelage als Punktliste beschrieben. Für jedes Schlüsselbild werden die
Punkte quer zur Körperachse verschoben und zu einem glatten Pfad verbunden; SVG blendet
zwischen den Pfaden über (<animate attributeName="d">). Das funktioniert nur, wenn alle
Schlüsselbilder einer Form dieselbe Befehlsfolge haben. Deshalb hat jede Form eine feste
Punktzahl und wird immer gleich aufgebaut.
"""

import math
import random
from collections.abc import Sequence

type Point = tuple[float, float]

# Körpermaße in Zeichen-Einheiten (vor der Skalierung nach Wachstum).
HEAD_X = 64.0
PEDUNCLE_X = -50.0  # Schwanzstiel, Ansatz der Schwanzflosse
BODY_LENGTH = HEAD_X - PEDUNCLE_X
MAX_HALF_WIDTH = 23.0
PEDUNCLE_HALF_WIDTH = 4.5
WIDEST_AT = 0.3  # Anteil der Körperlänge ab Kopf, an dem der Koi am breitesten ist
OUTLINE_SAMPLES = 12

# Schwimmwelle.
KEYFRAMES = 12
WAVE_AMPLITUDE = 6.5
WAVE_PHASE_SHIFT = 1.15 * math.pi  # Versatz Kopf → Schwanzstiel; erzeugt die S-Form


def x_at(u: float) -> float:
    """x-Koordinate für den Anteil `u` der Körperlänge (0 = Schnauze, 1 = Schwanzstiel)."""
    return HEAD_X - u * BODY_LENGTH


def u_at(x: float) -> float:
    """Umkehrung von `x_at`; hinter dem Schwanzstiel (Flosse) wird `u` größer als 1."""
    return (HEAD_X - x) / BODY_LENGTH


def half_width(u: float) -> float:
    """Halbe Körperbreite von oben gesehen: runder Kopf, breite Schultern, schlanker Stiel."""
    if u < WIDEST_AT:
        k = (WIDEST_AT - u) / (WIDEST_AT + 0.02)
        return MAX_HALF_WIDTH * math.sqrt(max(0.0, 1 - k * k))
    t = (u - WIDEST_AT) / (1 - WIDEST_AT)
    return PEDUNCLE_HALF_WIDTH + (MAX_HALF_WIDTH - PEDUNCLE_HALF_WIDTH) * (
        0.5 + 0.5 * math.cos(math.pi * t)
    )


def wave(u: float, phase: float) -> float:
    """Querauslenkung an der Stelle `u` zur Phase `phase` (Bogenmaß)."""
    amplitude = WAVE_AMPLITUDE * (0.08 + 0.92 * u * u)
    return amplitude * math.sin(phase - WAVE_PHASE_SHIFT * u)


def displaced(points: Sequence[Point], phase: float) -> list[Point]:
    """Verschiebt Punkte der Ruhelage gemäß der Schwimmwelle."""
    return [(x, y + wave(u_at(x), phase)) for x, y in points]


def displaced_point(point: Point, phase: float) -> Point:
    """Verschiebt einen einzelnen Punkt gemäß der Schwimmwelle."""
    x, y = point
    return (x, y + wave(u_at(x), phase))


def _fmt(p: Point) -> str:
    return f"{p[0]:.1f} {p[1]:.1f}"


def smooth_closed(points: Sequence[Point]) -> str:
    """Glatter geschlossener Pfad durch alle Punkte (Catmull-Rom als kubische Bézier)."""
    n = len(points)
    parts = [f"M{_fmt(points[0])}"]
    for i in range(n):
        p0, p1, p2, p3 = points[i - 1], points[i], points[(i + 1) % n], points[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        parts.append(f"C{_fmt(c1)} {_fmt(c2)} {_fmt(p2)}")
    return "".join(parts) + "Z"


def _mirror(points: Sequence[Point]) -> list[Point]:
    return [(x, -y) for x, y in points]


# --- Formen in Ruhelage ---------------------------------------------------------------


def body_outline() -> list[Point]:
    """Umriss des Rumpfes: Schnauze, obere Seite bis zum Stiel, untere Seite zurück."""
    us = [i / (OUTLINE_SAMPLES - 1) for i in range(OUTLINE_SAMPLES)]
    upper = [(x_at(u), -half_width(u)) for u in us]
    lower = [(x_at(u), half_width(u)) for u in reversed(us)]
    return [(HEAD_X + 3, 0.0), *upper, *lower]


# Schleierschwanz: obere Hälfte vom Ansatz über die Spitze zur Kerbe, untere gespiegelt.
_TAIL_UPPER: list[Point] = [
    (-44.0, -5.0),
    (-60.0, -12.0),
    (-77.0, -23.0),
    (-94.0, -30.0),
    (-96.0, -22.0),
    (-87.0, -12.0),
    (-81.0, -4.0),
]


def tail_outline() -> list[Point]:
    """Umriss der Schwanzflosse."""
    notch = (-79.0, 0.0)
    return [*_TAIL_UPPER, notch, *reversed(_mirror(_TAIL_UPPER))]


def tail_rays() -> list[tuple[Point, Point, Point]]:
    """Flossenstrahlen als (Ansatz, Mitte, Ende); die Mitte wird extra ausgelenkt (Biegung)."""
    root = (-46.0, 0.0)
    ends: list[Point] = [(-92, -26), (-86, -16), (-80, -7), (-80, 7), (-86, 16), (-92, 26)]
    return [(root, ((root[0] + x) / 2, (root[1] + y) / 2), (x, y)) for x, y in ends]


def dorsal_ridge() -> list[Point]:
    """Rückenkamm von oben: schmaler Streifen entlang der Mittellinie."""
    us = [0.26 + i * 0.07 for i in range(8)]
    upper = [(x_at(u), -2.2 * (1 - abs(u - 0.5) * 1.6)) for u in us]
    return [*upper, *reversed(_mirror(upper))]


def pelvic_fin(side: int) -> list[Point]:
    """Bauchflosse; side = -1 oben, +1 unten (von oben gesehen links/rechts)."""
    u = 0.6
    x0, y0 = x_at(u), side * (half_width(u) - 2)
    shape: list[Point] = [(0, 0), (-3, 4), (-9, 8), (-14, 8), (-13, 4), (-8, 1)]
    return [(x0 + dx, y0 + side * dy) for dx, dy in shape]


PECTORAL_ROOT_X = 36.0


def pectoral_fin(side: int) -> list[Point]:
    """Brustflosse relativ zu ihrem Ansatzpunkt (wird per Drehung bewegt, nicht verformt)."""
    shape: list[Point] = [(0, 0), (-3, 6), (-10, 13), (-19, 17), (-24, 14), (-20, 7), (-10, 1)]
    return [(dx, side * dy) for dx, dy in shape]


def pectoral_root(side: int) -> Point:
    """Ansatzpunkt der Brustflosse am Körperrand."""
    return (PECTORAL_ROOT_X, side * (half_width(u_at(PECTORAL_ROOT_X)) - 3))


def spot_blob(rng: random.Random, size: float) -> list[Point]:
    """Organischer Fleck: Punkte auf einem unregelmäßigen, leicht länglichen Kreis.

    Liegt bevorzugt im vorderen und mittleren Körper; was über den Rand ragt, schneidet der
    Renderer am Körperumriss ab, wie Muster, die bei echten Koi über die Flanke laufen.
    """
    u = rng.uniform(0.1, 0.82)
    cx = x_at(u)
    cy = rng.uniform(-1, 1) * half_width(u) * 0.85
    points: list[Point] = []
    count = 9
    for i in range(count):
        angle = 2 * math.pi * (i + rng.uniform(-0.25, 0.25)) / count
        radius = size * rng.uniform(0.7, 1.2)
        points.append((cx + 1.3 * radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points


# --- Schlüsselbilder ---------------------------------------------------------------------


def phases() -> list[float]:
    """Phasen der Schlüsselbilder über eine volle Welle."""
    return [2 * math.pi * k / KEYFRAMES for k in range(KEYFRAMES)]


def closed_keyframes(points: Sequence[Point]) -> list[str]:
    """Glatte geschlossene Pfade einer Form, je Schlüsselbild einer."""
    return [smooth_closed(displaced(points, phase)) for phase in phases()]


def ray_keyframes(rays: Sequence[tuple[Point, Point, Point]]) -> list[str]:
    """Strahlen als gebogene Linien; die Mitte folgt der Welle mit kleinem Versatz."""
    frames: list[str] = []
    for phase in phases():
        parts: list[str] = []
        for start, mid, end in rays:
            s = displaced_point(start, phase)
            m = displaced_point(mid, phase - 0.4)  # Mitte hängt nach: Strahl biegt sich
            e = displaced_point(end, phase)
            parts.append(f"M{_fmt(s)}Q{_fmt(m)} {_fmt(e)}")
        frames.append("".join(parts))
    return frames


def animate_d(frames: Sequence[str], seconds: float) -> str:
    """SMIL-Animation, die einen Pfad in Endlosschleife durch die Schlüsselbilder führt."""
    values = ";".join([*frames, frames[0]])
    return (
        f'<animate attributeName="d" dur="{seconds:.2f}s" repeatCount="indefinite" '
        f'values="{values}"/>'
    )


def morphing_path(frames: Sequence[str], seconds: float, attributes: str) -> str:
    """Fertiges <path>-Element, das sich mit der Schwimmwelle verformt."""
    return f'<path d="{frames[0]}" {attributes}>{animate_d(frames, seconds)}</path>'
