"""
Slide design.
=============

Four 1080x1350 artboards: a cover, then one per sale.

The brief was "a marketer or graphic designer built this, not an engineer":
warm paper rather than white, one restrained accent, a display serif doing
the heavy lifting, micro-labels in wide-tracked uppercase, and a lot of air.
Nothing is centred by default and nothing is bold-blue.

Everything is inlined (fonts as base64, no external requests) so the render
is deterministic and works with no network.
"""

import base64
import pathlib
import datetime as dt

# Fonts are NOT vendored into the repo - they are fetched at build time:
#
#     npm install @fontsource/instrument-serif @fontsource/inter \
#                 @fontsource/newsreader
#
# This repo already commits an archive every hour; 140KB of binaries it
# doesn't need is 140KB in every clone forever. CI installs dependencies
# anyway. To vendor them instead, drop the .woff2 files in postkit/assets/.
FONT_SEARCH_PATHS = [
    pathlib.Path(__file__).parent / "assets",
    pathlib.Path(__file__).parent.parent / "node_modules" / "@fontsource",
    pathlib.Path.cwd() / "node_modules" / "@fontsource",
]


def _find_font(filename: str) -> pathlib.Path:
    family = filename.rsplit("-latin-", 1)[0]
    for root in FONT_SEARCH_PATHS:
        for candidate in (root / filename, root / family / "files" / filename):
            if candidate.exists():
                return candidate
    raise FileNotFoundError(
        f"Font {filename} not found. Run:\n"
        f"  npm install @fontsource/instrument-serif @fontsource/inter "
        f"@fontsource/newsreader\n"
        f"or place the .woff2 files in postkit/assets/.")

# Instagram serves feed images at 1080px wide and recommends 4:5 portrait,
# so 1080x1350 is the native size - not a size we scale to.
W, H = 1080, 1350

# Since Jan 2025 the profile GRID crops every thumbnail to 3:4, which takes
# ~34px off each side of a 4:5 post (1080 -> ~1012 centred). The grid is
# where a new visitor decides whether to follow, so nothing that carries
# meaning may sit in those strips. The 84px page padding clears it with
# room to spare; this constant exists so the guard can be checked.
GRID_SAFE_INSET = 34
PAGE_PADDING = 84


def _font_face(family, file, weight=400, style="normal"):
    data = base64.b64encode(_find_font(file).read_bytes()).decode()
    return (f"@font-face{{font-family:'{family}';font-style:{style};"
            f"font-weight:{weight};font-display:block;"
            f"src:url(data:font/woff2;base64,{data}) format('woff2');}}")


def font_css():
    return "".join([
        _font_face("Instrument Serif", "instrument-serif-latin-400-normal.woff2", 400),
        _font_face("Inter", "inter-latin-400-normal.woff2", 400),
        _font_face("Inter", "inter-latin-500-normal.woff2", 500),
        _font_face("Inter", "inter-latin-600-normal.woff2", 600),
        _font_face("Newsreader", "newsreader-latin-300-normal.woff2", 300),
        _font_face("Newsreader", "newsreader-latin-400-normal.woff2", 400),
    ])


PALETTE = {
    "paper":    "#F2EEE6",
    "paper_2":  "#EAE4D8",
    "ink":      "#22201C",
    "ink_soft": "#6E675C",
    "ink_faint":"#A39B8D",
    "line":     "#D9D2C4",
    "clay":     "#9C4A38",
}


