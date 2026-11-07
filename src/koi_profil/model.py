"""Übersetzt GitHub-Zahlen in Eigenschaften des Koi. Keine Netzwerkzugriffe hier.

Grundidee: Der Koi spiegelt, wie *regelmäßig* in letzter Zeit gearbeitet wurde, nicht
die Lebenssumme. Jeder Tag der letzten 365 zählt, jüngere Tage stärker als ältere
(Halbwertszeit). Wer regelmäßig arbeitet, hat einen großen Koi; wer pausiert, sieht ihn
langsam schrumpfen, nie verschwinden.
"""

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

# Betrachtungszeitraum. Mehr liefert der Contribution-Kalender von GitHub nicht.
WINDOW_DAYS = 365
# Nach so vielen Tagen zählt ein Tag nur noch halb so viel. Kleiner = reagiert schneller.
HALF_LIFE_DAYS = 30
# Zeitraum der Zahl in der Beschriftung. Passt zur Halbwertszeit: Das ist die Arbeit,
# die die Größe des Koi gerade prägt.
MONTH_DAYS = 30
# Ab so vielen Contributions gilt ein Tag als voll aktiv. Mehr bringt nichts, damit ein
# einzelner Großkampftag nicht eine Woche Pause aufwiegt: Regelmäßigkeit vor Masse.
FULL_DAY_CONTRIBUTIONS = 3
# Gewichtete Quote voll aktiver Tage, ab der der Koi ausgewachsen ist.
# 0.43 ≈ an drei von sieben Tagen je mindestens drei Contributions.
ADULT_ACTIVITY = 3 / 7
# Ab dieser Änderung der Wachstumsstufe binnen 7 Tagen gilt der Koi als wachsend/schrumpfend.
TREND_THRESHOLD = 0.01

# So viele Sprachen bekommen eigene Flecken.
MAX_LANGUAGES = 5
# Sprachen unter diesem Anteil fallen weg, sonst bekäme jede Randnotiz einen ganzen Fleck.
MIN_LANGUAGE_SHARE = 0.05
FALLBACK_COLOR = "#8b8b8b"
# Nur solche Farben gelangen ins SVG-Attribut, gleich aus welcher Datenquelle.
_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
# Wachstum wird in diesen Stufen ausgegeben. Feiner sieht niemand; gröber spart
# tägliche Commits, wenn sich der Koi nur unmerklich verändert.
GROWTH_STEP = 0.01

# Zeichengröße: frisch geschlüpft bzw. ausgewachsen (1 = Zeichnung in Originalgröße).
SCALE_MIN = 0.28
SCALE_MAX = 0.78

# Lebensphasen nach Wachstum (0..1), aufsteigend; die erste passende Obergrenze gilt.
STAGES: tuple[tuple[float, str], ...] = (
    (0.25, "Frisch geschlüpft"),
    (0.55, "Jungkoi"),
    (0.85, "Halbstark"),
    (math.inf, "Ausgewachsen"),
)


@dataclass(frozen=True)
class Language:
    """Rohgewicht einer Sprache, z. B. Commits × Code-Anteil im Repository."""

    name: str
    weight: float
    color: str | None = None


@dataclass(frozen=True)
class LanguageShare:
    """Anteil einer Sprache an den Flecken (0..1, alle zusammen 1)."""

    name: str
    share: float
    color: str


def activity_score(daily: Mapping[date, int], today: date) -> float:
    """Gewichtete Quote voll aktiver Tage im Zeitfenster vor `today` (0..1).

    Tage vor dem Kontostart fehlen im Kalender und zählen als inaktiv. Ein neues Konto
    startet deshalb klein und wächst über Wochen, statt mit dem ersten Commit voll da zu sein.

    Args:
        daily: Contributions je Kalendertag.
        today: Stichtag (zählt mit Gewicht 1).

    Returns:
        0 = nichts getan, 1 = jeden Tag voll aktiv.
    """
    decay = 0.5 ** (1 / HALF_LIFE_DAYS)
    weighted = 0.0
    total_weight = 0.0
    for age in range(WINDOW_DAYS):
        weight = decay**age
        count = daily.get(today - timedelta(days=age), 0)
        weighted += weight * min(max(count, 0), FULL_DAY_CONTRIBUTIONS) / FULL_DAY_CONTRIBUTIONS
        total_weight += weight
    return weighted / total_weight


