"""Schwimmroute des Koi: ein Streifzug mit Pausen und Wenden statt immer derselben Runde.

GitHub zeigt das SVG als Bild; Skripte laufen dort nicht, Zufall zur Laufzeit gibt es
also nicht. Stattdessen wird hier einmal eine lange, abwechslungsreiche Route geplant und
in eine einzige SMIL-Animation (<animateMotion>) übersetzt:

- **Pfad:** glatte Kurve durch Wegpunkte; der Koi dreht sich per rotate="auto" mit.
- **Tempo:** keyTimes/keyPoints legen fest, wann der Koi welchen Anteil der Strecke
  erreicht hat. keySplines lassen ihn dazwischen sanft beschleunigen und abbremsen.
- **Pausen:** zwei aufeinanderfolgende keyTimes mit gleichem keyPoint – der Koi steht.

Verhalten, aus denen die Route zufällig zusammengesetzt wird:

| Verhalten   | Ablauf                                                                  |
|-------------|-------------------------------------------------------------------------|
| umherziehen | zwei bis vier freie Punkte in Schlangenlinien, Tempo schwankt leicht    |
| ausruhen    | gleitet aus, steht kurz mitten im Teich, schwimmt weiter                |
| Versteck    | schwimmt in eine Ecke oder an den Rand, verharrt, wendet in engem Bogen |

Die Route dauert je nach Tempo rund zwei bis fünf Minuten, damit die Wiederholung kaum
auffällt. Der Zufall kommt von außen (fester Startwert je Benutzer), also gleiche Eingabe,
gleiche Route.
"""

import itertools
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

from .fish import Point

# Bereich, in dem freie Wegpunkte liegen (Mittelpunkt des Koi; Teich 840 × 270, unten die
# Legende). Als (x_min, y_min, x_max, y_max).
FREE_AREA = (140.0, 72.0, 700.0, 165.0)
# Diese Grenzen überschreitet die fertige Kurve nie; Kopf und Schwanz ragen noch darüber.
POND_LIMITS = (60.0, 40.0, 790.0, 192.0)
POND_CENTER: Point = (420.0, 120.0)

# Verstecke am Rand: vier Ecken (oben rechts unter der großen Seerose) und zwei Seitenmitten.
# Gemeint ist, wie tief der Koi beim Wenden hineinschwimmt; der Bogen liegt dabei um
# seinen Radius zur Teichmitte hin versetzt.
HIDEOUTS: tuple[Point, ...] = (
    (104, 70),
    (756, 68),
    (104, 170),
    (740, 170),
    (88, 120),
    (752, 120),
)

# `KoiData.swim_seconds` ist die Zeit für diese Strecke im Reisetempo (Länge der früheren
# Rundbahn; so bleibt das Tempo des Koi wie gewohnt).
REFERENCE_DISTANCE = 570.0

# Umfang der Route: so viele Verhalten hintereinander, davon mindestens so viele Verstecke.
LEGS = 12
MIN_HIDEOUTS = 2
# Weiter darf die Schwimmrichtung an einem Wegpunkt nicht von der Sehne zum nächsten Punkt
# abweichen, sonst schlägt die Kurve Haken oder Schleifen.
MAX_TANGENT_ANGLE = math.radians(70)
MAX_ATTEMPTS = 2000  # in Tests über 1000 Benutzer höchstens rund 220 nötig


@dataclass(frozen=True)
class Waypoint:
    """Ein Punkt der Route.

    Attributes:
        point: Lage des Koi-Mittelpunkts.
        speed: Tempo an diesem Punkt als Vielfaches des Reisetempos (0 = steht).
        pause: So viele Sekunden verharrt der Koi hier, bevor er weiterschwimmt.
        heading: Feste Schwimmrichtung (Einheitsvektor); ohne Angabe ergibt sie sich aus
            den Nachbarpunkten.
    """

    point: Point
    speed: float
    pause: float = 0.0
    heading: Point | None = None


# --- Vektorrechnung ----------------------------------------------------------------------


def _sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1])


