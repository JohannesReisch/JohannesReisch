# github-koi: Anleitung

Ein Koi fürs GitHub-Profil. Er wächst mit **regelmäßiger** Arbeit, schrumpft in Pausen,
und seine Flecken haben die Farben der Programmiersprachen, an denen gerade gearbeitet wird.
Ein Workflow zeichnet ihn jede Nacht neu.

**Verantwortlich:** Johannes Reisch · **Betrieb:** GitHub Actions im Profil-Repo
`JohannesReisch/JohannesReisch`, keine eigene Infrastruktur.

## Was den Koi bestimmt

| Daten von GitHub | Wirkung |
|---|---|
| Contribution-Kalender der letzten 365 Tage | **Größe.** Jeder Tag zählt bis höchstens 3 Contributions („voll aktiv“), jüngere Tage stärker (Halbwertszeit 30 Tage). Regelmäßigkeit schlägt Masse. |
| Veränderung gegenüber vor 7 Tagen | Beschriftung „↗ wächst“, „→ hält sich“, „↘ schrumpft“ |
| Contributions der letzten 30 Tage | Zahl in der Beschriftung (passt zur Halbwertszeit: die Arbeit, die die Größe gerade prägt) |
| Commits der letzten 90 Tage je Repo × Sprachanteil im Repo | **Fleckenfarben** in GitHubs Sprachfarben, Fleckenzahl nach Anteil (bis 5 Sprachen, unter 5 % entfällt). Ohne Commits in 90 Tagen: das ganze Jahr. |
| Contributions der letzten 7 Tage | Schwimmtempo |
| Benutzername und Sprache | Lage der Flecken (je Sprache fest, neue Sprachen verschieben nichts) |

Gezählt wird bis einschließlich **gestern** (UTC): Der Nachtlauf startet kurz nach
Mitternacht, der angebrochene Tag wäre fast leer und ließe den Koi scheinbar schrumpfen.

**Lebensphasen:** Frisch geschlüpft → Jungkoi → Halbstark → Ausgewachsen.
Ausgewachsen ist der Koi bei etwa drei voll aktiven Tagen pro Woche über einige Wochen.
Rechenbeispiele (aus den Tests):

| Verlauf | Ergebnis |
|---|---|
| neues Konto, 1 Contribution | Frisch geschlüpft (kleinste Größe) |
| 30 Tage werktags aktiv | deutlich gewachsen |
| ein Jahr werktags aktiv | Ausgewachsen |
| danach 4 Wochen Urlaub | sichtbar kleiner, „↘ schrumpft“ |
| ein halbes Jahr Pause | klein, aber nie ganz weg |

Alle Schwellenwerte stehen kommentiert oben in [`src/koi_profil/model.py`](../src/koi_profil/model.py).

## Einrichten (einmalig)

1. **Commit-Adresse prüfen:** GitHub rechnet einen Commit nur dann dir zu, wenn seine
   E-Mail-Adresse (`git config user.email`) in deinem Konto hinterlegt ist
   (*Settings → Emails*). Das gilt auch für die Commits in deinen privaten Repos.
