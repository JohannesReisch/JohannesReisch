from datetime import date, timedelta

import pytest

from koi_profil.model import (
    FALLBACK_COLOR,
    FULL_DAY_CONTRIBUTIONS,
    MAX_LANGUAGES,
    SCALE_MIN,
    KoiData,
    Language,
    activity_score,
    language_shares,
)

TODAY = date(2026, 11, 7)


def calendar(days: int, per_day: int = 5, *, gap: int = 0, weekdays_only: bool = False):
    """Kalender: `days` Tage Aktivität, die jüngsten `gap` Tage davon Pause."""
    result: dict[date, int] = {}
    for age in range(gap, gap + days):
        day = TODAY - timedelta(days=age)
        if not weekdays_only or day.weekday() < 5:
            result[day] = per_day
    return result


def koi(daily: dict[date, int], today: date = TODAY) -> KoiData:
    return KoiData.build("a", daily, [], today)


def test_activity_is_bounded():
    assert activity_score({}, TODAY) == 0
    assert activity_score(calendar(365), TODAY) == pytest.approx(1)


def test_busy_day_counts_no_more_than_full_day():
    full = activity_score({TODAY: FULL_DAY_CONTRIBUTIONS}, TODAY)
    huge = activity_score({TODAY: 500}, TODAY)
    assert full == huge


def test_regular_work_beats_one_big_day():
    """Regelmäßigkeit vor Masse: 20 kleine Tage schlagen einen Tag mit 200 Commits."""
    regular = koi(calendar(20, per_day=FULL_DAY_CONTRIBUTIONS))
    burst = koi({TODAY: 200})
    assert regular.growth > burst.growth


def test_new_account_starts_small_and_grows():
    first_day = koi({TODAY: 1})
    one_month = koi(calendar(30, weekdays_only=True))
    three_months = koi(calendar(90, weekdays_only=True))
    assert first_day.stage == "Frisch geschlüpft"
    assert first_day.scale < one_month.scale < three_months.scale


def test_regular_weekday_work_grows_to_adult():
    assert koi(calendar(365, weekdays_only=True)).stage == "Ausgewachsen"


def test_pause_shrinks_but_never_vanishes():
    active = koi(calendar(365, weekdays_only=True))
    vacation = koi(calendar(300, weekdays_only=True, gap=28))
    long_break = koi(calendar(200, weekdays_only=True, gap=165))
    assert active.scale > vacation.scale > long_break.scale > SCALE_MIN
    assert vacation.trend == -1


def test_trend_grows_when_starting_to_work():
    assert koi(calendar(10)).trend == 1
    assert koi({}).trend == 0


def test_contribution_counts():
    data = koi(calendar(400, per_day=2))
    assert data.week_contributions == 14
    assert data.month_contributions == 30 * 2


def test_active_week_swims_faster():
    assert koi(calendar(7)).swim_seconds < koi({}).swim_seconds


def test_language_shares_sum_to_one_and_merge_duplicates():
    shares = language_shares(
        [Language("Python", 3), Language("Go", 1, "#00ADD8"), Language("Python", 2, "#3572A5")]
    )
    assert sum(s.share for s in shares) == pytest.approx(1)
    assert shares[0].name == "Python"
    assert shares[0].color == "#3572A5"
    assert shares[0].share == pytest.approx(5 / 6)


def test_language_without_color_gets_fallback():
    (share,) = language_shares([Language("Brainfuck", 1)])
    assert share.color.startswith("#")


def test_tiny_and_surplus_languages_are_dropped():
    langs = [Language(f"L{i}", 100 - i) for i in range(MAX_LANGUAGES + 3)]
    langs.append(Language("Winzig", 0.5))
    shares = language_shares(langs)
    assert len(shares) == MAX_LANGUAGES
    assert "Winzig" not in {s.name for s in shares}


def test_no_languages():
    assert language_shares([]) == ()
    assert language_shares([Language("Python", 0)]) == ()


def test_steady_weekly_rhythm_holds_size():
    """Gleichmäßig Mo–Fr gearbeitet: kein Schrumpfen, egal welcher Werktag Stichtag ist."""
    monday = date(2026, 11, 9)
    daily = {
        monday - timedelta(days=age): 1
        for age in range(400)
        if (monday - timedelta(days=age)).weekday() < 5
    }
    for reference in (monday, monday - timedelta(days=3), monday - timedelta(days=1)):
        assert koi(daily, reference).trend == 0, reference


def test_tail_beats_faster_in_active_week():
    lazy, busy = koi({}).tail_beat_seconds, koi(calendar(7, per_day=10)).tail_beat_seconds
    assert lazy == pytest.approx(1.8)
    assert busy == pytest.approx(1.0)


def test_growth_comes_in_steps():
    """Gerundetes Wachstum: kleine tägliche Schwankungen erzeugen kein neues Bild."""
    growth = koi(calendar(40, weekdays_only=True)).growth
    assert growth == pytest.approx(round(growth, 2))


def test_invalid_color_falls_back():
    (share,) = language_shares([Language("X", 1, 'red"/><script>')])
    assert share.color == FALLBACK_COLOR
