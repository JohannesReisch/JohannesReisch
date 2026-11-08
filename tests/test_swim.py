"""Schwimmroute: abwechslungsreich, aber nie mit Haken, Sprüngen oder Ausflügen aus dem Teich."""

import itertools
import math
import random
import re

import pytest

from koi_profil import swim

# Viele verschiedene Benutzer, damit seltene Zufallsfälle auch auftreten.
SEEDS = [f"user-{i}" for i in range(60)]


def route_for(seed: str) -> tuple[list[swim.Waypoint], swim.Route]:
    waypoints = swim.plan_waypoints(random.Random(seed))
    return waypoints, swim.Route.build(waypoints, swim_seconds=20)


@pytest.mark.parametrize("seed", SEEDS)
def test_planned_route_is_valid(seed: str):
    """Jede Route besteht die eigene Prüfung (die Planung bricht sonst mit Fehler ab)."""
    waypoints, _ = route_for(seed)
    assert swim.is_valid(waypoints)


@pytest.mark.parametrize("seed", SEEDS[:10])
def test_route_stays_in_pond(seed: str):
    waypoints, _ = route_for(seed)
    for seg in swim.segments(waypoints):
        for k in range(41):
            x, y = swim.bezier_point(seg, k / 40)
            x_min, y_min, x_max, y_max = swim.POND_LIMITS
            assert x_min <= x <= x_max
            assert y_min <= y <= y_max


@pytest.mark.parametrize("seed", SEEDS[:10])
def test_path_has_no_kinks(seed: str):
    """An jedem Knoten zeigen ein- und auslaufende Tangente in dieselbe Richtung.

    Sonst dreht sich der Koi bei rotate="auto" ruckartig.
    """
    _, route = route_for(seed)
    numbers = [float(n) for n in re.findall(r"-?\d+\.?\d*", route.path)]
    start, rest = numbers[:2], numbers[2:]
    segments = [rest[i : i + 6] for i in range(0, len(rest), 6)]
    for i, (_, _, c2x, c2y, px, py) in enumerate(segments):
        nx, ny = segments[(i + 1) % len(segments)][:2]  # erster Kontrollpunkt danach
        incoming = math.atan2(py - c2y, px - c2x)
        outgoing = math.atan2(ny - py, nx - px)
        # Etwas Spielraum: Koordinaten sind auf 0,1 px gerundet, Wendebögen sind kurz.
        assert abs(math.remainder(incoming - outgoing, 2 * math.pi)) < math.radians(3)
    assert (segments[-1][4], segments[-1][5]) == pytest.approx(tuple(start), abs=0.05)


@pytest.mark.parametrize("seed", SEEDS[:10])
def test_route_contains_hideouts_with_pause_and_u_turn(seed: str):
    """Der Koi verharrt mehrmals am Rand und schwimmt danach in Gegenrichtung zurück."""
    waypoints, _ = route_for(seed)
    hovers = [i for i, wp in enumerate(waypoints) if wp.pause > 0 and wp.heading is not None]
    assert len(hovers) >= swim.MIN_HIDEOUTS
    for i in hovers:
        facing = waypoints[i].heading
        after_turn = waypoints[i + 4].heading
        assert facing is not None
        assert after_turn is not None
        dot = facing[0] * after_turn[0] + facing[1] * after_turn[1]
        assert dot == pytest.approx(-1, abs=1e-6)


def test_timeline_is_well_formed():
    """keyTimes steigen von 0 auf 1, keyPoints ebenso; Anzahl passt zu keySplines."""
    _, route = route_for("zeitplan")
    times, points = route.key_times, route.key_points
    assert len(times) == len(points) == len(route.key_splines) + 1
    assert times[0] == 0
    assert times[-1] == pytest.approx(1)
    assert points[0] == 0
    assert points[-1] == pytest.approx(1)
    assert all(a < b for a, b in itertools.pairwise(times))
    assert all(a <= b for a, b in itertools.pairwise(points))


def test_pauses_hold_position():
    """Während einer Pause vergeht Zeit, aber der Koi bleibt an seinem Punkt."""
    waypoints, route = route_for("pausen")
    holds = sum(
        1 for i in range(len(route.key_splines)) if route.key_points[i] == route.key_points[i + 1]
    )
    assert holds == sum(1 for wp in waypoints if wp.pause > 0)
    assert holds >= swim.MIN_HIDEOUTS


