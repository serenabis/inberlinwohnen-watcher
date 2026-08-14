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
der Adresszeile kopieren und alles hinter `?q=` als `q` in `config.json`
eintragen (das abschließende `%3D` gehört dazu). Ändern, committen, pushen.

Der aktuell hinterlegte Filter:

* **Bezirke:** Charlottenburg-Wilmersdorf, Friedrichshain-Kreuzberg,
  Lichtenberg, Mitte, Neukölln, Pankow, Tempelhof-Schöneberg, Treptow-Köpenick
* **Zimmer:** ab 1
* ergibt rund 199 von 274 Wohnungen

Sollte der Token einmal ungültig werden, schaltet der Watcher automatisch auf
lokale Filterung nach denselben Kriterien um (`FALLBACK_DISTRICTS` in
`finder.py`) und weist in der Mail darauf hin.

## Lokal ausprobieren

```bash
python3 watch.py --dry-run    # zeigt die Mail an, verschickt und speichert nichts

export SMTP_HOST=smtp.web.de SMTP_USER=... SMTP_PASS=... MAIL_TO=...
python3 watch.py --test-mail  # nur eine Testmail
python3 watch.py              # echter Lauf
```

## Dateien

| Datei                            | Zweck                                              |
|----------------------------------|----------------------------------------------------|
| `finder.py`                      | Abruf und Auswertung des Wohnungsfinders            |
| `watch.py`                       | Abgleich mit dem Stand, Mailversand                 |
| `config.json`                    | Suchfilter (`q`)                                    |
| `state/seen.json`                | bereits gemeldete Wohnungen                         |
| `.github/workflows/watch.yml`    | Zeitplan für GitHub Actions                         |

`state/seen.json` wird vom Workflow nach jedem Lauf ins Repository
zurückgeschrieben. Das ist zugleich praktisch, weil regelmäßige Commits
verhindern, dass GitHub den Zeitplan nach 60 Tagen Inaktivität abschaltet.

Einträge, die 90 Tage nicht mehr in den Treffern auftauchten, werden vergessen –
die Datei wächst also nicht unbegrenzt. Bei Störungen (Seite nicht erreichbar,
Aufbau geändert) kommt höchstens alle 12 Stunden eine Warnmail.
