"""Holt Profildaten über die GitHub-GraphQL-API.

Nur Standardbibliothek, damit der Workflow nichts installieren muss. Die GraphQL-API
verlangt immer einen Token. Was er sieht, bestimmt das Ergebnis:

- eigener Token (Secret `KOI_TOKEN`): auch private Repos, auf die er Zugriff hat,
  mit ihren Sprachen.
- eingebauter `GITHUB_TOKEN` des Workflows: öffentliche Repos; private Arbeit erscheint
  nur als Anzahl im Kalender, wenn im Profil „Private contributions“ eingeschaltet ist.

Die Antwort wird vollständig geprüft (`parse_response`), bevor etwas gezeichnet wird.
Teilfehler (z. B. ein Repo, auf das der Token keinen Zugriff hat) halten den Koi nicht
an: Er wird mit den übrigen Daten gezeichnet, der Fehler erscheint als Warnung.
"""

import http.client
import json
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from .model import KoiData, Language, is_hex_color

API_URL = "https://api.github.com/graphql"
# Sprachen kommen aus den Commits dieses Zeitraums ("woran arbeite ich gerade").
LANGUAGE_WINDOW_DAYS = 90
TIMEOUT_SECONDS = 30
RETRIES = 3

_REPO_FIELDS = """
  contributions { totalCount }
  repository {
    languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
      totalSize
      edges { size node { name color } }
    }
  }
"""

QUERY = f"""
query($login: String!, $from: DateTime!, $to: DateTime!) {{
  user(login: $login) {{
    year: contributionsCollection {{
      contributionCalendar {{ weeks {{ contributionDays {{ date contributionCount }} }} }}
      commitContributionsByRepository(maxRepositories: 100) {{ {_REPO_FIELDS} }}
    }}
    recent: contributionsCollection(from: $from, to: $to) {{
      commitContributionsByRepository(maxRepositories: 100) {{ {_REPO_FIELDS} }}
    }}
  }}
}}
"""


class GitHubError(RuntimeError):
    """Abfrage gescheitert; die Meldung sagt, was zu tun ist."""


class TokenRejectedError(GitHubError):
    """Token ungültig, abgelaufen oder ohne Zugriff; ein anderer Token kann helfen."""


@dataclass(frozen=True)
class FetchResult:
    """Koi-Daten plus Hinweise auf Teilfehler, die den Lauf nicht verhindert haben."""

    data: KoiData
    warnings: tuple[str, ...] = ()


# JSON von außen ist untypisiert. Any bleibt auf dieses Modul beschränkt; parse_response
# prüft jedes Feld, bevor es in typisierte Modelle wandert.
type Json = Any


def _post(payload: Mapping[str, object], token: str) -> Json:
    """Schickt eine GraphQL-Abfrage; wiederholt bei Netz- und Serverfehlern."""
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "github-koi",
        },
    )
    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
                return json.load(response)
        except urllib.error.HTTPError as err:
            # 401 = ungültig/abgelaufen, 403 = ohne Recht (z. B. von der Org nicht freigegeben)
            if err.code in (401, 403):
                raise TokenRejectedError(f"Token abgelehnt (HTTP {err.code}).") from err
            if err.code < 500 or attempt == RETRIES:
                raise GitHubError(
                    f"GitHub-API antwortet mit HTTP {err.code}: {err.reason}"
                ) from err
        # OSError deckt Verbindungsabbruch und Timeout ab, HTTPException abgerissene
        # Antworten, ValueError kaputtes JSON. Alles vorübergehend: noch einmal versuchen.
        except (OSError, http.client.HTTPException, ValueError) as err:
            if attempt == RETRIES:
                raise GitHubError(f"GitHub-API nicht erreichbar: {err!r}") from err
        time.sleep(2**attempt)
    raise AssertionError("unerreichbar")  # pragma: no cover


def _color(value: Json) -> str | None:
    """Übernimmt nur echte Hex-Farben, damit nichts Fremdes ins SVG-Attribut gelangt."""
    if is_hex_color(value):
        return cast(str, value)
    return None


def _get(obj: Json, key: str) -> Json:
    """Feld eines JSON-Objekts, oder None, wenn das Objekt selbst `null` ist."""
    return None if obj is None else obj.get(key)