BASE_CSS = """
*{margin:0;padding:0;box-sizing:border-box;}
body{background:#3a3a38;}
.sheet{
  width:1080px;height:1350px;position:relative;overflow:hidden;
  background:var(--paper);color:var(--ink);
  font-family:'Inter',sans-serif;
  display:flex;flex-direction:column;
}
/* A barely-there paper tooth. Flat colour reads as a screenshot; this
   reads as something printed. */
.sheet::after{
  content:'';position:absolute;inset:0;pointer-events:none;opacity:.5;
  background-image:radial-gradient(circle at 1px 1px, rgba(90,80,64,.055) 1px, transparent 0);
  background-size:4px 4px;
}
.pad{padding:78px 84px;}

/* --- micro type ------------------------------------------------- */
.label{
  font-size:15px;font-weight:500;letter-spacing:.22em;text-transform:uppercase;
  color:var(--ink-faint);
}
.label.dark{color:var(--ink-soft);}
.rule{height:1px;background:var(--line);width:100%;}

/* --- header / footer -------------------------------------------- */
.top{display:flex;justify-content:space-between;align-items:baseline;}
.foot{
  margin-top:auto;display:flex;justify-content:space-between;align-items:flex-end;
  font-size:15px;color:var(--ink-faint);letter-spacing:.06em;
}
.handle{font-weight:500;letter-spacing:.16em;text-transform:uppercase;font-size:14px;}

/* --- serif display ---------------------------------------------- */
.display{font-family:'Instrument Serif',Georgia,serif;font-weight:400;line-height:.92;}
.jp{font-family:'Noto Sans CJK JP','Noto Sans JP',sans-serif;font-weight:300;}
"""


COVER_CSS = """
.cover .kicker{margin-bottom:26px;}
.cover h1{
  font-family:'Instrument Serif',Georgia,serif;font-weight:400;
  font-size:104px;line-height:.94;letter-spacing:-.015em;margin-bottom:18px;
}
/* The italic's overhang swallows the following word-space, so give it back. */
.cover h1 em{font-style:italic;color:var(--clay);padding-right:.24em;}
.cover .sub{
  font-family:'Newsreader',Georgia,serif;font-weight:300;font-size:25px;
  line-height:1.5;color:var(--ink-soft);max-width:520px;margin-bottom:56px;
}
/* Pushed down so the list sits against the footer instead of leaving a
   dead band at the bottom of the frame. */
.cover .list{margin-top:auto;margin-bottom:76px;}
.cover .row{
  display:flex;align-items:baseline;gap:26px;
  padding:26px 0;border-top:1px solid var(--line);
}
.cover .row:last-child{border-bottom:1px solid var(--line);}
.cover .idx{
  font-family:'Inter',sans-serif;font-size:13px;font-weight:500;
  letter-spacing:.18em;color:var(--ink-faint);width:30px;flex:none;
}
.cover .nm{flex:1;min-width:0;}
.cover .nm .t{
  font-family:'Newsreader',Georgia,serif;font-size:29px;font-weight:400;
  line-height:1.22;letter-spacing:-.005em;
}
.cover .nm .s{
  font-size:14px;color:var(--ink-faint);letter-spacing:.13em;
  text-transform:uppercase;margin-top:9px;
}
.cover .amt{
  font-family:'Instrument Serif',Georgia,serif;font-size:46px;line-height:1;
  white-space:nowrap;letter-spacing:-.01em;
}
"""


