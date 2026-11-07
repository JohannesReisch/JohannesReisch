"""Erfundene Beispieldaten, um den Koi ohne Token und in jeder Lebensphase zu sehen."""

import random
from datetime import date, timedelta

from .model import WINDOW_DAYS, KoiData, Language

# Wahrscheinlichkeit für einen aktiven Werktag je Szenario.
SCENARIOS: dict[str, float] = {
    "neu": 0.0,
    "gelegentlich": 0.15,
    "regelmaessig": 0.45,
    "intensiv": 0.9,
}

DEMO_LANGUAGES = (
    Language("Python", 52, "#3572A5"),
    Language("C#", 30, "#178600"),
    Language("TypeScript", 14, "#3178c6"),
    Language("PowerShell", 4, "#012456"),
)


def demo_data(scenario: str = "regelmaessig", today: date | None = None) -> KoiData:
    """Koi-Daten für ein Szenario aus `SCENARIOS`; immer gleich für gleiche Eingaben."""
    if scenario not in SCENARIOS:
        raise ValueError(f"Unbekanntes Szenario '{scenario}'. Möglich: {', '.join(SCENARIOS)}")
    today = today or date.today()
    rng = random.Random(scenario)
    chance = SCENARIOS[scenario]
    daily: dict[date, int] = {}
    for age in range(WINDOW_DAYS):
        day = today - timedelta(days=age)
        if day.weekday() < 5 and rng.random() < chance:
            daily[day] = rng.randint(1, 8)
    if scenario == "neu":
        daily[today] = 1
    return KoiData.build(f"demo-{scenario}", daily, DEMO_LANGUAGES, today)
