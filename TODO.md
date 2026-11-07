# TODO

## Etappe 1: Koi verfeinert und geprüft ✔
- [x] Wachstum aus regelmäßiger Aktivität (365 Tage, Halbwertszeit 30 Tage), schrumpft in Pausen
- [x] Farben aus den Commits der letzten 90 Tage, gewichtet nach Sprachanteil
- [x] Lebensphase und Trend in der Beschriftung
- [x] KOI_TOKEN für private Repos, Rückfall auf GITHUB_TOKEN bei Ablauf
- [x] Projekt nach Hausstandard: uv, ruff, pyright strict, pytest, CI
- [x] Sichttest aller Lebensphasen, Echtlauf gegen die API
- [x] Review: Stichtag = gestern, Teilfehler der API, Wiederholung bei Netzabbruch, Farbprüfung
- [x] Neuer Look: Schwimmwelle, Koi-Silhouette, Schuppen, Schleierschwanz, Seerose mit Blüte
- [x] Review des Zeichencodes: glatte Bahn, Safari-sicherer Zuschnitt, gestuftes Wachstum, Tests

## Etappe 2: Online bringen (privates Konto JohannesReisch)
- [x] Frische Historie ohne Arbeitskonto; Commits über die GitHub-noreply-Adresse
- [x] Erster Commit, Repo `JohannesReisch/JohannesReisch` öffentlich anlegen (docs/ANLEITUNG.md)
- [ ] KOI_TOKEN anlegen (nur Metadata: Read, alle Repos) und als Secret hinterlegen
- [ ] Workflow „Koi“ manuell starten, Log prüfen: keine Warnung, Sprachen erscheinen
- [ ] Workflow „Prüfen“ grün
- [ ] Nach einigen Tagen: Größe und Trend plausibel?

## Etappe 2a: Feinschliff ✔
- [x] Becken im Breitformat 840 × 270, füllt die README-Breite
- [x] Beschriftung: Contributions der letzten 30 Tage statt des Jahres
- [x] Profiltext oberhalb des Koi: „Das ist mein Contribution-Koi“

## Später
- [ ] Ähnliche Sprachfarben (Python/TypeScript sind beide blau) unterscheidbarer machen
