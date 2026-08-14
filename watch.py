#!/usr/bin/env python3
"""Beobachtet den Wohnungsfinder von inberlinwohnen.de und mailt neue Inserate.

Aufruf:
    python3 watch.py            # normaler Lauf
    python3 watch.py --dry-run  # nichts versenden, nichts speichern
    python3 watch.py --test-mail # Testmail verschicken und beenden
"""

import argparse
import datetime
import json
import os
import smtplib
import ssl
import sys
import urllib.parse
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

import finder

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
STATE_PATH = os.path.join(HERE, "state", "seen.json")

# IDs, die so lange nicht mehr in den Treffern auftauchten, werden vergessen.
# Damit waechst die Zustandsdatei nicht unbegrenzt, und eine Wohnung, die nach
# Monaten neu inseriert wird, gilt zu Recht wieder als neu.
FORGET_AFTER_DAYS = 90

# Bei Stoerungen (Seite nicht erreichbar, Aufbau geaendert) hoechstens so oft
# eine Warnmail - sonst kaeme bei einem laengeren Ausfall alle 5 Minuten eine.
ERROR_MAIL_EVERY_HOURS = 12


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def save_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# E-Mail
# --------------------------------------------------------------------------

def load_env_file():
    """Lokal hinterlegte Zugangsdaten aus .env uebernehmen.

    In GitHub Actions gibt es diese Datei nicht - dort kommen die Werte aus den
    Secrets. Bereits gesetzte Umgebungsvariablen haben Vorrang.
    """
    path = os.path.join(HERE, ".env")
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def env(name, default=None):
    """Umgebungsvariable lesen und Leerstrings wie 'nicht gesetzt' behandeln.

    Noetig wegen GitHub Actions: Dort wird `${{ secrets.X }}` auch dann in die
    Umgebung geschrieben, wenn das Secret gar nicht existiert - eben als leerer
    Text. Ein schlichtes os.environ.get(name, "587") liefert dann "" statt der
    Vorgabe, und der Lauf scheitert an einer Stelle, die mit der eigentlichen
    Ursache nichts zu tun hat.
    """
    wert = os.environ.get(name)
    if wert is None or not wert.strip():
        return default
    return wert.strip()


def smtp_settings():
    load_env_file()
    missing = [
        name
        for name in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "MAIL_TO")
        if not env(name)
    ]
    if missing:
        raise SystemExit(
            "Fehlende Konfiguration: %s\n"
            "Lokal per Umgebungsvariablen setzen, in GitHub Actions als Secrets."
            % ", ".join(missing)
        )
    roher_port = env("SMTP_PORT", "587")
    try:
        port = int(roher_port)
    except ValueError:
        raise SystemExit(
            "SMTP_PORT ist keine Zahl: %r\n"
            "Ueblich sind 587 (STARTTLS) oder 465 (durchgehend verschluesselt)."
            % roher_port
        )

    # Port 587 spricht Klartext und schaltet per STARTTLS auf TLS um, Port 465
    # ist von Anfang an verschluesselt. SMTP_SSL erlaubt es, das bei
    # abweichenden Ports selbst festzulegen.
    ssl_wahl = env("SMTP_SSL")
    if ssl_wahl is None:
        implicit_tls = port == 465
    else:
        implicit_tls = ssl_wahl.lower() in ("1", "true", "yes", "ja")

    return {
        "host": env("SMTP_HOST"),
        "port": port,
        "implicit_tls": implicit_tls,
        "user": env("SMTP_USER"),
        "password": os.environ["SMTP_PASS"],
        "sender": env("MAIL_FROM") or env("SMTP_USER"),
        "recipients": [
            a.strip() for a in env("MAIL_TO", "").split(",") if a.strip()
        ],
    }


def send_or_explain(subject, text_body, html_body=None):
    """Verschicken und im Fehlerfall erklaeren, aber den Fehler durchreichen.

    Das Durchreichen ist wichtig: Nur so bricht der Lauf ab, bevor die
    Wohnungen als gemeldet vermerkt werden - sonst waeren sie verloren.
    """
    try:
        return send_mail(subject, text_body, html_body)
    except Exception as fehler:  # noqa: BLE001 - wird erklaert und neu geworfen
        print(diagnose(fehler), file=sys.stderr)
        raise


