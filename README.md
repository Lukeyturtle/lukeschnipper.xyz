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

## Pages

| File             | URL          |
|------------------|--------------|
| `index.html`     | `/`          |
| `youtube.html`   | `/youtube`   |
| `portfolio.html` | `/portfolio` |
| `store.html`     | `/store`     |

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
