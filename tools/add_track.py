#!/usr/bin/env python3
"""Add a buyable track to the store.

Give it ONE high-quality master (WAV or AIFF is best) and it will:
  1. make MP3 (320k), AAC (256k .m4a), WAV and AIFF versions, tagged with title, artist and cover art
  2. upload those to the private R2 bucket (they never go to GitHub)
  3. make a public 30-second preview and a cover image for the store page
  4. add the track to store/tracks.json and publish the site

Usage:
  python3 tools/add_track.py                        # asks you everything
  python3 tools/add_track.py song.wav --title "Despair" --price 1.99 --cover art.jpg

Handy flags: --preview-start 1:05 (start the preview at the chorus), --no-publish (don't git push yet).
"""
import argparse, datetime, json, re, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "store"
CATALOG = STORE / "tracks.json"
WORKER_DIR = ROOT / "store-worker"
BUCKET = "luke-store-tracks"
ARTIST = "Luke Schnipper"
CONTENT_TYPES = {"mp3": "audio/mpeg", "m4a": "audio/mp4", "wav": "audio/wav", "aiff": "audio/aiff"}


def die(msg):
    print(f"\n  ✗ {msg}\n", file=sys.stderr)
    sys.exit(1)


def run(cmd, **kw):
    res = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if res.returncode != 0:
        die(f"Command failed: {' '.join(map(str, cmd[:3]))} ...\n{res.stderr.strip()[-1500:]}")
    return res.stdout


def ask(prompt, default=None, required=False):
    if not sys.stdin.isatty():
        if required and default is None:
            die(f"Missing value for: {prompt}")
        return default
    suffix = f" [{default}]" if default not in (None, "") else ""
    while True:
        val = input(f"  {prompt}{suffix}: ").strip()
        if val:
            return val
        if default is not None or not required:
            return default
        print("    (required)")


def clean_path(raw):
    """Accept paths dragged into the Terminal: strips quotes and backslash escapes."""
    raw = raw.strip()
    if len(raw) > 1 and raw[0] == raw[-1] and raw[0] in "'\"":
        raw = raw[1:-1]
    return Path(re.sub(r"\\(.)", r"\1", raw)).expanduser()


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80] or "track"


def title_from(path):
    name = re.sub(r"^\d+[\s._-]+", "", path.stem).replace("_", " ")
    name = re.sub(r"(?<! )-(?! )", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:1].upper() + name[1:] if name else path.stem


def parse_time(val):
    val = str(val or "0").strip()
    if ":" in val:
        m, s = val.split(":", 1)
        return int(m) * 60 + float(s)
    return float(val)


def probe(master):
    out = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                          "stream=codec_name,sample_rate,channels,bits_per_sample,bits_per_raw_sample:format=duration",
                          "-of", "json", str(master)]))
    if not out.get("streams"):
        die(f"{master.name} doesn't contain any audio.")
    s = out["streams"][0]
    bits = int(s.get("bits_per_raw_sample") or 0) or int(s.get("bits_per_sample") or 0)
    lossless = s["codec_name"].startswith("pcm_") or s["codec_name"] in ("flac", "alac")
    return {"codec": s["codec_name"], "rate": int(s["sample_rate"]), "lossless": lossless,
            "bits": 24 if bits > 16 else 16, "duration": float(out["format"]["duration"])}


def make_cover(src, dest_public, dest_embed):
    from PIL import Image, ImageOps
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        side = min(im.size)
        left, top = (im.width - side) // 2, (im.height - side) // 2
        im = im.crop((left, top, left + side, top + side))
        im.resize((min(side, 1000),) * 2, Image.LANCZOS).save(dest_public, "JPEG", quality=86, optimize=True, progressive=True)
        im.resize((min(side, 600),) * 2, Image.LANCZOS).save(dest_embed, "JPEG", quality=88)


