# Datenschutz (DSGVO)

Welche personenbezogenen Daten InfraSales verarbeitet, wozu und wie lange.

> **Entwurf.** Die Rechtsgrundlagen sind noch nicht geprüft. Vor dem ersten Kunden wird dieses
> Dokument mit einer Rechtsberatung abgestimmt ([ADR 06 §8](docs/adr/06_adr_infrasales.md)).
> Bis dahin steht in der Spalte „Rechtsgrundlage“ die Grundlage, die wir annehmen.

## Grundsätze

- **Datenminimierung:** Nutzer werden über ein pseudonymes Subject erkannt (`basic:alice` oder
  das `sub` des Identity Providers). E-Mail-Adressen, Profile und Freitexte über Personen werden
  nicht gespeichert.
- **Keine Personen in der Projektakte:** Akteure sind Firmen und Organisationen. Namen von
  Personen aus Ratsdokumenten werden nicht extrahiert ([CONTEXT.md](CONTEXT.md)).
- **Zweckbindung:** Sessions dienen der Anmeldung, das Audit-Log der Nachweisbarkeit und
  Sicherheit. Beides wird für nichts anderes verwendet.
- **Speicherbegrenzung:** Jede Tabelle mit personenbezogenen Daten hat eine Frist. Gesammelte
  Dokumente sind die Ausnahme (siehe unten).

## Verzeichnis der Verarbeitungen

| Daten | Inhalt | Zweck | Rechtsgrundlage (angenommen) | Frist |
|---|---|---|---|---|
| Sessions (`auth_session`) | Subject, Anzeigename, Rolle, Hash des Tokens, Zeitstempel | Anmeldung | Art. 6 Abs. 1 lit. b DSGVO | bis zur Abmeldung oder zum Ablauf (≤ 24 h); `infrasales prune` löscht abgelaufene |
| Job-Läufe (`job_run`) | bei manuellen Läufen das Subject des Admins, der ihn gestartet hat | Betrieb und Nachverfolgung | Art. 6 Abs. 1 lit. f DSGVO | `RETENTION__JOB_RUN_DAYS` (90) nach Ende des Laufs |
| „Jetzt ausführen“-Anfragen (`job_trigger`) | Job, ein zufälliger Schlüssel je Klick, der beantwortende Lauf | eine wiederholte Anfrage mit demselben Lauf beantworten | Art. 6 Abs. 1 lit. f DSGVO | mit ihrem Lauf |
| Job-Schritte (`job_step`) | was die Versuche eines Laufs erledigt haben; bei Mails je Empfänger ein SHA-256-Hash der Adresse, nie die Adresse | einen Lauf wiederholen, ohne Arbeit doppelt zu tun oder doppelt zu mailen | Art. 6 Abs. 1 lit. f DSGVO | mit ihrem Lauf |
| Audit-Log (`audit_event`) | Subject, Aktion, Ergebnis, Ziel, Details, Netz des Clients (/24 IPv4, /48 IPv6) | Nachweisbarkeit und Sicherheit (Art. 5 Abs. 2, Art. 32 DSGVO) | Art. 6 Abs. 1 lit. c/f DSGVO | `RETENTION__AUDIT_DAYS` (180) |
| Gesammelte Dokumente (`source`, `source_version`, ihre Ordner im Sink) | veröffentlichte Dokumente (Wärmepläne, Sitzungsvorlagen, Protokolle, Ausschreibungen, Pressemitteilungen) wie abgerufen und extrahiert, mit Adresse, Abrufzeit, Antwort-Headern (nie Cookies) und Hashes. Die Texte können Personen nennen, etwa Mitglieder eines Gemeinderats | Belege für die Angaben der Projektakte | Art. 6 Abs. 1 lit. f DSGVO; Kopien nach § 44b UrhG | dauerhaft ([ADR 06 §7](docs/adr/06_adr_infrasales.md)); zu begründen |
| Projektakte (`municipality`, `actor`, `project`, `claim`, `project_actor`, `project_event`) | Fakten über Kommunen, Organisationen und Projekte; Zitate aus Dokumenten, die beiläufig Personen nennen können | das Produkt | Art. 6 Abs. 1 lit. f DSGVO | solange das Projekt geführt wird |
| Alert-Empfänger (`ALERTS__RECIPIENTS`) | E-Mail-Adressen, nur in der Konfiguration | Benachrichtigung bei Fehlern | Art. 6 Abs. 1 lit. f DSGVO | bis zur Entfernung aus der Konfiguration |
| Anwendungslogs (stdout) | Pfad, Status, Request-ID, Subject, Kopien der Audit-Einträge | Betrieb und Sicherheit | Art. 6 Abs. 1 lit. f DSGVO | durch die Log-Plattform festgelegt (dokumentieren) |
| Traces (optional: OTLP, Langfuse) | Pfade und Laufzeiten, das angemeldete Subject (`user.id`), Job-Läufe, Modellaufrufe; Prompts und Antworten nur mit `LLM__TRACE_CONTENT` | Betrieb, Fehlersuche | Art. 6 Abs. 1 lit. f DSGVO | durch das Trace-Backend festgelegt (dokumentieren) |

