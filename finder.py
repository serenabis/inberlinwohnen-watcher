"""Zugriff auf den Wohnungsfinder von inberlinwohnen.de.

Die Seite rendert ihre Treffer als Livewire-Komponenten. Jede Wohnung steckt als
HTML-escapetes JSON in einem `wire:snapshot`-Attribut, und die Hauptkomponente
`apartment-finder.rentable-apartment-finder` liefert unter `itemIds` die
*vollstaendige* Menge der Treffer-IDs - nicht nur die zehn Wohnungen der
aktuellen Seite. Das macht das Erkennen neuer Inserate billig: Seite 1 holen und
`itemIds` mit dem gemerkten Stand vergleichen.

Zwei Eigenheiten, die man kennen muss:

* `itemIds` ist aufsteigend nach ID sortiert, *nicht* nach Einstelldatum. Die
  Liste taugt als Menge, nicht als Reihenfolge. Angezeigt wird dagegen nach
  `created_at` absteigend - neue Wohnungen stehen also auf Seite 1.
* Der Filter-Token `q` kommt prozentkodiert aus der Adresszeile. Wird er ein
  zweites Mal kodiert, ignoriert die Seite den Filter kommentarlos und liefert
  alle Wohnungen. Siehe `build_url`.
"""

import gzip
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://www.inberlinwohnen.de/wohnungsfinder"

# Ohne Browser-User-Agent antwortet die Seite mit 403.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip",
}

SNAPSHOT_RE = re.compile(r'wire:snapshot="([^"]*)"')

MAIN_COMPONENT = "apartment-finder.rentable-apartment-finder"
ITEM_COMPONENT = "apartment-finder.item.apartment-item"


class FinderError(RuntimeError):
    pass


TAG_RE = re.compile(r"<[^>]+>")


def _plain(value):
    """Feldwerte enthalten teils Markup (z. B. `Gasheizung<br>`) - entfernen."""
    if value is None:
        return ""
    text = TAG_RE.sub(" ", str(value))
    return " ".join(html.unescape(text).split()).strip(" ,;")


def _unwrap(value):
    """Livewire verpackt Arrays als `[daten, {"s": "arr"}]` - Marker entfernen."""
    if isinstance(value, list):
        if len(value) == 2 and isinstance(value[1], dict) and set(value[1]) == {"s"}:
            return _unwrap(value[0])
        return [_unwrap(v) for v in value]
    if isinstance(value, dict):
        return {k: _unwrap(v) for k, v in value.items()}
    return value


def build_url(page=1, q=None):
    params = {"page": str(page)}
    if q:
        # Der Token wird meist samt Prozentkodierung aus der Adresszeile kopiert
        # (er endet dann auf `%3D`). Erst dekodieren, sonst kodiert urlencode ein
        # zweites Mal - die Seite ignoriert den Filter dann stillschweigend und
        # liefert *alle* Wohnungen zurueck.
        params["q"] = urllib.parse.unquote(q)
    return BASE_URL + "?" + urllib.parse.urlencode(params)


def fetch_page(page=1, q=None, attempts=4, timeout=45):
    url = build_url(page, q)

    last_error = None
    for attempt in range(attempts):
        if attempt:
            time.sleep(2 ** attempt)
        try:
            request = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", "replace")
        except (urllib.error.URLError, OSError, gzip.BadGzipFile) as exc:
            last_error = exc
    raise FinderError("Seite %s nicht erreichbar: %s" % (url, last_error))


def _snapshots(page_html):
    for escaped in SNAPSHOT_RE.findall(page_html):
        try:
            yield json.loads(html.unescape(escaped))
        except (ValueError, TypeError):
            continue


def _parse_item(component):
    data = component["data"]
    item = _unwrap(data["item"])
    address = item.get("address") or {}
    company = item.get("company") or []
    company_name = ""
    if isinstance(company, list) and company:
        company_name = (company[0].get("name") or "").strip()
    elif isinstance(company, dict):
        company_name = (company.get("name") or "").strip()

    details = []
    for group in _unwrap(item.get("details") or []):
        if not isinstance(group, list):
            continue
        for entry in group:
            if not isinstance(entry, dict) or not entry.get("label"):
                continue
            value = _plain(entry.get("value"))
            suffix = _plain(entry.get("suffix"))
            # Einheiten nur an Zahlen haengen - sonst entsteht Unsinn
            # wie "unbekannt kWh/(a m2)".
            if suffix and any(c.isdigit() for c in value):
                value = value + " " + suffix
            details.append((entry["label"], value))

    return {
        "id": item["id"],
        "objectId": item.get("objectId") or "",
        "title": _plain(item.get("title")),
        "rooms": item.get("rooms") or "",
        "area": item.get("area") or "",
        "rentNet": item.get("rentNet") or "",
        "extraCosts": item.get("extraCosts") or "",
        "rentGross": item.get("rentGross"),
        "level": item.get("level"),
        "levelsTotal": item.get("levelsTotal"),
        "constructionYear": item.get("constructionYear") or "",
        "occupationDate": item.get("occupationDate") or "",
        "createdAt": item.get("createdAt") or "",
        "street": (address.get("street") or "").strip(),
        "number": (address.get("number") or "").strip(),
        "zipCode": (address.get("zipCode") or "").strip(),
        "district": (address.get("district") or "").strip(),
        "company": company_name,
        "deeplink": item.get("deeplink") or "",
        "hasWbs": bool(data.get("hasWbs")),
        "details": details,
    }


