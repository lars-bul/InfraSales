# InfraSales

InfraSales erkennt Infrastrukturprojekte, bevor sie ausgeschrieben werden, zuerst Wärmenetze, und
belegt jede Angabe mit der Stelle im Dokument, aus der sie stammt. Was das Produkt ist und welche
Entscheidungen dahinterstehen, steht in [ADR 06](docs/adr/06_adr_infrasales.md). Die Begriffe sind
in [CONTEXT.md](CONTEXT.md) erklärt.

## Einrichtung

```bash
make install        # Abhängigkeiten und Git-Hooks (braucht uv und pnpm)
make profiles       # kopiert profiles/*.env.example nach profiles/*.env
make dev            # die App auf http://localhost:5173, lädt bei Codeänderungen neu (SQLite)
PROFILE=prod make up  # der Container-Stack mit PostgreSQL, mit profiles/prod.env
```

Die Einstellungen kommen aus den Profilen in `profiles/`: `dev.env` für `make dev`, `stack.env`
(Standard) oder `prod.env` für `make up`. Jede `*.env.example` nennt alle Variablen mit einem
Kommentar. Trag die Werte, die du brauchst, in die kopierte `.env` ein. Diese Dateien enthalten
Geheimnisse und werden nicht eingecheckt. `make help` listet alle Befehle.

**Windows und OneDrive:** OneDrive verträgt keine Hardlinks. Setze vor `make install`
`UV_LINK_MODE=copy`, und installiere das Frontend mit
`pnpm --dir frontend install --config.package-import-method=copy`. Besser liegt das Repository
außerhalb von OneDrive, sonst synchronisiert OneDrive auch `.venv` und `node_modules`.

### Entwicklungsschleife

`make dev` startet zwei Server und beendet beide mit Strg+C:

- den Vite-Dev-Server auf http://localhost:5173, den du öffnest. Er liefert die Quellen ohne
  Build aus, lädt die Seite neu, wenn du eine Frontend-Datei speicherst, und leitet `/api` an
  FastAPI weiter;
- FastAPI (`infrasales web --reload`) auf dem `WEB__PORT` des Profils (8000), das bei
  Backend-Änderungen neu startet. In der Entwicklung liefert es nur die API aus.

Melde dich als `alice` (Admin) oder `vera` (Viewer) mit dem `AUTH__PASSWORD` des Dev-Profils an.
Die eingebaute Anmeldung funktioniert über den Proxy, weil das Backend relativ weiterleitet und
der Browser nur einen Ursprung sieht. Die Anmeldung über OpenID Connect funktioniert über den
Proxy nicht, weil der Identity Provider zu `WEB__PUBLIC_URL` zurückkehrt. Teste sie mit dem
Produktions-Build (`make up`).

Auf dem Dev-Server öffnet der Knopf der TanStack-Devtools (Ecke unten) die Panels für Router und
Query. Builds enthalten sie nie.

### Aufbau des Frontends

`frontend/src/` hält die Einstiegspunkte auf oberster Ebene und alles andere in Ordnern. Tests
liegen neben dem Modul, das sie testen (`run-now.tsx` → `run-now.test.tsx`).

```text
main.tsx app.tsx create-app.ts router.tsx  # Einstieg der Seite, Wurzel der App, ihr Router
routeTree.gen.ts styles.css                # generierter Routenbaum, das Stylesheet
routes/      # Dateirouten von TanStack Router: Guards und Loader, je ein Bildschirm eines Features
features/    # ein Ordner je Feature: auth/, dashboard/, jobs/, schedules/, runs/, feeds/, sources/, audit/, settings/
components/  # gemeinsame Teile (App-Shell, Nutzermenü, Theme, Fehlerseiten, Datentabelle)
  ui/        # von `shadcn add` erzeugt
hooks/       # gemeinsame React-Hooks
lib/         # übergreifende Helfer: Query-Client, Theme, Anzeige einer Person
api/         # Laufzeitkonfiguration des generierten Clients, Request-Deadline, API-Fehler
client/      # aus openapi.json erzeugt (`make api-types`)
i18n/        # i18next, seine Typdeklarationen, locales/
test/        # gemeinsame Testhelfer
```

