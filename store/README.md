Store catalog. Add tracks with `python3 tools/add_track.py` (see the main README). Don't put full-quality audio in this folder: everything here is public.

tracks.json is safe to edit by hand, including on GitHub:
- change "price" to reprice a track
- set "available": false to stop selling a track (past buyers can still download)
- change "currency" (e.g. "gbp", "eur") to switch currency for every track
