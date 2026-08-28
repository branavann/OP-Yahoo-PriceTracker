"""
One Piece Card Sales Dashboard
==============================

Scrapes Yahoo! Auctions / Yahoo!フリマ sold listings and writes a static
HTML dashboard with three columns: top sales of the past DAY, WEEK, and
MONTH. Each entry links back to the original listing so you can verify it.

The output is a plain index.html file - no server required. Open it in a
browser, or host it anywhere that serves static files.

HOW THE FETCHING WORKS
----------------------
Two passes per search term, because one isn't enough:
  1. Sorted by END TIME  - guarantees full coverage of the last 24 hours,
     even for cheap items.
  2. Sorted by PRICE     - finds the big sales from further back that a
     time-sorted crawl would never reach within a few pages.
Results merge, dedupe by auction ID, then bucket into the three windows.

SETUP
-----
    pip install requests beautifulsoup4

USAGE
-----
    python dashboard.py                 # scrape once, write index.html
    python dashboard.py --open          # ...and open it in your browser
    python dashboard.py --loop          # rescrape every 60 min, keep updating
    python dashboard.py --debug         # dump raw HTML for troubleshooting

This is scraping, and contrary to Yahoo's Terms of Service. Defaults are
deliberately gentle (a few seconds between requests, hourly at most).
"""

import os
import re
import sys
import json
import time
import html
import logging
import argparse
import itertools
import statistics
import webbrowser
import datetime as dt
from pathlib import Path
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

# Mercari is optional - the dashboard still builds from Yahoo alone if the
# library isn't installed. pip install mercari
try:
    import mercari as mercari_lib
    MERCARI_AVAILABLE = True
except ImportError:
    mercari_lib = None
    MERCARI_AVAILABLE = False


# =====================================================================
# CONFIGURATION
# =====================================================================

# =====================================================================
# SETS WE TRACK
# =====================================================================
# Each entry is (display label, [keywords that identify it]).
# ORDER MATTERS: more specific entries come first, because "Berry Match IC"
# also contains "Berry Match", and "Miracle Battle Carddass" also contains
# "Carddass". The first match wins.
#
# This list does double duty: it decides what counts as a tracked card at
# all (see is_wanted), and it labels each sale with its set on the board.

SET_SIGNATURES = [
    ("Berry Match IC",   ["ベリーマッチIC", "ベリーマッチアイス", "ベリマッチIC",
                          "ベリーマッチＩＣ"]),
    ("Berry Match W",    ["ベリーマッチW", "ベリーマッチＷ", "ベリーマッチダブル",
                          "ベリマッチW"]),
    ("Berry Match",      ["ベリーマッチ", "ベリマッチ", "バーストベリー"]),
    ("Miracle Battle",   ["ミラクルバトルカードダス", "ミラバト",
                          "ミラクルバトル"]),
    ("J-Heroes",         ["Jヒーローズ", "J-HEROES", "JHEROES", "ジェイヒーローズ",
                          "Ｊヒーローズ"]),
    ("AR Formation",     ["ARカードダス", "ＡＲカードダス", "ARフォーメーション",
                          "AR フォーメーション"]),
    ("Hyper Battle",     ["ハイパーバトル"]),
    ("Visual Adventure", ["ビジュアルアドベンチャー", "ヴィジュアルアドベンチャー"]),
    ("OP Card Game",     ["旧ワンピースカード", "旧裏", "認定証", "WANTEDカード",
                          "ライセンス", "ワンピースカードゲーム"]),
    ("Data Carddass",    ["データカードダス"]),
    ("Carddass",         ["カードダスマスターズ", "スペシャルパック", "カードダス"]),
]

# Flattened for quick membership checks.
ALL_SET_KEYWORDS = [kw for _, kws in SET_SIGNATURES for kw in kws]

