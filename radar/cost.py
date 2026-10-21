"""What a month of runs costs on AIsa, from the unit prices the modules record.

The prices are the ones seen in October 2026 and are written down where they were
observed: aisa.py for the tool router, asks.py for Reddit, sellers.py for the payment
platforms, README.md for the keyword table. They move; the report's own "spent" line,
summed from the billing field of every call, is the check.

An estimate only covers AIsa. Hugging Face, GitHub, the sitemaps, GSC, itch.io, CoinGecko
and DefiLlama are free, TrustMRR has its own key, and GoAnyAPI is a separate optional one.
"""
from __future__ import annotations

from . import sources

X_ACCOUNT = 0.003       # one account's last 20 posts (aisa.py, 2026-10)
TRENDS = 0.0012         # one Trends task (aisa.py, 2026-10)
WHOIS = 0.13            # one whois overview query (aisa.py, 2026-10)
VOLUME = 0.09           # one Google Ads volume batch (README, 2026-10)
NAME = 0.05             # one name through the keyword table: an X search, two chats, two Trends (README)
REDDIT = 0.0019         # one Reddit search (asks.py)
SELLER = 0.056          # one platform, its links and its new sites (sellers.py, 2026-10-14)
JUDGE_DAY = 0.007       # a day of name judging on a small model, 2-6 batches of 25 terms
X_RUNS = 3              # sources at 0, 8 and 16; `daily` should skip x when this runs apart
DAYS = 30
WEEKS = DAYS / 7


def on(cfg: dict, signal: str) -> bool:
    """A signal runs unless config.json (or the field's pack) switches it off."""
    return (cfg.get("signals") or {}).get(signal, True)


def estimate(cfg: dict, x_runs: int = X_RUNS) -> dict[str, float]:
    """{signal: USD a month} for the signals that are on. Keys match the report's blocks."""
    out: dict[str, float] = {}
    if on(cfg, "x"):
        out["x"] = len(sources.accounts(cfg)) * X_ACCOUNT * x_runs * DAYS
    if on(cfg, "usecases"):
        out["usecases"] = (cfg["usecases"]["per_day"] * NAME + VOLUME) * DAYS
    if on(cfg, "newsites"):
        out["newsites"] = len(cfg["new_sites"]["queries"]) * WHOIS * WEEKS
    if on(cfg, "asks"):
        out["asks"] = (len(cfg["asks"]["patterns"]) * REDDIT + VOLUME) * WEEKS
    if on(cfg, "sellers"):
        out["sellers"] = len(cfg["sellers"]["platforms"]) * SELLER * WEEKS
    if on(cfg, "review"):
        out["review"] = cfg["review"]["per_day"] * TRENDS * DAYS
    if on(cfg, "judge"):
        out["judge"] = JUDGE_DAY * DAYS
    return out


def total(cfg: dict, x_runs: int = X_RUNS) -> float:
    return sum(estimate(cfg, x_runs).values())


def line(cfg: dict, x_runs: int = X_RUNS) -> str:
    """`$17.70 a month (x 4.32, usecases 10.20, ...)`, biggest first."""
    rows = estimate(cfg, x_runs)
    parts = ", ".join(f"{k} {v:.2f}" for k, v in sorted(rows.items(), key=lambda r: -r[1]))
    return f"${sum(rows.values()):.2f} a month ({parts})"
