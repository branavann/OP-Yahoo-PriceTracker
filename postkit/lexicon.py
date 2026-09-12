"""
Japanese -> English lexicon for One Piece vintage card listings.
=================================================================

Listing titles are written by sellers, not by a database, so they are
inconsistent, abbreviated and full of decorative noise. Everything here is
built around one rule: TRANSLATE WHAT WE RECOGNISE, FLAG WHAT WE DON'T.

Never guess. A card labelled with the wrong name on a public post is worse
than a card labelled "unidentified" - the whole point of the account is
that the information can be trusted.

Add entries as you encounter new cards; each addition permanently raises
the share of sales that resolve at HIGH confidence.
"""

# =====================================================================
# CHARACTERS
# =====================================================================
# Order matters where one name contains another.

CHARACTERS = [
    ("モンキー・D・ルフィ", "Monkey D. Luffy"),
    ("ルフィ", "Luffy"),
    ("ロロノア・ゾロ", "Roronoa Zoro"),
    ("ゾロ", "Zoro"),
    ("ナミ", "Nami"),
    ("ウソップ", "Usopp"),
    ("サンジ", "Sanji"),
    ("チョッパー", "Chopper"),
    ("ニコ・ロビン", "Nico Robin"),
    ("ロビン", "Robin"),
    ("フランキー", "Franky"),
    ("ブルック", "Brook"),
    ("ジンベエ", "Jinbe"),
    ("ポートガス・D・エース", "Portgas D. Ace"),
    ("エース", "Ace"),
    ("サボ", "Sabo"),
    ("白ひげ", "Whitebeard"),
    ("シャンクス", "Shanks"),
    ("ミホーク", "Mihawk"),
    ("ハンコック", "Boa Hancock"),
    ("トラファルガー・ロー", "Trafalgar Law"),
    ("トラファルガー", "Trafalgar Law"),
    ("バギー", "Buggy"),
    ("クロコダイル", "Crocodile"),
    ("ドフラミンゴ", "Doflamingo"),
    ("カイドウ", "Kaido"),
    ("ビッグマム", "Big Mom"),
    ("ゴールドロジャー", "Gol D. Roger"),
    ("ゴール・D・ロジャー", "Gol D. Roger"),
    ("ロジャー", "Roger"),
    ("エネル", "Enel"),
    ("クロ", "Kuro"),
    ("アーロン", "Arlong"),
    ("スモーカー", "Smoker"),
    ("たしぎ", "Tashigi"),
    ("ビビ", "Vivi"),
    ("Mr.2", "Mr. 2"),
    ("ボンクレー", "Bon Clay"),
]

# =====================================================================
# NAMED CARDS
# =====================================================================
# The chase cards. A match here is the single strongest identity signal
# available, so these drive HIGH confidence.
#
# (japanese, english, optional note shown as a subtitle)

NAMED_CARDS = [
    ("未来の海賊王",     "Future Pirate King",      "the flagship vintage chase card"),
    ("鬼斬り",           "Oni Giri",                None),
    ("三人の大海賊",     "Three Great Pirates",     None),
    ("麦わら航海記",     "Straw Hat Voyage Log",    None),
    ("ROMANCE DAWN",    "Romance Dawn",            None),
    ("ロマンスドーン",   "Romance Dawn",            None),
    ("海賊の航海士",     "Navigator of the Pirates", None),
    ("ゴムゴムの",       "Gum-Gum",                 None),
    ("海賊野球",         "Pirate Baseball",         None),
    ("グランドバトル",   "Grand Battle",            None),
    ("トレジャーパック", "Treasure Pack",           None),
    ("スペシャルパック", "Special Pack",            None),
    ("アラバスタの攻防", "Battle for Alabasta",     None),
    ("超新星",           "Supernova",               None),
]

# =====================================================================
# GRADING
# =====================================================================
# Explicit numeric grades only. "鑑定品" means "graded/certified" with no
# number, which is NOT the same as knowing the grade.