# --- Franchise guard --------------------------------------------------
# Several of these sets are multi-franchise: Miracle Battle Carddass and
# J-Heroes cover Dragon Ball, Naruto, Toriko and more. Broad set-name
# queries are the only way to get good recall, so every result must also
# prove it is One Piece before it qualifies.
ONE_PIECE_TOKENS = [
    "ワンピース", "ONE PIECE", "ONEPIECE", "麦わら", "ワンピ",
    # Main crew and the characters that actually carry value in these sets.
    "ルフィ", "ゾロ", "ナミ", "ウソップ", "サンジ", "チョッパー",
    "ロビン", "フランキー", "ブルック", "ジンベエ",
    "エース", "サボ", "白ひげ", "シャンクス", "ミホーク", "ハンコック",
    # NB: bare "ロー" is deliberately absent - it is a substring of
    # "ヒーローズ", which matched every J-Heroes card of every franchise.
    "トラファルガー", "バギー", "クロコダイル",
    "ドフラミンゴ", "カイドウ", "ビッグマム", "ゴールドロジャー", "ロジャー",
]

# --- Listing kind -----------------------------------------------------
# A graded PSA 10 and a raw single are not comparable prices, and neither
# is a 50-card lot. Tagging them lets the board separate the three.
LOT_KEYWORDS = ["まとめ", "セット", "コンプ", "フルコンプ", "一括", "大量",
                "枚セット", "点セット", "詰め合わせ", "まとめ売り"]
GRADED_RE = re.compile(r"\b(?:PSA|BGS|CGC|ARS)\s?(?:10|9\.5|9|8|7)\b|鑑定品|鑑定済", re.IGNORECASE)
LOT_COUNT_RE = re.compile(r"(\d{2,4})\s*枚")


SEARCH_QUERIES = [
    # Yahoo matches all words in a query, so "ワンピース ハイパーバトル"
    # misses a listing titled "カードダス ハイパーバトル ルフィ C05".
    # Bare set names give far better recall; the franchise guard and the
    # set filter keep the extra results clean.
    # --- Carddass / Hyper Battle / Visual Adventure ------------------
    "ハイパーバトル",
    "ビジュアルアドベンチャー",
    "カードダスマスターズ",
    "ワンピース カードダス",
    "ONE PIECE カードダス",

    # --- 2002-2005 One Piece Card Game (tournament / promo) ----------
    "ワンピース 旧裏",
    "旧ワンピースカード",
    "ワンピース カード 認定証",
    "ワンピース カードゲーム 2002",

    # --- Data Carddass: Berry Match family ---------------------------
    "ベリーマッチ",
    "ベリーマッチIC",
    "データカードダス ワンピース",

    # --- Miracle Battle Carddass / J-Heroes --------------------------
    # Multi-franchise sets: broad here, filtered by ONE_PIECE_TOKENS.
    "ミラクルバトルカードダス ワンピース",
    "ミラバト ワンピース",
    "Jヒーローズ ワンピース",

    # --- AR Formation ------------------------------------------------
    "ARカードダス",
    "ARフォーメーション",
]

# The three columns. (label, hours, how many to show)
WINDOWS = [
    ("Past 24 Hours", 24, 20),
    ("Past Week", 24 * 7, 20),
    ("Past Month", 24 * 30, 20),
]

MIN_PRICE_JPY = 3000

# --- Not a card at all ------------------------------------------------
# Magazines are the big one: V Jump issues get sold in bulk as vehicles for
# mail-in (応募) card offers, so they surface on card searches constantly
# while being, in fact, magazines.
NON_CARD_KEYWORDS = [
    # print media
    "特大号", "増刊", "月号", "雑誌", "書籍", "単行本", "攻略本", "ムック",
    "写真集", "画集", "設定資料", "応募券", "応募用紙", "抽選券", "冊",
    # other merchandise
    "フィギュア", "ぬいぐるみ", "キーホルダー", "タオル", "Tシャツ",
    "マグカップ", "クリアファイル", "下敷き", "文具", "食玩", "DVD",
    "ブルーレイ", "ゲームソフト", "コスプレ",
    # storage / equipment rather than cards
    "ケース", "スリーブ", "バインダー", "ファイル", "自販機", "本体", "空箱",
    # reproductions
    "複製", "コピー", "リメイク", "自作", "非公式",
]

