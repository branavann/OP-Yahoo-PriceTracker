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


SEARCH_QUERIES = [
    # --- Carddass / Hyper Battle / Visual Adventure ------------------
    "ワンピース カードダス",
    "ワンピース ハイパーバトル",
    "ONE PIECE ハイパーバトル",
    "ワンピース ビジュアルアドベンチャー",
    "ワンピース カードダスマスターズ",

    # --- 2002-2005 One Piece Card Game (tournament / promo) ----------
    "ワンピース 旧裏",
    "旧ワンピースカード",
    "ワンピース カード 認定証",
    "ワンピース カードゲーム 2002",

    # --- Data Carddass: Berry Match family ---------------------------
    "ワンピース ベリーマッチ",
    "ワンピース ベリーマッチW",
    "ワンピース ベリーマッチIC",
    "データカードダス ワンピース",

    # --- Miracle Battle Carddass / J-Heroes --------------------------
    "ミラクルバトルカードダス ワンピース",
    "ワンピース ミラバト キラ",
    "ワンピース Jヒーローズ",

    # --- AR Formation ------------------------------------------------
    "ワンピース ARカードダス",
    "ワンピース ARフォーメーション",
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
PAGES_PRICE_SORTED = 3
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


def fetch_page(session, query: str, page: int, sort_by: str, debug=False) -> str:
    """sort_by: 'end' (most recently closed) or 'price' (highest first)."""
    sort_key = "cbids" if sort_by == "price" else "end"
    params = {
        "p": query,
        "va": query,
        "b": (page - 1) * RESULTS_PER_PAGE + 1,
        "n": RESULTS_PER_PAGE,
        "s1": sort_key,
        "o1": "d",
    }
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
            "image_url": raw.get("imageUrl") or "",
            "end_date": parse_end_time(raw.get("endTime")),
            "bid_count": raw.get("bidCount"),
        })
    return items


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

    # Positive requirement: it must look like one of the sets we track.
    # This is what keeps V Jump magazine lots and other stray listings off
    # the board - they match no set signature, so they never qualify.
    if not item.get("set_name"):
        return False

    return True


def collect_yahoo(session, debug=False) -> dict:
    """Scrape Yahoo Auctions / Yahoo!フリマ; return {item_id: item}."""
    merged = {}
    plan = [("end", PAGES_TIME_SORTED), ("price", PAGES_PRICE_SORTED)]

    for query in SEARCH_QUERIES:
        for sort_by, n_pages in plan:
            for page in range(1, n_pages + 1):
                log.info("Yahoo: %s (%s-sorted, page %d)", query, sort_by, page)
                found = parse_results(fetch_page(session, query, page, sort_by, debug))
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
    order_desc = _pick_enum(getattr(mercari_lib, "MercariOrder", None),
                            "ORDER_DESC", "DESC", "SORT_DESC")

    if sold_status is None:
        log.error("Could not resolve Mercari's SOLD_OUT status - the library's "
                  "API may have changed. Skipping Mercari.")
        return {}

    kwargs = {"status": sold_status}
    if sort_price is not None:
        kwargs["sort"] = sort_price
    if order_desc is not None:
        kwargs["order"] = order_desc

    merged = {}
    for query in SEARCH_QUERIES:
        log.info("Mercari: %s (sold, price desc, max %d)", query, MERCARI_MAX_PER_QUERY)
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
            log.error("  Mercari query failed (%s): %s", query, e)

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
            "image_url": getattr(raw, "imageURL", "") or "",
            "end_date": end_date,
            "bid_count": bid_count,
        }
    except Exception as e:
        log.debug("Could not normalise a Mercari item: %s", e)
        return None


