# ADR 06: InfraSales – Produkt, Fachmodell, Mandanten, Daten und Modelle

Status: **Angenommen** (2026-11-19). Ändert ADR 01, 03 und 06 dort, wo dieses ADR es sagt.
Ergänzt am selben Tag um die Datenwege und Modelle (§4), die Vergabevorschau und die Partnersuche (§5) und
die Grundsätze für rechtliche Grauzonen (§8).

## Kontext

InfraSales ist ein kommerzielles Datenprodukt auf der Plattform, die ADR 01 bis 06 beschreiben:
Scheduler, Sammeln mit Katalog, Anmeldung und Verwaltung, Oberfläche. Die Produkte kommen in
dieser Reihenfolge:

1. **Abo für Bauunternehmen, Planer und Hersteller im Wärmenetzbau.** Aus kommunalen Wärmeplänen,
   Ratsinformationssystemen, Ausschreibungen, Betreiber-Fahrplänen und weiteren Signalen erkennen
   wir Wärmenetz-Projekte, bevor sie ausgeschrieben werden, und sagen voraus, ob, wann und in
   welcher Form die Bauleistung vergeben wird. Dazu kommen die Partnersuche privater Bauherren
   (§5) und ein Werkzeug für Pipeline und Bietentscheidung. Kostenlos für alle ist die
   Vergabevorschau (§5). Wir beginnen in Baden-Württemberg, weil dort Wärmepläne seit 2020 Pflicht
   sind und es daher eine Historie für den Backtest gibt.
2. **Benchmarks für Auftraggeber** (Stadtwerke, Netzbetreiber, Kommunen): Kostenkennwerte,
   Spannen für Nachträge, Plausibilitätsprüfung von Kostenschätzungen, Prüfung von
   Ausschreibungsentwürfen. Es startet in einer Region und einem Segment, sobald dort mindestens
   fünf unabhängige Bauunternehmen mit Einwilligung beitragen. Diese Zahl, nicht ein Datum, ist
   die Bedingung.
3. **Daten für Finanzierer** (Banken, Förderbanken, Versicherer) aus demselben Pool: Kosten- und
   Terminverläufe, Projektpipeline.

Das Ziel ist, die Nische zu besetzen, ohne später teuer umbauen zu müssen. In einem Datengeschäft
entscheiden fünf Dinge über die Stellung im Markt: Vollständigkeit, Vertrauen in jede Angabe,
eine Historie, die niemand nachholen kann, Kennungen, die Kunden übernehmen, und ein Rückkanal von
den Kunden. Jede Entscheidung unten dient mindestens einem davon.

Bewusst nicht verfolgt: Erkenntnisse aus dem Pool an Bauunternehmen verkaufen, Kommunen kostenlos
beraten, um an ihre Daten zu kommen, und ein allgemeiner Ausschreibungsdienst für alle Branchen
werden.

## Entscheidung

### 1. Die Plattform

**Die Plattform** umfasst `core`, `scheduler` (Läufe, Leases, Wiederholungen,
Schritte), `config`, `audit`, `auth` (Sessions, Cookies, OIDC, CSRF), `alerts`, `mail`, `ai`
(Modelladapter, Laufzeit-Einstellungen, Ratenbegrenzung, verschlüsselte Schlüssel), `fetch`
(robots.txt, Pausen je Host, Bot-Sperren), `sink`, `catalog` (Source und Source Version),
`feeds` (RSS, Sitemap), `extract`, Retention, Migrationen und Observability. Im Frontend bleiben
die Technik (React, TanStack, shadcn/ui, i18next, Tests, CSP, Barrierefreiheit) und die Seiten
für den Betrieb: Dashboard, Jobs, Läufe, Feeds, Quellen, Audit, Einstellungen.

**Embeddings** bleiben als Teil von `ai` (`infrasales.ai.embeddings`), weil die Projektzuordnung sie
braucht.