SALE_CSS = """
.sale .top{margin-bottom:52px;}
.sale .plate{
  width:100%;height:648px;background:var(--paper-2);
  border:1px solid var(--line);
  display:flex;align-items:center;justify-content:center;
  position:relative;overflow:hidden;margin-bottom:46px;
}
.sale .plate img{max-width:84%;max-height:84%;object-fit:contain;
  box-shadow:0 22px 48px -20px rgba(40,32,20,.42), 0 3px 10px rgba(40,32,20,.10);}
.sale .plate .ph{
  text-align:center;color:var(--ink-faint);
}
.sale .plate .ph .box{
  width:268px;height:376px;border:1px dashed var(--line);margin:0 auto 22px;
  background:linear-gradient(150deg,#E4DDCF 0%,#EFEAE0 52%,#E1D9C9 100%);
  display:flex;align-items:center;justify-content:center;
  font-family:'Instrument Serif',serif;font-size:34px;color:#BDB3A0;
  box-shadow:0 20px 40px -22px rgba(40,32,20,.35);
}
.sale .plate .ph .cap{font-size:12px;letter-spacing:.2em;text-transform:uppercase;}

.sale .eyebrow{
  font-size:13px;font-weight:500;letter-spacing:.2em;text-transform:uppercase;
  color:var(--clay);margin-bottom:16px;
  display:flex;align-items:center;gap:14px;
}
/* Sealed product is a real market signal but it is not a card sale, and a
   reader must never have to work that out from the photo. */
.badge{
  font-size:11px;font-weight:600;letter-spacing:.18em;
  border:1px solid var(--clay);color:var(--clay);
  padding:5px 10px 4px;border-radius:2px;line-height:1;
}
.cover .badge{margin-left:12px;vertical-align:middle;}
.sale h2{
  font-family:'Instrument Serif',Georgia,serif;font-weight:400;
  font-size:70px;line-height:.98;letter-spacing:-.018em;margin-bottom:12px;
}
/* Only the card's own Japanese name, never the seller's keyword-stuffed
   title - the whole title reads as clutter and defeats the point. */
.sale .jptitle{
  font-size:21px;color:var(--ink-faint);line-height:1.4;letter-spacing:.04em;
}
.sale .meta{
  display:flex;gap:0;border-top:1px solid var(--line);
  padding-top:26px;align-items:flex-start;margin-top:auto;
}
.sale .cell{flex:1;}
.sale .cell .k{
  font-size:12px;letter-spacing:.2em;text-transform:uppercase;
  color:var(--ink-faint);margin-bottom:10px;
}
.sale .cell .v{
  font-family:'Newsreader',Georgia,serif;font-size:23px;font-weight:400;
  line-height:1.25;color:var(--ink);
}
.sale .price{text-align:right;flex:none;}
.sale .price .v{
  font-family:'Instrument Serif',Georgia,serif;font-size:78px;line-height:.86;
  letter-spacing:-.02em;color:var(--clay);
}
.sale .num{
  font-family:'Instrument Serif',Georgia,serif;font-size:20px;
  color:var(--ink-faint);letter-spacing:.04em;
}
"""


def _money(n: int) -> str:
    return f"${n:,}"


def _date_line(day: str) -> str:
    d = dt.date.fromisoformat(day)
    return d.strftime("%d %B %Y").upper().lstrip("0")


def _source_label(sale: dict) -> str:
    src = {
        "auction": "Yahoo! Auctions",
        "marketplace": "Yahoo! Flea Market",
        "mercari": "Mercari Japan",
    }.get(sale.get("source", ""), sale.get("source", "—"))
    bids = sale.get("bids")
    if bids:
        src += f" · {bids} bid{'s' if bids != 1 else ''}"
    return src


def _short_name(sale: dict) -> str:
    """Title for the slide. Falls back gracefully rather than printing a
    guess: an unidentified card says so."""
    # The set already sits on the line beneath, so a sealed row only needs
    # the product unit.
    if sale["sealed"]:
        return sale["display_name"].split("—")[-1].strip()
    if sale["display_name"] and sale["display_name"] != "Unidentified card":
        return sale["display_name"].replace(" · ", " ")
    if sale["code"]:
        return f"{sale['set_name']} {sale['code']}"
    return sale["set_name"] or "Unidentified"


def _headline(sale: dict):
    """(eyebrow, headline). The character is the eyebrow and the card name
    is the headline - reads as a gallery label rather than a database row.
    With no card name the headline carries whatever identity we do have."""
    if sale["sealed"]:
        # "MIRACLE BATTLE" / "Sealed Box" - the set is the eyebrow, the
        # product unit is the headline.
        unit = sale["display_name"].split("—")[-1].strip()
        return (sale["set_name"] or "Sealed").upper(), unit
    if sale["card_name"] and sale["character"]:
        return sale["character"].upper(), sale["card_name"]
    if sale["card_name"]:
        return (sale["code"] or sale["set_name"]).upper(), sale["card_name"]
    if sale["character"]:
        return (sale["code"] or sale["set_name"]).upper(), sale["character"]
    if sale["code"]:
        return sale["set_name"].upper(), f"Card {sale['code']}"
    return sale["set_name"].upper(), "Unidentified card"