def parse_page(page_html):
    """Liefert (alle_treffer_ids, wohnungen_dieser_seite, suchparameter)."""
    item_ids = None
    search_params = None
    items = []
    for component in _snapshots(page_html):
        name = component.get("memo", {}).get("name")
        if name == MAIN_COMPONENT and item_ids is None:
            data = component.get("data", {})
            raw_ids = _unwrap(data.get("itemIds"))
            if isinstance(raw_ids, list):
                item_ids = [int(i) for i in raw_ids if isinstance(i, (int, str))]
            search_params = _unwrap(data.get("searchParams"))
        elif name == ITEM_COMPONENT:
            try:
                items.append(_parse_item(component))
            except (KeyError, TypeError, ValueError):
                continue
    return item_ids, items, search_params


# Sicherheitsnetz, falls der verschluesselte `q`-Token einmal ungueltig wird:
# dieselben Kriterien lokal auf die ungefilterte Liste anwenden.
FALLBACK_DISTRICTS = {
    "Charlottenburg-Wilmersdorf",
    "Friedrichshain-Kreuzberg",
    "Lichtenberg",
    "Mitte",
    "Neukölln",
    "Pankow",
    "Tempelhof-Schöneberg",
    "Treptow-Köpenick",
}
FALLBACK_MIN_ROOMS = 1.0


def matches_fallback_filter(item):
    if item.get("district") and item["district"] not in FALLBACK_DISTRICTS:
        return False
    rooms = (item.get("rooms") or "").replace(",", ".")
    try:
        if float(rooms) < FALLBACK_MIN_ROOMS:
            return False
    except ValueError:
        pass
    return True


def filter_is_active(search_params):
    """Prueft, ob der `q`-Token serverseitig noch als Suchfilter ankommt."""
    if not isinstance(search_params, dict):
        return False
    return bool(search_params.get("district"))


def collect(q=None, need_ids=None, max_pages=40, fetch_all=False):
    """Seite fuer Seite laden und Treffer einsammeln.

    Standardmaessig wird nur Seite 1 geholt - deren `itemIds` enthaelt bereits
    *alle* Treffer-IDs, und die zehn neuesten Wohnungen stehen dank Sortierung
    nach Einstelldatum ebenfalls dort. Weitere Seiten werden nur geladen, wenn
    `need_ids` Wohnungen nennt, deren Details noch fehlen.
    """
    item_ids, items, search_params = parse_page(fetch_page(1, q))
    if item_ids is None:
        raise FinderError(
            "Trefferliste (itemIds) nicht gefunden - hat sich der Seitenaufbau geaendert?"
        )

    def load_more(stop):
        page = 1
        while page < max_pages and not stop():
            page += 1
            _, more, _ = parse_page(fetch_page(page, q))
            if not more:
                break
            items.extend(more)

    if fetch_all:
        load_more(lambda: len(items) >= len(item_ids))
    elif need_ids:
        outstanding = set(need_ids)
        load_more(lambda: not outstanding - {i["id"] for i in items})

    by_id = {}
    for item in items:
        by_id.setdefault(item["id"], item)

    return item_ids, by_id, search_params


def collect_with_fallback(q):
    """Gefiltert laden; wenn der `q`-Token nicht mehr greift, lokal filtern.

    Rueckgabe: (item_ids, wohnungen_nach_id, hinweis_oder_None). Der Hinweis ist
    gesetzt, wenn auf die lokale Filterung ausgewichen wurde - dann sollte der
    gespeicherte Link auf inberlinwohnen.de erneuert werden.
    """
    item_ids, by_id, search_params = collect(q, fetch_all=False)
    if filter_is_active(search_params):
        return item_ids, by_id, search_params, None

    # Der Token wird ignoriert: alles laden und die Kriterien selbst anwenden.
    all_ids, all_items, _ = collect(None, fetch_all=True)
    kept = {k: v for k, v in all_items.items() if matches_fallback_filter(v)}
    ordered = [i for i in all_ids if i in kept]
    note = (
        "Der gespeicherte Suchfilter (q-Parameter) wird von inberlinwohnen.de "
        "nicht mehr akzeptiert. Es wurde ersatzweise lokal nach Bezirk und "
        "Zimmerzahl gefiltert. Bitte einen neuen Link aus dem Wohnungsfinder "
        "kopieren und in config.json eintragen."
    )
    return ordered, kept, None, note