Importe zwischen Ordnern nutzen die Subpath-Importe `#/…` (`#/features/runs/run-now.tsx`),
Importe innerhalb eines Ordners bleiben relativ. `src/layout.test.ts` prüft, dass jedes Modul
seinen Test hat und die oberste Ebene nur Einstiegspunkte enthält.

### UI-Komponenten

Die Oberfläche besteht aus shadcn/ui-Komponenten auf Base UI, gestaltet mit Tailwind CSS. Eine
neue Komponente fügst du mit der CLI hinzu, aus `frontend/`:

```bash
pnpm exec shadcn add <component>    # z. B. dialog; schreibt src/components/ui/<component>.tsx
```

`components.json` ist von Hand geschrieben und bildet die Aliase der CLI auf die Subpath-Importe
`#/…` ab. Die erzeugten Dateien in `src/components/ui/` bleiben, wie sie erzeugt wurden, und sind
von Biome und Coverage ausgenommen. Nach jedem `add` sind zwei Dinge zu prüfen: Texte, die sie
zeigen oder ansagen, laufen über i18next unter den Schlüsseln `ui.*`, und eine Komponente, die zur
Laufzeit ein `<style>`-Element einfügt, bricht unter der Content-Security-Policy der Produktion
(`make e2e` meldet es). Die Farbtokens in `src/styles.css` erfüllen WCAG 2.1 AA in beiden Themes,
`src/styles.test.ts` prüft sie.

## Daten einspielen und die Prognose

Die Prognose (ADR 06 §4, Modell A) sagt für jede Kommune voraus, ob sie den Bau eines Wärmenetzes
in den nächsten 24 Monaten ausschreibt, und nennt die Gründe. Sie liest nur öffentliche Daten der
Nachfrageseite: Kommunen, Signale, Vergaben und Kennzahlen. Solange die Sammler dafür nicht fertig
sind, kommen diese Daten als CSV:

```bash
infrasales import municipalities gemeinden.csv  # ags,name,population,population_as_of,area_km2
infrasales import signals signale.csv           # kind,ags,available_on,occurred_on,ref,note,url
infrasales import tenders vergaben.csv          # origin,ref,kind,status,title,ags,available_on,published_on,…
infrasales import metrics kennzahlen.csv        # ags,metric,as_of,available_on,value,source
```

Eine Datei ist UTF-8, durch Kommas oder Semikolons getrennt, mit den Feldnamen als Kopfzeile.
Daten im ISO-Format (2026-03-01). Eine Datei wird ganz oder gar nicht übernommen; jeder Fehler
nennt seine Zeile. Erneut eingespielt, aktualisiert sie Datensätze über ihren Schlüssel (AGS,
`ref`, Herkunft und `ref`, Kommune mit Kennzahl, Stichtag und Quelle), statt sie zu verdoppeln.
Die erlaubten Werte für `kind`, `origin`, `status` und `metric` stehen in
`src/infrasales/projects/models.py`. Wichtig ist `available_on`: der Tag, an dem die
Öffentlichkeit davon wissen konnte. Die Prognose eines Tages nutzt nur, was bis dahin verfügbar
war, sonst lernt der Backtest aus der Zukunft.

```bash
infrasales forecast-predict [--as-of 2026-01-05]   # bewertet alle Kommunen mit dem aktiven Modell
infrasales forecast-backtest [--horizon 24]        # Heuristik und gelerntes Modell im Zeitvergleich
infrasales forecast-train [--horizon 24] [--activate]
```

Bis genug Vergaben bekannt sind, rankt eine Heuristik mit von Hand gesetzten Gewichten. Ihr Score
ordnet, er ist keine Wahrscheinlichkeit. `forecast-train` lernt eine logistische Regression auf
Quartals-Schnappschüssen und speichert sie mit ihrem Backtest; aktiv wird sie erst mit
`--activate` oder per Klick der Admins auf der Seite Forecast. Mit weniger als 30 positiven
Schnappschüssen auf jeder Seite des Zeitschnitts bricht das Training ab: Dann hilft nur mehr
Historie, kein weiterer Code. Der Job `forecast` bewertet jeden Montag um 05:00 alle Kommunen neu.

