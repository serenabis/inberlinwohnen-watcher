# Wohnungs-Watcher für inberlinwohnen.de

Prüft rund um die Uhr den Wohnungsfinder der landeseigenen Berliner
Wohnungsunternehmen und schickt eine E-Mail, sobald eine Wohnung neu inseriert
wird, die zum gespeicherten Suchfilter passt.

Läuft kostenlos in GitHub Actions – also unabhängig davon, ob der eigene Rechner
an ist. Kein Login bei inberlinwohnen.de nötig, keine externen Bibliotheken.

## Wie es funktioniert

Der Wohnungsfinder ist eine Livewire-Anwendung. Jede Wohnung steckt als JSON in
einem `wire:snapshot`-Attribut im HTML, und die Hauptkomponente liefert unter
`itemIds` die **vollständige** Liste aller Treffer-IDs – nicht nur die zehn
Wohnungen der angezeigten Seite. Ein Abruf von Seite 1 genügt deshalb, um jede
Änderung am Trefferbestand zu erkennen; Details werden nur für tatsächlich neue
Wohnungen nachgeladen.

Der gespeicherte Suchfilter steckt im `q`-Parameter der Adresszeile. Er ist
serverseitig verschlüsselt, funktioniert aber auch ohne Anmeldung.

## Einrichtung

### 1. Repository anlegen

```bash
cd inberlinwohnen-watcher
git init && git add -A && git commit -m "Wohnungs-Watcher"
```

Dann auf github.com ein **privates** Repository anlegen und hochladen:

```bash
git remote add origin git@github.com:<DEIN-NAME>/inberlinwohnen-watcher.git
git branch -M main && git push -u origin main
```

### 2. Postausgang wählen

Zum Versenden wird ein Mailkonto benötigt, das SMTP erlaubt. Empfangen wird an
die Adresse in `MAIL_TO` – das kann eine ganz andere sein.

| Anbieter   | `SMTP_HOST`                    | `SMTP_PORT` | Voraussetzung                                             |
|------------|--------------------------------|-------------|-----------------------------------------------------------|
| web.de     | `smtp.web.de`                  | `587`       | In den Einstellungen „POP3/IMAP-Zugriff“ aktivieren        |
| GMX        | `mail.gmx.net`                 | `587`       | dito                                                      |
| Gmail      | `smtp.gmail.com`               | `587`       | 2FA an, dann ein App-Passwort erzeugen                     |
| HU Berlin  | `mailhost.cms.hu-berlin.de`    | `587`       | HU-Account; Versand von außerhalb ggf. gesperrt            |

Das normale Web-Passwort funktioniert bei Gmail nicht und bei web.de/GMX nur,
wenn kein App-Passwort eingerichtet ist. Im Zweifel ein App-Passwort anlegen.

### 3. Secrets hinterlegen

Im Repository unter **Settings → Secrets and variables → Actions → New
repository secret** anlegen:

| Name        | Beispiel                        | Pflicht |
|-------------|---------------------------------|---------|
| `SMTP_HOST` | `smtp.web.de`                   | ja      |
| `SMTP_PORT` | `587`                           | nein (Vorgabe 587) |
| `SMTP_SSL`  | `1` für durchgehendes TLS       | nein (automatisch bei Port 465) |
| `SMTP_USER` | `dein-konto@web.de`             | ja      |
| `SMTP_PASS` | das App-Passwort                | ja      |
| `MAIL_FROM` | `dein-konto@web.de`             | nein (Vorgabe = `SMTP_USER`) |
| `MAIL_TO`   | `wohin-die-meldungen-sollen@example.org` | ja |
| `FINDER_Q`  | der Suchfilter (siehe unten)    | ja      |

`MAIL_TO` verträgt mehrere Adressen, durch Komma getrennt.

### 4. Starten

Unter **Actions → Wohnungs-Watcher → Run workflow** einmal von Hand auslösen.

Der erste Lauf meldet **nicht** den gesamten Bestand, sondern merkt sich alle
aktuell passenden Wohnungen und schickt nur eine kurze Bestätigungsmail. Ab dann
kommt Post ausschließlich bei echten Neuzugängen.

Danach läuft der Workflow selbstständig alle fünf Minuten. GitHub garantiert
diesen Takt nicht – unter Last werden geplante Läufe verzögert, in der Praxis
sind es eher 5 bis 15 Minuten.

## Suchfilter ändern

Auf inberlinwohnen.de die Kriterien im Wohnungsfinder einstellen, den Link aus
der Adresszeile kopieren und alles zwischen `?q=` und `&page=` übernehmen (das
abschließende `%3D` gehört dazu). Dieser Token gehört an **zwei** Stellen:

* **GitHub → Settings → Secrets and variables → Actions → `FINDER_Q`** — das
  ist die Stelle, die der 5-Minuten-Lauf tatsächlich benutzt.
* `.env` auf dem eigenen Rechner — nur für lokale Testläufe.

Der aktuell hinterlegte Filter:

* **Bezirke:** Charlottenburg-Wilmersdorf, Friedrichshain-Kreuzberg,
  Lichtenberg, Mitte, Neukölln, Pankow, Tempelhof-Schöneberg, Treptow-Köpenick
* **Zimmer:** ab 2
* **Kaltmiete:** bis 1400 €
* ergibt rund 124 von 274 Wohnungen