# --- Modern-era exclusion -------------------------------------------
# The 2022+ ONE PIECE Card Game shares category and price range with the
# vintage material and would otherwise flood the board.
MODERN_TCG_KEYWORDS = [
    "手配書", "パラレル", "リーダー", "シークレット",
    "ロマンスドーン", "頂上決戦", "強大な敵", "謀略の王国",
    "新時代の主役", "双璧の覇者", "500年後の未来", "二つの伝説",
    "王族の血統", "受け継がれる意志", "プレミアムブースター",
]

# Modern set codes: OP01-118, ST12-004, EB02-001, PRB01-... etc.
MODERN_CODE_RE = re.compile(r"\b(?:OP|ST|EB|PRB)\d{2}[-–]\d{2,3}\b", re.IGNORECASE)

# Pages per query, per sort mode. Time-sorted covers "recent"; price-sorted
# reaches back for the big-ticket sales that fill the week/month columns.
PAGES_TIME_SORTED = 2
PAGES_PRICE_SORTED = 2
# The high-value sweep: only sales at or above this figure. This is the pass
# that catches expensive listings a recency-first crawl would never reach.
PAGES_VALUE_SWEEP = 3
HIGH_VALUE_FLOOR_JPY = 15000
RESULTS_PER_PAGE = 50

REQUEST_DELAY_SEC = 4.0
REQUEST_TIMEOUT_SEC = 30
MAX_RETRIES = 3
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

FX_ENDPOINT = "https://open.er-api.com/v6/latest/JPY"
FALLBACK_JPY_TO_USD = 0.0064
FX_CACHE_FILE = Path("fx_cache.json")
FX_CACHE_HOURS = 12

ENABLE_MERCARI = True
# The mercari library's search() walks EVERY page of results, which can take
# many minutes on a broad query. It yields lazily, so we cap it per query.
MERCARI_MAX_PER_QUERY = 80
MERCARI_DELAY_SEC = 3.0

OUTPUT_FILE = Path("index.html")
# Every run appends to this archive. Yahoo's closedsearch only reaches back
# ~180 days and Mercari less, so the archive is what lets the site show
# trends beyond what either source will still tell us on any given day.
HISTORY_FILE = Path("data/history.json")
HISTORY_RETAIN_DAYS = 400
TEMPLATE_FILE = Path("template.html")
DATA_PLACEHOLDER = "/*__DATA__*/"
# Cap the inlined payload so the page stays light. The front end filters
# and sorts client-side, so this is the pool it works from.
PAYLOAD_CAP = 400
LOOP_INTERVAL_MIN = 60

BASE_URL = "https://auctions.yahoo.co.jp/closedsearch/closedsearch"

NEXT_DATA_ITEM_PATH = [
    "props", "pageProps", "initialState", "search", "items", "listing", "items",
]

CARD_NUMBER_RE = re.compile(
    # Two-part codes glued to Japanese text, e.g. RG-C02, BN-04, PAS-016.
    # (?<![A-Za-z0-9]) rather than \b so 一歩RG-C02 still matches.
    r"(?<![A-Za-z0-9])[A-Z]{1,4}-[A-Z]?\d{2,4}(?![A-Za-z0-9])"
    # Plain codes, e.g. C428, S75, H10.
    r"|(?<![A-Za-z0-9])[A-Z]{1,2}\d{1,4}(?![A-Za-z0-9])"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("dashboard")


# =====================================================================
# CURRENCY
# =====================================================================

def get_jpy_to_usd() -> float:
    if FX_CACHE_FILE.exists():
        try:
            cache = json.loads(FX_CACHE_FILE.read_text())
            if time.time() - cache.get("fetched_at", 0) < FX_CACHE_HOURS * 3600:
                return float(cache["rate"])
        except (json.JSONDecodeError, KeyError, ValueError, OSError):
            pass
    try:
        resp = requests.get(FX_ENDPOINT, timeout=15)
        resp.raise_for_status()
        rate = float(resp.json()["rates"]["USD"])
        FX_CACHE_FILE.write_text(json.dumps({"rate": rate, "fetched_at": time.time()}))
        log.info("FX rate: 1 JPY = %.6f USD", rate)
        return rate
    except Exception as e:
        log.warning("FX lookup failed (%s). Using fallback.", e)
        return FALLBACK_JPY_TO_USD


# =====================================================================
# SCRAPING
# =====================================================================

def build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
    })
    return s