def diagnose(fehler):
    """Aus einer SMTP-Ausnahme eine verstaendliche Erklaerung machen.

    Laeuft vor allem in GitHub Actions: Dort liest niemand gern einen Traceback,
    und der haeufigste Fall - der Mailserver laesst den Versand aus fremden
    Netzen nicht zu - sieht einem falschen Passwort zum Verwechseln aehnlich.
    """
    host = os.environ.get("SMTP_HOST", "(unbekannt)")
    text = str(fehler)
    kopf = "MAILVERSAND FEHLGESCHLAGEN (%s)" % host
    strich = "=" * len(kopf)

    if isinstance(fehler, smtplib.SMTPAuthenticationError):
        grund = (
            "Der Server hat die Anmeldung abgelehnt.\n\n"
            "Da derselbe Zugang lokal funktioniert hat, ist die wahrscheinlichste\n"
            "Ursache: Dieser Mailserver erlaubt den Versand nur aus dem eigenen\n"
            "Netz - und GitHub laeuft in einem Rechenzentrum.\n\n"
            "Zweite Moeglichkeit: In den Secrets steckt ein Tippfehler.\n"
            "Pruefe SMTP_USER und SMTP_PASS, danach hilft nur ein Wechsel des\n"
            "Absenders (z. B. web.de oder GMX)."
        )
    elif isinstance(fehler, smtplib.SMTPSenderRefused):
        grund = (
            "Der Server akzeptiert die Absenderadresse nicht.\n"
            "MAIL_FROM muss meist zum Anmeldenamen passen."
        )
    elif isinstance(fehler, smtplib.SMTPRecipientsRefused):
        grund = "Der Server hat die Empfaengeradresse abgelehnt (MAIL_TO pruefen)."
    elif isinstance(fehler, (smtplib.SMTPConnectError, TimeoutError, OSError)):
        grund = (
            "Es kam keine Verbindung zustande.\n\n"
            "Moeglich: Der Server blockt Verbindungen aus Rechenzentren, oder\n"
            "SMTP_HOST bzw. SMTP_PORT stimmen nicht."
        )
    else:
        grund = "Unerwarteter Fehler."

    return "\n%s\n%s\n\n%s\n\nTechnische Meldung: %s\n" % (
        kopf, strich, grund, text)


def send_mail(subject, text_body, html_body=None):
    cfg = smtp_settings()
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = cfg["sender"]
    message["To"] = ", ".join(cfg["recipients"])
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain="inberlinwohnen-watcher.local")
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()
    if cfg["implicit_tls"]:
        server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=60, context=context)
    else:
        server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=60)
    with server:
        server.ehlo()
        if not cfg["implicit_tls"]:
            server.starttls(context=context)
            server.ehlo()
        server.login(cfg["user"], cfg["password"])
        server.send_message(message)
    return cfg["recipients"]


# --------------------------------------------------------------------------
# Darstellung
# --------------------------------------------------------------------------

def finder_link(config):
    q = config.get("q")
    if not q:
        return finder.BASE_URL
    return finder.BASE_URL + "?" + urllib.parse.urlencode(
        {"q": urllib.parse.unquote(q)}
    )


def headline(item):
    parts = []
    if item["rooms"]:
        parts.append("%s Zi." % item["rooms"])
    if item["area"]:
        parts.append("%s m2" % item["area"])
    if item["rentNet"]:
        parts.append("%s EUR kalt" % item["rentNet"])
    where = item["district"] or "Berlin"
    return "%s - %s" % (" / ".join(parts) if parts else "Wohnung", where)


def item_text(item):
    lines = [headline(item)]
    address = " ".join(x for x in (item["street"], item["number"]) if x)
    location = ", ".join(x for x in (address, item["zipCode"], item["district"]) if x)
    if location:
        lines.append("  " + location)
    for label, value in item["details"]:
        if label == "Adresse" or not value:
            continue
        lines.append("  %s: %s" % (label, value))
    if item["company"]:
        lines.append("  Vermieterin: %s" % item["company"])
    if item["title"]:
        lines.append("  Hinweis: %s" % item["title"])
    if item["deeplink"]:
        lines.append("  Zum Angebot: %s" % item["deeplink"])
    return "\n".join(lines)


