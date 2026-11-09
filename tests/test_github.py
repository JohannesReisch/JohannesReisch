"""Prüft Abfrage und Auswertung der GitHub-API mit erfundenen Daten, ohne Netzwerk."""

import io
import json
import urllib.error
from datetime import UTC, date, datetime
from email.message import Message
from typing import Any

import pytest

from koi_profil import github
from koi_profil.github import (
    GitHubError,
    TokenRejectedError,
    UserNotFoundError,
    parse_author_id,
    parse_profile,
    parse_repositories,
)

NOW = datetime(2026, 11, 8, 4, 15, tzinfo=UTC)
DAYS = [
    {"date": "2026-11-01", "contributionCount": 4},
    {"date": "2026-11-06", "contributionCount": 3},
    {"date": "2026-11-07", "contributionCount": 2},
]
PYTHON = ("Python", 10, "#3572A5")


def profile(user_id: str = "U_jo") -> dict[str, Any]:
    """Antwort auf PROFILE_QUERY."""
    calendar = {"weeks": [{"contributionDays": DAYS}]}
    return {
        "data": {
            "user": {"id": user_id, "contributionsCollection": {"contributionCalendar": calendar}}
        }
    }


def repo(recent: int, *langs: tuple[str, int, str | None], year: int | None = None) -> Any:
    """Ein Repo-Knoten: eigene Commits in beiden Zeitfenstern und Sprachen mit Codegröße."""
    return {
        "defaultBranchRef": {
            "target": {
                "recent": {"totalCount": recent},
                "year": {"totalCount": recent if year is None else year},
            }
        },
        "languages": {
            "totalSize": sum(size for _, size, _ in langs),
            "edges": [
                {"size": size, "node": {"name": name, "color": color}}
                for name, size, color in langs
            ],
        },
    }


def repos(*nodes: Any) -> dict[str, Any]:
    """Antwort auf REPOSITORY_QUERY."""
    return {"data": {"user": {"repositories": {"totalCount": len(nodes), "nodes": list(nodes)}}}}


def weights(langs: tuple[Any, ...]) -> dict[str, float]:
    return {lang.name: lang.weight for lang in langs}


# --- Schritt 1: Profil --------------------------------------------------------------------


def test_profile_reads_id_and_calendar():
    result = parse_profile(profile(), "jo")
    assert result.user_id == "U_jo"
    assert result.daily[date(2026, 11, 6)] == 3
    assert result.warnings == ()


def test_profile_without_id_is_unusable():
    with pytest.raises(GitHubError, match="unerwartetes Format"):
        parse_profile(profile(user_id=""), "jo")


def test_unexpected_format_is_reported():
    with pytest.raises(GitHubError, match="unerwartetes Format"):
        parse_profile({"data": {"user": {"id": "U"}}}, "jo")


def test_forbidden_without_data_rejects_token():
    payload = {
        "data": {"user": None},
        "errors": [{"type": "FORBIDDEN", "message": "Resource not accessible"}],
    }
    with pytest.raises(TokenRejectedError):
        parse_profile(payload, "jo")


def test_unknown_user():
    """So antwortet GitHub bei unbekanntem Login: user null und ein NOT_FOUND-Fehler."""
    payload = {
        "data": {"user": None},
        "errors": [{"type": "NOT_FOUND", "message": "Could not resolve to a User"}],
    }
    with pytest.raises(UserNotFoundError, match="Kein GitHub-Konto"):
        parse_profile(payload, "niemand")


def test_api_errors_are_reported():
    payload = {"data": None, "errors": [{"type": "RATE_LIMITED", "message": "rate limit"}]}
    with pytest.raises(GitHubError, match="rate limit"):
        parse_profile(payload, "jo")


# --- Schritt 2: weitere Autoren -----------------------------------------------------------


def test_author_id():
    assert parse_author_id({"data": {"user": {"id": "U_zweit"}}}, "zweit") == "U_zweit"


def test_unknown_author():
    with pytest.raises(UserNotFoundError):
        parse_author_id({"data": {"user": None}}, "tippfehler")


# --- Schritt 3: Sprachen aus den Repos ----------------------------------------------------