Das Audit-Log speichert fehlgeschlagene Anmeldungen nicht unter Namen, die es nicht gibt, weil
Menschen ihr Passwort ins Namensfeld tippen. Es speichert auch nicht die volle IP-Adresse des
Clients. Wer das Audit-Log liest, wird selbst protokolliert (`audit.read`).

Mit den Mandanten ([ADR 06 §3](docs/adr/06_adr_infrasales.md)) kommen Mitgliedschaften,
Notizen, Watchlists und Rückmeldungen von Kunden hinzu. Sie werden hier ergänzt, bevor sie
entstehen.

## Gesammelte Dokumente

Die Source Collection (ADR 03) liest die Feeds, die Admins anlegen, und legt jeden Text eines
Dokuments als Source Version ab: Rohdatei, extrahierter Text und Metadaten in einem Ordner des
Sinks, verzeichnet im Katalog.

- **Zweck:** Jede Angabe der Projektakte nennt die Source Version, aus der sie stammt. Ohne das
  Dokument ist die Angabe nicht mehr belegbar. Die Texte werden nicht veröffentlicht und nicht
  genutzt, um Profile der genannten Personen zu bilden.
- **Rechtmäßiger Zugang:** robots.txt wird beachtet. Bot-Sperren, Paywalls und andere technische
  Schutzmaßnahmen werden nicht umgangen (§ 95a UrhG). Ein maschinenlesbarer Vorbehalt gegen
  Text- und Data-Mining (§ 44b Abs. 3 UrhG) wird beachtet. Die Nutzungsbedingungen eines Portals
  werden geprüft, bevor es angebunden wird.
- **Aufbewahrung:** Source Versions werden standardmäßig nicht gelöscht, weil die Historie die
  Grundlage von Belegen und Backtest ist. Ob und wie lange das bei Texten mit Personennamen
  zulässig ist, klärt die Rechtsberatung. Wird eine Frist gesetzt (`RETENTION__SOURCE_DAYS`),
  löscht `infrasales prune` Dateien und Zeilen gemeinsam und protokolliert jede Runde.

## Dienstleister

- **Sprachmodell (z. B. OpenRouter, USA):** erhält Ausschnitte gesammelter Dokumente, aber keine
  Subjects und keine Kundendaten. Die Übermittlung in die USA (Art. 44 ff. DSGVO) und ein Vertrag
  zur Auftragsverarbeitung sind zu prüfen. Ein Anbieter mit Sitz in der EU wäre einfacher.
- **Langfuse und OTLP-Backend (optional):** erhalten Traces wie oben beschrieben.
- **Webhook für Alerts (optional):** erhält Alerts. Sie nennen Job, Lauf, Versuch und Fehlertyp,
  aber keine Subjects, keine Inhalte und keine personenbezogenen Daten.
