# InfraSales

InfraSales erkennt Infrastrukturprojekte, bevor sie ausgeschrieben werden, und belegt jede Angabe
mit der Stelle im Dokument, aus der sie stammt. Der erste Sektor sind Wärmenetze, die ersten Kunden
sind Vertriebsleiter von Herstellern, Leitungsbau- und Tiefbaufirmen und Planungsbüros
([ADR 06](docs/adr/06_adr_infrasales.md)).

Die Begriffe unten gelten in Gesprächen, in der Oberfläche und im Code. In Klammern steht der Name
im Code.

## Projektakte

**Kommune** (`municipality`):
Eine Gemeinde mit ihrem amtlichen Gemeindeschlüssel. Die Kommune ist das Rückgrat der Geografie:
Jedes Projekt liegt in einer Kommune, und Regionen sind Präfixe ihres Schlüssels.
_Vermeiden_: Stadt (wenn jede Gemeinde gemeint ist), Ort

**AGS**:
Der achtstellige amtliche Gemeindeschlüssel. Die ersten zwei Ziffern bezeichnen das Land (`08` =
Baden-Württemberg), die ersten fünf den Kreis (`08111` = Stuttgart).

**Region**:
Ein Präfix des AGS: ein Land, ein Regierungsbezirk, ein Kreis oder eine einzelne Kommune. Abos
und Alerts werden über Regionen eingegrenzt.

**Wärmeplan**:
Der kommunale Wärmeplan nach dem Wärmeplanungsgesetz des Bundes oder nach Landesrecht. Er weist Gebiete aus, die sich für Wärmenetze eignen, und ist meist die
früheste Quelle eines Projekts.

**Projekt** (`project`):
Ein konkretes Vorhaben in einer Kommune, z. B. der Neubau, die Erweiterung oder die Umstellung
eines Wärmenetzes auf erneuerbare Wärme. Ein Projekt hat eine stabile öffentliche Kennung, die nie
neu vergeben wird.
_Vermeiden_: Lead, Opportunity (das sind Begriffe im CRM eines Kunden), Event

**Sektor** (`sector`):
Die Art der Infrastruktur eines Projekts. Zunächst gibt es nur Wärmenetze (`heat_network`).
Jeder Sektor hat ein eigenes Schema für seine Eckdaten.

**Phase** (`phase`):
Wo ein Projekt in seinem Lebenszyklus steht: Wärmeplan, Studie, Beschluss, Förderung,
Ausschreibung, Zuschlag, Bau, Betrieb, oder eingestellt. Die Phasen gelten für alle Sektoren.

**Statusereignis** (`project_event`):
Der Eintritt eines Projekts in eine Phase, mit zwei Zeitpunkten: wann es geschah und ab wann wir
davon wussten. Erst der zweite Zeitpunkt macht Trefferquote und Vorlaufzeit nachprüfbar.

**Angabe** (`claim`):
Eine einzelne Aussage über ein Projekt, etwa seine Trassenlänge, seinen Betreiber oder ein
Statusereignis, zusammen mit ihrem Beleg und ihrer Herkunft. Die Eckdaten eines Projekts werden
aus seinen angenommenen Angaben berechnet. Neue Auswertungen legen neue Angaben an, statt alte zu
überschreiben.
_Vermeiden_: Feld, Attribut (wenn die belegte Aussage gemeint ist)

**Beleg**:
Wo eine Angabe steht: Source Version, Seite und ein wörtliches Zitat. Ein Zitat, das im Dokument
nicht vorkommt, macht die Angabe unsicher.
_Vermeiden_: Quelle (wenn die Fundstelle gemeint ist), Referenz

**Herkunft** (`origin`):
Wer eine Angabe gemacht hat: ein Modell (mit Version), ein Kurator, eine Kommune, ein
Auftraggeber oder ein strukturierter Datensatz. Die Angabe eines Kurators hat Vorrang vor der eines
Modells.

**Akteur** (`actor`):
Eine Firma oder Organisation, die an Projekten beteiligt ist: Stadtwerk, Netzbetreiber,
Planungsbüro, Auftragnehmer, Hersteller, Verwaltung oder ein privater Bauherr. Privatpersonen sind
keine Akteure.
_Vermeiden_: Kontakt, Ansprechpartner