def test_languages_weighted_by_commits():
    """9 Commits in 90 % Python / 10 % HTML ergeben Python 8,1 und HTML 0,9."""
    payload = repos(
        repo(9, ("Python", 900, "#3572A5"), ("HTML", 100, "#e34c26")),
        repo(1, ("C#", 1000, "#178600")),
    )
    result = parse_repositories(payload, "jo")
    assert weights(result.recent) == pytest.approx({"Python": 8.1, "HTML": 0.9, "C#": 1})
    assert result.warnings == ()


def test_year_window_is_counted_separately():
    result = parse_repositories(repos(repo(0, PYTHON, year=4)), "jo")
    assert result.recent == ()
    assert weights(result.year) == {"Python": 4}


@pytest.mark.parametrize(
    "node",
    [
        repo(0, PYTHON, year=0),  # keine eigenen Commits
        repo(5),  # Repo ohne erkannte Sprache
        {**repo(5, PYTHON), "defaultBranchRef": None},  # leeres Repo ohne Hauptzweig
        {**repo(5, PYTHON), "defaultBranchRef": {"target": {}}},  # Zweig zeigt nicht auf Commit
        {**repo(5, PYTHON), "defaultBranchRef": {"target": {"recent": None, "year": None}}},
        None,  # Repo ohne Zugriff
    ],
)
def test_repos_without_usable_commits_are_skipped(node: Any):
    result = parse_repositories(repos(node), "jo")
    assert result.recent == ()
    assert result.year == ()


def test_invalid_color_is_not_embedded():
    result = parse_repositories(repos(repo(1, ("Evil", 10, 'red"/><script>'))), "jo")
    (lang,) = result.recent
    assert lang.color is None


def test_history_without_access_warns_with_hint():
    """Token sieht die Repos, darf aber die Historie nicht lesen: zeichnen, warnen, Hinweis."""
    payload = repos(repo(3, PYTHON), {**repo(0, PYTHON), "defaultBranchRef": None})
    payload["errors"] = [{"type": "FORBIDDEN", "message": "Resource not accessible"}]
    result = parse_repositories(payload, "jo")
    assert weights(result.recent) == {"Python": 3}
    assert "Resource not accessible" in result.warnings[0]
    assert "Contents: Read-only" in result.warnings[0]


def test_missing_repository_list_is_unusable():
    with pytest.raises(GitHubError, match="unerwartetes Format"):
        parse_repositories({"data": {"user": {}}}, "jo")


# --- Gesamtablauf -------------------------------------------------------------------------


def fake_api(
    monkeypatch: pytest.MonkeyPatch, by_author: dict[str, Any], known: dict[str, str]
) -> list[dict[str, Any]]:
    """Ersetzt _post: beantwortet die drei Abfragen anhand der Variablen."""
    seen: list[dict[str, Any]] = []

    def fake_post(payload: dict[str, Any], token: str) -> Any:
        variables = payload["variables"]
        seen.append({**variables, "query": payload["query"], "token": token})
        if payload["query"] == github.PROFILE_QUERY:
            return profile(user_id=known[variables["login"]])
        if payload["query"] == github.AUTHOR_QUERY:
            user_id = known.get(variables["login"])
            return {"data": {"user": {"id": user_id} if user_id else None}}
        return by_author[variables["author"]]

    monkeypatch.setattr(github, "_post", fake_post)
    return seen


