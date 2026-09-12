"""
HTML -> 1080x1350 PNGs, via headless Chromium.

Screenshotting real HTML rather than drawing with PIL is what makes the
typography possible: real kerning, real font features, real shadows, and a
design you can iterate on in seconds instead of recomputing coordinates.
"""

import base64
import pathlib
import mimetypes

from .design import build_html, W, H


def _ssl_context():
    """macOS Pythons installed from python.org do not use the system
    certificate store, so every HTTPS fetch fails with
    CERTIFICATE_VERIFY_FAILED until Install Certificates.command is run.
    Prefer certifi's bundle when it's available so the download works
    either way."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def fetch_image_data_uri(url: str, timeout: int = 20):
    """Listing photo -> data: URI, so the render needs no network and the
    PNG can't break later if the listing is deleted.

    Yahoo serves a 300px thumbnail by default; its CDN accepts larger
    dimensions on the same URL, which matters on a 1080px canvas.

    Returns (data_uri, error). A missing photo degrades to the empty plate
    rather than failing the build - but the caller is told WHY, because a
    silent "MISS" on all three photos hides a single fixable cause (an SSL
    trust store that was never set up, say) behind what looks like three
    dead listings."""
    import re
    import urllib.request

    candidates = [url]
    if "yimg.jp" in url:
        big = re.sub(r"w=\d+", "w=1200", url)
        big = re.sub(r"h=\d+", "h=1200", big)
        candidates.insert(0, big)
    if "mercdn.net" in url:
        candidates.insert(0, url.replace("/thumb/item/webp/", "/item/detail/orig/")
                               .split("?")[0])

    ctx = _ssl_context()
    last_error = "no candidate URLs"
    for cand in candidates:
        try:
            req = urllib.request.Request(cand, headers={
                "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/120.0.0.0 Safari/537.36"),
                "Referer": "https://auctions.yahoo.co.jp/",
            })
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                blob = resp.read()
                ctype = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
            if len(blob) < 1200:        # a placeholder "no image" pixel
                last_error = f"response was only {len(blob)} bytes"
                continue
            return f"data:{ctype};base64,{base64.b64encode(blob).decode()}", None
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            continue
    return None, last_error


def attach_images(post: dict, verbose=True) -> dict:
    errors = []
    for s in post["sales"]:
        if not s.get("image"):
            s["image_data"] = None
            continue
        data, error = fetch_image_data_uri(s["image"])
        s["image_data"] = data
        if verbose:
            print(f"  photo {'ok  ' if data else 'MISS'}  {s['display_name'][:40]}")
            if error:
                print(f"              {error}")
        if error:
            errors.append(error)

    # Every photo failing the same way is one problem, not three. Say so,
    # and name the fix for the cause that actually accounts for most of them.
    if verbose and len(errors) == len(post["sales"]) and errors:
        print("\n  Every photo failed. That is usually one cause, not three.")
        if any("CERTIFICATE_VERIFY" in e or "SSLError" in e for e in errors):
            print("  This Python has no certificate store. Fix it once with:")
            print("    /Applications/Python\\ 3.x/Install\\ Certificates.command")
            print("  (substitute your version), or:  pip install certifi")
        else:
            print("  Check your internet connection, then try again.")
    return post


SUPERSAMPLE = 2


def render(post: dict, outdir, handle="@handle", html_only=False):
    """Render at 2x, then downsample to exactly 1080x1350 with Lanczos.

    Instagram serves at 1080px wide, so a larger upload buys nothing - but
    rendering AT 1080 and rendering at 2160 then resampling are not the same
    picture. Instrument Serif is a high-contrast display face whose hairlines
    land on fractional pixels at 1x and get thinned or dropped by hinting.
    Supersampling resolves them properly and the downsample keeps them.

    The output is a PNG, which Instagram re-encodes once. Uploading a PNG
    rather than our own JPEG means only one generation of compression
    instead of two.
    """
    outdir = pathlib.Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    html = build_html(post, handle=handle)
    html_path = outdir / "slides.html"
    html_path.write_text(html, encoding="utf-8")
    if html_only:
        return [html_path]

    from playwright.sync_api import sync_playwright
    from PIL import Image

    written = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--font-render-hinting=none"])
        page = browser.new_page(viewport={"width": W, "height": H},
                                device_scale_factor=SUPERSAMPLE)
        page.goto(html_path.resolve().as_uri())
        page.wait_for_timeout(600)          # let the embedded fonts settle

        for i in range(len(post["sales"]) + 1):
            target = outdir / (f"{i+1}-cover.png" if i == 0 else f"{i+1}-sale-{i}.png")
            page.locator(f"#slide-{i}").screenshot(path=str(target))
            img = Image.open(target)
            if img.size != (W, H):
                img.convert("RGB").resize((W, H), Image.LANCZOS).save(
                    target, "PNG", optimize=True)
            written.append(target)
        browser.close()
    return written
