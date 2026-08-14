#!/usr/bin/env python3
"""Einrichtungsassistent fuer den Mailversand.

Fragt die Zugangsdaten des Postausgangs ab, probiert sie sofort aus und
verschickt eine Testmail. Das Passwort wird verdeckt eingegeben, landet nur in
der lokalen Datei .env (nur fuer dich lesbar) und wird nirgends angezeigt.

Aufruf im Terminal:
    python3 ~/inberlinwohnen-watcher/einrichten.py
"""

import getpass
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import formatdate

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, ".env")

ANBIETER = [
    ("web.de", "smtp.web.de", 587,
     "In den web.de-Einstellungen muss 'POP3/IMAP-Zugriff' aktiviert sein."),
    ("GMX", "mail.gmx.net", 587,
     "In den GMX-Einstellungen muss 'POP3/IMAP-Zugriff' aktiviert sein."),
    ("Gmail", "smtp.gmail.com", 587,
     "Es funktioniert nur ein App-Passwort, nicht das normale Passwort."),
    ("HU Berlin", "mailhost.cms.hu-berlin.de", 587,
     "Anmeldename ist meist der HU-Account (z. B. mustermm), nicht die\n"
     "     Mailadresse. Versand aus fremden Netzen ist evtl. gesperrt."),
    ("anderer Anbieter", None, 587, ""),
]


def bisheriger_empfaenger():
    """Empfaengeradresse aus einer frueheren Einrichtung als Vorgabe anbieten.

    Sie steht nur in der lokalen .env - im Programmcode selbst taucht keine
    persoenliche Adresse auf, damit das Repository oeffentlich sein kann.
    """
    try:
        with open(ENV_PATH, encoding="utf-8") as datei:
            for zeile in datei:
                if zeile.strip().startswith("MAIL_TO="):
                    return zeile.split("=", 1)[1].strip() or None
    except OSError:
        pass
    return None


def frage(text, vorgabe=None):
    zusatz = " [%s]" % vorgabe if vorgabe else ""
    while True:
        antwort = input("%s%s: " % (text, zusatz)).strip()
        if antwort:
            return antwort
        if vorgabe:
            return vorgabe
        print("   Bitte etwas eingeben.")


def linie(zeichen="-"):
    print(zeichen * 64)


def waehle_anbieter():
    print("Es sind zwei verschiedene Adressen im Spiel:")
    print()
    print("   ABSENDER  = das Postfach, ueber das verschickt wird")
    print("               (fragt diese Seite gleich ab)")
    print("   EMPFAENGER = wo die Wohnungsmeldungen ankommen")
    print("               (fragt der Assistent weiter unten)")
    print()
    print("Beides duerfen verschiedene Adressen sein: die Meldungen landen dort,")
    print("wo du sie haben willst, egal welches Konto sie verschickt.")
    print()
    linie()
    print("Ueber welches Postfach soll VERSCHICKT werden?")
    print()
    for nummer, (name, host, _port, hinweis) in enumerate(ANBIETER, 1):
        ziel = " (%s)" % host if host else ""
        print("  %d) %s%s" % (nummer, name, ziel))
        if hinweis:
            print("     %s" % hinweis)
    print()
    while True:
        wahl = frage("Nummer eingeben", "1")
        if wahl.isdigit() and 1 <= int(wahl) <= len(ANBIETER):
            name, host, port, _ = ANBIETER[int(wahl) - 1]
            if host is None:
                host = frage("SMTP-Server (z. B. smtp.beispiel.de)")
                port = int(frage("Port", "587"))
            return name, host, port
        print("   Bitte eine der angezeigten Nummern eingeben.")


def erklaere_fehler(fehler):
    if isinstance(fehler, smtplib.SMTPAuthenticationError):
        return (
            "Der Server hat die Zugangsdaten abgelehnt.\n"
            "  - Stimmt die Adresse genau so, wie du dich sonst anmeldest?\n"
            "  - Bei web.de/GMX: ist 'POP3/IMAP-Zugriff' in den Einstellungen an?\n"
            "  - Bei Gmail: hast du ein App-Passwort erzeugt (nicht das normale)?"
        )
    if isinstance(fehler, (smtplib.SMTPConnectError, OSError)):
        return (
            "Es kam keine Verbindung zum Server zustande.\n"
            "  - Server-Adresse und Port pruefen.\n"
            "  - Besteht gerade eine Internetverbindung?"
        )
    if isinstance(fehler, smtplib.SMTPRecipientsRefused):
        return "Der Server hat die Empfaengeradresse abgelehnt. Tippfehler?"
    if isinstance(fehler, smtplib.SMTPSenderRefused):
        return (
            "Der Server erlaubt diese Absenderadresse nicht. Sie muss meist\n"
            "  identisch mit dem Anmeldenamen sein."
        )
    return str(fehler)