def _languages(collection: Json) -> list[Language]:
    """Gewichtet Sprachen nach Commits: Commits im Repo × Anteil der Sprache am Code.

    Repos ohne Zugriff liefert GitHub als `null`; sie werden übersprungen.
    """
    result: list[Language] = []
    entries: list[Json] = collection.get("commitContributionsByRepository") or []
    for entry in entries:
        langs = _get(_get(entry, "repository"), "languages")
        if not langs:
            continue
        commits = int(entry["contributions"]["totalCount"])
        total = int(langs["totalSize"])
        if commits <= 0 or total <= 0:
            continue
        for edge in langs["edges"]:
            node = edge["node"]
            share = int(edge["size"]) / total
            result.append(Language(str(node["name"]), commits * share, _color(node.get("color"))))
    return result


def _object(value: Json, what: str) -> dict[str, Json]:
    """Stellt sicher, dass `value` ein JSON-Objekt ist."""
    if not isinstance(value, dict):
        raise GitHubError(f"Unerwartete Antwort der GitHub-API: {what} fehlt.")
    return cast(dict[str, Json], value)


def parse_response(payload: Json, login: str, today: date) -> FetchResult:
    """Prüft die API-Antwort und baut daraus die Koi-Daten.

    GraphQL meldet viele Probleme mit HTTP 200 und einer Liste `errors` neben Teildaten.
    Reichen die Daten, wird gezeichnet und gewarnt; sonst entscheidet der Fehlertyp.

    Args:
        payload: geparstes JSON der API.
        login: abgefragter Benutzername (für Meldungen und Fleckenlage).
        today: Stichtag der Auswertung.

    Raises:
        TokenRejectedError: wenn der Token keinen Zugriff hat (FORBIDDEN).
        GitHubError: wenn das Konto fehlt, die API sonst scheitert oder Felder fehlen.
    """
    body = _object(payload, "JSON-Objekt")
    raw_errors: list[Json] = body.get("errors") or []
    errors = [_object(e, "Fehlereintrag") for e in raw_errors]
    messages = "; ".join(str(e.get("message", "?")) for e in errors)
    types: set[Json] = {e.get("type") for e in errors}

    user: Json = _object(body.get("data") or {}, "data").get("user")
    if user is None:
        if "FORBIDDEN" in types:
            raise TokenRejectedError(f"Token ohne Zugriff: {messages}")
        if errors and "NOT_FOUND" not in types:
            raise GitHubError(f"GitHub-API meldet: {messages}")
        raise GitHubError(f"Kein GitHub-Konto mit dem Namen '{login}' gefunden.")

    try:
        daily = {
            date.fromisoformat(day["date"]): int(day["contributionCount"])
            for week in user["year"]["contributionCalendar"]["weeks"]
            for day in week["contributionDays"]
        }
        languages = _languages(user["recent"])
        if not languages:
            # In den letzten 90 Tagen keine Commits: auf das ganze Jahr ausweichen,
            # damit der Koi nach einer Pause nicht sofort farblos wird.
            languages = _languages(user["year"])
    except (KeyError, TypeError, ValueError, AttributeError) as err:
        if "FORBIDDEN" in types:
            raise TokenRejectedError(f"Token ohne Zugriff: {messages}") from err
        detail = f"GitHub-API meldet: {messages}" if errors else f"unerwartetes Format: {err!r}"
        raise GitHubError(f"Antwort unbrauchbar, {detail}") from err

    warnings = (
        (f"Teilfehler der GitHub-API, Koi trotzdem gezeichnet: {messages}",) if errors else ()
    )
    return FetchResult(KoiData.build(login, daily, languages, today), warnings)


def fetch_koi_data(login: str, token: str, now: datetime | None = None) -> FetchResult:
    """Fragt die GitHub-API ab und liefert die Koi-Daten für `login`.

    Stichtag ist der letzte *abgeschlossene* Tag (UTC). Der Nachtlauf startet kurz nach
    Mitternacht; der angebrochene Tag wäre fast leer und ließe den Koi scheinbar schrumpfen.
    """
    now = now or datetime.now(UTC)
    variables = {
        "login": login,
        "from": (now - timedelta(days=LANGUAGE_WINDOW_DAYS)).isoformat(timespec="seconds"),
        "to": now.isoformat(timespec="seconds"),
    }
    payload = _post({"query": QUERY, "variables": variables}, token)
    return parse_response(payload, login, (now - timedelta(days=1)).date())