**Auftraggeber**:
Wer eine Leistung öffentlich vergibt und dabei dem Vergaberecht unterliegt: ein Stadtwerk, ein
Netzbetreiber oder eine Kommune. Er muss alle Bieter gleich behandeln.

**Privater Bauherr**:
Wer ein Wärmenetz baut, ohne dem Vergaberecht zu unterliegen: Contracting- und
Energiedienstleister, Genossenschaften, Wohnungsunternehmen, Projektentwickler, Industrie mit
Abwärme, private Netzbetreiber ohne besondere Rechte.

**Vergabe** (`tender`):
Die Vergabe einer Leistung zu einem Projekt: Planung, Bau oder Lieferung, als Einzelauftrag, Los
oder Rahmenvertrag. Sie ist geplant, veröffentlicht, vergeben oder aufgehoben und stammt aus einer
Bekanntmachung, der Vergabevorschau oder einer Anfrage eines privaten Bauherrn.
_Vermeiden_: Ausschreibung (wenn auch Direktvergaben und private Aufträge gemeint sind)

**Beteiligung** (`project_actor`):
Welche Rolle ein Akteur in einem Projekt hat, etwa Bauherr, Betreiber, Planer oder Auftragnehmer.

**Zusammenführung**:
Stellen sich zwei Projekte oder Akteure als dasselbe heraus, verweist der eine auf den anderen
(`merged_into_id`). Seine Kennung bleibt gültig und führt zum verbliebenen Eintrag.

**Veröffentlichung**:
Ein Projekt ist ein Entwurf, veröffentlicht oder zurückgezogen. Kunden sehen nur veröffentlichte
Projekte.

## Sammeln

**Source**:
Ein Dokument unter einer Adresse: ein Wärmeplan, eine Sitzungsvorlage, ein Protokoll, eine
Ausschreibung, eine Pressemitteilung, ein Fahrplan eines Netzbetreibers.
_Vermeiden_: Artikel, Seite

**Source Version**:
Der Text einer Source zu einem Zeitpunkt. Eine neue Version entsteht nur, wenn sich der Text
ändert. Belege zeigen auf Source Versions, damit sie zeigen, was ein Dokument sagte, als wir es
lasen. Source Versions werden dauerhaft aufbewahrt.

**Feed**:
Ein Ort, von dem InfraSales Sources sammelt: ein RSS-Feed, eine Sitemap, eine API, ein
Ratsinformationssystem oder ein Vergabeportal. Jeder Feed hat eine Kategorie: Presse (`press`),
Kommune (`municipality`), Versorger (`utility`), Vergabe (`procurement`) oder Behörde
(`authority`).
_Vermeiden_: Scraper, Kanal

**Source Collection**:
Der Job, der jeden Feed liest und neue Source Versions ablegt (Code-ID `scrape`).
_Vermeiden_: Scraping, Crawl

**Prognose**:
Was Modell A vorhersagt: für jede Kommune, wie wahrscheinlich sie in den nächsten 24 Monaten den
Bau eines Wärmenetzes ausschreibt, mit den Gründen dafür (Code: `forecast`). Später auch je
Projekt, wann und in welcher Form die Bauleistung vergeben wird. Bis genug Vergaben bekannt sind,
rankt eine Heuristik; ihr Score ordnet nur, er ist keine Wahrscheinlichkeit.

**Signal**:
Eine Angabe, die auf ein Projekt hinweist, bevor es ausgeschrieben ist, etwa ein Eignungsgebiet im
Wärmeplan oder ein Ratsbeschluss zu einer Machbarkeitsstudie. Ein Signal gehört zu einer Kommune,
auch wenn noch kein Projekt bekannt ist, und hat zwei Tage: wann es geschah (`occurred_on`) und
ab wann die Öffentlichkeit davon wissen konnte (`available_on`).

**Stichtag**:
Der Tag, für den eine Prognose gilt (`as_of`). Sie nutzt nur, was bis dahin verfügbar war.

**Vorlaufzeit**:
Die Zeit zwischen dem ersten Signal eines Projekts und seiner Ausschreibung.

