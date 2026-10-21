"""A domain pack: the words, prompts and feeds of one field.

The engine is field-agnostic; what changes between AI products, game development and
crypto is which words are everyday noise, which feeds carry the first mention of a new
name, and how a model should read a term. A pack holds exactly that, as JSON:

    radar/profiles/ai.json        AI products, models and repos (the original field)
    radar/profiles/gamedev.json   games, engines and game-dev tools
    radar/profiles/crypto.json    tokens, protocols and chains

Pick one in config.json, or several to watch them together:

    "profile": "gamedev"
    "profile": ["gamedev", "crypto"]

A pack never overrides config.json: its values become the defaults, and whatever you
write in config.json still wins. A file named profiles/<name>.json next to config.json
shadows the built-in pack of that name, so a fork can carry its own field without
touching the package.

Union fields (stop_words, domain_sources, x_accounts, sitemaps, topics) add up when you
name several packs; prompts (judge, usecases) come from the first pack that has them.
"""
from __future__ import annotations

import json
from pathlib import Path

DIR = Path(__file__).with_name("profiles")
UNION = ("stop_words", "domain_sources")
MERGE = ("x_accounts", "sitemaps", "topics")
PROMPTS = ("judge", "usecases")

_ACTIVE: dict = {}


def available() -> list[str]:
    return sorted(p.stem for p in DIR.glob("*.json"))


def resolve(spec, near: Path | None = None) -> dict:
    """The merged pack for a name, a list of names, or a path; {} when spec is empty."""
    names = spec if isinstance(spec, list) else ([spec] if spec else [])
    out: dict = {}
    for name in names:
        pack = _read(str(name), near)
        for k, v in pack.items():
            if k in UNION:
                out[k] = list(dict.fromkeys([*out.get(k, []), *v]))
            elif k in MERGE or k in PROMPTS:
                out[k] = {**out.get(k, {}), **v}
            elif k == "label":
                out.setdefault("label", v)
            else:
                out[k] = v          # tickers, benchmark, name: the last pack wins
    return out


def _read(name: str, near: Path | None) -> dict:
    candidates = [Path(name)] + [DIR / f"{name}.json"]
    if near:
        candidates.insert(0, near / "profiles" / f"{name}.json")
    for cand in candidates:
        if cand.is_file():
            return json.loads(cand.read_text())
    raise SystemExit(f"profile {name!r} not found; built in: {', '.join(available())}")


def apply(defaults: dict, pack: dict) -> dict:
    """The defaults with the pack folded in: lists add up, dicts merge, scalars replace."""
    out = dict(defaults)
    for k, v in pack.items():
        d = defaults.get(k)
        if k in UNION and isinstance(d, list):
            out[k] = list(dict.fromkeys([*d, *v]))
        elif isinstance(d, dict) and isinstance(v, dict):
            out[k] = {**d, **v}
        else:
            out[k] = v
    if "benchmark" in pack:
        out["usecases"] = {**out.get("usecases", {}), "benchmark": pack["benchmark"]}
    return out


def set_active(pack: dict) -> None:
    _ACTIVE.clear()
    _ACTIVE.update(pack or {})


def get() -> dict:
    return _ACTIVE


def line(where: str, key: str, fallback: str = "") -> str:
    """One prompt line of the active pack: line("judge", "names_line")."""
    return (_ACTIVE.get(where) or {}).get(key) or fallback


def label(lang: str = "en") -> str:
    """The field, in the report's language: "game development", "币圈"."""
    v = _ACTIVE.get("label") or {}
    return v.get(lang) or v.get("en") or ""
