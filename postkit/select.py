"""
Pick the three sales that make today's post.
============================================

Editorial rules, not just "sort by price". The three choices are the post,
so the filtering matters more than anything downstream:

  - lots and bundles are out       (a 200-card lot isn't a card price)
  - sealed product is separated    (real market data, but not a card sale)
  - a USD floor keeps the bar high (a slow day posts nothing, not filler)
  - one sale per card              (the same Zoro twice is a weak carousel)

Returning fewer than three is a legitimate outcome. A thin day should be
reported, not padded.
"""

import json
import datetime as dt
import collections

from .enrich import enrich, HIGH, MEDIUM, LOW


DEFAULT_FLOOR_USD = 300


def _same_card_key(sale: dict) -> str:
    """Identity for dedupe.

    The set is always part of the key: 'Future Pirate King' exists in both
    AR Formation and Carddass and they are genuinely different cards at
    genuinely different prices.

    Within a set, the NAME is the better key even though a code looks more
    precise - two listings of the same card often disagree about whether to
    print the code at all, so keying on the code would treat them as two
    different cards and put the same Zoro on two slides."""
    s = sale["set_name"] or "?"
    if sale["card_name"]:
        return f"name:{s}|{sale['character'] or ''}|{sale['card_name']}"
    if sale["code"]:
        return f"code:{s}|{sale['code']}"
    if sale["character"]:
        return f"char:{s}|{sale['character']}"
    return f"id:{sale['id']}"


def load_archive(path) -> list:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["items"]


def sales_for_day(records, day, jpy_to_usd, floor_usd=DEFAULT_FLOOR_USD,
                  include_sealed=True):
    """All qualifying sales that closed on `day` (a YYYY-MM-DD string),
    enriched, deduped, ranked by price.

    Returns (chosen, rejected) so a thin day can explain itself."""
    rejected = collections.Counter()
    candidates = []

    for rec in records:
        if not rec.get("end", "").startswith(day):
            continue

        if rec.get("kind") == "lot":
            rejected["lot or bundle"] += 1
            continue

        sale = enrich(rec, jpy_to_usd)

        if sale["price_usd"] < floor_usd:
            rejected[f"under ${floor_usd}"] += 1
            continue

        if sale["sealed"] and not include_sealed:
            rejected["sealed product"] += 1
            continue

        candidates.append(sale)

    candidates.sort(key=lambda s: -s["price_usd"])

    # Dedupe: highest sale of any given card wins, the rest are noted.
    seen, chosen = set(), []
    for sale in candidates:
        key = _same_card_key(sale)
        if key in seen:
            rejected["duplicate of a higher sale"] += 1
            sale["duplicate_of"] = key
            continue
        seen.add(key)
        chosen.append(sale)

    return chosen, rejected


def build_day(archive_path, day, jpy_to_usd, floor_usd=DEFAULT_FLOOR_USD,
              include_sealed=True, want=3):
    records = load_archive(archive_path)
    ranked, rejected = sales_for_day(
        records, day, jpy_to_usd, floor_usd, include_sealed)

    top = ranked[:want]
    needs_review = [s for s in top if s["confidence"] != HIGH]

    return {
        "day": day,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "fx_rate": jpy_to_usd,
        "floor_usd": floor_usd,
        "sales": top,
        "runners_up": ranked[want:want + 4],
        "qualifying_count": len(ranked),
        "rejected": dict(rejected),
        "needs_review": [
            {"id": s["id"], "name": s["display_name"],
             "confidence": s["confidence"], "flags": s["flags"],
             "title_jp": s["title_jp"], "url": s["url"]}
            for s in needs_review
        ],
        "publishable": len(top) == want and not needs_review,
    }
