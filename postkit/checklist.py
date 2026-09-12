"""
A set-code checklist, learned from the archive itself.
======================================================

No public checklist for these sets was available, so this builds one from
the data already collected.

The insight: a lot of sellers write BOTH the code and the card, e.g.
"ハイパーバトル C01 未来の海賊王". Those listings teach us what C01 means.
Once learned, the knowledge applies to the listings that carry only the
code - which is exactly the case that was being flagged as unidentifiable.

On the current archive this resolves ~140 codes, most of them from 5+
independent listings that agree with each other.

Regenerate after any long stretch of new sales:

    python -m postkit.checklist data/history.json

The generated file is meant to be hand-corrected. Anything with
"reviewed": true is treated as ground truth and never overwritten.
"""

import sys
import json
import pathlib
import collections

CHECKLIST_FILE = pathlib.Path(__file__).parent / "checklist.json"

# A code is only accepted when several independent listings agree. One
# seller's typo should never become a published card name.
MIN_SIGHTINGS = 2
MIN_AGREEMENT = 0.60

# Stricter bar for treating a checklist hit as HIGH confidence.
STRONG_SIGHTINGS = 4
STRONG_AGREEMENT = 0.80


def _key(set_name: str, code: str) -> str:
    return f"{set_name}|{code}"


def build(archive_path) -> dict:
    from .enrich import strip_noise, find_character, find_named_card

    records = json.loads(pathlib.Path(archive_path).read_text(encoding="utf-8"))["items"]

    votes = collections.defaultdict(collections.Counter)
    for rec in records:
        code = (rec.get("card") or "").strip()
        set_name = rec.get("set") or ""
        if not code or not set_name:
            continue
        clean = strip_noise(rec["title"])
        character, _ = find_character(clean)
        card_name, _, _ = find_named_card(clean)
        if character or card_name:
            votes[_key(set_name, code)][(character, card_name)] += 1

    out = {}
    for key, counter in votes.items():
        (character, card_name), n = counter.most_common(1)[0]
        total = sum(counter.values())
        agreement = n / total
        if total < MIN_SIGHTINGS or agreement < MIN_AGREEMENT:
            continue
        out[key] = {
            "character": character,
            "card_name": card_name,
            "sightings": total,
            "agreement": round(agreement, 3),
            "strong": bool(total >= STRONG_SIGHTINGS and agreement >= STRONG_AGREEMENT),
            "reviewed": False,
        }
    return out


def merge_preserving_reviews(fresh: dict, existing: dict) -> dict:
    """Hand-corrected entries win. The point of reviewing an entry is that
    it stops changing underneath you."""
    merged = dict(fresh)
    for key, entry in existing.items():
        if entry.get("reviewed"):
            merged[key] = entry
    return merged


def load() -> dict:
    if not CHECKLIST_FILE.exists():
        return {}
    try:
        return json.loads(CHECKLIST_FILE.read_text(encoding="utf-8"))["codes"]
    except (json.JSONDecodeError, KeyError, OSError):
        return {}


def lookup(set_name: str, code: str):
    if not set_name or not code:
        return None
    return load().get(_key(set_name, code))


def main():
    archive = sys.argv[1] if len(sys.argv) > 1 else "data/history.json"
    fresh = build(archive)
    existing = load()
    merged = merge_preserving_reviews(fresh, existing)

    CHECKLIST_FILE.write_text(json.dumps({
        "source": str(archive),
        "min_sightings": MIN_SIGHTINGS,
        "min_agreement": MIN_AGREEMENT,
        "codes": dict(sorted(merged.items())),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    strong = sum(1 for e in merged.values() if e["strong"])
    reviewed = sum(1 for e in merged.values() if e.get("reviewed"))
    print(f"{len(merged)} codes ({strong} strong, {reviewed} hand-reviewed) "
          f"-> {CHECKLIST_FILE}")


if __name__ == "__main__":
    main()
