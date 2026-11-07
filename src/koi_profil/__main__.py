"""Kommandozeile: python -m koi_profil --user NAME [--out koi/koi.svg]."""

import argparse
import os
import sys
from collections.abc import Mapping
from pathlib import Path

from .demo import SCENARIOS, demo_data
from .github import GitHubError, TokenRejectedError, fetch_koi_data
from .model import KoiData
from .render import BODIES, render_svg

# Reihenfolge = Vorrang. KOI_TOKEN sieht private Repos, GITHUB_TOKEN ist der Rückfall.
TOKEN_VARIABLES = ("KOI_TOKEN", "GITHUB_TOKEN")


def _warn(message: str) -> None:
    # Das Präfix macht daraus in GitHub Actions eine sichtbare Warnung im Lauf;
    # lokal ist es eine normale Zeile auf stderr.
    print(f"::warning::{message}", file=sys.stderr)


def fetch_with_fallback(login: str, env: Mapping[str, str]) -> KoiData:
    """Fragt mit dem ersten gesetzten Token ab; lehnt GitHub ihn ab, mit dem nächsten.

    Grund: Ein abgelaufener KOI_TOKEN soll den Koi nicht anhalten. Er zeichnet dann mit
    den öffentlichen Daten weiter und warnt, statt jede Nacht fehlzuschlagen.
    Teilfehler der API erscheinen ebenfalls als Warnung.

    Raises:
        GitHubError: wenn kein Token gesetzt ist oder alle scheitern.
    """
    tokens = [(name, env[name]) for name in TOKEN_VARIABLES if env.get(name)]
    if not tokens:
        raise GitHubError(
            "Kein Token: KOI_TOKEN oder GITHUB_TOKEN setzen, die GraphQL-API verlangt einen."
        )
    for index, (name, token) in enumerate(tokens):
        try:
            result = fetch_koi_data(login, token)
        except TokenRejectedError as err:
            if index == len(tokens) - 1:
                raise GitHubError(f"{name}: {err}") from err
            _warn(f"{name} abgelehnt ({err}). Weiter mit {tokens[index + 1][0]}; neu ausstellen.")
            continue
        for warning in result.warnings:
            _warn(f"{name}: {warning}")
        return result.data
    raise AssertionError("unerreichbar")  # pragma: no cover


def main(argv: list[str] | None = None) -> int:
    """Zeichnet den Koi und schreibt ihn als SVG; Rückgabe ist der Exit-Code."""
    parser = argparse.ArgumentParser(prog="koi_profil", description=__doc__)
    parser.add_argument("--user", help="GitHub-Benutzername")
    parser.add_argument("--out", default="koi/koi.svg", help="Zieldatei (Standard: koi/koi.svg)")
    parser.add_argument("--body", default="white", choices=sorted(BODIES), help="Grundfarbe")
    parser.add_argument("--no-label", action="store_true", help="Keine Beschriftung im Teich")
    parser.add_argument(
        "--demo", choices=list(SCENARIOS), help="Erfundene Beispieldaten statt GitHub-Abfrage"
    )
    args = parser.parse_args(argv)

    if args.demo:
        data = demo_data(args.demo)
    else:
        if not args.user:
            parser.error("--user fehlt (oder --demo für Beispieldaten)")
        try:
            data = fetch_with_fallback(args.user, os.environ)
        except GitHubError as err:
            print(f"Fehler: {err}", file=sys.stderr)
            return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_svg(data, body=args.body, label=not args.no_label), encoding="utf-8")
    langs = ", ".join(f"{lang.name} {lang.share:.0%}" for lang in data.languages) or "keine"
    print(
        f"Koi gezeichnet: {out} | {data.stage}, Wachstum {data.growth:.0%}, "
        f"{data.month_contributions} Contributions in 30 Tagen, "
        f"{data.week_contributions} diese Woche "
        f"| Sprachen: {langs}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
