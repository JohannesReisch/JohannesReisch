"""Prüft Abfrage und Auswertung der GitHub-API mit erfundenen Daten, ohne Netzwerk."""

import io
import json
import urllib.error
from datetime import UTC, date, datetime
from email.message import Message
from typing import Any

import pytest

from koi_profil import github
from koi_profil.github import GitHubError, TokenRejectedError, parse_response

TODAY = date(2026, 11, 7)


def repo(commits: int, *langs: tuple[str, int, str | None]) -> dict[str, Any]:
    return {
        "contributions": {"totalCount": commits},
        "repository": {
            "languages": {
                "totalSize": sum(size for _, size, _ in langs),
                "edges": [
                    {"size": size, "node": {"name": name, "color": color}}
                    for name, size, color in langs
                ],
            }
        },
    }


def response(recent: list[Any], year: list[Any] | None = None) -> dict[str, Any]:
    days = [
        {"date": "2026-11-06", "contributionCount": 3},
        {"date": "2026-11-07", "contributionCount": 2},
    ]
    return {
        "data": {
            "user": {
                "year": {
                    "contributionCalendar": {"weeks": [{"contributionDays": days}]},
                    "commitContributionsByRepository": year or [],
                },
                "recent": {"commitContributionsByRepository": recent},
            }
        }
    }


# --- Auswertung der Antwort -------------------------------------------------------------


def test_languages_weighted_by_commits():
    payload = response(
        [
            repo(9, ("Python", 900, "#3572A5"), ("HTML", 100, "#e34c26")),
            repo(1, ("C#", 1000, "#178600")),
        ]
    )
    result = parse_response(payload, "jo", TODAY)
    shares = {s.name: s.share for s in result.data.languages}
    assert shares["Python"] == pytest.approx(8.1 / 10)
    assert shares["C#"] == pytest.approx(1 / 10)
    assert result.data.week_contributions == 5
    assert result.warnings == ()


def test_falls_back_to_year_when_no_recent_commits():
    payload = response([], year=[repo(4, ("Python", 10, "#3572A5"))])
    assert [s.name for s in parse_response(payload, "jo", TODAY).data.languages] == ["Python"]


def test_empty_repo_is_ignored():
    payload = response([repo(5), repo(0, ("Go", 10, None))])
    assert parse_response(payload, "jo", TODAY).data.languages == ()


def test_invalid_color_is_not_embedded():
    payload = response([repo(1, ("Evil", 10, 'red"/><script>'))])
    (lang,) = parse_response(payload, "jo", TODAY).data.languages
    assert lang.color.startswith("#")
    assert "script" not in lang.color


def test_partial_error_still_draws_and_warns():
    """Token ohne Zugriff auf ein Repo: GitHub liefert null plus Fehler, Rest ist brauchbar."""
    payload = response([repo(3, ("Python", 10, "#3572A5")), {"repository": None}])
    payload["errors"] = [{"type": "FORBIDDEN", "message": "Resource not accessible"}]
    result = parse_response(payload, "jo", TODAY)
    assert [s.name for s in result.data.languages] == ["Python"]
    assert "Resource not accessible" in result.warnings[0]


def test_forbidden_without_data_rejects_token():
    payload = {
        "data": {"user": None},
        "errors": [{"type": "FORBIDDEN", "message": "Resource not accessible"}],
    }
    with pytest.raises(TokenRejectedError):
        parse_response(payload, "jo", TODAY)


def test_unknown_user():
    """So antwortet GitHub bei unbekanntem Login: user null und ein NOT_FOUND-Fehler."""
    payload = {
        "data": {"user": None},
        "errors": [{"type": "NOT_FOUND", "message": "Could not resolve to a User"}],
    }
    with pytest.raises(GitHubError, match="Kein GitHub-Konto"):
        parse_response(payload, "niemand", TODAY)


