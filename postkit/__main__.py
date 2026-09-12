"""
Build today's Instagram carousel.

    python -m postkit                    # yesterday's sales
    python -m postkit --day 2026-09-12   # a specific day
    python -m postkit --open             # ...and open the folder when done

Writes four 1080x1350 PNGs plus a review.json into  posts/YYYY-MM-DD/ .

Exit codes: 0 = ready to post, 1 = built but something needs your eyes,
2 = not enough qualifying sales to make a post. So a scheduled run can tell
the three apart without reading the output.
"""

import sys
import json
import time
import argparse
import datetime as dt
import subprocess
from pathlib import Path

from .select import build_day, DEFAULT_FLOOR_USD
from .render import render, attach_images

HANDLE = "@retroromancedawn"
ARCHIVE = Path("data/history.json")
OUT_ROOT = Path("posts")

FX_ENDPOINT = "https://open.er-api.com/v6/latest/JPY"
FX_FALLBACK = 0.0065


def jpy_to_usd() -> float:
    """Today's rate, or a sane fallback. A missing rate must not stop the
    build - a post with a slightly stale conversion beats no post."""
    try:
        import urllib.request
        with urllib.request.urlopen(FX_ENDPOINT, timeout=15) as resp:
            rate = float(json.load(resp)["rates"]["USD"])
        print(f"FX: 1 USD = {1/rate:,.1f} JPY")
        return rate
    except Exception as e:
        print(f"FX lookup failed ({e}); using fallback {1/FX_FALLBACK:,.0f} JPY/USD")
        return FX_FALLBACK


def banner(text):
    print(f"\n{text}\n{'-' * len(text)}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m postkit",
                                 description="Build the daily Instagram carousel.")
    ap.add_argument("--day", help="YYYY-MM-DD (default: yesterday, UTC)")
    ap.add_argument("--floor", type=int, default=DEFAULT_FLOOR_USD,
                    help=f"minimum sale price in USD (default: {DEFAULT_FLOOR_USD})")
    ap.add_argument("--handle", default=HANDLE)
    ap.add_argument("--archive", default=str(ARCHIVE))
    ap.add_argument("--out", default=None, help="output folder")
    ap.add_argument("--no-sealed", action="store_true",
                    help="leave sealed boxes and packs out of the post")
    ap.add_argument("--no-photos", action="store_true",
                    help="skip downloading listing photos (much faster)")
    ap.add_argument("--open", action="store_true",
                    help="open the output folder when finished")
    args = ap.parse_args(argv)

    day = args.day or (dt.datetime.now(dt.timezone.utc).date()
                       - dt.timedelta(days=1)).isoformat()

    archive = Path(args.archive)
    if not archive.exists():
        print(f"Can't find the sales archive at {archive}.")
        print("Run this from the repository folder, the one containing dashboard.py.")
        return 2

    banner(f"Building the post for {day}")
    rate = jpy_to_usd()
    post = build_day(str(archive), day, rate,
                     floor_usd=args.floor,
                     include_sealed=not args.no_sealed)

    if not post["sales"]:
        print(f"\nNo sales on {day} cleared ${args.floor}. Nothing to post.")
        print(f"  considered and rejected: {post['rejected']}")
        return 2

    banner("Selected")
    for i, s in enumerate(post["sales"], 1):
        mark = {"high": "  ok  ", "medium": " CHECK", "low": " CHECK"}[s["confidence"]]
        seal = "  [SEALED]" if s["sealed"] else ""
        print(f" {i}. {mark}  ${s['price_usd']:>6,}  {s['display_name']}{seal}")
        for flag in s["flags"]:
            print(f"          - {flag}")

    if len(post["sales"]) < 3:
        print(f"\nOnly {len(post['sales'])} sale(s) qualified - the carousel will be short.")

    if not args.no_photos:
        banner("Listing photos")
        attach_images(post)

    outdir = Path(args.out) if args.out else OUT_ROOT / day
    banner("Rendering")
    files = render(post, outdir, handle=args.handle)
    for f in files:
        print(f"  {f}")

    # The review file is the audit trail: what was chosen, what was rejected
    # and why, and the source listing URL for anything needing a second look.
    review = {k: post[k] for k in
              ("day", "generated_at", "fx_rate", "floor_usd",
               "qualifying_count", "rejected", "needs_review", "publishable")}
    review["sales"] = [
        {k: s[k] for k in ("display_name", "set_name", "code", "condition",
                           "price_usd", "price_jpy", "confidence",
                           "identified_via", "sealed", "url", "title_jp")}
        for s in post["sales"]
    ]
    (outdir / "review.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    if post["needs_review"]:
        banner("Check these before posting")
        for item in post["needs_review"]:
            print(f"  {item['name']}  ({item['confidence']})")
            for flag in item["flags"]:
                print(f"    - {flag}")
            print(f"    listing: {item['url']}")
            print(f"    seller's title: {item['title_jp']}")

    if args.open:
        opener = {"darwin": "open", "win32": "explorer"}.get(sys.platform, "xdg-open")
        subprocess.run([opener, str(outdir)], check=False)

    if post["publishable"]:
        print(f"\nReady to post. Files are in {outdir}")
        return 0
    print(f"\nBuilt, but see the notes above first. Files are in {outdir}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
