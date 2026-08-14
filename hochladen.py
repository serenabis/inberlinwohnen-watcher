#!/usr/bin/env python3
"""Laedt den Wohnungs-Watcher zu GitHub hoch.

Fragt das Zugangs-Token verdeckt ab und verwendet es nur fuer diesen einen
Vorgang. Es wird danach im macOS-Schluesselbund hinterlegt, damit spaetere
Uploads ohne erneute Eingabe funktionieren - und steht nirgends im Klartext.

Aufruf im Terminal:
    python3 ~/inberlinwohnen-watcher/hochladen.py
"""

import getpass
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def linie(zeichen="-"):
    print(zeichen * 66)


def git(*args, token_url=None):
    """Git aufrufen. token_url ersetzt die Remote-Adresse nur fuer diesen Aufruf."""
    befehl = ["git"] + list(args)
    ergebnis = subprocess.run(
        befehl, cwd=HERE, capture_output=True, text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    ausgabe = (ergebnis.stdout + ergebnis.stderr)
    if token_url:
        # Falls Git die Adresse in einer Fehlermeldung wiederholt, das Token
        # herausfiltern, damit es nicht auf dem Bildschirm landet.
        ausgabe = ausgabe.replace(token_url, "(Adresse mit Token)")
    return ergebnis.returncode, ausgabe.strip()


def erklaere(ausgabe, benutzer, repo):
    text = ausgabe.lower()
    if "workflow" in text and ("refus" in text or "scope" in text):
        return (
            "Dem Token fehlt die Berechtigung 'workflow'.\n\n"
            "  Der Wohnungs-Watcher enthaelt eine Datei unter\n"
            "  .github/workflows/ - dafuer verlangt GitHub diese Berechtigung\n"
            "  ausdruecklich. Erzeuge ein neues Token und setze BEIDE Haken:\n"
            "  'repo' UND 'workflow'."
        )
    if "authentication failed" in text or "invalid username or password" in text \
            or "403" in text:
        return (
            "GitHub hat das Token abgelehnt.\n\n"
            "  - Wurde das Token vollstaendig kopiert? Es beginnt mit 'ghp_'.\n"
            "  - Ist es evtl. schon abgelaufen?\n"
            "  - Beim Erzeugen den Haken bei 'repo' gesetzt?"
        )
    if "not found" in text or "404" in text:
        return (
            "GitHub findet das Repository nicht:\n"
            "  https://github.com/%s/%s\n\n"
            "  - Ist es unter github.com/new wirklich angelegt worden?\n"
            "  - Heisst es exakt 'inberlinwohnen-watcher'?\n"
            "  - Stimmt der Benutzername '%s'?" % (benutzer, repo, benutzer)
        )
    if "could not resolve host" in text or "network" in text:
        return "Keine Verbindung zu github.com. Besteht eine Internetverbindung?"
    if "non-fast-forward" in text or "fetch first" in text:
        return (
            "Im Repository liegt schon etwas, das hier fehlt.\n\n"
            "  Vermutlich wurde es doch mit README oder .gitignore angelegt.\n"
            "  Am einfachsten: das Repository auf GitHub loeschen\n"
            "  (Settings ganz unten) und leer neu anlegen."
        )
    return None


def main():
    linie("=")
    print("  Wohnungs-Watcher - Hochladen zu GitHub")
    linie("=")
    print()

    benutzer = input("Dein GitHub-Benutzername: ").strip()
    if not benutzer:
        print("\nKein Benutzername eingegeben. Abbruch.")
        return 1
    repo = "inberlinwohnen-watcher"
    print()
    print("Ziel: https://github.com/%s/%s" % (benutzer, repo))
    print()
    linie()
    print("Jetzt das Zugangs-Token (NICHT dein GitHub-Passwort).")
    print("Wie du es erzeugst, steht in der Anleitung von Claude.")
    print("Es wird beim Einfuegen nicht angezeigt - das ist normal.")
    print()
    sys.stdout.flush()
    token = getpass.getpass("Token einfuegen und Enter: ").strip()
    if not token:
        print("\nKein Token eingegeben. Abbruch.")
        return 1
    if not token.startswith(("ghp_", "github_pat_")):
        print()
        print("Warnung: Das sieht nicht nach einem GitHub-Token aus")
        print("(es sollte mit 'ghp_' oder 'github_pat_' beginnen).")
        if input("Trotzdem weitermachen? [j/N]: ").strip().lower() not in ("j", "ja"):
            return 1

    klar_url = "https://github.com/%s/%s.git" % (benutzer, repo)
    token_url = "https://%s:%s@github.com/%s/%s.git" % (benutzer, token, benutzer, repo)

    print()
    linie()
    print("Lade hoch ...")

    # Absender fuer kuenftige lokale Aenderungen festlegen.
    git("config", "user.name", benutzer)
    git("config", "user.email", "%s@users.noreply.github.com" % benutzer)

    git("remote", "remove", "origin")
    code, ausgabe = git("remote", "add", "origin", klar_url)
    if code:
        print("\nFEHLGESCHLAGEN beim Einrichten der Adresse:\n%s" % ausgabe)
        return 1

    code, ausgabe = git("push", "-u", token_url, "main:main", token_url=token_url)
    if code:
        print()
        print("FEHLGESCHLAGEN.")
        print()
        hinweis = erklaere(ausgabe, benutzer, repo)
        if hinweis:
            print(hinweis)
        else:
            print(ausgabe)
        print()
        print("Wenn du es korrigiert hast, einfach nochmal starten:")
        print("  python3 ~/inberlinwohnen-watcher/hochladen.py")
        return 1

    # Damit kuenftige Uploads das Token nicht erneut verlangen.
    git("config", "credential.helper", "osxkeychain")
    git("branch", "--set-upstream-to=origin/main", "main")

    print()
    print("GESCHAFFT. Alle Dateien liegen jetzt bei GitHub.")
    print()
    linie()
    print("Oeffne im Browser:")
    print("  https://github.com/%s/%s" % (benutzer, repo))
    print()
    print("Du solltest dort diese Dateien sehen:")
    print("  README.md, watch.py, finder.py, config.json,")
    print("  einrichten.py, hochladen.py, state/, .github/")
    print()
    print("Sag Claude Bescheid - dann kommt der letzte Schritt:")
    print("die Zugangsdaten bei GitHub hinterlegen.")
    linie()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
        sys.exit(1)