def fetch_page(session, query: str, page: int, sort_by: str,
               min_price: int = 0, debug=False) -> str:
    """sort_by: 'end' (most recently closed) or 'price' (highest first).

    min_price restricts the RESULT SET to sales at or above that figure,
    using the price_type/min parameters Yahoo uses on its own pages. This
    is what guarantees big-ticket sales surface: sorting alone can't be
    relied on, but a filtered result set can."""
    sort_key = "cbids" if sort_by == "price" else "end"
    params = {
        "p": query,
        "va": query,
        "b": (page - 1) * RESULTS_PER_PAGE + 1,
        "n": RESULTS_PER_PAGE,
        "s1": sort_key,
        "o1": "d",
    }
    if min_price:
        params["price_type"] = "currentprice"
        params["min"] = min_price
    url = f"{BASE_URL}?{urlencode(params)}"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT_SEC)
            if resp.status_code == 429:
                wait = 30 * attempt
                log.warning("Rate limited. Backing off %ss.", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            if debug:
                Path(f"debug_{sort_by}.html").write_text(resp.text, encoding="utf-8")
            return resp.text
        except requests.RequestException as e:
            log.warning("Fetch failed (%d/%d): %s", attempt, MAX_RETRIES, e)
            if attempt < MAX_RETRIES:
                time.sleep(5 * attempt)
    return ""


def extract_listing_items(page_html: str) -> list:
    if not page_html:
        return []
    soup = BeautifulSoup(page_html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        log.warning("No __NEXT_DATA__ found - Yahoo's page structure may have changed.")
        return []
    try:
        data = json.loads(script.string)
    except json.JSONDecodeError:
        return []

    node = data
    for key in NEXT_DATA_ITEM_PATH:
        if isinstance(node, dict) and key in node:
            node = node[key]
        else:
            log.warning("__NEXT_DATA__ structure changed (missing '%s').", key)
            return []
    return node if isinstance(node, list) else []


def parse_end_time(iso_text: str):
    if not iso_text:
        return None
    try:
        return dt.datetime.fromisoformat(iso_text)
    except ValueError:
        return None


def extract_card_number(title: str) -> str:
    m = CARD_NUMBER_RE.search(title)
    return m.group(0) if m else ""


def parse_results(page_html: str) -> list:
    raw_items = extract_listing_items(page_html)
    items = []
    for raw in raw_items:
        if raw.get("isShoppingItem"):
            continue
        auction_id = raw.get("auctionId")
        title = (raw.get("title") or "").strip()
        price = raw.get("price")
        if not auction_id or not title or price is None:
            continue

        is_flea = bool(raw.get("isFleamarketItem"))
        url = (f"https://paypayfleamarket.yahoo.co.jp/item/{auction_id}" if is_flea
               else f"https://page.auctions.yahoo.co.jp/jp/auction/{auction_id}")

        items.append({
            "auction_id": auction_id,
            "title": title,
            "price_jpy": int(price),
            "url": url,
            "source": "marketplace" if is_flea else "auction",
            "card_number": extract_card_number(title),
            "set_name": identify_set(title),
            "kind": classify_kind(title),
            "image_url": raw.get("imageUrl") or "",
            "end_date": parse_end_time(raw.get("endTime")),
            "bid_count": raw.get("bidCount"),
        })
    return items


def classify_kind(title: str) -> str:
    """'graded', 'lot' or 'single'. Graded wins: a PSA 10 in a lot title is
    still the thing setting the price."""
    if GRADED_RE.search(title):
        return "graded"
    if any(k in title for k in LOT_KEYWORDS):
        return "lot"
    m = LOT_COUNT_RE.search(title)
    if m and int(m.group(1)) >= 10:      # "50枚" is a lot; "1枚" is not
        return "lot"
    return "single"


def is_one_piece(title: str) -> bool:
    return any(tok in title for tok in ONE_PIECE_TOKENS)


def identify_set(title: str) -> str:
    """Return the display label of the first matching set, or '' if the
    title doesn't look like any set we track."""
    for label, keywords in SET_SIGNATURES:
        if any(kw in title for kw in keywords):
            return label
    return ""


def is_wanted(item: dict) -> bool:
    title = item["title"]

    if item["price_jpy"] < MIN_PRICE_JPY:
        return False

    # Not a card - magazines, merch, storage, repros.
    if any(bad in title for bad in NON_CARD_KEYWORDS):
        return False

    # Drop the modern (2022+) One Piece TCG.
    if MODERN_CODE_RE.search(title):
        return False
    if any(modern in title for modern in MODERN_TCG_KEYWORDS):
        return False

    # Broad set-name queries pull in other franchises (Miracle Battle and
    # J-Heroes covered Dragon Ball, Naruto and more), so prove it's One Piece.
    if not is_one_piece(title):
        return False

    # Positive requirement: it must look like one of the sets we track.
    # This is what keeps V Jump magazine lots and other stray listings off
    # the board - they match no set signature, so they never qualify.
    if not item.get("set_name"):
        return False

    return True


def collect_yahoo(session, debug=False) -> dict:
    """Scrape Yahoo Auctions / Yahoo!フリマ; return {item_id: item}."""
    merged = {}
    # Three passes, because no single one is sufficient:
    #   recent - full coverage of the last day, cheap items included
    #   value  - result set restricted to high-value sales, so a big sale
    #            from a week ago can't be buried under newer cheap ones
    #   price  - price-sorted sweep as a belt-and-braces third angle
    plan = [
        ("end",   PAGES_TIME_SORTED,  0),
        ("end",   PAGES_VALUE_SWEEP,  HIGH_VALUE_FLOOR_JPY),
        ("price", PAGES_PRICE_SORTED, 0),
    ]

    for query in SEARCH_QUERIES:
        for sort_by, n_pages, floor in plan:
            for page in range(1, n_pages + 1):
                tag = f"{sort_by}-sorted" + (f", ≥¥{floor:,}" if floor else "")
                log.info("Yahoo: %s (%s, page %d)", query, tag, page)
                found = parse_results(
                    fetch_page(session, query, page, sort_by, floor, debug))
                log.info("  parsed %d listings", len(found))
                for item in found:
                    merged.setdefault(item["auction_id"], item)
                time.sleep(REQUEST_DELAY_SEC)
                if len(found) < RESULTS_PER_PAGE:
                    break

    log.info("Yahoo unique listings: %d", len(merged))
    return merged


# ---------------------------------------------------------------------
# MERCARI
# ---------------------------------------------------------------------

def _pick_enum(cls, *candidate_names):
    """The mercari library's README disagrees with itself about enum member
    names, so resolve by trying each candidate rather than assuming one."""
    if cls is None:
        return None
    for name in candidate_names:
        if hasattr(cls, name):
            return getattr(cls, name)
    return None


def collect_mercari() -> dict:
    """Fetch sold listings from Mercari JP, normalised to the same shape
    as the Yahoo items so bucketing and rendering work unchanged."""
    if not ENABLE_MERCARI:
        return {}
    if not MERCARI_AVAILABLE:
        log.warning("mercari library not installed - skipping Mercari. "
                    "Install it with:  pip install mercari")
        return {}

    sold_status = _pick_enum(getattr(mercari_lib, "MercariSearchStatus", None),
                             "SOLD_OUT", "STATUS_SOLD_OUT")
    sort_price = _pick_enum(getattr(mercari_lib, "MercariSort", None),
                            "SORT_PRICE", "PRICE", "STATUS_PRICE")
    sort_recent = _pick_enum(getattr(mercari_lib, "MercariSort", None),
                             "SORT_CREATED_TIME", "CREATED_TIME", "SORT_CREATED",
                             "SORT_SCORE")
    order_desc = _pick_enum(getattr(mercari_lib, "MercariOrder", None),
                            "ORDER_DESC", "DESC", "SORT_DESC")

    if sold_status is None:
        log.error("Could not resolve Mercari's SOLD_OUT status - the library's "
                  "API may have changed. Skipping Mercari.")
        return {}

    # Two passes, for the same reason as Yahoo. Price-sorted returns the
    # dearest sales of ALL TIME for a query, so if 80 expensive historical
    # sales exist, today's big sale never appears. The recency pass is what
    # actually guarantees we see today.
    passes = [("price", sort_price)]
    if sort_recent is not None and sort_recent is not sort_price:
        passes.append(("recent", sort_recent))

    merged = {}
    for query in SEARCH_QUERIES:
        for label, sort_key in passes:
            kwargs = {"status": sold_status}
            if sort_key is not None:
                kwargs["sort"] = sort_key
            if order_desc is not None:
                kwargs["order"] = order_desc

            log.info("Mercari: %s (sold, %s, max %d)", query, label, MERCARI_MAX_PER_QUERY)
            try:
                # search() yields lazily and would otherwise walk every page.
                results = itertools.islice(
                    mercari_lib.search(query, **kwargs), MERCARI_MAX_PER_QUERY
                )
                count = 0
                for raw in results:
                    item = normalise_mercari_item(raw)
                    if item:
                        merged.setdefault(item["auction_id"], item)
                        count += 1
                log.info("  collected %d listings", count)
            except Exception as e:
                # One bad query shouldn't sink the whole build.
                log.error("  Mercari query failed (%s, %s): %s", query, label, e)

            time.sleep(MERCARI_DELAY_SEC)

    log.info("Mercari unique listings: %d", len(merged))
    return merged


def normalise_mercari_item(raw):
    """Map a mercari library item onto our internal shape. Returns None if
    the item is unusable."""
    try:
        item_id = getattr(raw, "id", None)
        title = (getattr(raw, "productName", "") or "").strip()
        price = getattr(raw, "price", None)
        url = getattr(raw, "productURL", "") or ""

        if not item_id or not title or price is None:
            return None

        # Mercari exposes no explicit "sold at" field. 'updated' is the last
        # mutation on the listing, which for a sold item is effectively the
        # sale - the best available proxy, but not guaranteed exact.
        updated = getattr(raw, "updated", None)
        end_date = None
        if updated:
            try:
                end_date = dt.datetime.fromtimestamp(int(updated), tz=dt.timezone.utc)
            except (ValueError, OSError, TypeError):
                end_date = None

        # Mercari now runs auctions too; surface the bid count when present.
        bid_count = None
        auction = getattr(raw, "auction", None)
        if auction is not None:
            bid_count = getattr(auction, "total_bid", None)

        return {
            "auction_id": f"mercari:{item_id}",
            "title": title,
            "price_jpy": int(price),
            "url": url or f"https://jp.mercari.com/item/{item_id}",
            "source": "mercari",
            "card_number": extract_card_number(title),
            "set_name": identify_set(title),
            "kind": classify_kind(title),
            "image_url": getattr(raw, "imageURL", "") or "",
            "end_date": end_date,
            "bid_count": bid_count,
        }
    except Exception as e:
        log.debug("Could not normalise a Mercari item: %s", e)
        return None


# =====================================================================
# HISTORY
# =====================================================================

def load_history() -> dict:
    """Previously-seen sales, keyed by id."""
    if not HISTORY_FILE.exists():
        log.info("No history file yet - starting a fresh archive.")
        return {}
    try:
        raw = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return {r["id"]: r for r in raw.get("items", [])}
    except (json.JSONDecodeError, OSError, KeyError, TypeError) as e:
        # A corrupt archive must not stop today's build.
        log.warning("Could not read history (%s). Starting fresh.", e)
        return {}


def merge_history(history: dict, all_items: dict) -> dict:
    """Fold this run's qualifying sales into the archive.

    First sighting wins: a listing's price is final once sold, and keeping
    the original record avoids a later re-scrape shifting a past figure."""
    added = 0
    # A single stamp for the whole run: per-item timestamps would make every
    # item its own "batch" and break new-arrival detection.
    batch_stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    for item in all_items.values():
        if not is_wanted(item) or not item["end_date"]:
            continue
        key = item["auction_id"]
        if key in history:
            continue
        history[key] = {
            "id": key,
            "title": item["title"],
            "price": item["price_jpy"],
            "url": item["url"],
            "source": item["source"],
            "set": item.get("set_name") or "",
            "card": item.get("card_number") or "",
            "kind": item.get("kind") or "single",
            "image": item.get("image_url") or "",
            "end": item["end_date"].astimezone(dt.timezone.utc).isoformat(),
            "bids": item.get("bid_count"),
            "first_seen": batch_stamp,
        }
        added += 1

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=HISTORY_RETAIN_DAYS)
    pruned = {}
    for key, rec in history.items():
        try:
            if dt.datetime.fromisoformat(rec["end"]) >= cutoff:
                pruned[key] = rec
        except (ValueError, KeyError):
            continue

    log.info("History: %d new, %d total (%d pruned)",
             added, len(pruned), len(history) - len(pruned))
    return pruned


def save_history(history: dict) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated": dt.datetime.now(dt.timezone.utc).isoformat(),
        "items": sorted(history.values(), key=lambda r: r["end"], reverse=True),
    }
    HISTORY_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    log.info("Archive written: %s (%d sales)", HISTORY_FILE, len(history))