def bucket_by_window(all_items: dict) -> dict:
    """Split into the three time windows, each ranked by price."""
    now = dt.datetime.now(dt.timezone.utc)
    buckets = {}

    for label, hours, top_n in WINDOWS:
        cutoff = now - dt.timedelta(hours=hours)
        matching = [
            item for item in all_items.values()
            if is_wanted(item) and item["end_date"] and item["end_date"] >= cutoff
        ]
        matching.sort(key=lambda i: i["price_jpy"], reverse=True)
        buckets[label] = matching[:top_n]
        log.info("%s: %d qualifying, showing %d", label, len(matching), len(buckets[label]))

    return buckets


# =====================================================================
# HTML OUTPUT
# =====================================================================

def render_html(buckets: dict, rate: float) -> str:
    now_local = dt.datetime.now()

    SOURCE_LABELS = {
        "auction": ("Yahoo Auction", "auction"),
        "marketplace": ("Yahoo Flea", "market"),
        "mercari": ("Mercari", "mercari"),
    }

    def render_item(item, rank):
        usd = item["price_jpy"] * rate
        tag, tag_class = SOURCE_LABELS.get(item.get("source"), ("Listing", "auction"))
        # Yahoo Flea listings are fixed-price and have no bidding, even
        # though the feed sometimes carries a stray bidCount.
        bids = item.get("bid_count")
        show_bids = bids and item.get("source") != "marketplace"
        bid_str = f"&nbsp;&middot;&nbsp;{bids} bids" if show_bids else ""
        date_str = f"{item['end_date']:%d %b}" if item["end_date"] else "&mdash;"
        card = item.get("card_number")
        card_html = f'<span class="chip">{html.escape(card)}</span>' if card else ""
        set_name = item.get("set_name")
        set_html = f'<span class="chip set">{html.escape(set_name)}</span>' if set_name else ""
        img = html.escape(item.get("image_url") or "")
        img_html = (f'<img src="{img}" alt="" loading="lazy">' if img
                    else '<span class="ph"></span>')

        return f"""
          <a class="row" href="{html.escape(item['url'])}" target="_blank" rel="noopener">
            <span class="rank{' top' if rank <= 3 else ''}">{rank}</span>
            <span class="thumb">{img_html}</span>
            <span class="info">
              <span class="price">&yen;{item['price_jpy']:,}<span class="usd">${usd:,.0f}</span></span>
              <span class="name">{html.escape(item['title'][:110])}</span>
              <span class="meta"><span class="tag {tag_class}">{tag}</span>{set_html}{card_html}<span class="when">{date_str}{bid_str}</span></span>
            </span>
            <span class="chev">&rsaquo;</span>
          </a>"""

    columns = []
    for label, hours, _ in WINDOWS:
        items = buckets.get(label, [])
        subtotal = sum(i["price_jpy"] for i in items)
        peak = max((i["price_jpy"] for i in items), default=0)
        rows = "".join(render_item(it, n) for n, it in enumerate(items, 1))
        if not rows:
            rows = '<div class="empty">Nothing sold in this window</div>'
        columns.append(f"""
        <section class="col">
          <div class="col-head">
            <h2>{html.escape(label)}</h2>
            <div class="figures">
              <span class="fig"><em>&yen;{peak:,}</em><small>Peak</small></span>
              <span class="rule"></span>
              <span class="fig"><em>&yen;{subtotal:,}</em><small>Volume</small></span>
              <span class="rule"></span>
              <span class="fig"><em>{len(items)}</em><small>Sales</small></span>
            </div>
          </div>
          <div class="rows">{rows}</div>
        </section>""")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{LOOP_INTERVAL_MIN * 60}">