def test_animate_motion_values():
    """Geprüft wird der ausgegebene Text, denn den liest der Browser."""
    _, route = route_for("svg")
    tag = route.animate_motion()

    def attribute(name: str) -> list[str]:
        found = re.search(rf'{name}="([^"]+)"', tag)
        assert found is not None
        return found.group(1).split(";")

    times, points, splines = attribute("keyTimes"), attribute("keyPoints"), attribute("keySplines")
    assert len(times) == len(points) == len(splines) + 1
    for values in (times, points):
        assert values[0] == "0"
        assert values[-1] == "1"
    # Zusammenfallende keyTimes ließen den Koi springen
    assert all(float(a) < float(b) for a, b in itertools.pairwise(times))
    assert all(float(a) <= float(b) for a, b in itertools.pairwise(points))
    # Alle Kontrollwerte der keySplines müssen laut SVG-Spezifikation in [0, 1] liegen
    for spline in splines:
        assert all(0 <= float(v) <= 1 for v in spline.split())


@pytest.mark.parametrize("seed", SEEDS[:10])
def test_speed_has_no_jumps(seed: str):
    """Das Tempo läuft an jedem Wegpunkt ohne Sprung weiter, sonst ruckt der Koi.

    Tempo am Rand eines Intervalls = mittleres Tempo im Intervall × Steigung der keySpline
    dort. Ende des einen und Anfang des nächsten Intervalls müssen übereinstimmen.
    """
    waypoints, route = route_for(seed)
    total = sum(swim.bezier_length(seg) for seg in swim.segments(waypoints))
    edges: list[tuple[float, float]] = []  # (Tempo am Anfang, Tempo am Ende) je Intervall
    for i, spline in enumerate(route.key_splines):
        dist = (route.key_points[i + 1] - route.key_points[i]) * total
        if dist == 0:  # Pause
            edges.append((0.0, 0.0))
            continue
        mean = dist / ((route.key_times[i + 1] - route.key_times[i]) * route.duration)
        x1, y1, x2, y2 = (float(v) for v in spline.split())
        edges.append((mean * y1 / x1, mean * (1 - y2) / (1 - x2)))
    # Auch über den Schleifenanfang hinweg
    for (_, end), (start, _) in itertools.pairwise([*edges, edges[0]]):
        assert start == pytest.approx(end, rel=0.02, abs=0.05)


@pytest.mark.parametrize("seed", SEEDS[:20])
def test_u_turn_bends_towards_pond_center(seed: str):
    """Die Wende führt in den Teich hinein, nicht am Rand entlang nach außen."""
    waypoints, _ = route_for(seed)
    for i, wp in enumerate(waypoints):
        if wp.pause > 0 and wp.heading is not None:
            hx, hy = wp.point
            ex, ey = waypoints[i + 4].point  # Ende des Wendebogens
            cx, cy = swim.POND_CENTER
            assert (ex - hx) * (cx - hx) + (ey - hy) * (cy - hy) > 0


def test_ease_matches_speed_at_both_ends():
    """Steigung der keySpline am Anfang/Ende = Tempo dort im Verhältnis zum Mittel."""
    x1, y1, x2, y2 = (float(v) for v in swim._ease(0.0, 1.0).split())  # pyright: ignore[reportPrivateUsage]
    assert y1 / x1 == pytest.approx(0, abs=1e-6)  # aus dem Stand
    assert (1 - y2) / (1 - x2) == pytest.approx(2, abs=0.01)  # Endtempo = doppeltes Mittel


def test_faster_koi_same_route_shorter_travel_time():
    waypoints = swim.plan_waypoints(random.Random("tempo"))
    slow = swim.Route.build(waypoints, swim_seconds=30)
    fast = swim.Route.build(waypoints, swim_seconds=15)
    assert slow.path == fast.path
    # Nur die Fahrzeit halbiert sich; Pausen dauern gleich lang, egal wie flott der Koi ist.
    pauses = sum(wp.pause for wp in waypoints)
    assert fast.duration - pauses == pytest.approx((slow.duration - pauses) / 2)


def test_same_seed_same_route():
    assert route_for("gleich")[1] == route_for("gleich")[1]
    assert route_for("gleich")[1].path != route_for("anders")[1].path