**Trefferquote**:
Der Anteil der Ausschreibungen, zu denen InfraSales vorher ein Signal hatte. Wie viele Signale zu
einer Ausschreibung führen, ist die Treffsicherheit.

**Backtest**:
Die Rückrechnung von Trefferquote, Treffsicherheit und Vorlaufzeit an vergangenen Ausschreibungen
und Zuschlägen, nur mit dem, was zum jeweiligen Zeitpunkt bekannt war.

## Betrieb

**Job**:
Arbeit, die InfraSales selbst erledigt, nach Zeitplan oder nach einem anderen Job.
_Vermeiden_: Workflow, Task, Pipeline

**Job Run**:
Ein Durchlauf eines Jobs, vom Start bis zum Erfolg oder Fehlschlag.
_Vermeiden_: Run (allein), Ausführung

**Kuration**:
Die Prüfung unsicherer Angaben durch einen Kurator, bevor ein Projekt veröffentlicht wird. Was zu
prüfen ist, steht in der Prüfliste.

**Backoffice**:
Der Bereich der Oberfläche für unser eigenes Team: Dashboard, Feeds, Sources, Jobs, Läufe,
Prüfliste, Audit und Einstellungen.

**Dashboard**:
Die Übersicht im Backoffice: wie es um das Sammeln steht, welche Läufe als Nächstes anstehen und
was geprüft werden muss.

## Kunden

**Mandant** (`tenant`):
Ein Kunde oder Teilnehmer als Organisation: ein Bauunternehmen, ein Hersteller, ein Planer, ein
Auftraggeber, ein privater Bauherr, ein Finanzierer. Unser eigenes Team ist der Plattform-Mandant.
_Vermeiden_: Account, Kunde (wenn die Organisation im System gemeint ist)

**Mitgliedschaft** (`membership`):
Dass ein Nutzer zu einem Mandanten gehört, mit seiner Rolle dort. Ein Nutzer kann mehreren
Mandanten angehören.

**Abo** (`entitlement`):
Was ein Mandant sehen darf: Sektor, Region und Laufzeit.
_Vermeiden_: Lizenz, Plan

**Datenzone**:
Wo ein Datum liegt und wer es liest: öffentlich (Projektakte, Vergaben, Vorschau), privat (nur
der Mandant) oder Pool (Kopien ohne Absender, nur für die Produkte der Auftraggeber und
Finanzierer).

**Private Daten**:
Daten, die einem Mandanten gehören und nur er sieht: Notizen, Pipeline, Watchlists, Alert-Regeln,
eigene Angebote und Preise, Nachträge, Bietentscheidungen mit Gründen, gewonnen oder verloren.

**Beigesteuerte Daten**:
Private Daten, die ein Mandant mit Einwilligung in den Pool gibt. Gezeigt werden sie nur
Auftraggebern und Finanzierern, zusammengefasst, historisch und erst ab mindestens fünf
unabhängigen Unternehmen. Bauunternehmen sehen sie nie, auch nicht zusammengefasst.

**Modelle A, B, C**:
A, die Projektprognose, ist für alle Bauunternehmen gleich und lernt nur über die Nachfrageseite.
B ist die Passung je Mandant aus dessen eigenen Daten. C sind die Benchmarks aus dem Pool für
Auftraggeber und Finanzierer.

**Vergabevorschau**:
Geplante Vergaben, die Auftraggeber für die nächsten 6 bis 24 Monate eintragen. Kostenlos und für
alle lesbar: der Einstieg in die Plattform.

**Partnersuche**:
Private Bauherren stellen Projekte ein und suchen einen Baupartner. Für sie kostenlos; die Anfragen
gehen exklusiv an zahlende Kunden.

**Kundenbereich**:
Der Bereich der Oberfläche für Kunden: Projekte, Projektakte, Prognose, Watchlist, Alerts,
Pipeline und Bietentscheidung, Export, Team.

**Öffentlicher Bereich**:
Der Bereich ohne Abo: die Vergabevorschau, das Eintragen von Vergaben durch Auftraggeber und von
Projekten durch private Bauherren.