# =====================================================================
# OUTPUT
# =====================================================================
# Python no longer renders finished HTML. It emits the data, and
# template.html renders it in the browser - which is what makes search,
# filtering, currency switching and the detail drawer possible at all.

def summarise_sets(history: dict) -> list:
    """Per-set stats over the archive: how many sold, what the middle of the
    market looks like, and whether that has moved.

    Median rather than mean, because one ¥345,000 certification card would
    drag a mean well away from what a typical card in that set fetches."""
    now = dt.datetime.now(dt.timezone.utc)
    recent_cut = now - dt.timedelta(days=30)
    prior_cut = now - dt.timedelta(days=60)

    by_set = {}
    for rec in history.values():
        name = rec.get("set") or ""
        if not name:
            continue
        try:
            end = dt.datetime.fromisoformat(rec["end"])
        except (ValueError, KeyError):
            continue
        by_set.setdefault(name, {"recent": [], "prior": [], "peak": 0})
        b = by_set[name]
        if end >= recent_cut:
            b["recent"].append(rec["price"])
            b["peak"] = max(b["peak"], rec["price"])
        elif end >= prior_cut:
            b["prior"].append(rec["price"])

    out = []
    for name, b in by_set.items():
        if not b["recent"]:
            continue
        med = statistics.median(b["recent"])
        # Needs a comparable prior period; too few points and the number is
        # noise dressed up as a trend, so report nothing rather than mislead.
        change = None
        if len(b["prior"]) >= 3 and len(b["recent"]) >= 3:
            prior_med = statistics.median(b["prior"])
            if prior_med:
                change = round((med - prior_med) / prior_med * 100)
        out.append({
            "name": name,
            "count": len(b["recent"]),
            "median": int(med),
            "peak": b["peak"],
            "change": change,
        })

    out.sort(key=lambda s: s["count"], reverse=True)
    return out


