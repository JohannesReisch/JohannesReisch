import os
import re
import subprocess
import sys
import xml.dom.minidom
from datetime import date, timedelta

import pytest

from koi_profil.demo import SCENARIOS, demo_data
from koi_profil.model import KoiData, Language
from koi_profil.render import BODIES, render_svg

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


def test_koi_and_shadow_share_the_route():
    """Schatten und Koi müssen dieselbe Bewegung machen, sonst trennen sie sich."""
    svg = render_svg(demo_data("intensiv", TODAY))
    # Nur die Route des Koi hat einen Zeitplan (keyTimes); das Blütenblatt treibt gleichmäßig.
    motions = re.findall(r"<animateMotion[^>]*keyTimes[^>]*>", svg)
    assert len(motions) == 2
    assert motions[0] == motions[1]


def test_busy_week_means_faster_koi_on_same_route():
    """Mehr Contributions in der Woche: gleiche Route, kürzere Dauer."""
    lazy = KoiData.build("x", {TODAY: 1}, [], TODAY)
    busy = KoiData.build("x", {TODAY - timedelta(days=d): 5 for d in range(7)}, [], TODAY)

    def motion(data: KoiData) -> tuple[str, float]:
        tag = re.search(r'<animateMotion dur="([\d.]+)s"[^>]*path="([^"]+)"', render_svg(data))
        assert tag is not None
        return tag.group(2), float(tag.group(1))

    (lazy_path, lazy_dur), (busy_path, busy_dur) = motion(lazy), motion(busy)
    assert lazy_path == busy_path
    assert busy_dur < lazy_dur
