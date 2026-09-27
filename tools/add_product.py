#!/usr/bin/env python3
"""Add a store product that has no master file yet: an album bundle, or a pre-order single.

  # Album bundle — one price unlocks every single tagged with this album id, as each is released:
  python3 tools/add_product.py album --id orach --title "Orach" --price 10 --page orach

  # Pre-order single — buyable now, downloads appear here once you release it with add_track:
  python3 tools/add_product.py preorder --id orach-song-2 --title "Orach Song #2" \
      --price 1 --page orachsong2 --album orach

Later, release a pre-ordered single by running add_track.py on its master with the same --id;
that uploads the files, clears the pre-order flag, and every album buyer can then download it.

Add --no-publish to stage the change without committing/pushing.
"""
import argparse, datetime, json, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "store"
CATALOG = STORE / "tracks.json"


def die(msg):
    print(f"\n  ✗ {msg}\n", file=sys.stderr); sys.exit(1)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:80]


def clean_path(raw):
    raw = raw.strip()
    if len(raw) > 1 and raw[0] == raw[-1] and raw[0] in "'\"":
        raw = raw[1:-1]
    return Path(re.sub(r"\\(.)", r"\1", raw)).expanduser()


def make_cover(src, dest):
    from PIL import Image, ImageOps
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        side = min(im.size)
        left, top = (im.width - side) // 2, (im.height - side) // 2
        im.crop((left, top, left + side, top + side)).resize((min(side, 1000),) * 2, Image.LANCZOS) \
          .save(dest, "JPEG", quality=86, optimize=True, progressive=True)


def load_catalog():
    if CATALOG.exists():
        return json.loads(CATALOG.read_text())
    return {"currency": "gbp", "artist": "Luke Schnipper", "tracks": []}


def price_of(raw):
    try:
        v = round(float(str(raw).lstrip("$£€")), 2)
    except (TypeError, ValueError):
        die(f"'{raw}' isn't a price.")
    if v < 0.5:
        die("Stripe's minimum is 0.50.")
    return v


def publish(title, paths):
    rel = [str(p.relative_to(ROOT)) for p in paths]
    subprocess.run(["git", "add", "--"] + rel, cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-m", f"Add product: {title}", "--"] + rel, cwd=ROOT, check=True)
    subprocess.run(["git", "pull", "--rebase", "--autostash", "-q", "origin", "main"], cwd=ROOT, check=True)
    subprocess.run(["git", "push", "-q", "origin", "main"], cwd=ROOT, check=True)


def main():
    ap = argparse.ArgumentParser(description="Add an album or pre-order product.")
    ap.add_argument("kind", choices=["album", "preorder"])
    ap.add_argument("--id", required=True, help="url-safe id, e.g. 'orach' or 'orach-song-2'")
    ap.add_argument("--title", required=True)
    ap.add_argument("--price", required=True)
    ap.add_argument("--page", help="web address (defaults to the id without dashes)")
    ap.add_argument("--album", help="[preorder only] album id this single belongs to")
    ap.add_argument("--description", default="")
    ap.add_argument("--cover", help="square-ish cover image (optional)")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()

    tid = slug(a.id)
    if not tid:
        die("--id is empty after cleaning.")
    catalog = load_catalog()
    existing = next((t for t in catalog["tracks"] if t["id"] == tid), None)
    page = slug(a.page or (existing or {}).get("page") or tid.replace("-", ""))
    taken = {p.stem for p in ROOT.glob("*.html")} | {t.get("page") for t in catalog["tracks"] if t["id"] != tid}
    if page in taken:
        die(f"The page name '{page}' is already used. Pick another with --page.")
    price = price_of(a.price)

    cover = (existing or {}).get("cover", "")
    changed = [CATALOG]
    if a.cover:
        (STORE / "covers").mkdir(parents=True, exist_ok=True)
        dest = STORE / "covers" / f"{tid}.jpg"
        src = clean_path(a.cover)
        if not src.is_file():
            die(f"Can't find cover {src}")
        make_cover(src, dest)
        cover = f"store/covers/{tid}.jpg"
        changed.append(dest)

    entry = {
        "id": tid, "title": a.title, "price": price, "description": a.description or "",
        "cover": cover, "preview": "", "formats": [], "page": page,
        "released": (existing or {}).get("released", datetime.date.today().isoformat()),
        "available": True,
    }
    if a.kind == "album":
        entry["type"] = "album"
    else:
        entry["type"] = "single"
        entry["preorder"] = True
        album = slug(a.album) if a.album else (existing or {}).get("album")
        if album:
            entry["album"] = album

    catalog["tracks"] = [entry] + [t for t in catalog["tracks"] if t["id"] != tid]
    CATALOG.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")

    kind = "Album" if a.kind == "album" else "Pre-order"
    print(f"\n  {kind}: {a.title}  ·  {catalog['currency'].upper()} {price:.2f}  ·  id {tid}  ·  page lukeschnipper.xyz/{page}")
    if a.kind == "album":
        songs = [t for t in catalog["tracks"] if t.get("type") != "album" and t.get("album") == tid]
        out = [t for t in songs if t.get("formats")]
        print(f"  Album songs: {len(songs)} tagged, {len(out)} released. Tag more with: add_track ... --album {tid}")
    else:
        print(f"  Release it later with: python3 tools/add_track.py <master> --id {tid}")
    print(f"\n  Added to {CATALOG.relative_to(ROOT)}")
    if a.no_publish:
        print("  Not published (--no-publish).\n"); return
    print("  Publishing ...", end="", flush=True)
    publish(a.title, changed)
    print(f" pushed. lukeschnipper.xyz/{page} live in about a minute.\n")


if __name__ == "__main__":
    main()