def build_payload(all_items: dict, rate: float, history: dict = None) -> dict:
    """Everything that qualifies, within the widest window, ranked by price."""
    widest_hours = max(hours for _, hours, _ in WINDOWS)
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=widest_hours)

    # Draw from the archive, not just this run, so the board still shows a
    # full month even if one scrape comes back thin.
    source = history if history else {}
    rows = []
    for rec in source.values():
        try:
            end = dt.datetime.fromisoformat(rec["end"])
        except (ValueError, KeyError):
            continue
        if end < cutoff:
            continue
        rows.append(rec)

    rows.sort(key=lambda r: r["price"], reverse=True)
    rows = rows[:PAYLOAD_CAP]

    # --- record highs -------------------------------------------------
    # A sale is a record if nothing in the whole archive for that set (or
    # that specific card number) ever went higher. This is the signal worth
    # noticing: not "expensive", but "the most this has ever sold for".
    # Track the best price and how many sales share it. A price matched by
    # several listings isn't a record - it's just the going rate.
    def note(store, key, price):
        cur = store.get(key)
        if cur is None or price > cur[0]:
            store[key] = [price, 1]
        elif price == cur[0]:
            cur[1] += 1

    set_best, card_best = {}, {}
    for rec in source.values():
        if rec.get("set"):
            note(set_best, rec["set"], rec["price"])
        if rec.get("card"):
            note(card_best, rec["card"], rec["price"])

    # --- new since the previous run -----------------------------------
    seen_times = [r.get("first_seen") for r in source.values() if r.get("first_seen")]
    newest_batch = max(seen_times) if seen_times else None

    out = []
    for rec in rows:
        r = dict(rec)
        r["record"] = ""
        cb = card_best.get(rec.get("card") or "")
        sb = set_best.get(rec.get("set") or "")
        if cb and cb[1] == 1 and rec["price"] == cb[0]:
            r["record"] = "card"
        elif sb and sb[1] == 1 and rec["price"] == sb[0]:
            r["record"] = "set"
        r["is_new"] = bool(newest_batch and rec.get("first_seen") == newest_batch)
        r.pop("first_seen", None)
        out.append(r)
    rows = out

    log.info("Payload: %d items (%d new this run, %d record highs)",
             len(rows),
             sum(1 for r in rows if r["is_new"]),
             sum(1 for r in rows if r["record"]))
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "rate": rate,
        "windows": [{"label": label, "hours": hours} for label, hours, _ in WINDOWS],
        "items": rows,
        "sets": summarise_sets(source),
        "archive_size": len(source),
    }


