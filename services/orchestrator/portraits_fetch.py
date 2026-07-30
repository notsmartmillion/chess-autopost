"""Fetch player portraits from Wikimedia Commons, with their licences.

    python services/orchestrator/portraits_fetch.py --all
    python services/orchestrator/portraits_fetch.py "Tal, Mihail" "Botvinnik, Mikhail"

Why Commons rather than a scrape: photographs of chess players are almost all
press photography, and a press photo in a monetised video is a copyright claim.
Claims on images tend to arrive as strikes rather than demonetisation, which is
an unusually bad outcome for a channel that publishes unattended every day.
Commons files carry an explicit licence, and Wikidata already knows which file
belongs to which player, so the legitimate route is also the easy one.

Each portrait is cached as ``public/portraits/<surname>.jpg`` beside a sidecar
``<surname>.json`` holding licence, author and source URL. The build reads the
sidecars and lists any attribution-requiring image in the video description —
which is what makes this compliant rather than merely well-intentioned.

Nothing here is on the critical path: a player with no portrait renders with the
silhouette placeholder, exactly as before.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
PORTRAITS = ROOT / "apps" / "renderer" / "public" / "portraits"

# Wikimedia asks for a descriptive agent and a modest request rate; without one
# it answers 429 quickly and without much patience.
UA = "nocturne-chess/1.0 (daily chess video channel; portrait sourcing)"
PAUSE_S = 1.3

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
CHESS_PLAYER_QID = "Q10873124"  # occupation: chess player

# Licences that need a credit line in the description. CC0 and public domain
# do not, though crediting them costs nothing and is good manners.
NEEDS_ATTRIBUTION = re.compile(r"cc.?by|creative commons", re.IGNORECASE)


def _get(url: str, *, retries: int = 4) -> Optional[Dict[str, Any]]:
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except Exception as exc:  # noqa: BLE001
            if "429" in str(exc) and attempt < retries:
                time.sleep(PAUSE_S * 4 * attempt)  # they mean it
                continue
            if attempt == retries:
                return None
            time.sleep(PAUSE_S * attempt)
    return None


def _search_name(pgn_name: str) -> str:
    """"Bronstein, David I" -> "David Bronstein".

    Bare initials are dropped before searching: "David I Bronstein" matches
    nothing, because no encyclopaedia records him that way.
    """
    name = (pgn_name or "").strip()
    last, _, first = name.partition(",") if "," in name else (name, "", "")
    given = " ".join(
        part for part in first.split() if not re.fullmatch(r"[A-Za-z]\.?", part)
    )
    surname = last.strip()
    return (f"{given} {surname}".strip() if given else surname).strip()


def surname_of(pgn_name: str) -> str:
    """"Tal, Mihail" -> "tal"; "Magnus Carlsen" -> "carlsen"."""
    name = (pgn_name or "").strip()
    if not name or set(name) <= {"?", "."}:
        return ""
    first = name.split(",")[0].strip() if "," in name else name.split()[-1]
    return re.sub(r"[^a-z]", "", first.lower())


class LookupFailed(Exception):
    """The API did not answer. Distinct from answering "no such thing"."""


def _search_qid(name: str) -> Optional[str]:
    """The Wikidata id for a name, only if the entity is a chess player.

    The occupation check is the guard that matters: a bare name search will
    happily return a footballer or a town, and a wrong face is worse than none.

    Raises LookupFailed when the API itself did not answer, so a rate limit is
    never mistaken for "this player has no portrait" and cached forever.
    """
    data = _get(
        f"{WIKIDATA_API}?action=wbsearchentities&format=json&language=en&limit=5"
        f"&search={urllib.parse.quote(name)}"
    )
    if data is None:
        raise LookupFailed(f"search failed for {name}")
    for hit in data.get("search", []):
        qid = hit.get("id")
        if not qid:
            continue
        time.sleep(PAUSE_S)
        claims = _get(
            f"{WIKIDATA_API}?action=wbgetclaims&format=json&entity={qid}&property=P106"
        )
        if claims is None:
            raise LookupFailed(f"occupation lookup failed for {qid}")
        for occ in claims.get("claims", {}).get("P106", []):
            try:
                if occ["mainsnak"]["datavalue"]["value"]["id"] == CHESS_PLAYER_QID:
                    return qid
            except (KeyError, TypeError):
                continue
    return None


def _image_filename(qid: str) -> Optional[str]:
    time.sleep(PAUSE_S)
    data = _get(f"{WIKIDATA_API}?action=wbgetclaims&format=json&entity={qid}&property=P18")
    if data is None:
        raise LookupFailed(f"image lookup failed for {qid}")
    claims = data.get("claims", {}).get("P18") or []
    if not claims:
        return None
    try:
        return claims[0]["mainsnak"]["datavalue"]["value"]
    except (KeyError, TypeError):
        return None


def _strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", value or "")).strip()


def _commons_info(filename: str, width: int = 640) -> Optional[Dict[str, Any]]:
    time.sleep(PAUSE_S)
    data = _get(
        f"{COMMONS_API}?action=query&format=json&prop=imageinfo"
        f"&iiprop=extmetadata|url&iiurlwidth={width}"
        f"&titles=File:{urllib.parse.quote(filename)}"
    )
    if not data:
        return None
    pages = (data.get("query") or {}).get("pages") or {}
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        return {
            "url": url,
            "licence": _strip_html(meta.get("LicenseShortName", {}).get("value", "")),
            "author": _strip_html(meta.get("Artist", {}).get("value", "")),
            "credit": _strip_html(meta.get("Credit", {}).get("value", "")),
            "descriptionUrl": info.get("descriptionurl") or
            f"https://commons.wikimedia.org/wiki/File:{urllib.parse.quote(filename)}",
            "file": filename,
        }
    return None


def fetch_portrait(pgn_name: str, *, force: bool = False) -> Optional[Dict[str, Any]]:
    """Cache one player's portrait. Returns its credit record, or None."""
    key = surname_of(pgn_name)
    if not key:
        return None
    PORTRAITS.mkdir(parents=True, exist_ok=True)
    sidecar = PORTRAITS / f"{key}.json"
    image = PORTRAITS / f"{key}.jpg"
    if not force and sidecar.exists() and image.exists():
        try:
            return json.loads(sidecar.read_text(encoding="utf-8"))
        except ValueError:
            pass
    # A previous miss is remembered too, so an obscure opponent is not looked
    # up again on every single build.
    miss = PORTRAITS / f"{key}.none"
    if not force and miss.exists():
        return None

    display = _search_name(pgn_name)

    try:
        qid = _search_qid(display)
        if not qid:
            # Surname alone catches the many players whose PGN given name is
            # transliterated differently from their Wikidata label — "Mihail"
            # against "Mikhail", "Iosif" against "Josef".
            surname = display.split()[-1] if display.split() else ""
            qid = _search_qid(surname) if surname and surname != display else None
        if not qid:
            miss.write_text("no chess-player entity found\n", encoding="utf-8")
            return None
        filename = _image_filename(qid)
        if not filename:
            miss.write_text(f"{qid} has no P18 image\n", encoding="utf-8")
            return None
        info = _commons_info(filename)
        if not info:
            miss.write_text(f"no imageinfo for {filename}\n", encoding="utf-8")
            return None
    except LookupFailed as exc:
        # No sidecar and no miss marker: the next build simply tries again.
        print(f"[portraits] {display}: {exc} — will retry on a later build")
        return None

    try:
        req = urllib.request.Request(info["url"], headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as resp:
            image.write_bytes(resp.read())
    except Exception as exc:  # noqa: BLE001
        print(f"[portraits] download failed for {display}: {exc}")
        return None

    record = {
        "player": display,
        "wikidata": qid,
        "needsAttribution": bool(NEEDS_ATTRIBUTION.search(info["licence"])),
        **info,
    }
    sidecar.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    miss.unlink(missing_ok=True)
    print(f"[portraits] {display} -> {key}.jpg  ({info['licence'] or 'licence unknown'})")
    return record


def credits_for(*pgn_names: str) -> List[Dict[str, Any]]:
    """Credit records for players whose licence asks for attribution."""
    out: List[Dict[str, Any]] = []
    for name in pgn_names:
        key = surname_of(name)
        sidecar = PORTRAITS / f"{key}.json"
        if not key or not sidecar.exists():
            continue
        try:
            rec = json.loads(sidecar.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if rec.get("needsAttribution"):
            out.append(rec)
    return out


def ensure(*pgn_names: str, force: bool = False) -> None:
    """Best effort: a portrait is decoration, never a reason to fail a build."""
    for name in pgn_names:
        if not name:
            continue
        try:
            fetch_portrait(name, force=force)
        except Exception as exc:  # noqa: BLE001
            print(f"[portraits] skipped {name}: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Cache player portraits from Wikimedia")
    ap.add_argument("players", nargs="*", help='PGN-style names, e.g. "Tal, Mihail"')
    ap.add_argument("--all", action="store_true", help="every player in the classics pool")
    ap.add_argument("--force", action="store_true", help="re-fetch even if cached")
    args = ap.parse_args()

    names = list(args.players)
    if args.all:
        sys.path.insert(0, str(ROOT / "services" / "orchestrator"))
        from ingest.classics_fetch import LEGENDS  # type: ignore

        names.extend(LEGENDS.values())
    if not names:
        ap.error("give some names, or --all")

    for name in names:
        fetch_portrait(name, force=args.force)
    have = len(list(PORTRAITS.glob("*.jpg")))
    print(f"\n[portraits] cache now holds {have} portrait(s) in "
          f"{PORTRAITS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
