#!/bin/bash
# One-time setup for the store backend (safe to re-run).
#   - logs you in to Cloudflare, creates the private bucket, deploys the store API
#   - creates the download-link signing key
#   - asks YOU to paste your Stripe secret key (it goes straight to Cloudflare, never into the repo)
#   - points the website at the API and publishes that change
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
BUCKET=luke-store-tracks
w() { npx wrangler "$@"; }

echo; echo "  Store setup"; echo "  -----------"
[ -d node_modules ] || { echo "  Installing wrangler..."; npm install --silent; }

if ! w whoami 2>/dev/null | grep -q "You are logged in"; then
  echo "  Opening your browser to log in to Cloudflare..."
  w login
fi

echo "  Private bucket:"
if w r2 bucket list 2>/dev/null | grep -q "$BUCKET"; then
  echo "    $BUCKET already exists"
elif ! w r2 bucket create "$BUCKET"; then
  echo
  echo "  Cloudflare wouldn't create the bucket. R2 has to be switched on once in the dashboard:"
  echo "  dash.cloudflare.com > R2 Object Storage > Purchase R2 / Get started (the free tier is free,"
  echo "  but Cloudflare asks for a card on file). Then run this script again."
  exit 1
fi

echo "  Deploying the store API..."
w deploy                                  # interactive the first time: may ask you to pick a workers.dev name
URL=$(w deploy 2>&1 | grep -oE 'https://[A-Za-z0-9.-]+\.workers\.dev' | head -1 || true)
if [ -z "$URL" ]; then echo "  Couldn't work out the API address from wrangler's output. Run 'npx wrangler deploy' and check it."; exit 1; fi
echo "    live at $URL"

SECRETS=$(w secret list 2>/dev/null || echo "[]")
if ! grep -q DOWNLOAD_SIGNING_KEY <<<"$SECRETS"; then
  openssl rand -hex 32 | w secret put DOWNLOAD_SIGNING_KEY >/dev/null
  echo "  Created the download-link signing key."
fi
if ! grep -q STRIPE_SECRET_KEY <<<"$SECRETS"; then
  echo
  echo "  Paste your Stripe secret key: Stripe Dashboard > Developers > API keys."
  echo "  Start with the TEST key (sk_test_...). What you paste is hidden. Press Enter afterwards."
  w secret put STRIPE_SECRET_KEY
fi

sed -i '' -E "s#: \"[^\"]*\";\$#: \"$URL\";#" "$ROOT/store/config.js"
cd "$ROOT"
if ! git diff --quiet -- store/config.js; then
  git add store/config.js
  git commit -q -m "Connect store to its API" -- store/config.js
  git pull --rebase --autostash -q origin main
  git push -q origin main
  echo "  Website updated. The Buy buttons go live in about a minute."
fi
echo; echo "  Done. Store API: $URL"; echo
