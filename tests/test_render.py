import math
import os
import re
import subprocess
import sys
import xml.dom.minidom
from datetime import date

import pytest

from koi_profil.demo import SCENARIOS, demo_data
from koi_profil.model import KoiData, Language
from koi_profil.render import BODIES, SWIM_PATH, render_svg

TODAY = date(2026, 11, 7)


@pytest.mark.parametrize("body", sorted(BODIES))
@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_svg_is_valid_xml(body: str, scenario: str):
    xml.dom.minidom.parseString(render_svg(demo_data(scenario, TODAY), body=body))


def test_same_data_same_koi():
    assert render_svg(demo_data(today=TODAY)) == render_svg(demo_data(today=TODAY))


def test_names_are_escaped():
    data = KoiData.build("a<b", {TODAY: 1}, [Language("C&C++", 1, "#f34b7d")], TODAY)
    svg = render_svg(data)
    xml.dom.minidom.parseString(svg)
    assert "C&amp;C++" in svg


def test_unknown_body_is_rejected():
    with pytest.raises(ValueError, match="Unbekannter Körper"):
        render_svg(demo_data(today=TODAY), body="lila")


def test_legend_can_be_hidden():
    legend = "in den letzten 30 Tagen</text>"
    assert legend in render_svg(demo_data(today=TODAY))
    assert legend not in render_svg(demo_data(today=TODAY), label=False)


def test_legend_singular_and_hint_without_languages():
    svg = render_svg(KoiData.build("a", {TODAY: 1}, [], TODAY))
    assert ">1 Contribution in den letzten 30 Tagen<" in svg
    assert "Farben folgen" in svg


def test_unknown_demo_scenario_is_rejected():
    with pytest.raises(ValueError, match="Unbekanntes Szenario"):
        demo_data("gibtsnicht")


def test_quotes_in_login_keep_svg_valid():
    """Der Login steht auch im Attribut aria-label; ein " darf es nicht aufbrechen."""
    data = KoiData.build('a"b&c', {TODAY: 1}, [], TODAY)
    xml.dom.minidom.parseString(render_svg(data))


def test_every_reference_points_to_a_unique_id():
    """Ein Tippfehler in einer ID fällt sonst nicht auf: Der Browser lässt die Füllung weg."""
    svg = render_svg(demo_data("intensiv", TODAY))
    ids = re.findall(r'\bid="([^"]+)"', svg)
    assert len(ids) == len(set(ids))
    refs = set(re.findall(r"url\(#([^)]+)\)", svg)) | set(re.findall(r'href="#([^"]+)"', svg))
    assert refs <= set(ids)


def test_every_morph_animation_is_consistent():
    """Jede d-Animation im fertigen SVG: alle Schlüsselbilder mit gleicher Befehlsfolge."""
    svg = render_svg(demo_data("intensiv", TODAY))
    animations = re.findall(r'<animate attributeName="d"[^>]*values="([^"]+)"', svg)
    assert animations
    for values in animations:
        frames = values.split(";")
        assert frames[0] == frames[-1]
        assert len({re.sub(r"[^A-Za-z]", "", f) for f in frames}) == 1


def test_swim_path_has_no_kinks():
    """Glatte Bahn: An jedem Knoten zeigen ein- und auslaufende Tangente in dieselbe Richtung."""
    numbers = [float(n) for n in re.findall(r"-?\d+\.?\d*", SWIM_PATH)]
    start, segments = numbers[:2], numbers[2:]
    points = [segments[i : i + 6] for i in range(0, len(segments), 6)]
    for i, (_, _, c2x, c2y, px, py) in enumerate(points):
        nx, ny = points[(i + 1) % len(points)][:2]  # erster Kontrollpunkt des Folgesegments
        incoming = math.atan2(py - c2y, px - c2x)
        outgoing = math.atan2(ny - py, nx - px)
        assert abs(math.remainder(incoming - outgoing, 2 * math.pi)) < math.radians(0.5)
    assert (points[-1][4], points[-1][5]) == pytest.approx(tuple(start), abs=0.05)


def test_same_svg_across_processes():
    """Gleiche Daten, gleiches Bild, auch in einem neuen Prozess mit anderem Hash-Seed.

    Sonst würde der nächtliche Workflow jeden Tag ein unverändertes Bild committen.
    """
    code = (
        "from datetime import date;"
        "from koi_profil.demo import demo_data;"
        "from koi_profil.render import render_svg;"
        "import hashlib;"
        "print(hashlib.sha256(render_svg(demo_data('intensiv', date(2026, 11, 7))).encode())"
        ".hexdigest())"
    )
    digests = {
        subprocess.run(  # noqa: S603 - eigener Interpreter, fester Code, kein Fremdinput
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).stdout.strip()
        for seed in ("1", "2")
    }
    assert len(digests) == 1