def test_api_errors_are_reported():
    payload = {"data": None, "errors": [{"type": "RATE_LIMITED", "message": "rate limit"}]}
    with pytest.raises(GitHubError, match="rate limit"):
        parse_response(payload, "jo", TODAY)


def test_unexpected_format_is_reported():
    with pytest.raises(GitHubError, match="unerwartetes Format"):
        parse_response({"data": {"user": {"year": {}}}}, "jo", TODAY)


def test_reference_day_is_yesterday(monkeypatch: pytest.MonkeyPatch):
    """Nachtlauf um 04:15 UTC: Stichtag ist der abgeschlossene Vortag, nicht der leere Tag."""
    seen: dict[str, Any] = {}

    def fake_post(payload: dict[str, Any], token: str) -> dict[str, Any]:
        seen.update(payload=payload, token=token)
        result = response([repo(1, ("Python", 1, "#3572A5"))])
        days = result["data"]["user"]["year"]["contributionCalendar"]["weeks"][0]
        days["contributionDays"].append({"date": "2026-11-01", "contributionCount": 4})
        return result

    monkeypatch.setattr(github, "_post", fake_post)
    dummy = "erfunden"
    result = github.fetch_koi_data("jo", dummy, now=datetime(2026, 11, 8, 4, 15, tzinfo=UTC))
    assert seen["token"] is dummy
    assert seen["payload"]["variables"]["login"] == "jo"
    # Woche 01.–07.11. (Stichtag 07.) = 4 + 3 + 2; mit Stichtag 08. fiele der 01. heraus.
    assert result.data.week_contributions == 9


# --- HTTP-Verhalten ----------------------------------------------------------------------


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(github.API_URL, code, "Fehler", Message(), io.BytesIO())


def fake_urlopen(*outcomes: Exception | dict[str, Any]):
    """Liefert der Reihe nach die Ergebnisse; Ausnahmen werden geworfen."""
    queue = list(outcomes)
    calls: list[int] = []

    def urlopen(request: object, timeout: float) -> io.BytesIO:
        calls.append(1)
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return io.BytesIO(json.dumps(outcome).encode())

    return urlopen, calls


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    def sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(github.time, "sleep", sleep)


@pytest.mark.parametrize("code", [401, 403])
def test_rejected_token_raises_without_retry(monkeypatch: pytest.MonkeyPatch, code: int):
    urlopen, calls = fake_urlopen(http_error(code))
    monkeypatch.setattr(github.urllib.request, "urlopen", urlopen)
    with pytest.raises(TokenRejectedError):
        github._post({}, "x")  # pyright: ignore[reportPrivateUsage] - Kern des Rückfalls
    assert len(calls) == 1


def test_server_error_and_connection_reset_are_retried(monkeypatch: pytest.MonkeyPatch):
    urlopen, calls = fake_urlopen(http_error(502), ConnectionResetError(), {"data": 1})
    monkeypatch.setattr(github.urllib.request, "urlopen", urlopen)
    assert github._post({}, "x") == {"data": 1}  # pyright: ignore[reportPrivateUsage]
    assert len(calls) == 3


def test_gives_up_after_retries(monkeypatch: pytest.MonkeyPatch):
    urlopen, _ = fake_urlopen(*[TimeoutError()] * github.RETRIES)
    monkeypatch.setattr(github.urllib.request, "urlopen", urlopen)
    with pytest.raises(GitHubError, match="nicht erreichbar"):
        github._post({}, "x")  # pyright: ignore[reportPrivateUsage]


def test_client_error_is_not_retried(monkeypatch: pytest.MonkeyPatch):
    urlopen, calls = fake_urlopen(http_error(422))
    monkeypatch.setattr(github.urllib.request, "urlopen", urlopen)
    with pytest.raises(GitHubError, match="HTTP 422"):
        github._post({}, "x")  # pyright: ignore[reportPrivateUsage]
    assert len(calls) == 1
