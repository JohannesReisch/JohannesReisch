"""Kommandozeile und Token-Rückfall, ohne Netzwerk."""

from datetime import date
from pathlib import Path

import pytest

from koi_profil import __main__ as cli
from koi_profil.github import FetchResult, GitHubError, TokenRejectedError
from koi_profil.model import KoiData

KOI = KoiData.build("jo", {date(2026, 11, 7): 1}, [], date(2026, 11, 7))


def fake_fetch(valid: set[str], calls: list[str]):
    def fetch(login: str, token: str) -> FetchResult:
        calls.append(token)
        if token not in valid:
            raise TokenRejectedError("abgelaufen")
        return FetchResult(KOI)

    return fetch


def test_prefers_koi_token(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    monkeypatch.setattr(cli, "fetch_koi_data", fake_fetch({"koi", "gh"}, calls))
    cli.fetch_with_fallback("jo", {"KOI_TOKEN": "koi", "GITHUB_TOKEN": "gh"})
    assert calls == ["koi"]


def test_falls_back_when_koi_token_expired(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    calls: list[str] = []
    monkeypatch.setattr(cli, "fetch_koi_data", fake_fetch({"gh"}, calls))
    assert cli.fetch_with_fallback("jo", {"KOI_TOKEN": "alt", "GITHUB_TOKEN": "gh"}) is KOI
    assert calls == ["alt", "gh"]
    assert "::warning::KOI_TOKEN abgelehnt" in capsys.readouterr().err


def test_empty_koi_token_is_skipped(monkeypatch: pytest.MonkeyPatch):
    """Ohne Secret setzt der Workflow KOI_TOKEN als leeren Text."""
    calls: list[str] = []
    monkeypatch.setattr(cli, "fetch_koi_data", fake_fetch({"gh"}, calls))
    cli.fetch_with_fallback("jo", {"KOI_TOKEN": "", "GITHUB_TOKEN": "gh"})
    assert calls == ["gh"]


def test_all_tokens_rejected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cli, "fetch_koi_data", fake_fetch(set(), []))
    with pytest.raises(GitHubError, match="GITHUB_TOKEN"):
        cli.fetch_with_fallback("jo", {"KOI_TOKEN": "a", "GITHUB_TOKEN": "b"})


def test_no_token():
    with pytest.raises(GitHubError, match="Kein Token"):
        cli.fetch_with_fallback("jo", {})


def test_main_writes_demo_svg(tmp_path: Path):
    out = tmp_path / "koi" / "koi.svg"
    assert cli.main(["--demo", "neu", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("<svg")


def test_main_reports_error_with_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.delenv("KOI_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert cli.main(["--user", "jo", "--out", str(tmp_path / "k.svg")]) == 1
    assert "Kein Token" in capsys.readouterr().err


def test_partial_errors_become_warnings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    def fetch(login: str, token: str) -> FetchResult:
        return FetchResult(KOI, ("Teilfehler: Repo X",))

    monkeypatch.setattr(cli, "fetch_koi_data", fetch)
    assert cli.fetch_with_fallback("jo", {"KOI_TOKEN": "k"}) is KOI
    assert "::warning::KOI_TOKEN: Teilfehler: Repo X" in capsys.readouterr().err
