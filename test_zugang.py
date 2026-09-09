#!/usr/bin/env python3
"""Prueft Zugangsdaten fuer den Mailversand - mit genau EINEM Anmeldeversuch.

Warum eigenstaendig: Ein falsches Passwort merkt man sonst erst, wenn der
Waechter im Minutentakt scheitert - und genau dafuer sperren Mailanbieter
Konten. Hier wird einmal verbunden, einmal angemeldet, und das Ergebnis im
Klartext erklaert.

Das Passwort wird verdeckt abgefragt und nirgends gespeichert.

Aufruf:
    python3 test_zugang.py                      # fragt alles ab
    python3 test_zugang.py --aus-env            # nimmt die Werte aus .env
    python3 test_zugang.py --senden             # verschickt zusaetzlich eine Testmail
"""

import argparse
import getpass
import os
import smtplib
import ssl
import sys

HIER = os.path.dirname(os.path.abspath(__file__))

# Die gaengigen Anbieter, damit niemand Ports und Hostnamen raten muss.
ANBIETER = {
    "web.de": ("smtp.web.de", 587),
    "gmx": ("mail.gmx.net", 587),
    "gmail": ("smtp.gmail.com", 587),
    "posteo": ("posteo.de", 587),
    "mailbox.org": ("smtp.mailbox.org", 587),
}


def aus_env():
    werte = {}
    pfad = os.path.join(HIER, ".env")
    try:
        with open(pfad, encoding="utf-8") as handle:
            zeilen = handle.readlines()
    except OSError:
        raise SystemExit("Keine .env gefunden (%s)." % pfad)
    for zeile in zeilen:
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        schluessel, _, wert = zeile.partition("=")
        werte[schluessel.strip()] = wert.strip()
    return werte


def frage(text, vorgabe=None):
    zusatz = " [%s]" % vorgabe if vorgabe else ""
    antwort = input("%s%s: " % (text, zusatz)).strip()
    return antwort or vorgabe or ""


def erklaere(fehler, host, user, passwort):
    """Aus dem Fehler eine Handlungsanweisung machen, keine Fehlermeldung."""
    if isinstance(fehler, UnicodeEncodeError):
        return (
            "Das Passwort enthaelt ein Sonderzeichen (Umlaut oder ß), das\n"
            "Pythons Mailversand nicht uebertragen kann.\n\n"
            "Loesung: beim Anbieter ein Passwort ohne Sonderzeichen setzen\n"
            "oder ein App-Passwort erzeugen (nur Buchstaben und Ziffern)."
        )
    if isinstance(fehler, smtplib.SMTPAuthenticationError):
        hinweise = [
            "Der Server sagt: Zugangsdaten nicht akzeptiert. Der Reihe nach pruefen:",
            "",
            "1. Stimmt der BENUTZERNAME? Viele Anbieter wollen die volle",
            "   Mailadresse (dein-name@web.de), nicht nur den Kontonamen.",
            "   Aktuell versucht: %r" % user,
            "2. Ist der Zugriff durch externe Programme freigeschaltet?",
            "   Bei web.de/GMX: Einstellungen -> POP3/IMAP Abruf aktivieren.",
            "3. Hat das Konto Zwei-Faktor-Anmeldung? Dann funktioniert das",
            "   normale Passwort NICHT - es braucht ein App-Passwort.",
        ]
        if not passwort.isascii():
            hinweise.append(
                "4. Das Passwort enthaelt Sonderzeichen - manche Server\n"
                "   vergleichen die anders als erwartet. Ein App-Passwort\n"
                "   (nur Buchstaben/Ziffern) umgeht das Problem."
            )
        return "\n".join(hinweise)
    if isinstance(fehler, smtplib.SMTPNotSupportedError):
        return ("Der Server bietet keine Anmeldung ueber diesen Port an.\n"
                "Meist hilft Port 465 (durchgehend verschluesselt).")
    return ("Es kam keine Verbindung zustande.\n"
            "Stimmen Servername (%s) und Port? Blockt eine Firewall?" % host)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aus-env", action="store_true",
                        help="Werte aus der Datei .env nehmen")
    parser.add_argument("--senden", action="store_true",
                        help="nach erfolgreicher Anmeldung eine Testmail schicken")
    args = parser.parse_args()

    werte = aus_env() if args.aus_env else {}

    if args.aus_env:
        host = werte.get("SMTP_HOST", "")
        port = int(werte.get("SMTP_PORT") or 587)
        user = werte.get("SMTP_USER", "")
        passwort = werte.get("SMTP_PASS", "")
        empfaenger = werte.get("MAIL_TO", "")
        absender = werte.get("MAIL_FROM") or user
        print("Aus .env: %s:%d als %r" % (host, port, user))
    else:
        print("Bekannte Anbieter: %s" % ", ".join(sorted(ANBIETER)))
        wahl = frage("Anbieter (oder leer fuer eigenen Server)").lower()
        if wahl in ANBIETER:
            host, port = ANBIETER[wahl]
            print("  -> %s:%d" % (host, port))
        else:
            host = frage("SMTP-Server")
            port = int(frage("Port", "587"))
        user = frage("Benutzername (meist die volle Mailadresse)")
        passwort = getpass.getpass("Passwort (wird nicht angezeigt): ")
        absender = frage("Absenderadresse", user)
        empfaenger = frage("Empfaenger fuer die Testmail", absender)

    if not host or not user or not passwort:
        raise SystemExit("Server, Benutzername und Passwort werden gebraucht.")

    print("\nVerbinde zu %s:%d ..." % (host, port))
    kontext = ssl.create_default_context()
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=30, context=kontext)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
        with server:
            server.ehlo()
            if port != 465:
                server.starttls(context=kontext)
                server.ehlo()
            print("Verschluesselte Verbindung steht.")
            print("Angebotene Anmeldeverfahren: %s"
                  % server.esmtp_features.get("auth", "(keine)"))
            server.login(user, passwort)
            print("\n*** ANMELDUNG ERFOLGREICH ***")
            print("Diese Werte kannst du als Secrets hinterlegen:")
            print("  SMTP_HOST = %s" % host)
            print("  SMTP_PORT = %d" % port)
            print("  SMTP_USER = %s" % user)
            print("  SMTP_PASS = (das gerade eingegebene Passwort)")

            if args.senden and empfaenger:
                from email.message import EmailMessage
                nachricht = EmailMessage()
                nachricht["Subject"] = "Testmail des Wohnungs-Waechters"
                nachricht["From"] = absender
                nachricht["To"] = empfaenger
                nachricht.set_content(
                    "Wenn du das liest, funktioniert der Mailversand.")
                server.send_message(nachricht)
                print("\nTestmail verschickt an %s." % empfaenger)
    except Exception as fehler:  # noqa: BLE001 - wird uebersetzt
        print("\n*** ANMELDUNG FEHLGESCHLAGEN ***")
        print("Technische Meldung: %s\n" % fehler)
        print(erklaere(fehler, host, user, passwort))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