def encode(master, info, work, tid, title, embed_cover, formats):
    year = str(datetime.date.today().year)
    tags = ["-metadata", f"title={title}", "-metadata", f"artist={ARTIST}", "-metadata", f"album_artist={ARTIST}",
            "-metadata", f"date={year}", "-metadata", f"copyright=© {year} {ARTIST}. All rights reserved.",
            "-metadata", "comment=Personal listening licence. No sharing or re-uploading. lukeschnipper.xyz"]
    pcm = "24" if info["bits"] == 24 else "16"
    lossy_rate = ["-ar", "48000"] if info["rate"] > 48000 else []
    aac_codec = "aac_at" if "aac_at" in run(["ffmpeg", "-hide_banner", "-encoders"]) else "aac"
    cover_in = ["-i", str(embed_cover)] if embed_cover else []
    cover_map = (["-map", "1:v", "-c:v", "copy", "-disposition:v", "attached_pic"] if embed_cover else [])
    base = ["ffmpeg", "-y", "-v", "error", "-i", str(master)]
    out = {}
    jobs = {
        "mp3": base + cover_in + ["-map", "0:a:0"] + cover_map + lossy_rate +
               ["-c:a", "libmp3lame", "-b:a", "320k", "-id3v2_version", "3", "-map_metadata", "-1"] + tags,
        # An AAC master is copied as-is: re-encoding AAC to AAC only loses quality.
        "m4a": base + cover_in + ["-map", "0:a:0"] + cover_map +
               (["-c:a", "copy"] if info["codec"] == "aac" else lossy_rate + ["-c:a", aac_codec, "-b:a", "256k"]) +
               ["-movflags", "+faststart", "-map_metadata", "-1"] + tags,
        "wav": base + ["-map", "0:a:0", "-c:a", f"pcm_s{pcm}le", "-map_metadata", "-1"] + tags,
        "aiff": base + ["-map", "0:a:0", "-c:a", f"pcm_s{pcm}be", "-write_id3v2", "1", "-map_metadata", "-1"] + tags,
    }
    wanted = {"mp3": "mp3", "aac": "m4a", "wav": "wav", "aiff": "aiff"}
    jobs = {wanted[f]: jobs[wanted[f]] for f in formats}
    for ext, cmd in jobs.items():
        dest = work / f"{tid}.{ext}"
        print(f"    encoding {ext.upper():4} ...", end="", flush=True)
        run(cmd + [str(dest)])
        out[ext] = dest
        print(f" {dest.stat().st_size / 1_048_576:.1f} MB")
    return out


def make_preview(master, info, dest, start, length):
    start = max(0.0, min(start, max(0.0, info["duration"] - 5)))
    length = min(length, info["duration"] - start)
    fade_out = max(0.0, length - 3)
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start}", "-t", f"{length}", "-i", str(master),
         "-af", f"afade=t=in:d=0.8,afade=t=out:st={fade_out}:d=3", "-map_metadata", "-1",
         "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "44100", "-ac", "2", str(dest)])
    return start, length


def upload(files, tid, local):
    if not (WORKER_DIR / "node_modules").exists():
        print("    installing wrangler (one time) ...")
        run(["npm", "install", "--silent"], cwd=WORKER_DIR)
    where = "--local" if local else "--remote"
    for ext, path in files.items():
        key = f"{BUCKET}/tracks/{tid}/{tid}.{ext}"
        print(f"    uploading {ext.upper():4} -> {'local dev bucket' if local else 'R2'} ...", end="", flush=True)
        run(["npx", "wrangler", "r2", "object", "put", key, "--file", str(path),
             "--content-type", CONTENT_TYPES[ext], where], cwd=WORKER_DIR)
        print(" done")


def load_catalog():
    if CATALOG.exists():
        return json.loads(CATALOG.read_text())
    return {"currency": "gbp", "artist": ARTIST, "tracks": []}


