"""Holt Profildaten über die GitHub-GraphQL-API.

Nur Standardbibliothek, damit der Workflow nichts installieren muss. Die GraphQL-API
verlangt immer einen Token. Was er sieht, bestimmt das Ergebnis:

- eigener Token (Secret `KOI_TOKEN`): auch private Repos, auf die er Zugriff hat,
  mit ihren Sprachen. Für die Commit-Historie braucht er *Contents: Read-only*.
- eingebauter `GITHUB_TOKEN` des Workflows: öffentliche Repos; private Arbeit erscheint
  nur als Anzahl im Kalender, wenn im Profil „Private contributions“ eingeschaltet ist.

Ablauf in drei Schritten:

1. **Profil:** Konto-ID und Contribution-Kalender (bestimmt die Größe).
2. **Autoren:** Konto-IDs weiterer eigener Konten (z. B. ein Zweitkonto, mit dem
   ebenfalls in diesen Repos committet wird).
3. **Repos:** je Autor die Commits auf dem Hauptzweig jedes Repos, dazu dessen Sprachen.

Warum nicht GitHubs fertige Liste `commitContributionsByRepository`? Sie verschweigt
private Repos selbst gegenüber dem Kontoinhaber (nur als anonyme Zahl
`restrictedContributionsCount`). Die Historie je Repo liefert dagegen echte Zahlen.

Jede Antwort wird vollständig geprüft, bevor etwas gezeichnet wird. Teilfehler (z. B.
ein Repo, auf das der Token keinen Zugriff hat) halten den Koi nicht an: Er wird mit den
übrigen Daten gezeichnet, der Fehler erscheint als Warnung.
"""

import http.client
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from .model import KoiData, Language, is_hex_color

API_URL = "https://api.github.com/graphql"
# Sprachen kommen aus den Commits dieses Zeitraums ("woran arbeite ich gerade").
LANGUAGE_WINDOW_DAYS = 90
# Rückfall, wenn im Sprachzeitraum nichts committet wurde: das ganze Jahr.
YEAR_DAYS = 365
TIMEOUT_SECONDS = 30
RETRIES = 3
# Höchstzahl Repos je Abfrage; mehr erlaubt GitHub ohne Blättern nicht.
MAX_REPOSITORIES = 100
# GitHub-Benutzernamen: Buchstaben, Ziffern, Bindestrich, höchstens 39 Zeichen.
LOGIN_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")

PROFILE_QUERY = """
query($login: String!) {
  user(login: $login) {
    id
    contributionsCollection {
      contributionCalendar { weeks { contributionDays { date contributionCount } } }
    }
  }
}
"""

AUTHOR_QUERY = """
query($login: String!) {
  user(login: $login) { id }
}
"""

# Nur eigene Repos (OWNER): Fremde Org-Repos mit vielen Pushes könnten die eigenen sonst
# aus den ersten 100 verdrängen, und private fremde Repos sieht der KOI_TOKEN ohnehin nicht.
# Nach letztem Push sortiert, die aktiven stehen vorn; mehr als 100 meldet eine Warnung.
# Forks fehlen, weil GitHub Commits in Forks ebenfalls nicht als Contribution zählt.
# Zwei Zeitfenster in einer Abfrage (GraphQL-Alias), damit der Jahres-Rückfall nichts kostet.
REPOSITORY_QUERY = """
query(
  $login: String!, $author: ID!, $recent: GitTimestamp!, $year: GitTimestamp!, $first: Int!
) {
  user(login: $login) {
    repositories(
      first: $first
      isFork: false
      ownerAffiliations: [OWNER]
      orderBy: {field: PUSHED_AT, direction: DESC}
    ) {
      totalCount
      nodes {
        defaultBranchRef {
          target {
            ... on Commit {
              recent: history(since: $recent, author: {id: $author}) { totalCount }
              year: history(since: $year, author: {id: $author}) { totalCount }
            }
          }
        }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          totalSize
          edges { size node { name color } }
        }
      }
    }
  }
}
"""

