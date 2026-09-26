# Stripe integration — remaining steps

This file is the single source of truth for finishing the Checkout integration.

The store now uses **Stripe's embedded custom payment form**: the buyer pays on
lukeschnipper.xyz instead of being redirected to a Stripe-hosted page. After payment Stripe
sends them to the session's `return_url` (`download.html?session_id=…`, or the track's own
page), which is the same download flow as before.

## Values to Replace

The following value is a placeholder and must be updated before checkout will work.

**Files containing placeholders:**
- [store/config.js](store/config.js)

| Field | Current Value | What to Set |
|-------|--------------|-------------|
| `window.STRIPE_PUBLISHABLE_KEY` | `""` (empty) | Your publishable key from https://dashboard.stripe.com/test/apikeys — `pk_test_…` while testing, `pk_live_…` when you go live. This key is public and safe to commit. While it's empty the Buy buttons stay disabled ("Opening soon"). |

Nothing else is a placeholder. `mode` and `line_items` were already set to real values and were
kept as-is:

| Parameter | Value in your code | Why it stays |
|-----------|--------------------|--------------|
| `mode` | `payment` | Tracks are one-time digital purchases, not subscriptions. |
| `line_items` | built from `store/tracks.json` (`price_data`: currency, unit amount, product name, description, cover image) | Real prices come from your catalog, never from the browser. No Stripe Price IDs needed. Reprice a track by editing `store/tracks.json`. |

Because `mode` is `payment`, `payment_method_collection` is intentionally **not** sent — it only
applies to subscriptions. If you ever sell a subscription, add `payment_method_collection: "always"`
to that session.

## Configured Parameters

These parameters were configured in Checkout Studio and are already set correctly.

**Files containing these parameters:**
- [store-worker/src/index.js](store-worker/src/index.js) — the `checkout()` function
- [store/checkout.js](store/checkout.js) — the appearance settings

| Parameter | Value |
|-----------|-------|
| `ui_mode` | `form` |
| `billing_address_collection` | `auto` |
| `phone_number_collection.enabled` | `false` |
| `automatic_tax.enabled` | `false` |
| `submit_type` | `auto` |
| `name_collection.individual.enabled` | `true` |
| `name_collection.individual.optional` | `true` |
| `integration_identifier` | `custom_embedded_web_0001` |
| Stripe API version (`Stripe-Version` header) | `2026-03-25.dahlia; custom_checkout_payment_form_preview=v1` |
| `appearance` (client-side) | theme `stripe`, labels `auto`, inputs `spaced`, Montserrat 16px, radius 4px, spacing 4px, background `#2e45b8`, primary `#0570de`, text `#30313d`, success `#00ff9d`, danger `#df1b41` |

### What changed in the session parameters

- **Added** the parameters in the table above.
- **Removed** `allow_promotion_codes` — no longer configured in Checkout Studio. Re-add it if you
  still want buyers to be able to enter promo codes.
- **Replaced** `success_url` + `cancel_url` with `return_url`. The embedded form doesn't redirect
  away, so there is no "cancel" round trip; `return_url` keeps the
  `?session_id={CHECKOUT_SESSION_ID}` download link working exactly as before. The
  "checkout was cancelled" notice on the store page is now only reachable from an old link and can
  be deleted whenever you like.
- **Kept** `metadata[track_id]` and `payment_intent_data[metadata][track_id]` — the `/order`
  endpoint uses them to work out which track a payment was for.

### SDK version note

This project calls the Stripe REST API directly with `fetch` (no Stripe SDK is installed), so
`ui_mode: "form"` is used together with the pinned API version above. If you ever add an official
Stripe SDK, note that `ui_mode` is `form` on SDK 21.0.0 and newer, and `custom` on versions below
21.0.0.

## Setup

No new dependencies. Stripe.js is loaded straight from `https://js.stripe.com/dahlia/stripe.js`
(PCI requirement — never bundle or self-host it). The `dahlia` build is what provides
`stripe.initCheckoutFormSdk(...)`.