### Die öffentlichen Quellen laden

```bash
infrasales load gemeinden 31122024_Auszug_GV.xlsx        # Destatis, Gemeindeverzeichnis
infrasales load postcodes streets.csv                    # OpenPLZ (OpenStreetMap, ODbL)
infrasales load ted <seiten-ordner> [<xml-ordner>]       # TED: Suchseiten, ältere Bekanntmachungen als XML
infrasales load doe <ordner mit JJJJ-MM.csv.zip>         # Datenservice Öffentlicher Einkauf, Monatsexporte
infrasales load bew 2013968.pdf                          # Bundestag Drs. 20/13968, BEW Modul 1
infrasales forecast-wins [--cut 2025-01-01]              # wer gewinnt: Backtest, Training, aktiv
infrasales tenant "Muster Tiefbau GmbH" --owner oidc:<sub> --post-code 69117 --reach-km 80
```

Woher die Dateien kommen, steht in ADR 06 §4a. Die Monatsexporte des Datenservice liegen unter
`https://oeffentlichevergabe.de/api/notice-exports?pubMonth=JJJJ-MM&format=csv.zip`, TED antwortet
unter `https://api.ted.europa.eu/v3/notices/search`. Die Rohdaten gehören nicht ins Repository und
nicht in OneDrive (zusammen gut 750 MB).

## Tests

```bash
make test           # Lint, Typprüfung, dann alle Tests mit 85 % Coverage (pytest, vitest)
make test-pg        # die Backend-Tests gegen PostgreSQL 18 (Docker)
make e2e            # Playwright (Chromium) gegen den Produktions-Build hinter FastAPI
```

`make e2e` baut die Oberfläche und startet `infrasales web` mit einem eigenen Testprofil:
eingebaute Anmeldung für alice (Admin) und vera (Viewer), eine Wegwerf-SQLite-Datenbank und keine
geplanten Jobs. Jede Spec schlägt fehl bei einem CSP-Verstoß, einem Konsolen- oder Seitenfehler,
einer 5xx-Antwort oder einem Barrierefreiheitsfehler, den axe findet (WCAG 2.1 AA, Kontrast
inklusive), im hellen und im dunklen Modus. Die Specs liegen in `frontend/e2e/` (`*.e2e.ts`).

Unter Windows schlagen drei Backend-Tests fehl: zwei SMTP-Tests (`tests/mail/test_smtp.py`,
Abbruch bei hängender Verbindung) wegen des Socket-Verhaltens und
`tests/scheduler/test_worker.py::test_serve_runs_until_terminated`, weil Windows Signale anders
zustellt. Der Test für Stopp-Signale wird dort übersprungen. Unter Linux, also auch in der CI,
laufen alle.

Im Frontend lädt der erste Test einer Datei den Code seiner Seite. Auf einem langsamen Rechner
(Windows mit dem Repository in OneDrive) dauert das länger als die 5 Sekunden, die
`src/test/setup.ts` wartet: Dann scheitern Dutzende erste Tests mit „Loading…“, jede Datei allein
aber nicht. Mit längeren Wartezeiten (`asyncUtilTimeout`, `REAL_LIMIT_MS` in `src/test/run-now.ts`)
laufen alle.

## Dokumentation

| ADR | Thema |
|---|---|
| [01](docs/adr/01_adr_baseline.md) | Grundarchitektur: modularer Monolith, eingebauter Scheduler, Datenbank, Betrieb |
| [02](docs/adr/02_adr_openai_compatible_llm.md) | Sprachmodelle über jede OpenAI-kompatible API |
| [03](docs/adr/03_adr_scraper_sink.md) | Sources in einen Datei-Sink mit Katalog sammeln |
| [04](docs/adr/04_adr_frontend_application_stack.md) | Technik des Frontends |
| [05](docs/adr/05_adr_runtime_ai_settings.md) | KI-Verbindungen und Modelle als Laufzeit-Einstellungen |
| [06](docs/adr/06_adr_infrasales.md) | InfraSales: Fachmodell, Mandanten, Datenwege und Modelle, Vergabevorschau und Partnersuche, rechtliche Grauzonen, Reihenfolge |