def is_hex_color(value: object) -> bool:
    """True für Farben der Form #rrggbb."""
    return isinstance(value, str) and _HEX_COLOR.fullmatch(value) is not None


def language_shares(languages: Sequence[Language]) -> tuple[LanguageShare, ...]:
    """Fasst Rohgewichte zu Anteilen zusammen: größte zuerst, Kleinkram raus, Summe 1."""
    merged: dict[str, Language] = {}
    for lang in languages:
        if lang.weight <= 0:
            continue
        known = merged.get(lang.name)
        weight = lang.weight + (known.weight if known else 0)
        own = lang.color if is_hex_color(lang.color) else None
        color = own or (known.color if known else None)
        merged[lang.name] = Language(lang.name, weight, color)

    ranked = sorted(merged.values(), key=lambda lang: lang.weight, reverse=True)[:MAX_LANGUAGES]
    total = sum(lang.weight for lang in ranked)
    kept = [lang for lang in ranked if total and lang.weight / total >= MIN_LANGUAGE_SHARE]
    kept_total = sum(lang.weight for lang in kept)
    return tuple(
        LanguageShare(lang.name, lang.weight / kept_total, lang.color or FALLBACK_COLOR)
        for lang in kept
    )


@dataclass(frozen=True)
class KoiData:
    """Alles, was der Renderer über den Koi wissen muss."""

    login: str
    month_contributions: int
    week_contributions: int
    activity: float
    activity_week_ago: float
    languages: tuple[LanguageShare, ...] = ()

    @classmethod
    def build(
        cls,
        login: str,
        daily: Mapping[date, int],
        languages: Sequence[Language],
        today: date,
    ) -> "KoiData":
        """Rechnet Kalender und Sprachgewichte in Koi-Kennzahlen um."""
        week_start = today - timedelta(days=6)
        month_start = today - timedelta(days=MONTH_DAYS - 1)
        return cls(
            login=login,
            month_contributions=sum(
                max(c, 0) for d, c in daily.items() if month_start <= d <= today
            ),
            week_contributions=sum(max(c, 0) for d, c in daily.items() if week_start <= d <= today),
            activity=activity_score(daily, today),
            activity_week_ago=activity_score(daily, today - timedelta(days=7)),
            languages=language_shares(languages),
        )

    @staticmethod
    def _growth_of(activity: float) -> float:
        # Wurzelkurve: Die ersten aktiven Wochen zeigen sichtbares Wachstum,
        # der Weg zum ausgewachsenen Koi wird dann langsamer.
        return min(1.0, math.sqrt(activity / ADULT_ACTIVITY))

    @property
    def growth(self) -> float:
        """0 = winzig, 1 = ausgewachsen, in Stufen von `GROWTH_STEP`."""
        return round(self._growth_of(self.activity) / GROWTH_STEP) * GROWTH_STEP

    @property
    def trend(self) -> int:
        """+1 wächst, -1 schrumpft, 0 hält die Größe (Vergleich mit vor 7 Tagen)."""
        # Ungerundet vergleichen, damit die Stufen den Trend nicht verfälschen.
        delta = self._growth_of(self.activity) - self._growth_of(self.activity_week_ago)
        if delta > TREND_THRESHOLD:
            return 1
        if delta < -TREND_THRESHOLD:
            return -1
        return 0

    @property
    def stage(self) -> str:
        """Lebensphase als Text für die Beschriftung."""
        return next(name for limit, name in STAGES if self.growth < limit)

    @property
    def scale(self) -> float:
        """Zeichengröße relativ zum ausgewachsenen Koi (nie ganz verschwunden)."""
        return round(SCALE_MIN + (SCALE_MAX - SCALE_MIN) * self.growth, 4)

    @property
    def spot_opacity(self) -> float:
        """Junge Koi haben blasse Flecken, die mit dem Wachstum kräftiger werden."""
        return 0.45 + 0.55 * self.growth

    @property
    def swim_seconds(self) -> float:
        """Dauer einer Runde durch den Teich. Aktive Woche = schneller Koi."""
        return 34.0 - 21.0 * self._busyness

    @property
    def tail_beat_seconds(self) -> float:
        """Dauer eines Flossenschlags; schnelle Koi schlagen schneller."""
        return 1.8 - 0.8 * self._busyness

    @property
    def _busyness(self) -> float:
        # 0 = keine Contribution in der Woche, 1 = 15 oder mehr.
        busy_week = 15
        return min(self.week_contributions, busy_week) / busy_week
