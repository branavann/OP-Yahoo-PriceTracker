"""
Turn a raw archive record into something publishable.
=====================================================

The archive stores what the seller wrote. A post needs: what card is this,
what condition, what did it cost in USD - and, crucially, HOW SURE ARE WE.

Confidence is the whole design. Anything below HIGH is held back for
Branavan to check by hand rather than published on a guess.
"""

import re
import datetime as dt

from . import lexicon as lx


# =====================================================================
# CONFIDENCE
# =====================================================================
# HIGH   - card code AND a named card or character. Safe to post as-is.
# MEDIUM - character and set, but no code or known card name. Usually
#          right, but the specific card is inferred. Needs a glance.
# LOW    - set only. Do not post without checking the listing.

HIGH, MEDIUM, LOW = "high", "medium", "low"


def strip_noise(title: str) -> str:
    out = title
    for pat in lx.NOISE_PATTERNS:
        out = re.sub(pat, " ", out)
    return re.sub(r"\s+", " ", out).strip()


def find_character(title: str):
    for jp, en in lx.CHARACTERS:
        if jp in title:
            return en, jp
    return None, None


def find_named_card(title: str):
    for jp, en, note in lx.NAMED_CARDS:
        if jp.upper() in title.upper():
            return en, jp, note
    return None, None, None


def find_grade(title: str):
    """Returns (grade_label, is_graded). A certified card whose grade isn't
    stated returns ('Graded', True) - honest about what we don't know."""
    for pat, label in lx.GRADE_PATTERNS:
        if re.search(pat, title, re.IGNORECASE):
            return label, True
    if any(k in title for k in lx.GRADED_UNSPECIFIED):
        return "Graded (grade not stated)", True
    return None, False


def find_raw_condition(title: str):
    for jp, en in lx.RAW_CONDITION:
        if jp in title:
            return en
    return None


def is_sealed(title: str) -> bool:
    """Sealed product needs BOTH an unopened marker and a product unit -
    'BOX' alone catches storage boxes, '未開封' alone catches a single card
    still in its original sleeve, which IS a card sale."""
    return (any(k in title for k in lx.SEALED_STRONG)
            and any(u in title.upper() for u in [u.upper() for u in lx.SEALED_UNITS]))


def sealed_unit(title: str) -> str:
    """What kind of sealed product. A box and a single pack are different
    markets and conflating them makes the price meaningless."""
    t = title.upper()
    if "カートン" in title:
        return "Sealed Carton"
    if any(k in t for k in ["1BOX", "１BOX", "BOX", "ボックス", "1箱"]):
        return "Sealed Box"
    if "デッキ" in title:
        return "Sealed Deck"
    if "パック" in title:
        return "Sealed Pack"
    return "Sealed Product"


def find_attributes(title: str) -> list:
    seen, out = set(), []
    for jp, en in lx.ATTRIBUTES:
        if jp in title and en not in seen:
            seen.add(en)
            out.append(en)
    return out


def enrich(record: dict, jpy_to_usd: float) -> dict:
    """Archive record -> publishable sale, with a confidence verdict."""
    title = record["title"]
    clean = strip_noise(title)

    character, character_jp = find_character(clean)
    card_name, card_name_jp, card_note = find_named_card(clean)
    grade, graded = find_grade(title)
    identified_via = "title" if (character or card_name) else None
    raw_condition = find_raw_condition(title)
    code = (record.get("card") or "").strip()
    set_name = record.get("set") or ""
    sealed = is_sealed(title)

    # --- the checklist -----------------------------------------------
    # When the seller gave a code but no readable card identity, ask what
    # that code has meant on every previous sale. This is the single
    # biggest source of recovered identifications.
    checklist_hit = None
    if not sealed and code and set_name and not (character or card_name):
        from .checklist import lookup
        checklist_hit = lookup(set_name, code)
        if checklist_hit:
            character = checklist_hit.get("character") or None
            card_name = checklist_hit.get("card_name") or None
            identified_via = "checklist"

    # --- confidence -------------------------------------------------
    reasons = []
    if sealed:
        # Sealed product is identified by what it is, not which card it is.
        confidence = HIGH if set_name else MEDIUM
        if not set_name:
            reasons.append("sealed product, set not identified")
    elif checklist_hit:
        # Derived, not stated. A code backed by several agreeing sales is
        # as good as a title that spelled it out; a thinner one is worth
        # a glance before it goes out.
        if checklist_hit["strong"] or checklist_hit.get("reviewed"):
            confidence = HIGH
        else:
            confidence = MEDIUM
            reasons.append(
                f"card name taken from the archive checklist for {set_name} {code} "
                f"({checklist_hit['sightings']} prior sales, "
                f"{checklist_hit['agreement']:.0%} agreement) — confirm it")
    elif code and (card_name or character):
        confidence = HIGH
    elif card_name and character:
        # A named chase card plus the right character is as good as a code.
        confidence = HIGH
    elif character and set_name:
        confidence = MEDIUM
        reasons.append("no card number in the title; card inferred from character and set")
    elif card_name and set_name:
        # A known chase card in a known set. The character isn't spelled out,
        # but the card is named - that's most of the identification.
        confidence = MEDIUM
        reasons.append("card name recognised but no character or card number "
                       "in the title; confirm the exact card")
    elif code and set_name:
        # The code pins the card down even with no character in the title -
        # it just needs a checklist to say which card that is.
        confidence = MEDIUM
        reasons.append(f"identified only by set and code ({set_name} {code}); "
                       "confirm the card name")
    else:
        confidence = LOW
        if not character:
            reasons.append("no recognised character in the title")
        if not code:
            reasons.append("no card number in the title")
        if not set_name:
            reasons.append("set not identified")

    if grade == "Graded (grade not stated)":
        reasons.append("listed as certified but the grade is not in the title")

    # --- display name ------------------------------------------------
    if sealed:
        # What matters about sealed product is what UNIT it is - a box and a
        # single pack are different markets - not which card might be inside.
        display = f"{set_name} — {sealed_unit(title)}".strip(" —")
    else:
        bits = [b for b in (character, card_name) if b]
        display = " · ".join(bits) if bits else "Unidentified card"

    # --- condition line ----------------------------------------------
    if sealed:
        condition = "Sealed / unopened"
    elif grade:
        condition = grade
    elif raw_condition:
        condition = raw_condition
    else:
        condition = "Raw, condition not stated"

    price_jpy = int(record["price"])
    end = record["end"]

    return {
        "id": record["id"],
        "url": record["url"],
        "source": record.get("source", ""),
        "image": record.get("image", ""),
        "title_jp": title,

        "display_name": display,
        "character": character,
        "card_name": card_name,
        "card_name_jp": card_name_jp,
        "card_note": card_note,
        "set_name": set_name,
        "code": code,
        "condition": condition,
        "grade": grade,
        "graded": graded,
        "sealed": sealed,
        "attributes": find_attributes(title),

        # Yen is kept in the data even though the slide shows USD only -
        # the USD figure moves with FX, the yen figure is the actual fact,
        # and any future trend chart needs it.
        "price_jpy": price_jpy,
        "price_usd": round(price_jpy * jpy_to_usd),
        "fx_rate": jpy_to_usd,

        "sold_at": end,
        "bids": record.get("bids"),

        "confidence": confidence,
        "identified_via": identified_via,
        "flags": reasons,
    }
