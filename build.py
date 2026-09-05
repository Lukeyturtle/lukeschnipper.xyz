#!/usr/bin/env python3
"""Build the static site into _site/.

- Copies the hand-written pages, css and img folders.
- Resizes everything in photos/ into web-sized + thumbnail versions.
- Copies everything in music/.
- Writes data/photos.json and data/music.json, which portfolio.html reads.
"""
import json, re, shutil, subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "_site"
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_EXT = {".mp3", ".m4a", ".ogg", ".wav", ".flac"}
FULL_MAX, THUMB_MAX = 1800, 640


def slug(path: Path) -> str:
    """URL-safe file stem: 'Test Shot (1).JPG' -> 'test-shot-1'."""
    s = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")
    return s or "file"


def title_from(path: Path) -> str:
    name = re.sub(r"^\d+[\s._-]+", "", path.stem)  # drop a leading "01 - " style prefix
    name = re.sub(r"[-_]+", " ", name).strip()
    return name[:1].upper() + name[1:] if name else path.stem


def added_ts(path: Path) -> float:
    """Unix time the file was first committed; falls back to mtime outside git."""
    try:
        out = subprocess.run(
            ["git", "log", "--diff-filter=A", "--follow", "--format=%ct", "-1", "--", str(path)],
            cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        if out:
            return float(out.splitlines()[-1])
    except Exception:
        pass
    return path.stat().st_mtime


def exif_ts(img) -> float | None:
    try:
        raw = img.getexif().get_ifd(0x8769).get(0x9003) or img.getexif().get(0x0132)
        if raw:
            return time.mktime(time.strptime(str(raw)[:19], "%Y:%m:%d %H:%M:%S"))
    except Exception:
        pass
    return None


def build_photos():
    from PIL import Image, ImageOps
    src = ROOT / "photos"
    full_dir, thumb_dir = OUT / "photos" / "full", OUT / "photos" / "thumb"
    full_dir.mkdir(parents=True); thumb_dir.mkdir(parents=True)
    items = []
    for p in sorted(src.iterdir()) if src.exists() else []:
        if p.suffix.lower() not in PHOTO_EXT:
            continue
        name = slug(p)
        with Image.open(p) as im:
            im = ImageOps.exif_transpose(im)
            ts = exif_ts(im) or added_ts(p)
            im = im.convert("RGB")
            w, h = im.size
            full = im.copy(); full.thumbnail((FULL_MAX, FULL_MAX))
            full.save(full_dir / f"{name}.jpg", "JPEG", quality=84, optimize=True, progressive=True)
            th = im.copy(); th.thumbnail((THUMB_MAX, THUMB_MAX))
            th.save(thumb_dir / f"{name}.jpg", "JPEG", quality=80, optimize=True)
        items.append({"title": title_from(p), "full": f"photos/full/{name}.jpg",
                      "thumb": f"photos/thumb/{name}.jpg", "w": full.width, "h": full.height,
                      "date": time.strftime("%Y-%m-%d", time.localtime(ts)), "ts": ts})
        print(f"photo  {p.name} -> {full.width}x{full.height}")
    items.sort(key=lambda i: i["ts"], reverse=True)
    return items


def build_music():
    src = ROOT / "music"
    dest = OUT / "music"; dest.mkdir(parents=True)
    items = []
    for p in sorted(src.iterdir()) if src.exists() else []:
        if p.suffix.lower() not in AUDIO_EXT:
            continue
        name = slug(p) + p.suffix.lower()
        shutil.copy2(p, dest / name)
        ts = added_ts(p)
        items.append({"title": title_from(p), "src": f"music/{name}", "ext": p.suffix.lower().lstrip("."),
                      "size_mb": round(p.stat().st_size / 1_048_576, 1),
                      "date": time.strftime("%Y-%m-%d", time.localtime(ts)), "ts": ts})
        print(f"track  {p.name}")
    items.sort(key=lambda i: i["ts"], reverse=True)
    return items


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    for f in ROOT.glob("*.html"):
        shutil.copy2(f, OUT / f.name)
    for d in ("css", "img"):
        shutil.copytree(ROOT / d, OUT / d)
    if (ROOT / "CNAME").exists():
        shutil.copy2(ROOT / "CNAME", OUT / "CNAME")
    (OUT / ".nojekyll").write_text("")
    data = OUT / "data"; data.mkdir()
    (data / "photos.json").write_text(json.dumps(build_photos(), indent=1))
    (data / "music.json").write_text(json.dumps(build_music(), indent=1))
    print("built ->", OUT)


if __name__ == "__main__":
    main()