def repo_calls(seen: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [call for call in seen if call["query"] == github.REPOSITORY_QUERY]


def test_commits_of_other_authors_count_too(monkeypatch: pytest.MonkeyPatch):
    """Zweitkonto committet JavaScript in die eigenen Repos: beide Konten zählen."""
    js = ("JavaScript", 10, "#f1e05a")
    seen = fake_api(
        monkeypatch,
        by_author={"U_jo": repos(repo(3, PYTHON)), "U_zweit": repos(repo(1, js))},
        known={"jo": "U_jo", "zweit": "U_zweit"},
    )
    result = github.fetch_koi_data("jo", "t", ["zweit"], now=NOW)
    shares = {s.name: s.share for s in result.data.languages}
    assert shares == pytest.approx({"Python": 0.75, "JavaScript": 0.25})
    # Die Repos gehören immer dem Hauptkonto, nur der Autor-Filter wechselt.
    assert [(c["login"], c["author"]) for c in repo_calls(seen)] == [
        ("jo", "U_jo"),
        ("jo", "U_zweit"),
    ]
    assert result.warnings == ()


def test_same_author_twice_counts_once(monkeypatch: pytest.MonkeyPatch):
    seen = fake_api(monkeypatch, {"U_jo": repos(repo(3, PYTHON))}, known={"jo": "U_jo"})
    github.fetch_koi_data("jo", "t", ["jo"], now=NOW)
    assert len(repo_calls(seen)) == 1


def test_unknown_extra_author_only_warns(monkeypatch: pytest.MonkeyPatch):
    fake_api(monkeypatch, {"U_jo": repos(repo(3, PYTHON))}, known={"jo": "U_jo"})
    result = github.fetch_koi_data("jo", "t", ["tippfehler"], now=NOW)
    assert [s.name for s in result.data.languages] == ["Python"]
    assert "tippfehler" in result.warnings[0]


def test_falls_back_to_year_when_no_recent_commits(monkeypatch: pytest.MonkeyPatch):
    fake_api(monkeypatch, {"U_jo": repos(repo(0, PYTHON, year=4))}, known={"jo": "U_jo"})
    result = github.fetch_koi_data("jo", "t", now=NOW)
    assert [s.name for s in result.data.languages] == ["Python"]


def test_recent_window_wins_over_year(monkeypatch: pytest.MonkeyPatch):
    """Viel JavaScript vor Monaten, wenig Python jetzt: Die Flecken zeigen das Jetzt."""
    js = ("JavaScript", 10, "#f1e05a")
    by_author = {"U_jo": repos(repo(2, PYTHON), repo(0, js, year=50))}
    fake_api(monkeypatch, by_author, known={"jo": "U_jo"})
    result = github.fetch_koi_data("jo", "t", now=NOW)
    assert [s.name for s in result.data.languages] == ["Python"]


def test_forbidden_repo_does_not_reject_token(monkeypatch: pytest.MonkeyPatch):
    """Kaputte Repo-Antwort mit FORBIDDEN: Fehler ja, aber kein Rückfall auf GITHUB_TOKEN.

    Ein TokenRejectedError ließe __main__ das gültige Profil des KOI_TOKEN verwerfen.
    """
    broken = repos(repo(1, PYTHON))
    broken["data"]["user"]["repositories"]["nodes"][0]["defaultBranchRef"]["target"]["recent"] = {
        "totalCount": None
    }
    broken["errors"] = [{"type": "FORBIDDEN", "message": "Resource not accessible"}]
    fake_api(monkeypatch, {"U_jo": broken}, known={"jo": "U_jo"})
    with pytest.raises(GitHubError) as caught:
        github.fetch_koi_data("jo", "t", now=NOW)
    assert not isinstance(caught.value, TokenRejectedError)


def test_failing_author_lookup_stops_the_run(monkeypatch: pytest.MonkeyPatch):
    """Nur ein unbekanntes Zweitkonto wird übergangen; andere API-Fehler brechen ab."""
    fake_api(monkeypatch, {"U_jo": repos()}, known={"jo": "U_jo"})
    real_post = github._post  # pyright: ignore[reportPrivateUsage] - Fake aus fake_api

    def post(payload: dict[str, Any], token: str) -> Any:
        if payload["query"] == github.AUTHOR_QUERY:
            return {"data": None, "errors": [{"type": "RATE_LIMITED", "message": "rate limit"}]}
        return real_post(payload, token)

    monkeypatch.setattr(github, "_post", post)
    with pytest.raises(GitHubError, match="rate limit"):
        github.fetch_koi_data("jo", "t", ["zweit"], now=NOW)


def test_more_repos_than_one_page_warns():
    payload = repos(repo(1, PYTHON))
    payload["data"]["user"]["repositories"]["totalCount"] = 150
    (warning,) = parse_repositories(payload, "jo").warnings
    assert "150" in warning


def test_time_windows_and_reference_day(monkeypatch: pytest.MonkeyPatch):
    """Nachtlauf um 04:15 UTC: Stichtag ist der abgeschlossene Vortag, nicht der leere Tag."""
    seen = fake_api(monkeypatch, {"U_jo": repos()}, known={"jo": "U_jo"})
    dummy = "erfunden"
    result = github.fetch_koi_data("jo", dummy, now=NOW)
    (call,) = repo_calls(seen)
    assert call["token"] is dummy
    assert call["recent"] == "2026-08-10T04:15:00+00:00"  # 90 Tage zurück
    assert call["year"] == "2025-11-08T04:15:00+00:00"  # 365 Tage zurück
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