def esc(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def item_html(item):
    address = " ".join(x for x in (item["street"], item["number"]) if x)
    location = ", ".join(x for x in (address, item["zipCode"], item["district"]) if x)
    rows = "".join(
        '<tr><td style="padding:2px 12px 2px 0;color:#555;white-space:nowrap;">%s</td>'
        '<td style="padding:2px 0;">%s</td></tr>' % (esc(label), esc(value))
        for label, value in item["details"]
        if label != "Adresse" and value
    )
    badge = ""
    if item["hasWbs"]:
        badge = (
            '<span style="background:#fde68a;color:#78350f;border-radius:4px;'
            'padding:1px 6px;font-size:12px;margin-left:8px;">WBS</span>'
        )
    button = ""
    if item["deeplink"]:
        button = (
            '<p style="margin:12px 0 0;"><a href="%s" '
            'style="background:#1d4ed8;color:#fff;text-decoration:none;'
            'padding:8px 14px;border-radius:6px;display:inline-block;">'
            'Zum Angebot bei %s</a></p>'
            % (esc(item["deeplink"]), esc(item["company"] or "der Vermieterin"))
        )
    note = ""
    if item["title"]:
        note = (
            '<p style="margin:8px 0 0;color:#444;font-style:italic;">%s</p>'
            % esc(item["title"])
        )
    return (
        '<div style="border:1px solid #e5e7eb;border-radius:8px;padding:16px;'
        'margin:0 0 16px;">'
        '<h2 style="margin:0 0 4px;font-size:17px;">%s%s</h2>'
        '<p style="margin:0 0 10px;color:#555;">%s</p>'
        '<table style="border-collapse:collapse;font-size:14px;">%s</table>'
        "%s%s</div>"
        % (esc(headline(item)), badge, esc(location), rows, note, button)
    )


def build_mail(items, config, note=None, seeding=False):
    link = finder_link(config)
    count = len(items)

    if seeding:
        subject = "Wohnungs-Watcher aktiv (%d Wohnungen im Bestand)" % count
        intro = (
            "Der Waechter laeuft ab jetzt. Die aktuell %d passenden Wohnungen "
            "gelten als bekannt; ab sofort bekommst du nur noch neue Inserate "
            "gemeldet. Unten die drei zuletzt eingestellten zur Kontrolle."
            % count
        )
        shown = items[:3]
    else:
        subject = "%d neue Wohnung%s: %s" % (
            count,
            "en" if count != 1 else "",
            ", ".join(sorted({i["district"] for i in items if i["district"]}))
            or "Berlin",
        )
        intro = "Neu im Wohnungsfinder der landeseigenen Wohnungsunternehmen:"
        shown = items

    blocks = [intro]
    if note:
        blocks.append("ACHTUNG: " + note)
    blocks += [item_text(i) for i in shown]
    blocks.append("Alle Treffer mit deinem Filter: " + link)

    warning = ""
    if note:
        warning = (
            '<p style="background:#fef3c7;border-left:4px solid #f59e0b;'
            'padding:10px 14px;margin:0 0 16px;">%s</p>' % esc(note)
        )
    html_body = (
        '<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;'
        'max-width:640px;margin:0 auto;padding:8px;color:#111;">'
        '<p style="margin:0 0 16px;">%s</p>%s%s'
        '<p style="margin:20px 0 0;font-size:14px;">'
        '<a href="%s">Alle Treffer mit deinem Filter ansehen</a></p>'
        '<p style="margin:24px 0 0;font-size:12px;color:#888;">'
        "Automatische Nachricht deines Wohnungs-Waechters.</p></div>"
        % (esc(intro), warning, "".join(item_html(i) for i in shown), esc(link))
    )
    return subject, "\n\n".join(blocks), html_body


# --------------------------------------------------------------------------
# Ablauf
# --------------------------------------------------------------------------

def prune(seen, stamp):
    cutoff = (stamp - datetime.timedelta(days=FORGET_AFTER_DAYS)).date()
    kept = {}
    for key, value in seen.items():
        try:
            when = datetime.date.fromisoformat(str(value)[:10])
        except (TypeError, ValueError):
            continue
        if when >= cutoff:
            kept[key] = value
    return kept


def report_error(state, message, dry_run):
    """Warnmail schicken, aber hoechstens alle ERROR_MAIL_EVERY_HOURS Stunden."""
    stamp = now()
    last = state.get("last_error_mail")
    if last:
        try:
            age = stamp - datetime.datetime.fromisoformat(last)
            if age < datetime.timedelta(hours=ERROR_MAIL_EVERY_HOURS):
                return False
        except (TypeError, ValueError):
            pass
    if dry_run:
        print("[dry-run] Warnmail waere verschickt worden: %s" % message)
        return False
    send_mail(
        "Wohnungs-Watcher: Problem beim Abrufen",
        "Der Waechter konnte den Wohnungsfinder nicht auswerten.\n\n"
        "%s\n\nEr versucht es beim naechsten Lauf erneut. Kommt diese Meldung "
        "wiederholt, hat sich vermutlich der Aufbau der Seite geaendert."
        % message,
    )
    state["last_error_mail"] = stamp.isoformat()
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="nichts versenden und nichts speichern")
    parser.add_argument("--test-mail", action="store_true",
                        help="nur eine Testmail verschicken")
    args = parser.parse_args()

    if args.test_mail:
        try:
            to = send_mail(
                "Wohnungs-Watcher: Testmail",
                "Wenn du das liest, funktioniert der Mailversand.",
                '<p style="font-family:sans-serif;">Wenn du das liest, funktioniert '
                "der Mailversand.</p>",
            )
        except Exception as fehler:  # noqa: BLE001 - Ursache wird uebersetzt
            print(diagnose(fehler), file=sys.stderr)
            return 1
        print("Testmail verschickt an: %s" % ", ".join(to))
        return 0

    load_env_file()
    config = load_json(CONFIG_PATH, {})
    # Der Suchfilter gehoert niemandem ausser dir: er kommt aus der Umgebung
    # (lokal aus .env, bei GitHub aus dem Secret FINDER_Q), damit er nicht im
    # Repository steht. config.json dient nur noch als Rueckfallebene.
    search_q = env("FINDER_Q") or config.get("q")
    if not search_q:
        print("Warnung: kein Suchfilter gesetzt (FINDER_Q) - es wird "
              "ungefiltert geprueft.", file=sys.stderr)
    config = dict(config, q=search_q)

    state = load_json(STATE_PATH, {})
    seen = state.get("seen") or {}
    seeding = not seen

    try:
        item_ids, by_id, _params, note = finder.collect_with_fallback(config.get("q"))
    except finder.FinderError as exc:
        print("Fehler: %s" % exc, file=sys.stderr)
        if report_error(state, str(exc), args.dry_run) and not args.dry_run:
            save_json(STATE_PATH, state)
        return 1

    state.pop("last_error_mail", None)
    stamp = now()
    new_ids = [i for i in item_ids if str(i) not in seen]

    # Details fuer neue Wohnungen nachladen, die nicht auf Seite 1 standen.
    outstanding = [i for i in new_ids if i not in by_id]
    if outstanding and note is None:
        try:
            _ids, more, _p = finder.collect(config.get("q"), need_ids=outstanding)
            by_id.update(more)
        except finder.FinderError as exc:
            print("Warnung: Details unvollstaendig (%s)" % exc, file=sys.stderr)

    print("%d Treffer gesamt, %d davon neu%s"
          % (len(item_ids), len(new_ids), " (Erstlauf)" if seeding else ""))

    # `itemIds` ist nach ID sortiert, nicht nach Datum - fuer die Mail selbst
    # nach Einstelldatum absteigend ordnen, damit das Neueste oben steht.
    new_items = sorted(
        (by_id[i] for i in new_ids if i in by_id),
        key=lambda item: item.get("createdAt") or "",
        reverse=True,
    )

    if seeding:
        # Beim ersten Lauf nicht den kompletten Bestand mailen.
        if new_items and not args.dry_run:
            subject, text, html_body = build_mail(new_items, config, note, seeding=True)
            to = send_or_explain(subject, text, html_body)
            print("Startmail verschickt an: %s" % ", ".join(to))
        elif args.dry_run:
            print("[dry-run] Startmail mit %d Wohnungen im Bestand" % len(item_ids))
    elif new_items:
        subject, text, html_body = build_mail(new_items, config, note)
        if args.dry_run:
            print("[dry-run] Mail: %s\n\n%s" % (subject, text))
        else:
            to = send_or_explain(subject, text, html_body)
            print("Mail verschickt an: %s" % ", ".join(to))
    elif new_ids:
        print("Warnung: %d neue IDs ohne Details - werden erst spaeter gemeldet."
              % len(new_ids), file=sys.stderr)

    if args.dry_run:
        return 0

    # Neue Wohnungen, deren Details nicht geladen werden konnten, bleiben
    # ungemerkt: lieber beim naechsten Lauf noch einmal versuchen als eine
    # Wohnung stillschweigend verschlucken. Beim Erstlauf gilt das nicht - dort
    # wird der gesamte Bestand bewusst als bekannt verbucht.
    unresolved = set() if seeding else {i for i in new_ids if i not in by_id}
    if unresolved:
        print("%d Wohnungen bleiben fuer den naechsten Lauf offen." % len(unresolved))

    # Nur auf den Tag genau vermerken: Der Workflow schreibt die Datei nach
    # jedem Lauf ins Repository zurueck, und ein sekundengenauer Zeitstempel
    # wuerde sie alle fuenf Minuten aendern - knapp 300 Commits taeglich, nur
    # weil die Uhr weitergelaufen ist. Fuer das Vergessen nach 90 Tagen genuegt
    # das Datum, und die Datei aendert sich jetzt nur noch, wenn sich der
    # Wohnungsbestand tatsaechlich bewegt hat.
    heute = stamp.date().isoformat()
    marked = dict(seen)
    for item_id in item_ids:
        if item_id in unresolved:
            continue
        marked[str(item_id)] = heute
    state["seen"] = prune(marked, stamp)
    state.pop("last_run", None)
    state.pop("result_count", None)
    if state != load_json(STATE_PATH, None):
        save_json(STATE_PATH, state)
        print("Zustand aktualisiert.")
    else:
        print("Zustand unveraendert.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
