# lukeschnipper.xyz

Luke Schnipper's personal + YouTube site. Plain HTML/CSS, built by `build.py`, hosted on GitHub Pages.

## Adding photos or music (the easy way)

1. Open the repo on GitHub, go into the `photos` folder (or `music`).
2. Click **Add file > Upload files**, drag your files in, click **Commit changes**.
3. Wait about a minute. The Actions tab shows the deploy; when it's green the Portfolio page has the new stuff.

Rules of thumb: file name becomes the caption/title (`snowy-ridge.jpg` shows as "Snowy ridge"), newest shows first, keep each file under 100 MB. Photos are resized automatically, so upload the full-size originals.

You can do the same from this folder on your Mac: drop files in `photos/` or `music/`, then

```bash
cd ~/Projects/luka-site && git add -A && git commit -m "Add photos" && git push
```

## Selling tracks (the store)

### Add a track

```bash
cd ~/Projects/luka-site && python3 tools/add_track.py
```

It asks for the master file (drag it into the Terminal window), title, price, an optional description and cover image, and where the 30-second preview should start. Then it:

1. makes MP3 (320k), AAC (256k .m4a), WAV and AIFF versions, tagged with title, artist and cover art
2. uploads them to the private Cloudflare R2 bucket (full-quality audio never goes to GitHub)
3. adds a public preview + cover to `store/` and the listing to `store/tracks.json`
4. commits and pushes, so it's on the store page about a minute later

Export the master as WAV or AIFF at whatever quality you mixed at (24-bit is kept as 24-bit). Running it again with the same title replaces that track.

To change a price, hide a track (`"available": false`, past buyers can still download) or switch currency (default GBP), edit `store/tracks.json`, on GitHub is fine.

### Quick option: sell with a Stripe Payment Link (no Cloudflare needed)

```bash
cd ~/Projects/luka-site && python3 tools/add_track.py --payment-link https://buy.stripe.com/...
```

The Buy button goes straight to that Payment Link. Stripe doesn't deliver files, so the tool saves the four formats to a folder on your Desktop: upload it to Google Drive or Dropbox, share it as "anyone with the link", and set that as the Payment Link's after-payment redirect (Stripe > Payment Links > edit > After payment > Don't show confirmation page > redirect). Trade-off: the folder link never expires, so a buyer could pass it on. Tracks without `payment_link` use the full store below.

### How buying works (full store)

Store page -> Stripe Checkout -> `download.html?session_id=...`. The download page asks the store API (`store-worker/`, a Cloudflare Worker) to confirm with Stripe that the order is paid, then shows a button per format. Each button is a signed link that expires after 6 hours. The download page itself works for 30 days after purchase (`DOWNLOAD_DAYS` in `store-worker/wrangler.toml`).

If a buyer loses their link: find the payment in Stripe, open the Checkout Session, copy its `cs_live_...` id and send them `https://lukeschnipper.xyz/download.html?session_id=cs_live_...`.

### One-time setup (already done if the Buy buttons work)

```bash
cd ~/Projects/luka-site/store-worker && ./setup.sh
```

Needs a free Cloudflare account with R2 switched on. It deploys the API and asks you to paste your Stripe secret key. Start with the test key, buy something with card `4242 4242 4242 4242`, then switch to live:

```bash
cd ~/Projects/luka-site/store-worker && npx wrangler secret put STRIPE_SECRET_KEY
```

### Test the store locally

`store-worker/.dev.vars` (not committed) points the local API at a fake Stripe. Run `npm run dev` in `store-worker/` (port 8788) alongside the site preview, and use `python3 tools/add_track.py ... --local --no-publish` to put test files in the local bucket.

## Pages

| File             | URL          |
|------------------|--------------|
| `index.html`     | `/`          |
| `youtube.html`   | `/youtube`   |
| `portfolio.html` | `/portfolio` |
| `store.html`     | `/store`     |
| `download.html`  | post-purchase downloads (not in the nav) |

## Preview locally

```bash
cd ~/Projects/luka-site && python3 build.py && python3 -m http.server 8124 -d _site
```

Then open http://localhost:8124. Needs Pillow once: `pip3 install pillow`.

## How hosting works

- Pushing to `main` runs `.github/workflows/deploy.yml`, which runs `build.py` and publishes `_site/` to GitHub Pages.
- `CNAME` tells GitHub Pages the site lives at lukeschnipper.xyz.
- DNS at Namecheap: four A records for `@` pointing at GitHub's IPs and a CNAME for `www` pointing at `lukeyturtle.github.io`.

## Emails and the other domain

Mail is on lukaschnitzel.xyz (general@, buisness@, yt@) through Namecheap Private Email. That domain also redirects to the YouTube channel (Namecheap > Domain List > Manage > Redirect Domain).