2. **Repo hochladen:** siehe [Hochladen](#hochladen).
3. **KOI_TOKEN anlegen** (nötig, weil die Arbeit in privaten Repos liegt: der eingebaute
   Token des Workflows sieht nur Öffentliches):
   1. github.com → Profilbild oben rechts → **Settings** → links ganz unten
      **Developer settings** → **Personal access tokens** → **Fine-grained tokens** →
      **Generate new token**.
   2. **Token name:** `koi-profil`. **Description:** „Liest Sprachen und Contributions
      für den Profil-Koi“.
   3. **Resource owner:** `JohannesReisch` (dein Konto, keine Organisation).
   4. **Expiration:** *Custom* → ein Jahr ab heute. Termin für die Verlängerung in den
      Kalender eintragen.
   5. **Repository access:** **All repositories**. So zählen auch Repos, die du später
      anlegst.
   6. **Permissions:** nichts hinzufügen. **Metadata: Read-only** ist automatisch dabei
      und genügt für Sprachen und Contributions. Bei *Account permissions* bleibt alles
      auf *No access*. Keinesfalls *Contents* vergeben: Dann könnte ein geleakter Token
      deinen Code lesen.
   7. **Generate token** → den Token (beginnt mit `github_pat_`) kopieren. GitHub zeigt
      ihn nur dieses eine Mal.
   8. Im Profil-Repo `JohannesReisch/JohannesReisch`: **Settings** → **Secrets and
      variables** → **Actions** → **New repository secret**. Name `KOI_TOKEN`, Wert
      einfügen, **Add secret**. Den Token sonst nirgends speichern, auch nicht in einer
      Datei oder im Chat.
4. **Erster Lauf:** *Actions → Koi → Run workflow*. Im Log steht z. B.
   `Koi gezeichnet: … | Jungkoi, Wachstum 49 %, … Contributions in 30 Tagen … | Sprachen: Python 54 %, C# 31 %`.
   Danach läuft er jede Nacht um 04:15 UTC. Eine gelbe Warnung „KOI_TOKEN abgelehnt“
   heißt: Token falsch kopiert oder abgelaufen, also neu ausstellen. Bleiben die Sprachen
   trotz Commits in privaten Repos leer, beim Token zusätzlich *Contents: Read-only*
   vergeben (*Edit*, kein neuer Token nötig). Das ist der Kompromiss: Er sieht dann
   auch den Code, kann aber nichts ändern.
5. **Optional, nur für den Rückfall:** *Settings → Public profile → „Include private
   contributions on my profile“*. Dann zählt auch der eingebaute Token deine private
   Arbeit für die Größe. Achtung: Das zeigt den Kalender deiner privaten Arbeit (nur
   Anzahlen) öffentlich im Profil, unabhängig vom Koi. Mit gültigem KOI_TOKEN nicht nötig.

**Läuft der Token ab oder verliert er den Zugriff** (HTTP 401/403), zeichnet der Workflow
mit dem eingebauten Token weiter (nur öffentliche Daten) und zeigt im Lauf eine gelbe
Warnung. Dann einen neuen Token ausstellen und das Secret ersetzen. Fehlt der Zugriff nur
auf einzelne Repos, wird mit dem Rest gezeichnet, ebenfalls mit Warnung.

## Sicherheit und Datenschutz

- **Öffentlich wird:** Lebensphase, Contributions-Zahl der letzten 30 Tage und die Namen der
  Sprachen samt Mengenverhältnis. Weil der Workflow das Bild täglich committet, ergibt die
  Git-Historie dazu eine öffentliche Zeitreihe (Größe, Jahreszahl, Schwimmtempo als Maß
  der Wochenaktivität). Repo-Namen, Code und Commit-Texte erscheinen nirgends.
- **KOI_TOKEN** kann nur lesen und liegt als verschlüsseltes Secret im Repo. Workflows aus
  fremden Pull Requests bekommen ihn nicht. Nur der nächtliche Koi-Lauf nutzt ihn.
- **Eingebauter `GITHUB_TOKEN`** darf nur dieses Repo beschreiben, und der Workflow schreibt
  nur `koi/koi.svg`.
- **Actions** sind auf Commit-Hashes festgeschrieben (`actions/checkout`, im Prüf-Workflow
  zusätzlich `astral-sh/setup-uv`). Ein umgehängter Versions-Tag kann so keinen fremden
  Code einschleusen.
- **Öffentliches Repo:** GitHub zeigt ein Profil-README nur aus dem öffentlichen Repo
  `<name>/<name>`. Der Code enthält keine Geheimnisse und keine privaten Daten.
- **Ist der Token in einen Commit, Chat oder eine Datei geraten:** sofort auf GitHub
  löschen (*Developer settings → Fine-grained tokens → Delete*) und neu ausstellen. Ein
  Löschen aus der Historie genügt nicht.

**Bekannte Grenze:** GitHub schaltet geplante Workflows in öffentlichen Repos nach 60 Tagen
ohne Aktivität ab. Solange der Koi sich ändert, committet der Workflow selbst und hält das
Repo aktiv. Nach langer völliger Pause ggf. unter *Actions* wieder einschalten.

## Hochladen

Einmalig, im integrierten Terminal von VS Code, im Projektordner:

```powershell
git init -b main
# noreply-Adresse von GitHub: Commits zählen für dein Konto, die private Mail bleibt verborgen
git config user.email "84015416+JohannesReisch@users.noreply.github.com"
git add .gitignore .python-version pyproject.toml uv.lock README.md docs src tests koi .github .vscode TODO.md
git status                       # prüfen: nur diese Dateien, keine .env, nichts Fremdes
git commit -m "Koi fürs GitHub-Profil" -m "Wächst mit regelmäßiger Aktivität, Farben aus den Sprachen der letzten 90 Tage."
gh auth switch --user JohannesReisch
gh repo create JohannesReisch/JohannesReisch --public --source . --remote origin --push
```

## Entwicklung

Python 3.12 und [uv](https://docs.astral.sh/uv/). Zur Laufzeit nur Standardbibliothek,
damit der nächtliche Workflow nichts installieren muss (deshalb `urllib` statt `httpx` und
`dataclasses` statt Pydantic; die API-Antwort prüft `parse_response` Feld für Feld).

```powershell
uv sync

# Koi mit erfundenen Daten: neu | gelegentlich | regelmaessig | intensiv
uv run python -m koi_profil --demo regelmaessig --out koi\demo.svg
start koi\demo.svg

# Mit echten Daten (Token der GitHub CLI, nur lesend genutzt)
$env:GITHUB_TOKEN = (gh auth token)
uv run python -m koi_profil --user JohannesReisch --out koi\koi.svg

# Prüfungen, alle vier müssen grün sein (laufen auch in CI)
uv run ruff format --check
uv run ruff check
uv run pyright
uv run pytest
```

Optionen: `--body white|gold|black|platinum` (Grundfarbe), `--no-label` (ohne Beschriftung).

```
src/koi_profil/
  github.py    GraphQL-Abfrage und Prüfung der Antwort
  model.py     Kalender und Sprachen -> Größe, Phase, Trend, Farben (ohne Ein-/Ausgabe)
  fish.py      Körperform, Flossen, Flecken als Schlüsselbilder einer Schwimmwelle
  render.py    Teichszene als animiertes SVG (SMIL, läuft in GitHub-READMEs, Skripte dort nicht)
  demo.py      erfundene Beispieldaten
  __main__.py  Kommandozeile, Token-Rückfall
tests/         pytest, ohne Netzwerk
.github/workflows/koi.yml      nächtliches Neuzeichnen
.github/workflows/pruefen.yml  Prüfungen bei Push und Pull Request
```