def sende_testmail(host, port, benutzer, passwort, absender, empfaenger):
    nachricht = EmailMessage()
    nachricht["Subject"] = "Wohnungs-Watcher: Testmail"
    nachricht["From"] = absender
    nachricht["To"] = empfaenger
    nachricht["Date"] = formatdate(localtime=True)
    nachricht.set_content(
        "Diese Testmail kommt von deinem Wohnungs-Watcher.\n\n"
        "Wenn du sie liest, funktioniert der Mailversand und die Einrichtung\n"
        "kann weitergehen."
    )
    nachricht.add_alternative(
        '<div style="font-family:sans-serif;">'
        "<p>Diese Testmail kommt von deinem <b>Wohnungs-Watcher</b>.</p>"
        "<p>Wenn du sie liest, funktioniert der Mailversand und die "
        "Einrichtung kann weitergehen.</p></div>",
        subtype="html",
    )

    kontext = ssl.create_default_context()
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=45, context=kontext)
    else:
        server = smtplib.SMTP(host, port, timeout=45)
    with server:
        server.ehlo()
        if port != 465:
            server.starttls(context=kontext)
            server.ehlo()
        server.login(benutzer, passwort)
        server.send_message(nachricht)


def schreibe_env(werte):
    zeilen = ["# Zugangsdaten fuer den Mailversand - NICHT weitergeben.",
              "# Diese Datei bleibt auf deinem Rechner (steht in .gitignore).",
              ""]
    for schluessel, wert in werte.items():
        zeilen.append("%s=%s" % (schluessel, wert))
    with open(ENV_PATH, "w", encoding="utf-8") as datei:
        datei.write("\n".join(zeilen) + "\n")
    os.chmod(ENV_PATH, 0o600)


def main():
    linie("=")
    print("  Wohnungs-Watcher - Einrichtung des Mailversands")
    linie("=")
    print()

    name, host, port = waehle_anbieter()
    print()
    linie()
    benutzer = frage("Deine Mailadresse bei %s (= Anmeldename)" % name)
    absender = frage("Absenderadresse", benutzer)
    print()
    print("Und jetzt der EMPFAENGER - hier kommen die Wohnungen an.")
    empfaenger = frage("Empfaengeradresse", bisheriger_empfaenger())
    print()
    print("Jetzt das Passwort. Es wird beim Tippen NICHT angezeigt -")
    print("das ist normal, tippe einfach und druecke Enter.")
    sys.stdout.flush()  # sonst erscheint die Abfrage vor dieser Erklaerung
    passwort = getpass.getpass("Passwort: ")
    if not passwort:
        print("\nKein Passwort eingegeben. Abbruch.")
        return 1

    print()
    linie()
    print("Verbinde mit %s:%d und verschicke eine Testmail ..." % (host, port))
    try:
        sende_testmail(host, port, benutzer, passwort, absender, empfaenger)
    except Exception as fehler:  # noqa: BLE001 - Ursache wird uebersetzt
        print()
        print("FEHLGESCHLAGEN.")
        print()
        print(erklaere_fehler(fehler))
        print()
        print("Technische Meldung: %s" % fehler)
        print()
        print("Starte den Assistenten einfach nochmal, wenn du es")
        print("korrigiert hast: python3 ~/inberlinwohnen-watcher/einrichten.py")
        return 1

    schreibe_env({
        "SMTP_HOST": host,
        "SMTP_PORT": str(port),
        "SMTP_USER": benutzer,
        "SMTP_PASS": passwort,
        "MAIL_FROM": absender,
        "MAIL_TO": empfaenger,
    })

    print()
    print("GESCHAFFT. Eine Testmail ist unterwegs an %s" % empfaenger)
    print()
    linie()
    print("Schau jetzt in dein Postfach (auch in den Spam-Ordner).")
    print()
    print("Die Zugangsdaten liegen in dieser Datei auf deinem Rechner:")
    print("  %s" % ENV_PATH)
    print()
    print("Fuer GitHub brauchst du spaeter diese Werte. Das Passwort ist")
    print("bewusst nicht abgedruckt - es ist das, was du gerade getippt hast.")
    print()
    print("  SMTP_HOST = %s" % host)
    print("  SMTP_PORT = %d" % port)
    print("  SMTP_USER = %s" % benutzer)
    print("  SMTP_PASS = (dein soeben eingegebenes Passwort)")
    print("  MAIL_FROM = %s" % absender)
    print("  MAIL_TO   = %s" % empfaenger)
    linie()
    print()
    print("Sag Claude Bescheid, dass die Testmail angekommen ist.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
        sys.exit(1)