**Name und Auftritt:** Paket, Kommando und Datenbankrollen heißen `infrasales`. Der Crawler meldet
sich als `InfraSalesBot/1.0`. Vor dem Betrieb bekommt die Kennung eine Kontaktadresse
(`+https://…`), wie es für höfliche Crawler üblich ist. Die Oberfläche hat ein eigenes Icon und die
Hauptfarbe Petrol (#0f4c5c).

**Migrationen:** Es gibt noch keine Datenbank von InfraSales. Die Migrationskette beginnt deshalb
neu: 0001 Grundschema, 0002 Katalog ohne vorab angelegte Feeds, 0003 Projektakte.

### 2. Fachmodell: die Projektakte

Das Fachmodell liegt im Paket `infrasales.projects`. Es beschreibt öffentliche Fakten, die niemandem
außer uns als Betreiber gehören.

| Tabelle | Inhalt |
|---|---|
| `municipality` | Kommune mit amtlichem Gemeindeschlüssel (AGS, 8 Ziffern), Name, Einwohnerzahl |
| `actor` | Firma oder Organisation: Stadtwerk, Netzbetreiber, Planungsbüro, Auftragnehmer, Hersteller, Verwaltung, private Bauherren (Contracting, Genossenschaft, Wohnungsunternehmen, Projektentwickler, Industrie). Keine Privatpersonen. |
| `project` | Projekt mit stabiler öffentlicher Kennung, Sektor, Art, Kommune, aktueller Phase, Veröffentlichungsstatus und den berechneten Eckdaten |
| `project_actor` | Wer an einem Projekt in welcher Rolle beteiligt ist |
| `claim` | Eine Angabe zu einem Projekt mit Beleg |
| `project_event` | Ein Statusereignis im Lebenszyklus eines Projekts |
| `tender` (folgt in Schritt 2) | Eine Vergabe oder ein Los eines Projekts, siehe unten |

Sieben Regeln gelten für das Modell:

- **Belegpflicht als Datenstruktur.** Jede Angabe eines Projekts ist ein `claim`: Feld, Wert,
  Source Version, Seite, wörtliches Zitat, ob das Zitat im Dokument gefunden wurde, Herkunft
  (Modell mit Version, Kurator, Kommune, Auftraggeber, Datensatz) und Prüfstatus. Die sichtbaren
  Eckdaten des Projekts werden aus den angenommenen Claims berechnet. Eine neue Auswertung legt
  neue Claims an und überschreibt keine alten. Eine Angabe eines Kurators hat Vorrang vor der
  eines Modells.
- **Zwei Zeitachsen.** Ein Statusereignis hat das Datum, an dem es geschah (`occurred_on`), und
  den Zeitpunkt, ab dem wir davon wussten (`known_since`, aus `source.first_seen_at`). Nur so
  lassen sich Trefferquote und Vorlaufzeit ehrlich zurückrechnen.
- **Sektorneutral.** `project.sector` ist zunächst nur `heat_network`. Der Lebenszyklus ist für
  alle Sektoren gleich: Wärmeplan → Studie → Beschluss → Förderung → Ausschreibung → Zuschlag →
  Bau → Betrieb, dazu „eingestellt“. Sektorspezifische Eckdaten wie Trassenlänge, Leistung,
  Anschlüsse oder Investition prüft ein versioniertes Pydantic-Schema je Sektor
  (`infrasales.projects.sectors`). Strom, Wasser oder Glasfaser kommen als weitere Sektoren hinzu,
  ohne dass sich Tabellen ändern.
- **Vergaben sind eine eigene Einheit.** Ein Projekt hat oft mehrere Vergaben: Planung ab
  Leistungsphase 2, Tiefbau als Los, Rohrlieferung, einen Rahmenvertrag über mehrere Jahre. Eine
  Vergabe hat Art (Planung, Bau, Lieferung), Los, ob sie ein Rahmenvertrag ist, Laufzeit bis,
  Verfahrensart, Angebotsfrist, Zahl der Angebote, Zuschlagswert, Zuschlagsdatum, Gewinner,
  Status (geplant, veröffentlicht, vergeben, aufgehoben) und Herkunft (Bekanntmachung,
  Vergabevorschau, Anfrage eines privaten Bauherrn). Sie ist das Ziel der Prognose und die
  Grundlage der Benchmarks. Die Tabelle kommt in Schritt 2 mit den OCDS-Daten hinzu; das ist eine
  reine Erweiterung.
- **Stabile Kennungen mit Zusammenführung.** Eine Projektkennung wird nie neu vergeben. Stellen
  sich zwei Projekte als dasselbe heraus, verweist das eine per `merged_into_id` auf das andere,
  und Anfragen nach der alten Kennung werden weitergeleitet. Für Akteure gilt dasselbe.
- **Veröffentlichung erst nach Prüfung.** Ein Projekt ist `draft`, `published` oder `withdrawn`.
  Kunden sehen nur veröffentlichte Projekte. Was eine Prüfung braucht, landet in einer Prüfliste
  im Backoffice.
- **Die Kommune ist das Rückgrat der Geografie.** Regionen sind Präfixe des AGS: `08` ist
  Baden-Württemberg, `08111` Stuttgart. Geometrien kommen später als weitere Spalte (PostGIS)
  hinzu, ohne dass sich etwas anderes ändert.

### 3. Mandanten

Ein Mandant (`tenant`) ist ein Kunde oder Teilnehmer als Organisation, nicht als einzelne Person.
Alle Mandanten teilen sich eine Anwendung und eine Datenbank. Viele unserer Kunden sind
Wettbewerber, deshalb muss die Trennung ihrer Daten belastbar sein.

| Art des Mandanten | Beispiele | Zahlt |
|---|---|---|
| Bauunternehmen, Planer, Hersteller | Rohrleitungsbau, Tiefbau, Ingenieurbüro, Rohrhersteller | Abo (Produkt 1) |
| Auftraggeber | Stadtwerk, Netzbetreiber, Kommune | Produkt 2; die Vergabevorschau ist kostenlos |
| Privater Bauherr | Contracting, Genossenschaft, Wohnungsunternehmen, Projektentwickler, Industrie | nichts: die Partnersuche ist kostenlos |
| Finanzierer | Bank, Förderbank, Versicherer | Produkt 3 |
| Plattform | unser Team | – |

Es gibt drei **Datenzonen**:

| Zone | Beispiele | Gehört | Wer sie liest |
|---|---|---|---|
| Öffentlich | Kommunen, Projekte, Claims, Vergaben, Vergabevorschau | dem Betreiber | jeder Mandant, soweit sein Abo reicht; die Vorschau alle |
| Privat | Notizen, Pipeline, Watchlists, Alert-Regeln, eigene Angebote, Preise, Nachträge, Bietentscheidungen mit Gründen, gewonnen/verloren | dem Mandanten | nur dieser Mandant |
| Pool | Kopien privater Daten ohne Absender, nur mit Einwilligung je Zweck | den Beitragenden | nur die Produkte für Auftraggeber und Finanzierer, zusammengefasst |

Regeln:

- **Gemeinsame Tabellen mit `tenant_id`.** Jede private Tabelle hat eine Pflichtspalte
  `tenant_id`. Öffentliche Fakten haben keine. Der Pool liegt getrennt und trägt keine Kennung
  des Absenders.
- **Zweifache Absicherung.** Der Code filtert jede Abfrage nach dem Mandanten. Zusätzlich setzt
  die Anwendung zu Beginn jeder Transaktion `app.tenant_id`, und PostgreSQL Row-Level Security
  gibt nur passende Zeilen heraus. Vergisst eine Abfrage den Filter, liefert die Datenbank
  trotzdem nichts Fremdes. Auf den Pool greifen nur die Rollen der Produkte 2 und 3 zu.
- **Zweck je Feld.** Jeder private Datensatz trägt, wofür der Mandant eingewilligt hat: eigenes
  Modell (B), Pool für Auftraggeber, Pool für Finanzierer. Ohne Einwilligung bleibt er privat.
  Kündigt ein Mandant, werden seine Rohdaten gelöscht; seine Beiträge bleiben nur in bereits
  gebildeten historischen Aggregaten. Das steht so im Vertrag.
- **Mitgliedschaften statt Mandant am Nutzer.** `membership` verbindet einen Nutzer (`subject`)
  mit einem Mandanten und einer Rolle (`owner`, `member`). Ein Nutzer kann mehreren Mandanten
  angehören, etwa ein Ingenieurbüro, das mehrere Kommunen berät.
- **Plattform und Kunde sind getrennte Rollen.** Unser Team ist ein eigener Plattform-Mandant
  mit den Rollen `operator` und `curator` und arbeitet im Backoffice. Private Daten eines Kunden
  sieht es nur ausdrücklich für den Support. Jeder solche Zugriff landet im Audit-Log.
- **Auftraggeber in zwei Rollen.** Ein Mandant kann auf eine Kommune (`municipality_ags`) oder
  einen Akteur verweisen. Kommunen und Stadtwerke können als Kunde ihre eigenen Einträge
  berichtigen und Vergaben in die Vorschau eintragen. Das wird als Claim mit der Herkunft
  `municipality` oder `contracting_authority` gespeichert.
- **Anmeldung.** Sessions, Cookies und der OIDC-Client bleiben. Organisationen, Einladungen, MFA
  und das SSO der Kunden übernimmt ein Identity Provider mit Mandanten, z. B. Zitadel oder
  Keycloak. Der OIDC-Client liest zusätzlich die Organisation aus dem Token. Die Auswahl des
  Identity Providers ist noch offen.

Die Mandantentabellen entstehen, bevor die erste private Tabelle entsteht. Für den ersten Report,
der aus dem Backoffice verschickt wird, sind sie noch nicht nötig. Für den ersten Kunden-Login
schon.

### 4. Datenwege und Modelle

Die Trennlinie: Ein Modell, dessen Ausgabe Bauunternehmen sehen, lernt nur über die
**Nachfrageseite** (was der Auftraggeber plant, beschließt, vergibt und baut), nie über die
**Angebotsseite** (was ein Bauunternehmen bietet, kalkuliert, gewinnt oder an Kapazität frei hat).
Grund: Die Leitlinien der EU-Kommission zum Informationsaustausch (2023) kennen keinen sicheren
Hafen, zählen Preise, Kosten, Kapazitäten, Kunden und Pläne zu den sensiblen Informationen und
sehen auch einen gemeinsamen Algorithmus eines Dienstleisters als möglichen Kanal
(hub and spoke). Öffentliche Daten in einem Modell zu nutzen, ist dagegen zulässig. Bei
Ausschreibungen kommt § 298 StGB hinzu.

| Modell | Wer die Ausgabe sieht | Woraus es lernt |
|---|---|---|
| **A: Projektprognose** (gemeinsam) | alle Bauunternehmen | öffentliche Daten und historische Labels der Nachfrageseite |
| **B: Passung** (je Mandant) | nur dieser Mandant | Ausgabe von A und die eigenen privaten Daten |
| **C: Benchmarks** (Pool) | nur Auftraggeber und Finanzierer | alles, auch die Angebotsseite, zusammengefasst |

**Modell A, Eingaben (öffentlich):**

- Kommune: AGS, Einwohner, Bebauungsdichte, Anteil Gas- und Fernwärmeheizungen (Zensus), Stand
  und Datum des Wärmeplans, Zahl und Fläche der Eignungsgebiete, Ende der Gaskonzession (wo
  veröffentlicht).
- Auftraggeber: Art, Netzlänge und Anschlüsse (Geschäftsbericht, MaStR), Stellenanzeigen zu
  Wärmenetzen der letzten 12 Monate, Gründung einer Wärmegesellschaft, Veröffentlichung des
  Fahrplans, Einträge in der Vergabevorschau.
- Projekt: Sektor, Art, Phasen mit `occurred_on` und `known_since`, Eckdaten aus öffentlichen
  Belegen, Wärmequelle, BEW-Modul und -Bewilligung, Ratsbeschluss.
- Öffentliche Vergaben: Verfahrensart, Lose, Rahmenvertrag, Laufzeit, Angebotsfrist, Zahl der
  Angebote, Zuschlagswert, Zuschlagsdatum, Gewinner, so wie bekannt gemacht.

**Modell A, Labels:**

- Aus öffentlichen Daten: Bauausschreibung in 12 bzw. 24 Monaten, Monate bis zur
  Bauausschreibung, Vergabeform (Einzelauftrag, Los, Rahmenvertrag).
- Beigesteuert, nur unter Bedingungen: Projekt vergeben (ja/nein), Monat der Vergabe, Vergabeweg
  (öffentlich, beschränkt, Direktvergabe, privat, Contracting). Bedingungen: Vertrag seit
  mindestens 12 Monaten geschlossen, Projekt in der Projektakte bekannt, ohne Absender, ohne
  Auftragnehmer, ohne Wert, mindestens fünf unabhängige Unternehmen im Pool, Einwilligung.

**Nie in Modell A, in keiner Form:** Angebotspreise und Preise aus nicht öffentlichen Verfahren,
Endsummen, Nachträge, Kalkulation, Kosten, Marge, Kapazität und Auslastung, ob ein Unternehmen
bietet oder nicht und warum, gewonnen oder verloren eines bestimmten Unternehmens, wer mitgeboten
hat, Kundenbeziehungen und Ansprechpartner, alles zu laufenden Verfahren.

**Ausgaben an Bauunternehmen:** Wahrscheinlichkeit, Zeitraum und Form einer Bauausschreibung mit
Belegen; aus öffentlichen Zuschlägen auch Wettbewerbsdichte und typische Gewinner vergleichbarer
Vergaben. Nie aus dem Pool: erwartete Bieterzahl, Preisempfehlung, Gewinnchance, Auslastung von
Wettbewerbern.

**Modell C, Regeln:** mindestens fünf unabhängige Unternehmen je Zelle (vorsichtiger Startwert),
kein Unternehmen dominiert eine Zelle, nur Daten älter als 12 Monate, bei zu wenig Daten gröber
zusammenfassen. Nutzungsbedingungen: Werte nur für interne Kostenschätzung, nicht in
Bekanntmachungen. Auftraggeber mit eigener Bausparte bekommen keine Benchmarks. Bauunternehmen
sehen aus C nichts, auch keine Zusammenfassungen.

**Technisch erzwungen:** Jedes Merkmal trägt seine Herkunft (Zone und Zweck). Ein Test schlägt
fehl, sobald ein Merkmal aus der privaten Zone oder dem Pool im Training von A auftaucht oder ein
Merkmal aus dem Pool in einer Ausgabe an Bauunternehmen. Die Gewichte von B gehören dem Mandanten
und lassen sich löschen.

### 4a. Öffentliche Quellen und Modell B auf Modell A

Die Daten für Modell A und den öffentlichen Teil von Modell B stehen bereit und werden mit
`infrasales load <quelle>` geladen. Die Rohdateien bleiben unverändert (§10):

| Quelle | Inhalt | Zugang | Stand der Auswertung |
|---|---|---|---|
| Gemeindeverzeichnis (Destatis) | 10.959 Gemeinden mit AGS, Fläche, Einwohnern (Zensus 2022), PLZ des Rathauses, Mittelpunkt, Verstädterung | XLSX, frei | geladen |
| OpenPLZ (OpenStreetMap) | 8.159 PLZ mit Gemeinde je Straße | CSV, ODbL, Namensnennung | geladen; ordnet 95 % der Vergaben einer Gemeinde zu |
| TED | 3.151 deutsche Bekanntmachungen seit 2016 mit Wärmenetz-Code oder -Titel; eForms mit Losen, Gewinnern, Angebotszahl | Such-API ohne Schlüssel; ältere Bekanntmachungen als XML | geladen |
| Datenservice Öffentlicher Einkauf | alle deutschen Bekanntmachungen seit 12/2022 (rund 27.000 im Monat), auch unterhalb der EU-Schwelle (VOB/A, UVgO) | Monatsexport CSV, gemeinfrei | geladen; verdoppelt bis verdreifacht die Basis |
| Bundestag, Drs. 20/13968, Anlage 2 | 1.283 geförderte BEW-Modul-1-Projekte (Machbarkeitsstudien, Transformationspläne) mit PLZ und Fördersumme | PDF | geladen als Signale |
| Energieatlas BW, Wärmeplattform | Stand der Wärmeplanung, Datum von Ratsbeschluss und Veröffentlichung | Karte, Download zu prüfen | offen |
| Ratsinformationssysteme, Wärmepläne, Betreiber-Fahrpläne | datierte Frühsignale | HTML und PDF, Sammeln über Feeds | offen: liefert die Vorlaufzeit |
| Zensus 2022 (Heizungsart je Gemeinde), Marktstammdatenregister | Fernwärmeanteil, KWK-Anlagen | Landesämter, XML-Gesamtexport | offen |

Wie eine Bekanntmachung als Wärmenetz zählt, entscheiden Regeln, die ihren Grund mitspeichern
(`relevance`): der Hauptcode (Fernheizleitungen, Übergabestationen, Fernheizwerke) oder eigene
Worte im Titel. Fernwärme-Lieferung, Hausanschlüsse und Gebäude mit einem Netz-Code unter vielen
zählen nicht. Bekanntmachungen eines Verfahrens werden über die eForms-Verfahrens-ID über beide
Quellen hinweg zu einer Vergabe je Los zusammengeführt.

**Modell B baut auf Modell A auf.** Die Erfolgschance eines Bauunternehmens bei einer Vergabe ist
die Chance, dass die Vergabe kommt (bei einer veröffentlichten 1, sonst Modell A), mal die
Chance, dass es gewinnt, wenn es bietet. Die zweite lernt ein Wahlmodell (Conditional Logit) aus
den öffentlichen Zuschlägen: Jeder Zuschlag ist eine Wahl unter den Firmen des Markts. Merkmale
sind die Entfernung vom Sitz zur Baustelle, frühere Zuschläge beim selben Auftraggeber, im selben
Land und insgesamt, und die Größe. Das ist zulässig nach §4: Es nutzt nur veröffentlichte
Zuschläge, keine Angebote anderer Mandanten. Ein Kunde ist von Beginn an im Markt, mit den
Zuschlägen unter seinen Namen. Seine eigenen Gebote (gewonnen/verloren, mit Einwilligung
`own_model`) kalibrieren seine Chance, sobald 20 entschieden sind: seine Gewinnquote gegen die
eines typischen Bieters (1 durch die übliche Zahl der Angebote).

Ergebnisse auf echten Daten (Stand 20.11.2026):

- Modell A, Stichtag 1.10.2024, Horizont 24 Monate: von allen 10.959 Gemeinden schrieben 221 Bauleistungen aus (2 %). Von den 50 am höchsten eingestuften taten es 41 (82 %), AUC 0,94. Die Vorlaufzeit im Median ist mit 6 Monaten noch kurz, weil frühe Signale bisher nur mit einem Datum vorliegen.
- Modell B, öffentlicher Teil: auf 180 Zuschlägen vor 2025 gelernt, auf 218 danach geprüft, bei im Schnitt 284 Firmen im Markt. Der tatsächliche Gewinner steht in 27,5 % der Fälle auf Platz 1 und in 55 % unter den ersten 5, besser als ein Modell nur nach Entfernung.
- Form der Vergabe (1.580 Bau-Vergaben): 85 % ohne Lose, 5 % Rahmenverträge, 69 % reiner Preiswettbewerb, Laufzeit im Median 12 Monate, Wert im Median 0,83 Mio. €, im Median 3 Angebote, 25 % der Gewinner sitzen im Kreis der Baustelle.

Zweite Runde (20.11.2026): weitere Daten und was sie bringen. Geladen wurden der Zensus 2022 je
Gemeinde (Fernwärme-, Gas-, Öl- und Wärmepumpenanteil, Mehrfamilienhäuser, Wohnungsunternehmen;
Esri/Statistische Ämter, DL-DE BY 2.0), datierte Frühsignale aus allen Bekanntmachungen (900
beauftragte Wärmeplanungen, 394 Machbarkeitsstudien und Transformationspläne, 1.326 Projekte für
Wärmequellen) und 1.385 Leitungsbau-Zuschläge anderer Medien als Markt für Modell B. Gemessen mit
Ablation (`forecast-backtest --drop`) und in einem einheitlichen Datenzeitraum ab 2023
(`--since`), weil vor 12/2022 nur EU-Vergaben sichtbar sind:

| Messung | alle Daten | ohne Zensus | ohne Frühsignale | ohne beides |
|---|---|---|---|---|
| A, 18 Monate, alle Gemeinden: AUC / Top 50 | 0,947 / 76 % | 0,948 / 78 % | 0,947 / 80 % | 0,947 / 80 % |
| A, 18 Monate, Gemeinden ohne frühere Bauvergabe (93 Treffer): AUC / AP / Top 50 | 0,907 / 0,15 / 26 % | 0,909 / 0,15 / 30 % | 0,906 / 0,15 / 28 % | 0,908 / 0,15 / 30 % |

Modell B auf denselben 445 Wärmenetz-Zuschlägen (im Schnitt 554 Firmen): nur Wärmenetz-Zuschläge
12,8 % Platz 1, 29,7 % Top 5; mit Leitungsbau-Zuschlägen 13,0 % und 27,4 %. Die neuen Daten
ändern die Leistung nur im Rauschen (±1–2 Treffer). Der stärkste Hinweis bleibt die eigene
Vergabegeschichte. Für Gemeinden ohne frühere Vergabe fehlen datierte Beschlüsse aus
Ratsinformationssystemen. Für Modell B fehlen die unterlegenen Bieter: Sie sind nicht öffentlich,
nur die Angebotsdaten der Kunden zeigen sie.

### 5. Vergabevorschau und Partnersuche

**Vergabevorschau (kostenlos, öffentlich).** Auftraggeber tragen geplante Vergaben für die
nächsten 6 bis 24 Monate ein: Bauabschnitt, Leistung, Lose, Rahmenvertrag, voraussichtlicher
Zeitpunkt. Die Einträge sind unverbindlich und für alle frei lesbar; ein kostenloses Konto bietet
Merkliste und Benachrichtigungen.

- **Warum kostenlos:** Die Vorschau gewöhnt Auftraggeber und Bauunternehmen an die Plattform und
  macht sie zur zentralen Datenplattform des Marktes. Kommerziell ließe sie sich ohnehin nicht
  verwerten: Was eine kommende Vergabe betrifft, muss der Auftraggeber allen gleich zugänglich
  machen (§ 97 GWB), und öffentliche Stellen dürfen ihre Daten grundsätzlich nicht exklusiv
  vergeben (Datennutzungsgesetz). Es wird also kein Umsatz geopfert.
- **Was zahlende Kunden darüber hinaus haben:** die Einträge verknüpft mit Projektakte, Signalen,
  Prognose und Alerts. Das ist Auswertung, keine Exklusivität.
- **Anreiz für Auftraggeber:** mehr Angebote, weniger aufgehobene Verfahren; wer einträgt, bekommt
  Produkt 2 günstiger.
- Einträge werden Vergaben mit Status „geplant“ und Herkunft „Vergabevorschau“ und Claims mit der
  Herkunft des Auftraggebers.

**Partnersuche (exklusiv für zahlende Kunden).** Private Bauherren stellen Projekte ein und suchen
einen Baupartner: Ort, Umfang, Zeitplan, gesuchte Leistung. Für sie ist das kostenlos. Die Anfragen
gehen nur an zahlende Kunden, passend nach Region und Leistung.

- **Warum exklusiv zulässig:** Private Bauherren unterliegen meist nicht dem Vergaberecht. Wer
  doch darunter fällt (etwa ein privater Netzbetreiber mit besonderen oder ausschließlichen
  Rechten), wird markiert; seine Vorhaben laufen über die Vorschau.
- **Warum das zählt:** Diese Projekte stehen in keiner Datenbank, haben wenig Wettbewerb und sind
  der Grund, Kunde zu sein, den öffentliche Daten allein nicht liefern.
- **Kein Bauunternehmen sieht,** wer sonst eine Anfrage erhielt oder was andere angeboten haben.
- **Nach Abschluss** meldet der Bauherr, mit wem und wann gebaut wurde. Das sind die Labels zu
  Projekten ohne Ausschreibung (Modell A, unter den Bedingungen aus §4).

**Weitere Beitragende ohne Konflikt:** andere Spartenträger (Glasfaser, Strom, Wasser) mit
Terminen für Straßenaufbrüche, damit Lose gebündelt und Leitungen mitverlegt werden können;
Hersteller und Großhandel mit einem zusammengefassten Index für Lieferzeiten und Preise von Rohren
und Armaturen. Sie geben nie weiter, welcher Bieter welche Mengen angefragt hat.

### 6. Abos sind Daten

Ein Abo (`entitlement`) besteht aus Mandant, Umfang (kostenlos oder Abo), Sektor, Region als
AGS-Präfix und Laufzeit. So lassen sich Landkreise, Länder oder ganz Deutschland verkaufen, ohne
Code zu ändern. Die Sichtbarkeit öffentlicher Fakten folgt dem Abo, nicht dem Eigentum. Die
Vergabevorschau sieht jeder.

### 7. Die neue Pipeline

Der Scheduler und die Verkettung der Jobs (`then`) bleiben. Die Jobs werden ersetzt:

```
Sammeln (scrape, bleibt) + Datensätze (OCDS täglich, TED, MaStR, Gemeindeverzeichnis, Zensus)
  → Triage      Stichwörter und ein günstiges Modell, Schwelle am gelabelten Set kalibriert
  → Extraktion  Claims nach dem Schema des Sektors, mit Seite und Zitat; Zitate werden geprüft
  → Zuordnung   Kommune über AGS, Akteur über Register, Projekt über Embeddings und Regeln
  → Kuration    Unsicheres kommt in die Prüfliste; veröffentlicht wird nur Geprüftes
  → Prognose    Modell A: ob, wann und in welcher Form die Bauleistung vergeben wird
  → Melden      Alerts je Mandant nach Region und Watchlist, Wochenübersicht
  + Backtest    Zuschläge bis zum ersten Signal zurückverfolgen; liefert die Labels für A
```

Signale neben Wärmeplan und Ratsbeschluss: Fahrpläne der Netzbetreiber, Stellenanzeigen der
Stadtwerke, Gründung von Wärmegesellschaften, Haushaltsansätze und Kreditermächtigungen,
auslaufende Gaskonzessionen, Projekte für Wärmequellen (Großwärmepumpe, Abwärme, Geothermie),
BEW-Bewilligungen und Laufzeiten bestehender Verträge.

Beim Sammeln ändern sich drei Dinge:

- Feeds bekommen eine Kommune und sammeln auch rückwirkend, nicht nur die neuesten Einträge.
- Für jedes verbreitete Ratsinformationssystem (SessionNet, ALLRIS, SD.NET, OParl) gibt es einen
  Lister. Jeder erschließt Hunderte Kommunen.
- Die PDF-Extraktion behält die Seiten getrennt, damit ein Beleg seine Seite nennen kann, und
  liest gescannte Dokumente per OCR.

### 8. Rechtliche Grauzonen: vier Grundsätze

Viele Fragen dieses Produkts, vor allem zum Informationsaustausch zwischen Wettbewerbern über eine
Plattform, beantwortet kein Gesetzestext eindeutig. Auch Anwälte können sie meist nicht verbindlich
beantworten; im Ernstfall entscheidet ein Gericht. Wir handeln nach bestem Wissen und Gewissen und
halten uns von allem fern, was erkennbar unzulässig ist. Dafür gelten vier Grundsätze:

1. **Im Zweifel die strengere Variante.** Wo die Rechtslage offen ist, wählen wir die Gestaltung
   mit dem geringeren Risiko, auch wenn sie Nutzen kostet. Beispiel: Bauunternehmen sehen nichts
   aus dem Pool, auch keine Zusammenfassungen, obwohl die Leitlinien das teilweise erlauben würden.
2. **Die Abwägung wird dokumentiert.** Jede solche Entscheidung steht mit Begründung und Quellen in
   einem ADR. Das zeigt im Ernstfall, dass wir nach bestem Wissen gehandelt haben.
3. **Die Regeln sind technisch erzwungen.** Datenzonen, Zwecke je Feld, Rechte in der Datenbank und
   Tests sorgen dafür, dass die Regeln nicht nur auf dem Papier stehen.
4. **Wir ziehen nach, wenn sich die Lage klärt.** Neue Rechtsprechung, Leitlinien oder
   Entscheidungen der Behörden werden ausgewertet und die Regeln angepasst.

Anhaltspunkte, die wir heute kennen: die Leitlinien der EU-Kommission zu horizontalen
Vereinbarungen (2023, Informationsaustausch), § 298 StGB (Absprachen bei Ausschreibungen), § 97
GWB (Gleichbehandlung im Vergabeverfahren) und das Datennutzungsgesetz. Wird der Pool geschäftlich
wichtig, kommt nach unserem Kenntnisstand ein Antrag beim Bundeskartellamt auf eine Entscheidung
über die Kooperation in Betracht (§ 32c GWB). Das ist eine Option, keine Voraussetzung.

### 9. Nur noch PostgreSQL

Row-Level Security, deutsche Volltextsuche, pgvector und später PostGIS gibt es nur auf
PostgreSQL. SQLite für die Entwicklung entfällt. Bis eine lokale PostgreSQL-Umgebung für alle
Entwickler steht, bleibt SQLite für die Entwicklung erhalten. Neue Funktionen, die PostgreSQL
brauchen, dürfen es aber voraussetzen.

### 10. Rohdaten bleiben dauerhaft

ADR 03 §8 sah vor, alte Source Versions nach einem Jahr zu löschen. Für InfraSales ist die
Historie das Kapital: Dokumente in Ratsinformationssystemen können
verschwinden, und der Backtest braucht sie. Source Versions werden standardmäßig nicht mehr
gelöscht. Audit-Log, Job-Läufe und Sessions behalten ihre Fristen.

Gesammelt wird deshalb früh für ganz Deutschland, ausgewertet zuerst nur Baden-Württemberg.

### 11. Rechtsgrundlage für das Sammeln

Für ein kommerzielles Produkt gilt § 44b UrhG: Text- und Data-Mining ist erlaubt, wenn der Zugang
rechtmäßig ist und der Rechteinhaber nicht maschinenlesbar widersprochen hat. Der Fetcher beachtet
robots.txt, Pausen und Bot-Sperren bereits. Die Nutzungsbedingungen der Portale und
Ratsinformationssysteme werden vor der Anbindung einzeln geprüft. Als Akteure speichern wir nur
Firmen und Organisationen. Namen von Personen aus Ratsdokumenten werden nicht extrahiert.
`PRIVACY.md` wird vor dem ersten Kunden neu gefasst.

### 12. Oberfläche

Es gibt drei Bereiche. Das **Backoffice** (`/ops`) besteht aus den bestehenden Seiten für den
Betrieb und bekommt die Prüfliste, eine Übersicht der Abdeckung und den Backtest dazu. Der
**Kundenbereich** (`/app`) ist neu: Projektliste mit Filtern, Projektakte mit Zeitleiste und
Belegen, Prognose, Watchlist, Alerts, Pipeline und Bietentscheidung, Export und die
Teamverwaltung des Mandanten. Der **öffentliche Bereich** zeigt die Vergabevorschau ohne Abo und
lässt Auftraggeber Vergaben und private Bauherren Projekte eintragen. Deutsch wird die
Standardsprache.

## Umsetzung

| Schritt | Inhalt | Stand |
|---|---|---|
| 1 | Fachmodell anlegen, Plattform auf InfraSales ausrichten | erledigt |
| 2 | Quellen für Baden-Württemberg (Wärmepläne, OCDS, die häufigsten Ratsinformationssysteme), Vergaben als Tabelle, Extraktion mit Seiten und OCR, Prüfliste; nur PostgreSQL | offen |
| 3 | Mandanten, Mitgliedschaften, Abos, Datenzonen mit Row-Level Security, Zweck je Feld, Kundenbereich, Deutsch | gebaut bis auf Deutsch und Einladungen: Tabellen, RLS-Policies (PostgreSQL), Profil, Standorte, eigene Gebote, Pipeline-Tabelle, Seite Opportunities |
| 4 | Backtest und Prognose (Modell A): Trefferquote, Vorlaufzeit, Form der Vergabe | gebaut: Tabellen für Signale, Kennzahlen und Vergaben mit `available_on`, CSV-Import, Merkmale zum Stichtag, Heuristik, logistische Regression, zeitlicher Backtest, wöchentlicher Job, API und Seite Forecast. Offen: echte Historie laden, die Form der Vergabe vorhersagen |
| 5 | Vergabevorschau, Partnersuche, Pipeline und Bietentscheidung (Modell B) | offen |
| 6 | NRW und Bayern, Betreiber-Fahrpläne, CRM-Anbindung, API, Karte | offen |
| 7 | Produkt 2 je Region, sobald fünf unabhängige Unternehmen beitragen; dann Produkt 3 | offen |

## Verworfene Alternativen

| Option | Warum nicht |
|---|---|
| Eine Datenbank je Mandant | Gemeinsame Fakten müssten in jede Datenbank kopiert und Migrationen je Kunde ausgeführt werden. Aggregate über Mandanten (Produkte 2 und 3) wären kaum machbar. Eine Bank, die vertraglich eine eigene Instanz verlangt, lässt sich über `tenant_id` trotzdem herauslösen. |
| Ein Schema je Mandant | Hat dieselben Nachteile in kleinerem Maß und macht jede Migration zur Schleife über alle Kunden. |
| Eckdaten direkt am Projekt speichern, ohne Claims | Einfacher, aber jede Angabe verliert ihren Beleg, und eine neue Auswertung überschreibt die alte. |
| Sektorspezifische Tabellen (nur Wärme) | Jeder weitere Sektor bräuchte neue Tabellen, neue Abfragen und neue Seiten. |
| Ein gemeinsames Modell für Bauunternehmen, das aus Preisen, Kapazitäten und Bietentscheidungen aller lernt | Der gemeinsame Algorithmus würde zum Kanal zwischen Wettbewerbern (hub and spoke); bei Ausschreibungen droht § 298 StGB. Was Bauunternehmen wirklich brauchen, liegt auf der Nachfrageseite. |
| Zusammengefasste Pool-Werte auch an Bauunternehmen | Teilweise zulässig, aber offen; nach Grundsatz 1 verzichten wir darauf. |
| Die Vergabevorschau nur für zahlende Kunden | Vergaberecht (Gleichbehandlung) und Datennutzungsgesetz stehen dagegen; kommerziell wäre sie ohnehin kaum verwertbar. Als kostenloser Einstieg nützt sie mehr. |
| Kommunen kostenlos beraten, um an Daten zu kommen | Gefährdet Neutralität und Vertrauen der Auftraggeber, auf denen Produkt 2 beruht. |