# Hinweis, wenn der Token Repos sieht, aber deren Historie nicht lesen darf.
CONTENTS_HINT = "Fehlt dem Token die Berechtigung „Contents: Read-only“?"


class GitHubError(RuntimeError):
    """Abfrage gescheitert; die Meldung sagt, was zu tun ist."""


class TokenRejectedError(GitHubError):
    """Token ungültig, abgelaufen oder ohne Zugriff; ein anderer Token kann helfen."""


class UserNotFoundError(GitHubError):
    """Kein GitHub-Konto mit diesem Namen."""


@dataclass(frozen=True)
class FetchResult:
    """Koi-Daten plus Hinweise auf Teilfehler, die den Lauf nicht verhindert haben."""

    data: KoiData
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Profile:
    """Ergebnis von Schritt 1: wer der Nutzer ist und wie aktiv er war."""

    user_id: str
    daily: dict[date, int]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RepoLanguages:
    """Ergebnis von Schritt 3 für einen Autor: Sprachgewichte in beiden Zeitfenstern."""

    recent: tuple[Language, ...]
    year: tuple[Language, ...]
    warnings: tuple[str, ...] = ()


# JSON von außen ist untypisiert. Any bleibt auf dieses Modul beschränkt; die parse_-
# Funktionen prüfen jedes Feld, bevor es in typisierte Modelle wandert.
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
    if not isinstance(obj, dict):
        return None
    return cast(dict[str, Json], obj).get(key)


def _object(value: Json, what: str) -> dict[str, Json]:
    """Stellt sicher, dass `value` ein JSON-Objekt ist."""
    if not isinstance(value, dict):
        raise GitHubError(f"Unerwartete Antwort der GitHub-API: {what} fehlt.")
    return cast(dict[str, Json], value)


@dataclass(frozen=True)
class _Answer:
    """Geprüfte Hülle einer GraphQL-Antwort: das user-Objekt und mitgelieferte Fehler."""

    user: dict[str, Json]
    messages: str
    types: frozenset[str]

    def warnings(self, hint: str = "") -> tuple[str, ...]:
        """Teilfehler als Warnung; leer, wenn GitHub keine Fehler gemeldet hat."""
        if not self.messages:
            return ()
        extra = f" {hint}" if hint else ""
        return (f"Teilfehler der GitHub-API, Koi trotzdem gezeichnet: {self.messages}{extra}",)

    def broken(self, err: Exception, *, token_level: bool = True) -> GitHubError:
        """Fehler für eine Antwort, deren Felder nicht zu gebrauchen sind.

        `token_level=False` für Abfragen, in denen FORBIDDEN ein erwarteter Teilfehler
        einzelner Repos ist (z. B. ohne Contents-Recht). Dort wäre „Token abgelehnt“
        irreführend: Der Rückfall auf GITHUB_TOKEN würde das gültige Profil verwerfen.
        """
        if token_level and "FORBIDDEN" in self.types:
            return TokenRejectedError(f"Token ohne Zugriff: {self.messages}")
        detail = (
            f"GitHub-API meldet: {self.messages}"
            if self.messages
            else f"unerwartetes Format: {err!r}"
        )
        return GitHubError(f"Antwort unbrauchbar, {detail}")