<meta name="color-scheme" content="light dark">
<title>One Piece Card Sales</title>
<style>
  :root {{
    --bg:#fbfbfd;
    --surface:#ffffff;
    --ink:#1d1d1f;
    --ink-2:#6e6e73;
    --ink-3:#a1a1a6;
    --hair:rgba(0,0,0,.08);
    --hover:rgba(0,0,0,.022);
    --accent:#0071e3;
    --market:#8944ab;
    --mercari:#d0342c;
    --shadow:0 4px 20px rgba(0,0,0,.05);
    --radius:18px;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg:#000000;
      --surface:#1c1c1e;
      --ink:#f5f5f7;
      --ink-2:#a1a1a6;
      --ink-3:#6e6e73;
      --hair:rgba(255,255,255,.1);
      --hover:rgba(255,255,255,.04);
      --accent:#2997ff;
      --market:#bf5af2;
      --mercari:#ff6961;
      --shadow:none;
    }}
  }}

  * {{ box-sizing:border-box; }}
  html {{ -webkit-font-smoothing:antialiased; -moz-osx-font-smoothing:grayscale; }}
  body {{
    margin:0; background:var(--bg); color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text",
                "Helvetica Neue",Helvetica,Arial,sans-serif;
    font-size:15px; line-height:1.47;
    font-variant-numeric:tabular-nums;
  }}
  .wrap {{ max-width:1240px; margin:0 auto; padding:72px 24px 88px; }}

  /* ---------- header ---------- */
  .head {{ text-align:center; margin-bottom:52px; }}
  .kicker {{
    font-size:12px; font-weight:600; letter-spacing:.02em;
    color:var(--accent); margin:0 0 10px;
  }}
  h1 {{
    font-size:52px; font-weight:600; letter-spacing:-.025em;
    line-height:1.06; margin:0 0 14px;
  }}
  .sub {{
    font-size:19px; color:var(--ink-2); margin:0 auto; max-width:600px;
    letter-spacing:-.01em; font-weight:400;
  }}
  .stamp {{
    display:inline-flex; align-items:center;
    margin-top:22px; font-size:13px; color:var(--ink-3);
  }}
  .pip {{
    width:6px; height:6px; border-radius:50%; background:#30d158; margin-right:8px;
    animation:breathe 2.6s ease-in-out infinite;
  }}
  @keyframes breathe {{ 0%,100%{{opacity:1}} 50%{{opacity:.3}} }}

  /* ---------- columns ---------- */
  .grid {{ display:flex; align-items:flex-start; margin-right:-22px; }}
  .col {{
    flex:1 1 0; min-width:0; margin-right:22px;
    background:var(--surface); border-radius:var(--radius);
    box-shadow:var(--shadow); overflow:hidden;
  }}
  @media (max-width:940px) {{
    .grid {{ flex-direction:column; margin-right:0; }}
    .col {{ width:100%; margin-right:0; margin-bottom:22px; }}
    h1 {{ font-size:38px; }}
    .sub {{ font-size:17px; }}
    .wrap {{ padding:48px 18px 64px; }}
  }}

  .col-head {{ padding:26px 26px 20px; border-bottom:1px solid var(--hair); }}
  .col-head h2 {{
    font-size:21px; font-weight:600; letter-spacing:-.015em; margin:0 0 16px;
  }}
  .figures {{ display:flex; align-items:center; }}
  .fig {{ display:flex; flex-direction:column; min-width:0; margin-right:16px; }}
  .fig em {{
    font-style:normal; font-size:15px; font-weight:600;
    letter-spacing:-.01em; white-space:nowrap;
  }}
  .fig small {{
    font-size:11px; font-weight:400; color:var(--ink-3); letter-spacing:.01em;
  }}
  .rule {{ width:1px; align-self:stretch; background:var(--hair); margin-right:16px; }}

  /* ---------- rows ---------- */
  .rows {{ padding:4px 6px 6px; }}
  .row {{
    display:flex; align-items:center; position:relative;
    padding:10px 14px; border-radius:10px;
    text-decoration:none; color:inherit;
    transition:background .18s ease;
  }}
  /* Hairline between rows, inset past the thumbnail so it reads as a list
     rather than a table. Long columns need this to stay scannable. */
  .row + .row::before {{
    content:""; position:absolute; left:14px; right:14px; top:0;
    height:1px; background:var(--hair);
  }}
  .row:hover {{ background:var(--hover); }}
  .row:hover::before, .row:hover + .row::before {{ background:transparent; }}
  .row:hover .chev {{ opacity:.55; transform:translateX(2px); }}

  .rank {{
    flex:0 0 18px; text-align:center; margin-right:12px;
    font-size:12px; font-weight:500; color:var(--ink-3);
    font-variant-numeric:tabular-nums;
  }}
  .rank.top {{ color:var(--ink); font-weight:600; }}
  .thumb {{ flex:0 0 46px; margin-right:13px; }}
  .thumb img, .ph {{
    width:46px; height:46px; border-radius:9px; display:block;
    object-fit:cover; background:var(--hover);
    box-shadow:inset 0 0 0 1px var(--hair);
  }}

  .info {{ flex:1; min-width:0; display:flex; flex-direction:column; }}
  .info > * {{ margin-bottom:3px; }}
  .info > *:last-child {{ margin-bottom:0; }}
  .price {{
    font-size:15.5px; font-weight:600; letter-spacing:-.015em;
    display:flex; align-items:baseline;
  }}
  .usd {{
    font-size:12px; font-weight:400; color:var(--ink-3);
    letter-spacing:0; margin-left:8px;
  }}
  .name {{
    font-size:12.5px; color:var(--ink-2); line-height:1.35;
    display:-webkit-box; -webkit-line-clamp:1; -webkit-box-orient:vertical;
    overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
  }}
  .meta {{ display:flex; align-items:center; margin-top:2px; flex-wrap:wrap; }}
  .meta > * {{ margin-right:8px; }}
  .meta > *:last-child {{ margin-right:0; }}
  .tag {{ font-size:11px; font-weight:500; color:var(--accent); }}
  .tag.market {{ color:var(--market); }}
  .tag.mercari {{ color:var(--mercari); }}
  .chip {{
    font-size:10.5px; font-weight:500; color:var(--ink-2);
    background:var(--hover); box-shadow:inset 0 0 0 1px var(--hair);
    border-radius:5px; padding:1.5px 6px;
    font-family:ui-monospace,"SF Mono",Menlo,monospace;
  }}
  .chip.set {{
    font-family:inherit; font-weight:600; color:var(--ink-2);
    background:transparent; box-shadow:inset 0 0 0 1px var(--hair);
  }}
  .when {{ font-size:11.5px; color:var(--ink-3); }}

  .chev {{
    flex:0 0 auto; font-size:19px; color:var(--ink-3);
    opacity:0; transition:opacity .18s ease, transform .18s ease;
  }}
  .empty {{ padding:44px 20px; text-align:center; color:var(--ink-3); font-size:14px; }}

  /* ---------- footer ---------- */
  footer {{
    margin-top:44px; padding-top:26px; border-top:1px solid var(--hair);
    text-align:center; font-size:12px; color:var(--ink-3); line-height:1.8;
  }}
</style>
</head>
<body>
<div class="wrap">

  <header class="head">
    <p class="kicker">Market Tracker</p>
    <h1>One Piece Card Sales</h1>
    <p class="sub">Realised prices for Bandai One Piece card sets \u2014 Carddass, Hyper Battle, Visual Adventure, the 2002\u201305 card game, Berry Match, Miracle Battle, J-Heroes and AR Formation.</p>
    <div class="stamp"><span class="pip"></span>Updated {now_local:%-d %b, %-I:%M %p}
       &middot; refreshes hourly</div>
  </header>

  <div class="grid">{"".join(columns)}</div>

  <footer>
    Every figure is a completed sale, from Yahoo! Auctions, Yahoo!\u30d5\u30ea\u30de and Mercari JP.<br>
    Select any row to open the original listing.<br>
    1 JPY = {rate:.6f} USD
  </footer>

</div>
</body>
</html>"""

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

    buckets = bucket_by_window(all_items)

    OUTPUT_FILE.write_text(render_html(buckets, rate), encoding="utf-8")
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