def cover_slide(day: str, sales: list, handle: str) -> str:
    rows = []
    for i, s in enumerate(sales, 1):
        sub = " / ".join(x for x in [s["set_name"], s["code"] or None] if x)
        badge = '<span class="badge">SEALED</span>' if s["sealed"] else ""
        rows.append(f"""
        <div class="row">
          <div class="idx">{i:02d}</div>
          <div class="nm">
            <div class="t">{_short_name(s)}{badge}</div>
            <div class="s">{sub}</div>
          </div>
          <div class="amt">{_money(s['price_usd'])}</div>
        </div>""")

    return f"""
    <div class="sheet cover" id="slide-0">
      <div class="pad" style="display:flex;flex-direction:column;height:100%;">
        <div class="top">
          <div class="label">Japan Market Report</div>
          <div class="label">{_date_line(day)}</div>
        </div>
        <div style="margin-top:96px;">
          <h1>Yesterday&rsquo;s<br>three biggest<br><em>vintage</em>sales.</h1>
          <div class="sub">Sold prices from Yahoo! Auctions, Yahoo! Flea Market
          and Mercari Japan — converted, translated, and posted daily.</div>
        </div>
        <div class="list">{''.join(rows)}</div>
        <div class="foot">
          <div class="handle">{handle}</div>
          <div>Swipe →</div>
        </div>
      </div>
    </div>"""


def sale_slide(index: int, total: int, sale: dict, handle: str) -> str:
    if sale.get("image_data"):
        plate = f'<img src="{sale["image_data"]}" alt="">'
    else:
        plate = f"""<div class="ph">
            <div class="box">{sale['code'] or '—'}</div>
            <div class="cap">Listing photo</div>
          </div>"""

    eyebrow, headline = _headline(sale)

    # The card's own Japanese name, with the set code beside it. Anything
    # else from the seller's title is keyword noise.
    jp_bits = [b for b in (sale.get("card_name_jp"), sale["code"]) if b]
    jp = "　".join(jp_bits)

    top_label = " · ".join(x for x in [sale["set_name"] or "Vintage",
                                       sale["code"] or None] if x)

    # Sealed lots have no character, so the eyebrow would just repeat the set
    # name already sitting in the top-left. Drop it and let the badge stand.
    if eyebrow and top_label.upper().startswith(eyebrow):
        eyebrow = ""

    return f"""
    <div class="sheet sale" id="slide-{index}">
      <div class="pad" style="display:flex;flex-direction:column;height:100%;">
        <div class="top">
          <div class="label">{top_label}</div>
          <div class="num">{index:02d} / {total:02d}</div>
        </div>
        <div class="plate">{plate}</div>
        <div class="eyebrow">{eyebrow}{'<span class="badge">SEALED</span>' if sale['sealed'] else ''}</div>
        <h2>{headline}</h2>
        <div class="jptitle jp">{jp}</div>
        <div class="meta">
          <div class="cell">
            <div class="k">Condition</div>
            <div class="v">{sale['condition']}</div>
          </div>
          <div class="cell">
            <div class="k">Sold on</div>
            <div class="v">{_source_label(sale)}</div>
          </div>
          <div class="cell price">
            <div class="k">Sold for</div>
            <div class="v">{_money(sale['price_usd'])}</div>
          </div>
        </div>
        <div class="foot">
          <div class="handle">{handle}</div>
          <div>USD at {1/sale['fx_rate']:,.0f} JPY/USD</div>
        </div>
      </div>
    </div>"""


def build_html(post: dict, handle: str = "@handle") -> str:
    sales = post["sales"]
    slides = [cover_slide(post["day"], sales, handle)]
    for i, s in enumerate(sales, 1):
        slides.append(sale_slide(i, len(sales), s, handle))

    vars_css = ";".join(f"--{k.replace('_','-')}:{v}" for k, v in PALETTE.items())
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>
{font_css()}
:root{{{vars_css}}}
{BASE_CSS}
{COVER_CSS}
{SALE_CSS}
</style></head><body>{''.join(slides)}</body></html>"""