def _answer(payload: Json, login: str) -> _Answer:
    """Prüft die Hülle einer Antwort und holt das user-Objekt heraus.

    GraphQL meldet viele Probleme mit HTTP 200 und einer Liste `errors` neben Teildaten.
    Fehlt `user` ganz, entscheidet der Fehlertyp, was gemeldet wird.

    Raises:
        TokenRejectedError: wenn der Token keinen Zugriff hat (FORBIDDEN).
        UserNotFoundError: wenn es das Konto nicht gibt.
        GitHubError: wenn die API sonst scheitert.
    """
    body = _object(payload, "JSON-Objekt")
    raw_errors: list[Json] = body.get("errors") or []
    errors = [_object(e, "Fehlereintrag") for e in raw_errors]
    # Gleiche Meldungen nur einmal: 20 Repos ohne Zugriff sollen keine Endloszeile ergeben.
    messages = "; ".join(dict.fromkeys(str(e.get("message", "?")) for e in errors))
    types = frozenset(str(e.get("type")) for e in errors)

    user: Json = _object(body.get("data") or {}, "data").get("user")
    if user is None:
        if "FORBIDDEN" in types:
            raise TokenRejectedError(f"Token ohne Zugriff: {messages}")
        if errors and "NOT_FOUND" not in types:
            raise GitHubError(f"GitHub-API meldet: {messages}")
        raise UserNotFoundError(f"Kein GitHub-Konto mit dem Namen '{login}' gefunden.")
    return _Answer(_object(user, "user"), messages, types)


def _user_id(answer: _Answer) -> str:
    """Konto-ID aus einer Antwort; GitHub-IDs sind nicht leere Texte."""
    user_id = answer.user["id"]
    if not isinstance(user_id, str) or not user_id:
        raise ValueError(f"ungültige Konto-ID {user_id!r}")
    return user_id


def parse_profile(payload: Json, login: str) -> Profile:
    """Schritt 1: Konto-ID und Contributions je Kalendertag.

    Raises:
        TokenRejectedError, UserNotFoundError, GitHubError: siehe `_answer`, dazu
            GitHubError bei fehlenden Feldern.
    """
    answer = _answer(payload, login)
    try:
        daily = {
            date.fromisoformat(day["date"]): int(day["contributionCount"])
            for week in answer.user["contributionsCollection"]["contributionCalendar"]["weeks"]
            for day in week["contributionDays"]
        }
        return Profile(_user_id(answer), daily, answer.warnings())
    except (KeyError, TypeError, ValueError, AttributeError) as err:
        raise answer.broken(err) from err


def parse_author_id(payload: Json, login: str) -> str:
    """Schritt 2: Konto-ID eines weiteren Autors.

    Raises:
        UserNotFoundError: wenn es das Konto nicht gibt; sonst wie `parse_profile`.
    """
    answer = _answer(payload, login)
    try:
        return _user_id(answer)
    except (KeyError, TypeError, ValueError) as err:
        raise answer.broken(err) from err


def _commits(target: Json, window: str) -> int:
    """Commits eines Zeitfensters (Alias `recent`/`year`); 0, wenn nicht lesbar.

    Das Feld fehlt, wenn der Hauptzweig auf etwas anderes als einen Commit zeigt, und
    kann `null` sein, wenn GitHub die Historie nicht herausgibt.
    """
    history = _get(target, window)
    return int(history["totalCount"]) if history else 0


def parse_repositories(payload: Json, login: str) -> RepoLanguages:
    """Schritt 3: gewichtet Sprachen nach Commits, je Repo Commits × Anteil am Code.

    Beispiel: 10 Commits in einem Repo aus 80 % Python und 20 % HTML ergeben
    Python 8 und HTML 2. Über alle Repos und Autoren summiert, ergibt das die Fleckenanteile.

    Repos ohne Zugriff, ohne Hauptzweig oder ohne erkannte Sprache werden übersprungen.

    Raises:
        TokenRejectedError, UserNotFoundError, GitHubError: wie `parse_profile`.
    """
    answer = _answer(payload, login)
    recent: list[Language] = []
    year: list[Language] = []
    try:
        nodes: list[Json] = answer.user["repositories"]["nodes"] or []
        for node in nodes:
            target = _get(_get(node, "defaultBranchRef"), "target")
            langs = _get(node, "languages")
            if not target or not langs:
                continue
            total = int(langs["totalSize"])
            if total <= 0:
                continue
            for window, bucket in (("recent", recent), ("year", year)):
                commits = _commits(target, window)
                if commits <= 0:
                    continue
                for edge in langs["edges"]:
                    lang = edge["node"]
                    share = int(edge["size"]) / total
                    bucket.append(
                        Language(str(lang["name"]), commits * share, _color(lang.get("color")))
                    )
        repo_count = int(answer.user["repositories"]["totalCount"])
    except (KeyError, TypeError, ValueError, AttributeError) as err:
        # FORBIDDEN betrifft hier einzelne Repos, nicht den Token als Ganzes.
        raise answer.broken(err, token_level=False) from err
    hint = CONTENTS_HINT if "FORBIDDEN" in answer.types else ""
    warnings = answer.warnings(hint)
    if repo_count > MAX_REPOSITORIES:
        warnings += (
            f"{repo_count} eigene Repos, ausgewertet nur die {MAX_REPOSITORIES} zuletzt gepushten.",
        )
    return RepoLanguages(tuple(recent), tuple(year), warnings)