def publish(title, paths):
    rel = [str(p.relative_to(ROOT)) for p in paths]
    run(["git", "add", "--"] + rel, cwd=ROOT)
    run(["git", "commit", "-m", f"Add track: {title}", "--"] + rel, cwd=ROOT)
    run(["git", "pull", "--rebase", "--autostash", "-q", "origin", "main"], cwd=ROOT)
    run(["git", "push", "-q", "origin", "main"], cwd=ROOT)


def main():
    ap = argparse.ArgumentParser(description="Add a buyable track to the store.")
    ap.add_argument("master", nargs="?", help="master audio file (WAV/AIFF/FLAC best)")
    ap.add_argument("--title"); ap.add_argument("--price"); ap.add_argument("--description")
    ap.add_argument("--cover", help="square-ish image for the cover (jpg/png)")
    ap.add_argument("--preview-start", help="where the 30s preview starts, e.g. 45 or 1:05")
    ap.add_argument("--preview-length", type=float, default=30)
    ap.add_argument("--id", help="URL id (defaults to the title, e.g. 'late-night-drive')")
    ap.add_argument("--payment-link", help="Stripe Payment Link (https://buy.stripe.com/...) for the Buy button")
    ap.add_argument("--page", help="web address for the song's page, e.g. 'wunderinwun' -> lukeschnipper.xyz/wunderinwun")
    ap.add_argument("--formats", help="comma list from mp3,aac,wav,aiff (default: all four, or mp3,aac for a lossy master)")
    ap.add_argument("--export", help="also save the buyer files to this folder")
    ap.add_argument("--local", action="store_true", help="upload to the local dev bucket instead of R2")
    ap.add_argument("--no-upload", action="store_true"); ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    a = ap.parse_args()

    link = (a.payment_link or "").strip()
    if link:
        if not link.startswith("https://"):
            die("A Payment Link should start with https:// (usually https://buy.stripe.com/...).")
        if not link.startswith("https://buy.stripe.com/"):
            print(f"  ! {link} isn't a buy.stripe.com address. Using it anyway.")
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            die(f"{tool} isn't installed. Run: brew install ffmpeg")

    print("\n  Add a track to the store\n  ------------------------")
    master = clean_path(a.master or ask("Master file (drag it into this window)", required=True))
    if not master.is_file():
        die(f"Can't find {master}")
    info = probe(master)
    if a.formats:
        formats = [f.strip().lower() for f in a.formats.split(",") if f.strip()]
        bad = [f for f in formats if f not in ("mp3", "aac", "wav", "aiff")]
        if bad or not formats:
            die(f"Unknown format(s): {', '.join(bad) or '(none)'}. Pick from mp3, aac, wav, aiff.")
    elif info["lossless"]:
        formats = ["mp3", "aac", "wav", "aiff"]
    else:
        print(f"  ! {master.name} is {info['codec']}, a compressed (lossy) file. Converting it to WAV/AIFF")
        print("    gives huge files that sound no better, so they shouldn't be sold as lossless.")
        print("    For all four formats, export WAV or AIFF from your DAW (GarageBand: Share > Export Song to Disk).")
        answer = ask("Sell this one as MP3 + AAC only? (y/n)", "y")
        formats = ["mp3", "aac"] if answer.lower() in ("y", "yes") else ["mp3", "aac", "wav", "aiff"]

    title = a.title or ask("Title", title_from(master))
    catalog = load_catalog()
    tid = slug(a.id or title)
    existing = next((t for t in catalog["tracks"] if t["id"] == tid), None)
    page = slug(a.page or (existing or {}).get("page") or tid.replace("-", ""))
    taken = {p.stem for p in ROOT.glob("*.html")} | {t.get("page") for t in catalog["tracks"] if t["id"] != tid}
    if page in taken:
        die(f"The page name '{page}' is already used. Pick another with --page.")
    price_default = str(existing["price"]) if existing else "1.99"
    price_raw = a.price or ask(f"Price ({catalog.get('currency', 'gbp').upper()})", price_default)
    try:
        price = round(float(str(price_raw).lstrip("$£€")), 2)
    except ValueError:
        die(f"'{price_raw}' isn't a price.")
    if price < 0.5:
        die("Stripe's minimum is 0.50.")
    description = a.description if a.description is not None else ask("Short description (optional)", existing.get("description", "") if existing else "")
    cover_raw = a.cover or ask("Cover image (optional, drag it in or press Enter to skip)", "")
    cover_src = clean_path(cover_raw) if cover_raw else None
    if cover_src and not cover_src.is_file():
        die(f"Can't find {cover_src}")
    pstart = parse_time(a.preview_start if a.preview_start is not None else ask("Preview starts at (seconds or m:ss)", "0"))

    mins, secs = divmod(int(info["duration"]), 60)
    print(f"\n  {title}  ·  {price:.2f} {catalog.get('currency', 'gbp').upper()}  ·  {mins}:{secs:02d}"
          f"  ·  {info['rate'] // 1000} kHz / {info['bits']}-bit  ·  {'/'.join(f.upper() for f in formats)}"
          f"\n  page: lukeschnipper.xyz/{page}")
    if existing:
        print("  ! A track with this id already exists. Its files and listing will be replaced.")
    if not a.yes and sys.stdin.isatty() and ask("Go ahead? (y/n)", "y").lower() not in ("y", "yes"):
        die("Cancelled.")

    (STORE / "previews").mkdir(parents=True, exist_ok=True)
    (STORE / "covers").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="luke-track-") as tmp:
        work = Path(tmp)
        public_cover = STORE / "covers" / f"{tid}.jpg"
        embed = None
        if cover_src:
            embed = work / "cover.jpg"
            make_cover(cover_src, public_cover, embed)
        print("\n  Making formats")
        files = encode(master, info, work, tid, title, embed, formats)
        preview = STORE / "previews" / f"{tid}.mp3"
        make_preview(master, info, preview, pstart, a.preview_length)
        print(f"    preview   ... {preview.stat().st_size / 1024:.0f} KB (public)")
        export_dir = Path(a.export).expanduser() if a.export else None
        if export_dir:
            export_dir.mkdir(parents=True, exist_ok=True)
            for ext, path in files.items():
                shutil.copy2(path, export_dir / f"{ARTIST} - {title}.{ext}".replace("/", "-"))
            print(f"\n  Buyer files saved to {export_dir}")
        if not a.no_upload:
            print("\n  Uploading full-quality files (private)")
            upload(files, tid, a.local)

    entry = {
        "id": tid, "title": title, "price": price, "description": description or "",
        "cover": f"store/covers/{tid}.jpg" if (cover_src or (existing and existing.get("cover"))) else "",
        "preview": f"store/previews/{tid}.mp3",
        "formats": formats,
        "page": page,
        "duration": round(info["duration"]),
        "released": existing["released"] if existing else datetime.date.today().isoformat(),
        "available": True,
    }
    if link:
        entry["payment_link"] = link
    catalog["tracks"] = [entry] + [t for t in catalog["tracks"] if t["id"] != tid]
    CATALOG.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
    print(f"\n  Added to {CATALOG.relative_to(ROOT)}")
    if link:
        print("\n  In Stripe, set this Payment Link's After payment redirect to:")
        print(f"    https://lukeschnipper.xyz/{page}?session_id={{CHECKOUT_SESSION_ID}}")

    changed = [CATALOG, STORE / "previews" / f"{tid}.mp3"] + ([STORE / "covers" / f"{tid}.jpg"] if entry["cover"] else [])
    if a.no_publish:
        print("  Not published (--no-publish). Commit and push when you're ready.\n")
        return
    print("  Publishing ...", end="", flush=True)
    publish(title, changed)
    print(f" pushed. lukeschnipper.xyz/{page} and the store update in about a minute.\n")


if __name__ == "__main__":
    main()