1. **Publishable key** — paste it into `store/config.js` (see the table above), then commit and push.
2. **Secret key** — already handled the way this project does it: a Cloudflare Worker secret, never
   in the repo.
   ```bash
   cd store-worker && npx wrangler secret put STRIPE_SECRET_KEY
   ```
3. **Local development** — `store-worker/.dev.vars` (not committed) already holds
   `STRIPE_SECRET_KEY`, `DOWNLOAD_SIGNING_KEY`, `SITE_ORIGIN`, `CATALOG_URL`, `STRIPE_API`,
   `EXTRA_ORIGINS`. These names match what the code reads — nothing to rename. There is no `.env`
   file: this is a Worker, so vars live in `wrangler.toml` and secrets in Wrangler/`.dev.vars`.
4. **Deploy the API** — `cd store-worker && npm run deploy`.

## Files

```
store/checkout.js          new — loads Stripe.js, mounts the embedded payment form
store/config.js            + window.STRIPE_PUBLISHABLE_KEY
store.html                 + Stripe.js, #checkout-form container, Buy opens the form in place
templates/track.html       same, for the per-track pages (/songname)
store-worker/src/index.js  session params, pinned API version, returns {client_secret}
```

## How it works

1. Buyer clicks **Buy** on `store.html` or a track page.
2. The browser POSTs `{id}` to the Worker's `/checkout`. The Worker looks the price up in
   `store/tracks.json` (prices never come from the browser), creates the Checkout Session, and
   returns `{client_secret}` as JSON — no redirect.
3. `store/checkout.js` calls `stripe.initCheckoutFormSdk({clientSecret, appearance})`,
   `checkout.createForm({layout: 'expanded'})`, mounts it into `#checkout-form`, and wires the
   `confirm` event to `actions.confirm({formConfirmEvent: event})`.
4. On success Stripe sends the buyer to `return_url` —
   `download.html?session_id=cs_…` (or `/songname?session_id=cs_…`).
5. That page calls `/order`, which confirms with Stripe that the session is paid and returns
   signed R2 download links (6-hour links; the page keeps working for `DOWNLOAD_DAYS`, 30 by default).

Tracks that have a `payment_link` in `store/tracks.json` still use that hosted Stripe Payment Link
and don't touch the embedded form.

## Testing

Use a **test** publishable key plus a test secret key, then:

| Card | Result |
|------|--------|
| `4242 4242 4242 4242` | Payment succeeds |
| `4000 0025 0000 3155` | Requires 3D Secure authentication |
| `4000 0000 0000 9995` | Declined (insufficient funds) |
| `4000 0000 0000 0002` | Declined (generic) |

Any future expiry date, any CVC, any postcode.

```bash
cd store-worker && npm run dev      # API on :8788
python3 build.py && python3 -m http.server -d _site 8000
```

`store/config.js` points at `http://localhost:8788` automatically on localhost. Buy a track with
`4242…`, and check you land on the download page with working format buttons.

## Next steps

- **One form per page load.** The store page disables the other Buy buttons while a form is open; a
  buyer who wants a different track reloads the page. Worth revisiting if you ever sell bundles.
- **Add or reprice tracks** with `python3 tools/add_track.py` (or edit `store/tracks.json`:
  `price`, `available`, `currency`).
- **Fulfilment** is pull-based: the download page verifies the session with Stripe on each visit.
  There is no webhook handler, and none is needed for this flow. Add one
  (`checkout.session.completed`) only if you later want to email files, log orders, or track
  revenue outside Stripe.
- **Going live**: swap the publishable key for `pk_live_…` and put the live secret key in the
  Worker (`npx wrangler secret put STRIPE_SECRET_KEY`).
- **Note** that `ui_mode: "form"`, `name_collection` and `integration_identifier` rely on the
  pinned preview API version in `store-worker/src/index.js`. Keep that header in place, and check
  the docs before changing the version.

## Resources

- https://docs.stripe.com/mcp
- https://support.stripe.com
