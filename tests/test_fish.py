"""Geometrie des Koi: Formen müssen sich animieren lassen und plausibel aussehen."""

import math
import random
import re

import pytest

from koi_profil import fish


def commands(path: str) -> str:
    """Befehlsfolge eines Pfads ohne Zahlen, z. B. 'MCCCZ'."""
    return "".join(re.findall(r"[A-Za-z]", path))


SHAPES = {
    "body": fish.body_outline(),
    "tail": fish.tail_outline(),
    "ridge": fish.dorsal_ridge(),
    "pelvic": fish.pelvic_fin(1),
    "spot": fish.spot_blob(random.Random(1), 10),
}


@pytest.mark.parametrize("name", list(SHAPES))
def test_keyframes_share_command_sequence(name: str):
    """SVG blendet nur zwischen Pfaden mit gleicher Befehlsfolge über, sonst springt es."""
    frames = fish.closed_keyframes(SHAPES[name])
    assert len(frames) == fish.KEYFRAMES
    assert len({commands(f) for f in frames}) == 1


def test_ray_keyframes_share_command_sequence():
    frames = fish.ray_keyframes(fish.tail_rays())
    assert len({commands(f) for f in frames}) == 1


def test_body_is_widest_at_shoulders_and_slim_at_peduncle():
    assert fish.half_width(fish.WIDEST_AT) == pytest.approx(fish.MAX_HALF_WIDTH)
    assert fish.half_width(1) == pytest.approx(fish.PEDUNCLE_HALF_WIDTH)
    assert fish.half_width(0.1) < fish.MAX_HALF_WIDTH


def test_wave_grows_towards_tail():
    """Der Kopf bleibt fast ruhig, der Schwanz schwingt am stärksten."""
    head = max(abs(fish.wave(0, p)) for p in fish.phases())
    tail = max(abs(fish.wave(1, p)) for p in fish.phases())
    assert head < 1 < tail


def test_animation_loops_seamlessly():
    frames = ["M0 0Z", "M1 1Z"]
    values = re.search(r'values="([^"]*)"', fish.animate_d(frames, 1.0))
    assert values is not None
    parts = values.group(1).split(";")
    assert parts[0] == parts[-1]


def test_spot_stays_near_body():
    rng = random.Random(7)
    for _ in range(50):
        for x, y in fish.spot_blob(rng, 12):
            assert fish.PEDUNCLE_X - 30 < x < fish.HEAD_X + 30
            assert abs(y) < fish.MAX_HALF_WIDTH + 20


def test_keyframes_cover_exactly_one_wave():
    """Das Bild nach einer vollen Welle ist das erste, und es kommt nicht doppelt vor.

    Sonst stockt (Doppelbild) oder springt (fehlendes Stück) der Schwanzschlag.
    """
    points = fish.body_outline()
    frames = fish.closed_keyframes(points)
    after_full_wave = fish.smooth_closed(fish.displaced(points, 2 * math.pi))
    assert after_full_wave == frames[0]
    assert frames[0] not in frames[1:]