def render_page(payload: dict) -> str:
    """Inject the payload into template.html.

    The data is inlined rather than fetched, so the page works when opened
    straight off disk (a fetch() would be blocked by CORS on file://) as
    well as when hosted."""
    if not TEMPLATE_FILE.exists():
        raise FileNotFoundError(
            f"{TEMPLATE_FILE} not found. It must sit alongside dashboard.py."
        )

    template = TEMPLATE_FILE.read_text(encoding="utf-8")
    if DATA_PLACEHOLDER not in template:
        raise ValueError(f"{TEMPLATE_FILE} is missing the {DATA_PLACEHOLDER} marker.")

    # ensure_ascii keeps the JSON free of raw "</script>" and stray unicode
    # that could terminate the script block early.
    blob = json.dumps(payload, ensure_ascii=True).replace("<", "\\u003c")
    return template.replace(DATA_PLACEHOLDER, blob)


# =====================================================================
# MAIN
# =====================================================================

def build(debug=False) -> None:
    log.info("=== Build started ===")
    rate = get_jpy_to_usd()
    session = build_session()

    all_items = {}
    all_items.update(collect_yahoo(session, debug=debug))
    all_items.update(collect_mercari())
    log.info("Combined unique listings: %d", len(all_items))

    history = merge_history(load_history(), all_items)
    save_history(history)
    payload = build_payload(all_items, rate, history)

    OUTPUT_FILE.write_text(render_page(payload), encoding="utf-8")
    log.info("Wrote %s", OUTPUT_FILE.resolve())
    log.info("=== Build finished ===")


def main() -> None:
    parser = argparse.ArgumentParser(description="One Piece card sales dashboard")
    parser.add_argument("--open", action="store_true", help="open the page after building")
    parser.add_argument("--loop", action="store_true",
                        help=f"rebuild every {LOOP_INTERVAL_MIN} minutes")
    parser.add_argument("--debug", action="store_true", help="dump raw HTML")
    args = parser.parse_args()

    build(debug=args.debug)

    if args.open:
        webbrowser.open(OUTPUT_FILE.resolve().as_uri())

    if args.loop:
        log.info("Looping every %d minutes. Ctrl+C to stop.", LOOP_INTERVAL_MIN)
        while True:
            time.sleep(LOOP_INTERVAL_MIN * 60)
            try:
                build()
            except Exception as e:
                # Never let one bad run kill a long-running loop.
                log.error("Build failed: %s", e)


if __name__ == "__main__":
    main()
