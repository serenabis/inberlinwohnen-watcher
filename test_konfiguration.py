#!/usr/bin/env python3
"""Prueft das Einlesen der Zugangsdaten - besonders den Fall leerer Secrets.

GitHub Actions schreibt `${{ secrets.X }}` auch dann in die Umgebung, wenn das
Secret nicht existiert: als leeren Text. Genau daran ist der erste Cloud-Lauf
gescheitert. Diese Pruefungen halten den Fall fest, damit er nicht zurueckkehrt.

Aufruf:
    python3 test_konfiguration.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import watch  # noqa: E402

BASIS = {
    "SMTP_HOST": "smtp.beispiel.de",
    "SMTP_USER": "konto@beispiel.de",
    "SMTP_PASS": "geheim",
    "MAIL_TO": "ziel@beispiel.org",
}


def mit_umgebung(werte):
    """Umgebung exakt setzen - .env darf nicht hineinfunken."""
    for name in list(os.environ):
        if name.startswith(("SMTP_", "MAIL_", "FINDER_")):
            del os.environ[name]
    os.environ.update(werte)
    watch.load_env_file = lambda: None  # lokale .env ausblenden
    return watch.smtp_settings()


pruefungen = []


def pruefe(beschreibung, bedingung):
    pruefungen.append((beschreibung, bool(bedingung)))


# Der Fall, der in der Cloud abgestuerzt ist.
cfg = mit_umgebung({**BASIS, "SMTP_PORT": "", "MAIL_FROM": "", "SMTP_SSL": ""})
pruefe("leeres SMTP_PORT faellt auf 587 zurueck", cfg["port"] == 587)
pruefe("leeres MAIL_FROM faellt auf SMTP_USER zurueck",
       cfg["sender"] == "konto@beispiel.de")
pruefe("leeres SMTP_SSL bedeutet STARTTLS", cfg["implicit_tls"] is False)

# Ganz fehlende Variablen muessen sich genauso verhalten.
cfg = mit_umgebung(dict(BASIS))
pruefe("fehlendes SMTP_PORT faellt auf 587 zurueck", cfg["port"] == 587)
pruefe("fehlendes MAIL_FROM faellt auf SMTP_USER zurueck",
       cfg["sender"] == "konto@beispiel.de")

# Gesetzte Werte muessen weiterhin gelten.
cfg = mit_umgebung({**BASIS, "SMTP_PORT": "465", "MAIL_FROM": "absender@beispiel.de"})
pruefe("Port 465 schaltet auf durchgehendes TLS", cfg["implicit_tls"] is True)
pruefe("Port 465 wird uebernommen", cfg["port"] == 465)
pruefe("MAIL_FROM wird uebernommen", cfg["sender"] == "absender@beispiel.de")

cfg = mit_umgebung({**BASIS, "SMTP_PORT": "2525", "SMTP_SSL": "1"})
pruefe("SMTP_SSL=1 erzwingt TLS auch bei fremdem Port", cfg["implicit_tls"] is True)

# Leerzeichen beim Kopieren in die GitHub-Oberflaeche.
cfg = mit_umgebung({**BASIS, "SMTP_PORT": " 587 ", "MAIL_TO": " ziel@beispiel.org "})
pruefe("Leerzeichen um den Port stoeren nicht", cfg["port"] == 587)
pruefe("Leerzeichen um die Empfaenger stoeren nicht",
       cfg["recipients"] == ["ziel@beispiel.org"])

cfg = mit_umgebung({**BASIS, "MAIL_TO": "eins@beispiel.org, zwei@beispiel.org"})
pruefe("mehrere Empfaenger werden getrennt", len(cfg["recipients"]) == 2)

# Fehlende Pflichtangaben muessen verstaendlich abbrechen, nicht abstuerzen.
try:
    mit_umgebung({**BASIS, "SMTP_HOST": ""})
    pruefe("leeres SMTP_HOST wird bemaengelt", False)
except SystemExit as ende:
    pruefe("leeres SMTP_HOST wird bemaengelt", "SMTP_HOST" in str(ende))

# Unsinniger Port: verstaendliche Meldung statt Programmabsturz.
try:
    mit_umgebung({**BASIS, "SMTP_PORT": "fuenfhundert"})
    pruefe("unsinniger Port wird bemaengelt", False)
except SystemExit as ende:
    pruefe("unsinniger Port wird bemaengelt", "SMTP_PORT" in str(ende))
except ValueError:
    pruefe("unsinniger Port wird bemaengelt", False)

print("Konfigurationspruefungen")
print("=" * 52)
fehler = 0
for beschreibung, ok in pruefungen:
    print("  [%s] %s" % ("OK" if ok else "FEHLER", beschreibung))
    fehler += 0 if ok else 1
print("=" * 52)
print("%d von %d bestanden" % (len(pruefungen) - fehler, len(pruefungen)))
sys.exit(1 if fehler else 0)