GRADE_PATTERNS = [
    (r"PSA\s*\.?\s*10\b",        "PSA 10"),
    (r"PSA\s*\.?\s*9\.5\b",      "PSA 9.5"),
    (r"PSA\s*\.?\s*9\b",         "PSA 9"),
    (r"PSA\s*\.?\s*8\.5\b",      "PSA 8.5"),
    (r"PSA\s*\.?\s*8\b",         "PSA 8"),
    (r"PSA\s*\.?\s*7\b",         "PSA 7"),
    (r"PSA\s*\.?\s*6\b",         "PSA 6"),
    (r"BGS\s*\.?\s*10\b",        "BGS 10"),
    (r"BGS\s*\.?\s*9\.5\b",      "BGS 9.5"),
    (r"BGS\s*\.?\s*9\b",         "BGS 9"),
    (r"BGS\s*\.?\s*8\.5\b",      "BGS 8.5"),
    (r"CGC\s*\.?\s*10\b",        "CGC 10"),
    (r"CGC\s*\.?\s*9\.5\b",      "CGC 9.5"),
    (r"CGC\s*\.?\s*9\b",         "CGC 9"),
    (r"ARS\s*\.?\s*10\b",        "ARS 10"),
    (r"ARS\s*\.?\s*9\b",         "ARS 9"),
]

# Graded, but the grade itself is not in the title.
GRADED_UNSPECIFIED = ["鑑定品", "鑑定済", "鑑定"]

# =====================================================================
# RAW CONDITION
# =====================================================================
# Seller-stated condition, in the seller's own words. These are claims,
# not assessments - the post should present them as such.
# Order matters: 極美品 contains 美品.

RAW_CONDITION = [
    ("完全美品",   "Mint (stated)"),
    ("極美品",     "Near Mint (stated)"),
    ("超美品",     "Near Mint (stated)"),
    ("美品",       "Excellent (stated)"),
    ("良品",       "Good (stated)"),
    ("並品",       "Played (stated)"),
    ("傷あり",     "Damaged (stated)"),
    ("キズあり",   "Damaged (stated)"),
    ("難あり",     "Flawed (stated)"),
    ("現状品",     "Sold as-is"),
    ("ジャンク",   "Junk / as-is"),
]

# =====================================================================
# SEALED PRODUCT
# =====================================================================
# A sealed box is a real market data point but it is NOT a card sale, and
# putting one on a card-sale slide misleads. Detected separately so the
# selector can exclude or label it.

SEALED_STRONG = ["未開封", "シュリンク", "新品未開封", "内袋未開封"]
SEALED_UNITS = ["1BOX", "１BOX", "BOX", "ボックス", "カートン", "1箱", "箱",
                "パック", "スペシャルパック", "トレジャーパック", "デッキ"]

# =====================================================================
# ATTRIBUTES
# =====================================================================

ATTRIBUTES = [
    ("キラ",           "Holo"),
    ("プリズム",       "Prism"),
    ("ミラクルキラ",   "Miracle Holo"),
    ("オメガ",         "Omega"),
    ("プロモ",         "Promo"),
    ("非売品",         "Not for sale / promo"),
    ("当時物",         "Period original"),
    ("初期",           "Early print"),
    ("エラー",         "Error card"),
    ("認定証",         "Certificate"),
    ("ジャンプフェスタ", "Jump Festa"),
    ("来場者特典",     "Attendee exclusive"),
    ("限定",           "Limited"),
    ("希少",           "Scarce (stated)"),
    ("激レア",         "Ultra rare (stated)"),
]

# Decorative noise sellers wrap titles in. Stripped before any parsing so
# it can't be mistaken for card identity.
NOISE_PATTERNS = [
    r"[◆◇■□★☆※【】\[\]『』「」（）()]",
    r"売り切り", r"即決", r"送料無料", r"匿名配送", r"値下げ",
    r"最安値", r"交渉", r"おまけ", r"訳あり",
    r"[A-Za-z0-9]+様",          # "ふ*ぅ様" - a reserved-for-buyer marker
    r"\d+円",
]
