"""Domain packs and their feeds: the words each field ignores, the tickers crypto reads,
the prompt each pack builds, and the parsing of the free rankings (no network here)."""
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from radar import config, domains, i18n, judge, profile, terms, usecases


@pytest.fixture(autouse=True)
def _reset():
    """Every test starts from the built-in stop list, whatever the last one loaded."""
    terms.reset_stop()
    terms.set_tickers(False)
    profile.set_active({})
    i18n.set_lang("en")
    yield
    terms.reset_stop()
    terms.set_tickers(False)
    profile.set_active({})
    i18n.set_lang("en")


def _cfg(tmp_path: Path, **raw) -> dict:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    return config.load(path)


# --- the packs ---------------------------------------------------------------------

def test_every_built_in_pack_loads():
    for name in profile.available():
        pack = profile.resolve(name)
        assert pack["name"] == name and pack["label"]["en"]
        assert isinstance(pack["stop_words"], list)


def test_a_pack_supplies_defaults_and_config_still_wins(tmp_path):
    cfg = _cfg(tmp_path, profile="crypto")
    assert cfg["tickers"] is True
    assert cfg["usecases"]["benchmark"] == "bitcoin"
    assert cfg["_profile"] == "crypto"
    assert set(cfg["domain_sources"]) == {"coingecko", "defillama"}

    cfg = _cfg(tmp_path, profile="crypto", tickers=False, usecases={"benchmark": "ethereum"})
    assert cfg["tickers"] is False and cfg["usecases"]["benchmark"] == "ethereum"


def test_two_packs_add_up(tmp_path):
    cfg = _cfg(tmp_path, profile=["gamedev", "crypto"])
    assert "itch" in cfg["domain_sources"] and "coingecko" in cfg["domain_sources"]
    assert cfg["tickers"] is True                                  # the last pack that sets it wins
    assert "game" in cfg["stop_words"] and "airdrop" in cfg["stop_words"]


def test_an_unknown_pack_says_what_there_is(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"profile": "nope"}))
    with pytest.raises(SystemExit) as exc:
        config.load(path)
    assert "gamedev" in str(exc.value)


def test_stop_words_do_not_leak_between_profiles(tmp_path):
    _cfg(tmp_path, profile="gamedev")
    assert "airdrop" not in terms.STOP
    _cfg(tmp_path, profile="crypto")
    assert "airdrop" in terms.STOP and "game" not in terms.STOP


# --- tickers -----------------------------------------------------------------------

def test_dollar_tickers_are_names_only_for_the_fields_that_ask():
    text = "aped into $wif and $OP, also $PEPE and a $5 coffee"
    terms.set_tickers(True)
    assert {"wif", "op", "pepe"} <= terms.names(text)
    terms.set_tickers(False)
    assert "wif" not in terms.names(text)


def test_a_ticker_never_overrides_a_stop_word():
    terms.set_tickers(True)
    assert "free" not in terms.names("$free $OP")
    assert "op" in terms.names("$OP")


# --- prompts -----------------------------------------------------------------------

def test_the_judge_prompt_carries_the_fields_own_examples(tmp_path):
    _cfg(tmp_path, profile="crypto")
    assert "token, a ticker" in judge.system()
    _cfg(tmp_path, profile="gamedev")
    assert "hades ii" in judge.system()
    assert "token, a ticker" not in judge.system()


def test_the_keyword_prompt_speaks_the_fields_language(tmp_path):
    _cfg(tmp_path, profile="crypto")
    text = usecases.system()
    assert "new token, protocol or chain" in text and "solana meme coins" in text
    _cfg(tmp_path, profile="gamedev")
    text = usecases.system()
    assert "best metroidvania games" in text and "solana meme coins" not in text


def test_a_plain_config_keeps_the_original_ai_prompts(tmp_path):
    _cfg(tmp_path)
    assert "new model, product or repository" in usecases.system()
    assert "opus 5.5" in judge.system()


# --- the field's own feeds (parsing only) ------------------------------------------

def _feed(items: str) -> str:
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'


ITCH_XML = _feed(
    "<item><title>Tamaweb: Virtual Pet Game [Free]</title><plainTitle>Tamaweb: Virtual Pet Game</plainTitle>"
    "<link>https://sam.itch.io/tamaweb</link></item>"
    "<item><title>Plain Only</title><link>https://x.itch.io/plain</link></item>"
)


def test_itch_takes_the_name_not_the_blurb(monkeypatch):
    monkeypatch.setattr(domains, "_get", lambda url, gz=False: ITCH_XML)
    rows = domains.itch({}, Path("."), date(2026, 10, 21))
    assert [r["term"] for r in rows] == ["tamaweb", "plain only"]
    assert rows[0]["url"] == "https://sam.itch.io/tamaweb"


def test_coingecko_reads_the_usd_change_and_the_symbol(monkeypatch):
    payload = {"coins": [{"item": {"name": "Capybobo", "symbol": "PYBOBO", "slug": "capybobo", "market_cap_rank": 672,
                                   "data": {"price_change_percentage_24h": {"usd": 17.84}}}}]}
    monkeypatch.setattr(domains, "_get", lambda url, gz=False: json.dumps(payload))
    row = domains.coingecko({}, Path("."), date(2026, 10, 21))[0]
    assert row["term"] == "capybobo" and set(row["variants"]) == {"capybobo", "pybobo"}
    assert "+17.8%" in row["note"]


def test_defillama_keeps_this_week_and_the_money(monkeypatch):
    now = int(datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp())
    old = int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp())
    payload = [
        {"name": "Fresh", "tvl": 2_500_000, "listedAt": now, "slug": "fresh"},
        {"name": "Stale", "tvl": 9_000_000, "listedAt": old, "slug": "stale"},
        {"name": "Tiny", "tvl": 1_000, "listedAt": now, "slug": "tiny"},
    ]
    monkeypatch.setattr(domains, "_get", lambda url, gz=False: json.dumps(payload))
    rows = domains.defillama({}, Path("."), date(2026, 10, 21))
    assert [r["term"] for r in rows] == ["fresh"] and "2.5M" in rows[0]["note"]


def test_a_term_is_reported_once(monkeypatch, tmp_path):
    monkeypatch.setattr(domains, "SOURCES", {"itch": lambda cfg, state, today: [
        {"term": "one", "note": "n", "examples": [], "variants": ["one"]}]})
    cfg = {"domain_sources": ["itch"]}
    first = domains.new_terms(cfg, tmp_path, date(2026, 10, 21))
    again = domains.new_terms(cfg, tmp_path, date(2026, 10, 22))
    assert len(first["terms"]) == 1 and again["terms"] == []


def test_a_failing_feed_leaves_the_others_alone(monkeypatch, tmp_path):
    def boom(cfg, state, today):
        raise OSError("403")
    monkeypatch.setattr(domains, "SOURCES", {"bad": boom, "itch": lambda cfg, state, today: [
        {"term": "kept", "note": "n", "examples": [], "variants": ["kept"]}]})
    out = domains.new_terms({"domain_sources": ["bad", "itch"]}, tmp_path, date(2026, 10, 21))
    assert [r["term"] for r in out["terms"]] == ["kept"] and "bad" in out["error"]


def test_no_domain_sources_means_the_signal_is_skipped(tmp_path):
    assert domains.new_terms({"domain_sources": []}, tmp_path, date(2026, 10, 21)) == {"skipped": True, "terms": []}