### Ortsteile

Der Wohnungsfinder kennt nur Bezirke. Die feinere Eingrenzung auf Ortsteile
passiert deshalb im Watcher selbst, anhand der Postleitzahl
(`ORTSTEIL_PLZ` in `finder.py`):

| Bezirk | gewünschte Ortsteile |
| --- | --- |
| Mitte | alle |
| Friedrichshain-Kreuzberg | alle |
| Neukölln | nur Neukölln (ohne Britz, Buckow, Gropiusstadt, Rudow) |
| Pankow | Prenzlauer Berg, Weißensee, Pankow |
| Lichtenberg | Lichtenberg, Rummelsburg |
| Treptow-Köpenick | Alt-Treptow, Plänterwald |
| Tempelhof-Schöneberg | Schöneberg, Tempelhof |
| Charlottenburg-Wilmersdorf | Charlottenburg, Charlottenburg-Nord |

Von den 124 Treffern des Bezirksfilters bleiben so rund 18 übrig.

Einige Postleitzahlen liegen auf einer Ortsteilgrenze und lassen sich nicht
eindeutig zuordnen (etwa 10367: Lichtenberg *und* Fennpfuhl). Solche Wohnungen
werden **gemeldet** und in der Mail mit „Ortsteil prüfen" markiert — lieber ein
Inserat zu viel ansehen als eines verpassen. Sie stehen in
`ORTSTEIL_PLZ_UNKLAR`.

Sollte der Token einmal ungültig werden, schaltet der Watcher automatisch auf
lokale Filterung nach denselben Kriterien um (Bezirk, Ortsteil, Zimmerzahl,
Kaltmiete — `FALLBACK_*` in `finder.py`) und weist in der Mail darauf hin.

## Wie schnell der Watcher reagiert

Die Inserate erscheinen bei inberlinwohnen.de im Minutentakt (ein Import legt
sie jeweils in den Sekunden 2 bis 8 einer Minute an), praktisch aber nur
werktags zwischen 8 und 20 Uhr — von 129 ausgewerteten Zeitstempeln lagen zwei
am Wochenende.

Der Engpass war nie die Website, sondern GitHub: `cron` ist eine Bitte, keine
Zusage. Geplante Läufe werden unter Last 10 bis 30 Minuten verzögert oder
ganz übersprungen.

Deshalb startet der Cron jetzt nur noch **alle 30 Minuten** einen Job, und
dieser Job prüft **28 Minuten lang selbst weiter** (`watch.py --dauer 1680`):

* werktags 5–20 Uhr UTC: **jede Minute**
* sonst: alle 5 Minuten

Die Reaktionszeit hängt damit nicht mehr an GitHubs Warteschlange, sondern
liegt bei rund einer Minute. Der Zustand wird während der Schleife nur in die
Datei geschrieben; ins Repository zurück schreibt ihn der Workflow einmal am
Jobende — sonst entstünden hunderte Commits am Tag.

Für öffentliche Repositories rechnet GitHub keine Actions-Minuten ab, der
Dauerbetrieb kostet also nichts. Die Taktweiten stehen als `TAKT_*` in
`watch.py`; deutlich unter 60 Sekunden sollte man nicht gehen, sonst wird aus
regem Interesse eine Belastung für die fremde Seite.

## Lokal ausprobieren

```bash
python3 watch.py --dry-run    # zeigt die Mail an, verschickt und speichert nichts

export SMTP_HOST=smtp.web.de SMTP_USER=... SMTP_PASS=... MAIL_TO=...
python3 test_zugang.py        # Zugangsdaten pruefen (fragt das Passwort ab)
python3 test_zugang.py --aus-env  # dasselbe mit den Werten aus .env
python3 watch.py --test-mail  # nur eine Testmail
python3 watch.py              # echter Lauf
```

## Dateien

| Datei                            | Zweck                                              |
|----------------------------------|----------------------------------------------------|
| `finder.py`                      | Abruf und Auswertung des Wohnungsfinders            |
| `test_zugang.py`                 | prueft Zugangsdaten mit einem Anmeldeversuch        |
| `watch.py`                       | Abgleich mit dem Stand, Mailversand                 |
| `config.json`                    | Suchfilter (`q`)                                    |
| `state/seen.json`                | bereits gemeldete Wohnungen                         |
| `.github/workflows/watch.yml`    | Zeitplan für GitHub Actions                         |

`state/seen.json` wird vom Workflow nach jedem Lauf ins Repository
zurückgeschrieben. Das ist zugleich praktisch, weil regelmäßige Commits
verhindern, dass GitHub den Zeitplan nach 60 Tagen Inaktivität abschaltet.

Schlägt der **Mailversand** fehl, bricht der Lauf sofort ab und der Job wird
**rot**. Vorher verschluckte die Schleife solche Fehler und meldete trotzdem
Erfolg – ein abgelehntes Passwort blieb damit unbemerkt, während der Watcher
still keine einzige Wohnung meldete.

Einträge, die 90 Tage nicht mehr in den Treffern auftauchten, werden vergessen –
die Datei wächst also nicht unbegrenzt. Bei Störungen (Seite nicht erreichbar,
Aufbau geändert) kommt höchstens alle 12 Stunden eine Warnmail.
