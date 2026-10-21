"""Signals that exist in one field only: a game's release day, a coin's first days trending.

Hugging Face is where AI packs look; game development has itch.io's new-and-popular
chart, crypto has CoinGecko's trending list and DefiLlama's newest protocols. Each is a
ranking, so every entry is already a name — no prose to parse. Same contract as every
other signal: rows of {term, note, examples, variants}. A term is reported the day it
first shows up and never again; the state directory keeps what was reported for
KEEP_DAYS.

Headlines were tried here first (GameDeveloper, RPS, CoinDesk, Decrypt) and dropped:
pulling names out of prose without the novelty filter the ① signals have produced
"fuse games ceo" and "their smart tvs" often enough to poison the table. A site's sitemap
(③) already catches the same news, measured against its own baseline, which is the
better tool for it.

Only the sources named in config.json ("domain_sources", put there by the profile) run.
All are free and need no key.
"""
from __future__ import annotations

import gzip
import html
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from . import UA, snap
from .i18n import t
from .terms import STOP

KEEP_DAYS = 90
ITCH = "https://itch.io/games/new-and-popular.xml"
COINGECKO = "https://api.coingecko.com/api/v3/search/trending"
DEFILLAMA = "https://api.llama.fi/protocols"
ITCH_TOP = 12              # the feed is the current chart: take its head, not all of it
DEFI_DAYS = 7              # a protocol listed this week is news; a month-old one is not
DEFI_TOP = 10
TVL_MIN = 100_000          # a protocol below this is a test deployment, not a signal

_BRACKET = re.compile(r"\s*\[[^\]]*]\s*$")
_SPACES = re.compile(r"\s+")
_TAGS = re.compile(r"<[^>]+>")
_MAIN = re.compile(r"\s*(?://|\||~|—|–|:)\s*")     # "Tamaweb: Virtual Pet Game" is a title and its blurb


def _get(url: str, gz: bool = False) -> str:
    headers = {"User-Agent": UA}
    if gz:
        headers["Accept-Encoding"] = "gzip"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=45) as res:
        body = res.read()
    return (gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body).decode("utf-8", "replace")


def _when(text: str | None) -> datetime | None:
    try:
        when = parsedate_to_datetime(text or "")
    except (TypeError, ValueError):
        return None
    return when.replace(tzinfo=timezone.utc) if when.tzinfo is None else when


def _items(url: str) -> list[dict]:
    """Items of an RSS feed, in the feed's own order."""
    out = []
    for it in ET.fromstring(_get(url)).iter("item"):
        out.append({"title": (it.findtext("title") or "").strip(), "link": (it.findtext("link") or "").strip(),
                    "plain": (it.findtext("plainTitle") or "").strip(), "when": _when(it.findtext("pubDate"))})
    return out


def _clean(name: str) -> str:
    return _SPACES.sub(" ", html.unescape(_TAGS.sub("", name or ""))).strip(" -–—:.!")[:60]


def _main(name: str) -> str:
    """The game's own name, not the blurb after it: 'Tamaweb: Virtual Pet Game' -> 'Tamaweb'."""
    head = _MAIN.split(_clean(name), maxsplit=1)[0].strip(" -–—:.!~")
    return head if len(head) >= 3 else _clean(name)


def _worth(name: str) -> bool:
    """A name, not a heading: at least one word that is not everyday vocabulary."""
    words = [w for w in re.findall(r"[a-z0-9']+", name.lower()) if len(w) > 1]
    return len(name) >= 3 and bool(words) and any(w not in STOP for w in words)


def _row(name: str, note: str, example: str, url: str, variants: list[str] | None = None) -> dict:
    term = name.lower()
    extra = [v.lower() for v in (variants or []) if v]
    return {"term": term, "variants": list(dict.fromkeys([term, *extra])),
            "note": note, "examples": [example], "url": url}


def itch(cfg: dict, state: Path, today: date) -> list[dict]:
    """The current new-and-popular chart. Its pubDate is the game's own date, not today's,
    so there is no time filter: the snapshot is what makes tomorrow's report an increment."""
    rows = []
    for it in _items(ITCH)[:ITCH_TOP]:
        name = _main(_BRACKET.sub("", it["plain"] or it["title"]))
        if _worth(name):
            rows.append(_row(name, t("note_itch"), f"{name} — {it['link']}", it["link"]))
    return rows


def coingecko(cfg: dict, state: Path, today: date) -> list[dict]:
    """What the crowd is searching on CoinGecko right now: mostly new, sometimes a name
    coming back. The judge scores an old name 0.5, which is how it sinks in the report."""
    rows = []
    for i, entry in enumerate(json.loads(_get(COINGECKO)).get("coins") or []):
        item = entry.get("item") or {}
        name, sym = _clean(item.get("name") or ""), (item.get("symbol") or "").strip()
        if not name or not _worth(name):
            continue
        chg = (item.get("data") or {}).get("price_change_percentage_24h") or {}
        chg = chg.get("usd") if isinstance(chg, dict) else chg
        note = t("note_trending", rank=item.get("market_cap_rank") or t("new"),
                 chg=f"{chg:+.1f}%" if isinstance(chg, (int, float)) else t("dash"))
        slug = item.get("slug") or ""
        rows.append(_row(name, note, f"{name} ({sym}) — trending #{i + 1}",
                         f"https://www.coingecko.com/en/coins/{slug}", [sym]))
    return rows


def defillama(cfg: dict, state: Path, today: date) -> list[dict]:
    """Protocols listed in the last week, biggest TVL first: the ones with money already."""
    cut = today - timedelta(days=DEFI_DAYS)
    rows = []
    for p in json.loads(_get(DEFILLAMA, gz=True)):
        tvl, listed = p.get("tvl") or 0, p.get("listedAt")
        if not listed or tvl < TVL_MIN:
            continue
        try:
            day = datetime.fromtimestamp(int(listed), timezone.utc).date()
        except (TypeError, ValueError, OSError):
            continue
        name = _clean(p.get("name") or "")
        if day < cut or not _worth(name):
            continue
        rows.append((tvl, _row(name, t("note_defillama", tvl=f"{tvl / 1e6:.1f}M" if tvl >= 1e6 else f"{tvl / 1e3:.0f}K"),
                                f"{name} — TVL ${tvl:,.0f}, listed {day}",
                                f"https://defillama.com/protocol/{p.get('slug', '')}")))
    rows.sort(key=lambda pair: -pair[0])
    return [r for _, r in rows[:DEFI_TOP]]


SOURCES = {"itch": itch, "coingecko": coingecko, "defillama": defillama}


def new_terms(cfg: dict, state: Path, today: date | None = None) -> dict:
    """What each field's own feeds carry that this radar has not reported yet."""
    today = today or date.today()
    wanted = [s for s in (cfg.get("domain_sources") or []) if s in SOURCES]
    if not wanted:
        return {"skipped": True, "terms": []}
    path = state / "domain.json"
    seen = snap.load(path) or {}
    cut = (today - timedelta(days=KEEP_DAYS)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cut}
    rows, errors = [], []
    for name in wanted:
        try:
            found = SOURCES[name](cfg, state, today)
        except Exception as exc:  # noqa: BLE001 - one feed failing leaves the rest of the report
            errors.append(f"{name}: {type(exc).__name__}: {' '.join(str(exc).split())[:80]}")
            continue
        for r in found:
            if r["term"] in seen:
                continue
            seen[r["term"]] = today.isoformat()
            rows.append({**r, "recent": 1, "lift": 1})
    snap.save(path, seen)
    out = {"terms": rows, "sources": wanted}
    if errors:
        out["error"] = "; ".join(errors)
    return out