def fetch_koi_data(
    login: str,
    token: str,
    also_authors: Sequence[str] = (),
    now: datetime | None = None,
) -> FetchResult:
    """Fragt die GitHub-API ab und liefert die Koi-Daten für `login`.

    Stichtag ist der letzte *abgeschlossene* Tag (UTC). Der Nachtlauf startet kurz nach
    Mitternacht; der angebrochene Tag wäre fast leer und ließe den Koi scheinbar schrumpfen.

    Args:
        login: Konto, dessen Koi gezeichnet wird (Kalender und Repos).
        token: GitHub-Token für alle Abfragen.
        also_authors: weitere Konten, deren Commits in den Repos von `login` für die
            Sprachfarben mitzählen. Unbekannte Konten werden mit Warnung übersprungen.
        now: Zeitpunkt der Abfrage (für Tests), sonst jetzt.
    """
    now = now or datetime.now(UTC)

    # Schritt 1: Profil des Hauptkontos.
    profile = parse_profile(
        _post({"query": PROFILE_QUERY, "variables": {"login": login}}, token), login
    )
    warnings = list(profile.warnings)

    # Schritt 2: IDs der weiteren Autoren. Ein Tippfehler im Namen soll den Koi nicht anhalten.
    author_ids = [profile.user_id]
    for author in also_authors:
        payload = _post({"query": AUTHOR_QUERY, "variables": {"login": author}}, token)
        try:
            author_ids.append(parse_author_id(payload, author))
        except UserNotFoundError:
            warnings.append(f"Autor '{author}' nicht gefunden, seine Commits zählen nicht mit.")

    # Schritt 3: je Autor eine Repo-Abfrage. Die Gewichte addieren sich einfach, weil
    # (Commits A + Commits B) × Anteil = Commits A × Anteil + Commits B × Anteil.
    recent: list[Language] = []
    year: list[Language] = []
    for author_id in dict.fromkeys(author_ids):  # doppelte Konten nur einmal zählen
        variables = {
            "login": login,
            "author": author_id,
            "recent": (now - timedelta(days=LANGUAGE_WINDOW_DAYS)).isoformat(timespec="seconds"),
            "year": (now - timedelta(days=YEAR_DAYS)).isoformat(timespec="seconds"),
            "first": MAX_REPOSITORIES,
        }
        found = parse_repositories(
            _post({"query": REPOSITORY_QUERY, "variables": variables}, token), login
        )
        recent += found.recent
        year += found.year
        warnings += found.warnings

    # In den letzten 90 Tagen keine Commits: auf das ganze Jahr ausweichen,
    # damit der Koi nach einer Pause nicht sofort farblos wird.
    languages = recent or year
    today = (now - timedelta(days=1)).date()
    return FetchResult(
        KoiData.build(login, profile.daily, languages, today),
        tuple(dict.fromkeys(warnings)),  # gleiche Warnung je Autor nur einmal
    )