def _add(a: Point, b: Point, factor: float = 1.0) -> Point:
    """A + factor · b."""
    return (a[0] + factor * b[0], a[1] + factor * b[1])


def _unit(v: Point) -> Point:
    length = math.hypot(*v)
    if length < 1e-9:
        raise ValueError("Richtung eines Nullvektors ist undefiniert")
    return (v[0] / length, v[1] / length)


def _angle(a: Point, b: Point) -> float:
    """Winkel zwischen zwei Richtungen (0 … π)."""
    return abs(math.remainder(math.atan2(b[1], b[0]) - math.atan2(a[1], a[0]), 2 * math.pi))


def _fmt(p: Point) -> str:
    """Punkt im Pfad mit einer Nachkommastelle."""
    return f"{p[0]:.1f} {p[1]:.1f}"


def _inside(p: Point, area: tuple[float, float, float, float]) -> bool:
    x_min, y_min, x_max, y_max = area
    return x_min <= p[0] <= x_max and y_min <= p[1] <= y_max


# --- Planung -----------------------------------------------------------------------------


class _Planner:
    """Setzt Verhalten aneinander und merkt sich Lage und Richtung des Koi."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        x_min, y_min, x_max, y_max = FREE_AREA
        start = (rng.uniform(x_min + 100, x_max - 100), rng.uniform(y_min + 15, y_max - 15))
        angle = rng.uniform(0, 2 * math.pi)
        self.waypoints = [Waypoint(start, 1.0)]
        self.heading: Point = (math.cos(angle), math.sin(angle))
        self.hideouts = 0

    @property
    def position(self) -> Point:
        return self.waypoints[-1].point

    def _go(self, waypoint: Waypoint) -> None:
        """Hängt einen Wegpunkt an; die neue Richtung ist die feste oder die der Sehne."""
        self.heading = waypoint.heading or _unit(_sub(waypoint.point, self.position))
        self.waypoints.append(waypoint)

    @property
    def max_turn(self) -> float:
        """Größte Richtungsänderung, die am aktuellen Punkt ohne Haken möglich ist.

        Bei freier Richtung verteilt sich ein Knick hälftig auf beide Seiten (Winkel-
        halbierende), bei fester Richtung (Wendebogen) muss die neue Sehne allein passen.
        """
        limit = MAX_TANGENT_ANGLE if self.waypoints[-1].heading else 2 * MAX_TANGENT_ANGLE
        return limit - math.radians(10)

    def _free_point(self, min_dist: float, max_dist: float, turn: float) -> Point | None:
        """Zufälliger Punkt im freien Bereich, bevorzugt höchstens `turn` vom Kurs ab.

        Liegt dort nichts (Koi am Rand, Blick nach außen), lenkt er schrittweise stärker
        ein, bis zur Grenze `max_turn`, und nimmt kürzere Schritte. Dann dreht er eben in
        mehreren kleinen Bögen um, statt am Rand hängen zu bleiben.
        """
        base = math.atan2(self.heading[1], self.heading[0])
        attempts = 80
        for attempt in range(attempts):
            spread = min(turn + math.radians(2) * attempt, self.max_turn)
            shrink = 1 - 0.7 * attempt / attempts
            angle = base + self.rng.uniform(-spread, spread)
            dist = self.rng.uniform(min_dist, max_dist) * shrink
            p = _add(self.position, (math.cos(angle), math.sin(angle)), dist)
            if _inside(p, FREE_AREA):
                return p
        return None

    def wander(self) -> None:
        """Umherziehen: zwei bis vier freie Punkte in Schlangenlinien, das Tempo schwankt leicht."""
        for _ in range(self.rng.randint(2, 4)):
            p = self._free_point(70, 180, math.radians(80))
            if p is None:
                return
            self._go(Waypoint(p, self.rng.uniform(0.75, 1.3)))

    def rest(self) -> None:
        """Ausruhen: ausgleiten bis zum Stillstand, kurz verharren, weiterschwimmen."""
        p = self._free_point(130, 230, math.radians(40))
        if p is not None:
            self._go(Waypoint(p, 0.0, pause=self.rng.uniform(1.5, 3.5)))

    def hide(self) -> bool:
        """Versteck: zum Rand, abbremsen, verharren, in engem Bogen wenden.

        Returns:
            False, wenn kein Versteck ohne scharfen Haken erreichbar ist.
        """
        # Nur Verstecke in mittlerer Reichweite (keine Geraden quer durch den Teich),
        # ohne scharfen Haken erreichbar
        reachable = [
            (hx + self.rng.uniform(-10, 10), hy + self.rng.uniform(-6, 6))
            for hx, hy in HIDEOUTS
            if 150 < math.dist((hx, hy), self.position) < 340
            and _angle(self.heading, _sub((hx, hy), self.position)) < self.max_turn
        ]
        if not reachable:
            return False
        target = self.rng.choice(reachable)
        d = _unit(_sub(target, self.position))

        # Der Koi wendet auf einem Halbkreis mit Radius r zur Teichmitte hin. Er steht
        # r vor dem Ziel, damit der Bogen genau die Tiefe des Ziels erreicht.
        r = self.rng.uniform(24, 34)
        hover = _add(target, d, -r)
        normal: Point = (-d[1], d[0])
        to_center = _sub(POND_CENTER, hover)
        if normal[0] * to_center[0] + normal[1] * to_center[1] < 0:
            normal = (-normal[0], -normal[1])

        # Gerade Anfahrt, auf der er abbremst; dann Stillstand mit Blick in die Ecke.
        self._go(Waypoint(_add(hover, d, -self.rng.uniform(50, 80)), 0.55))
        self._go(Waypoint(hover, 0.0, pause=self.rng.uniform(2.0, 5.0), heading=d))

        # Halbkreis in Achteln: P(θ) = O + r(−n cos θ + d sin θ), Tangente n sin θ + d cos θ.
        # Langsam aus dem Stand, zum Ende der Wende zieht das Tempo an.
        origin = _add(hover, normal, r)
        for k, speed in enumerate((0.45, 0.6, 0.75, 0.9), start=1):
            theta = k * math.pi / 4
            radial = _add(
                (-normal[0] * math.cos(theta), -normal[1] * math.cos(theta)), d, math.sin(theta)
            )
            tangent = _add(
                (normal[0] * math.sin(theta), normal[1] * math.sin(theta)), d, math.cos(theta)
            )
            self._go(Waypoint(_add(origin, radial, r), speed, heading=_unit(tangent)))
        self.hideouts += 1
        return True

    def home(self, entry: Point) -> None:
        """Heimkehr: in sanften Bögen zum Punkt `entry` kurz vor dem Start.

        Von dort läuft die Schleife geradeaus in Startrichtung zurück zum Start; so
        schließt sie ohne Haken.
        """
        for _ in range(6):
            to_entry = _sub(entry, self.position)
            delta = math.remainder(
                math.atan2(to_entry[1], to_entry[0]) - math.atan2(self.heading[1], self.heading[0]),
                2 * math.pi,
            )
            if abs(delta) < self.max_turn / 2 and math.hypot(*to_entry) > 60:
                break
            # Höchstens 60° je Schritt Richtung Ziel einlenken
            turn = math.copysign(min(abs(delta), math.radians(60)), delta)
            angle = math.atan2(self.heading[1], self.heading[0]) + turn
            for dist in (140.0, 90.0, 55.0):
                p = _add(self.position, (math.cos(angle), math.sin(angle)), dist)
                if _inside(p, FREE_AREA):
                    self._go(Waypoint(p, self.rng.uniform(0.8, 1.2)))
                    break
            else:
                return
        self._go(Waypoint(entry, 1.0))

    def plan(self) -> list[Waypoint]:
        """Zufällige Folge von Verhalten, dann Heimkehr; nie zweimal hintereinander ausruhen."""
        start, start_heading = self.position, self.heading
        last = ""
        for _ in range(LEGS):
            choice = self.rng.choices(("wander", "rest", "hide"), weights=(3, 2, 5))[0]
            if choice == "rest" and last == "rest":
                choice = "wander"
            if choice == "hide" and not self.hide():
                choice = "wander"
            if choice == "wander":
                self.wander()
            elif choice == "rest":
                self.rest()
            last = choice
        self.home(_add(start, start_heading, -120))
        return self.waypoints


# --- Geometrie der Kurve -----------------------------------------------------------------

type Segment = tuple[Point, Point, Point, Point]


def headings(waypoints: Sequence[Waypoint]) -> list[Point]:
    """Schwimmrichtung an jedem Wegpunkt (die Route ist geschlossen).

    Ohne feste Richtung gilt die Winkelhalbierende aus ankommender und abgehender Sehne.
    """
    result: list[Point] = []
    n = len(waypoints)
    for i, wp in enumerate(waypoints):
        if wp.heading is not None:
            result.append(wp.heading)
            continue
        incoming = _unit(_sub(wp.point, waypoints[i - 1].point))
        outgoing = _unit(_sub(waypoints[(i + 1) % n].point, wp.point))
        result.append(_unit(_add(incoming, outgoing)))
    return result


def segments(waypoints: Sequence[Waypoint]) -> list[Segment]:
    """Kubische Bézier-Stücke von Wegpunkt zu Wegpunkt, zurück zum Start.

    Die Kontrollpunkte liegen in Schwimmrichtung, ein Drittel der Sehne entfernt. Damit
    stimmt die Richtung an jedem Wegpunkt auf beiden Seiten überein (kein Zucken), auch
    wenn kurze Wendebögen auf lange Strecken folgen.
    """
    dirs = headings(waypoints)
    n = len(waypoints)
    result: list[Segment] = []
    for i in range(n):
        p1, p2 = waypoints[i].point, waypoints[(i + 1) % n].point
        third = math.dist(p1, p2) / 3
        result.append((p1, _add(p1, dirs[i], third), _add(p2, dirs[(i + 1) % n], -third), p2))
    return result


def bezier_point(seg: Segment, t: float) -> Point:
    """Punkt auf einem Bézier-Stück zum Parameter t (0 … 1)."""
    s = 1 - t
    weights = (s**3, 3 * s * s * t, 3 * s * t * t, t**3)
    return (
        sum(w * p[0] for w, p in zip(weights, seg, strict=True)),
        sum(w * p[1] for w, p in zip(weights, seg, strict=True)),
    )


def bezier_length(seg: Segment, steps: int = 32) -> float:
    """Länge eines Bézier-Stücks, angenähert über einen feinen Polygonzug."""
    samples = [bezier_point(seg, k / steps) for k in range(steps + 1)]
    return sum(math.dist(a, b) for a, b in itertools.pairwise(samples))


def is_valid(waypoints: Sequence[Waypoint]) -> bool:
    """Prüft eine geplante Route auf alles, was im Bild unschön aussähe.

    - genug Verstecke, damit das neue Verhalten auch sichtbar wird
    - kein Wegpunkt doppelt, kein Abschnitt, auf dem der Koi nie ankäme (Tempo 0 → 0)
    - keine Haken oder Schleifen (Richtung nah an der Sehne)
    - die Kurve bleibt im Teich
    """
    n = len(waypoints)
    if sum(1 for wp in waypoints if wp.pause > 0 and wp.heading is not None) < MIN_HIDEOUTS:
        return False
    for i, wp in enumerate(waypoints):
        nxt = waypoints[(i + 1) % n]
        if math.dist(wp.point, nxt.point) < 10 or wp.speed + nxt.speed <= 0:
            return False
    try:
        segs = segments(waypoints)
    except ValueError:
        return False
    for p0, c1, c2, p3 in segs:
        chord = _sub(p3, p0)
        if (
            _angle(_sub(c1, p0), chord) > MAX_TANGENT_ANGLE
            or _angle(_sub(p3, c2), chord) > MAX_TANGENT_ANGLE
        ):
            return False
    return all(_inside(bezier_point(seg, k / 16), POND_LIMITS) for seg in segs for k in range(17))


def plan_waypoints(rng: random.Random) -> list[Waypoint]:
    """Plant so lange zufällige Routen, bis eine alle Prüfungen besteht.

    Raises:
        RuntimeError: falls nach `MAX_ATTEMPTS` Versuchen keine Route taugt (Konstanten
            widersprüchlich eingestellt).
    """
    for _ in range(MAX_ATTEMPTS):
        waypoints = _Planner(rng).plan()
        if is_valid(waypoints):
            return waypoints
    raise RuntimeError("Keine gültige Schwimmroute gefunden – Konstanten in swim.py prüfen")


# --- Animation ---------------------------------------------------------------------------


def _ease(a: float, b: float) -> str:
    """KeySpline für ein Teilstück, auf dem das Tempo gleichmäßig von a auf b wechselt.

    Die zurückgelegte Strecke wächst dann quadratisch mit der Zeit. Als Bézierkurve mit
    x-Kontrollpunkten bei 1/3 und 2/3 (Zeit läuft linear) braucht sie die y-Werte
    a/(3·Mittel) am Anfang und 1 − b/(3·Mittel) am Ende; Mittel = (a + b) / 2.
    """
    total = a + b
    return f"0.333 {2 * a / (3 * total):.3f} 0.667 {1 - 2 * b / (3 * total):.3f}"


@dataclass(frozen=True)
class Route:
    """Fertig berechnete Route: Pfad und Zeitplan für <animateMotion>."""

    path: str
    duration: float
    key_times: tuple[float, ...]
    key_points: tuple[float, ...]
    key_splines: tuple[str, ...]

    @classmethod
    def build(cls, waypoints: Sequence[Waypoint], swim_seconds: float) -> "Route":
        """Rechnet Wegpunkte und Reisetempo in Pfad und Zeitplan um.

        Erwartet eine geprüfte Route (`is_valid`), sonst drohen Divisionen durch null.

        Args:
            waypoints: Geplante Route, z. B. aus `plan_waypoints`.
            swim_seconds: Zeit für `REFERENCE_DISTANCE` im Reisetempo.
        """
        cruise = REFERENCE_DISTANCE / swim_seconds  # Pixel je Sekunde
        segs = segments(waypoints)
        n = len(waypoints)
        times, dists, splines = [0.0], [0.0], list[str]()
        t = s = 0.0
        for i, (wp, seg) in enumerate(zip(waypoints, segs, strict=True)):
            # Pause: Zeit vergeht, Strecke nicht
            if wp.pause > 0:
                t += wp.pause
                times.append(t)
                dists.append(s)
                splines.append("0 0 1 1")
            # Fahrt zum nächsten Punkt mit dem mittleren Tempo beider Enden
            nxt = waypoints[(i + 1) % n]
            length = bezier_length(seg)
            t += length / (cruise * (wp.speed + nxt.speed) / 2)
            s += length
            times.append(t)
            dists.append(s)
            splines.append(_ease(wp.speed, nxt.speed))

        path = f"M{_fmt(segs[0][0])}" + "".join(
            f"C{_fmt(c1)} {_fmt(c2)} {_fmt(p3)}" for _, c1, c2, p3 in segs
        )
        return cls(
            path=path,
            duration=t,
            key_times=tuple(x / t for x in times),
            key_points=tuple(x / s for x in dists),
            key_splines=tuple(splines),
        )

    def animate_motion(self) -> str:
        """<animateMotion>, das den Koi in Endlosschleife über die Route führt."""

        def fractions(values: Sequence[float]) -> str:
            # Erster und letzter Wert exakt, sonst verweigern Browser die Animation.
            inner = [f"{v:.5f}" for v in values[1:-1]]
            return ";".join(["0", *inner, "1"])

        return (
            f'<animateMotion dur="{self.duration:.1f}s" repeatCount="indefinite" '
            f'rotate="auto" calcMode="spline" keyTimes="{fractions(self.key_times)}" '
            f'keyPoints="{fractions(self.key_points)}" '
            f'keySplines="{";".join(self.key_splines)}" path="{self.path}"/>'
        )
