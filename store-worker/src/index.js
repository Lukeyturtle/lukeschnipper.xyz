// Store API for lukeschnipper.xyz.
//
//   POST /checkout  {id}          -> starts a Stripe Checkout session for one track, returns {url}
//   GET  /order?session_id=cs_... -> confirms the session is paid, returns short-lived download links
//   GET  /file?token=...          -> streams one file from the private R2 bucket
//
// Prices come from the public catalog (store/tracks.json), never from the browser.

const FORMATS = {
  mp3:  { label: "MP3",  detail: "320 kbps · plays everywhere",      type: "audio/mpeg" },
  aac:  { label: "AAC",  detail: ".m4a · smaller, great on Apple",   type: "audio/mp4", ext: "m4a" },
  wav:  { label: "WAV",  detail: "Lossless · best for editing",      type: "audio/wav" },
  aiff: { label: "AIFF", detail: "Lossless · Logic and GarageBand",  type: "audio/aiff" },
};
const FORMAT_ORDER = ["mp3", "aac", "wav", "aiff"];
const LINK_TTL_SECONDS = 6 * 60 * 60;
const ZERO_DECIMAL = new Set(["bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf"]);
const TRACK_ID = /^[a-z0-9-]{1,80}$/;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const cors = corsHeaders(request, env);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    try {
      if (url.pathname === "/checkout" && request.method === "POST") return await checkout(request, env, cors);
      if (url.pathname === "/order" && request.method === "GET") return await order(url, env, cors);
      if (url.pathname === "/file" && request.method === "GET") return await file(url, env);
      if (url.pathname === "/") return json({ ok: true }, 200, cors);
      return json({ error: "Not found" }, 404, cors);
    } catch (err) {
      console.error(err && err.stack ? err.stack : err);
      return json({ error: "Something went wrong on our end. Please try again in a moment." }, 500, cors);
    }
  },
};

async function checkout(request, env, cors) {
  let id;
  try { ({ id } = await request.json()); } catch { return json({ error: "Bad request" }, 400, cors); }
  const cat = await loadCatalog(env);
  const track = cat.tracks.get(String(id || ""));
  if (!track || track.available === false) return json({ error: "That track isn't for sale right now." }, 404, cors);

  const amount = ZERO_DECIMAL.has(cat.currency) ? Math.round(Number(track.price)) : Math.round(Number(track.price) * 100);
  if (!Number.isFinite(amount) || amount < 1) throw new Error(`track ${track.id} has no valid price`);

  const site = env.SITE_ORIGIN;
  const params = {
    mode: "payment",
    "line_items[0][quantity]": "1",
    "line_items[0][price_data][currency]": cat.currency,
    "line_items[0][price_data][unit_amount]": String(amount),
    "line_items[0][price_data][product_data][name]": `${track.title} (digital download)`,
    "metadata[track_id]": track.id,
    "payment_intent_data[metadata][track_id]": track.id,
    allow_promotion_codes: "true",
    success_url: `${site}/${track.page || "download.html"}?session_id={CHECKOUT_SESSION_ID}`,
    cancel_url: `${site}/store.html?cancelled=${encodeURIComponent(track.id)}`,
  };
  if (track.description) params["line_items[0][price_data][product_data][description]"] = String(track.description).slice(0, 500);
  if (track.cover) params["line_items[0][price_data][product_data][images][0]"] = new URL(track.cover, site + "/").href;

  const session = await stripe(env, "POST", "checkout/sessions", params);
  return json({ url: session.url }, 200, cors);
}

async function order(url, env, cors) {
  const sessionId = url.searchParams.get("session_id") || "";
  if (!/^cs_(test|live)_[A-Za-z0-9]{10,}$/.test(sessionId)) {
    return json({ error: "That download link isn't valid.", code: "invalid" }, 400, cors);
  }
  let session;
  try {
    session = await stripe(env, "GET", `checkout/sessions/${sessionId}`);
  } catch (err) {
    if (err.status === 404) return json({ error: "We couldn't find that order.", code: "not_found" }, 404, cors);
    throw err;
  }
  if (session.payment_status !== "paid" && session.payment_status !== "no_payment_required") {
    return json({ error: "This payment hasn't gone through yet. If you just paid, refresh this page in a minute.", code: "unpaid" }, 402, cors);
  }

  const now = Math.floor(Date.now() / 1000);
  const days = Number(env.DOWNLOAD_DAYS || 30);
  const expiresAt = session.created + days * 86400;
  if (now > expiresAt) {
    return json({ error: `This download page expired ${days} days after purchase.`, code: "expired" }, 410, cors);
  }

  const cat = await loadCatalog(env);
  // Sessions from our own checkout carry metadata.track_id; Stripe Payment Link sessions are
  // matched to a track by the link's URL (store/tracks.json "payment_link").
  let trackId = session.metadata && session.metadata.track_id;
  if (!trackId && session.payment_link) trackId = await trackIdFromPaymentLink(env, session.payment_link, cat);
  if (!TRACK_ID.test(trackId || "")) {
    console.error(`session ${sessionId} doesn't match any track (payment_link: ${session.payment_link})`);
    return json({ error: "Your payment went through, but I couldn't tell which song it was for. Email me and I'll send it right away.", code: "unknown_track" }, 500, cors);
  }
  // Honour the purchase even if the track has since been hidden or removed from the catalog.
  const track = cat.tracks.get(trackId) || { id: trackId, title: trackId };

  const files = [];
  for (const fmt of FORMAT_ORDER) {
    const head = await env.BUCKET.head(objectKey(trackId, fmt));
    if (!head) continue;
    const token = await sign(env, { t: trackId, f: fmt, e: now + LINK_TTL_SECONDS });
    files.push({ format: fmt, label: FORMATS[fmt].label, detail: FORMATS[fmt].detail, size: head.size,
                 url: `${url.origin}/file?token=${token}` });
  }
  if (!files.length) {
    return json({ error: "Your payment went through, but the files for this track are missing. Email us and we'll sort it out right away.", code: "missing" }, 500, cors);
  }

  return json({
    track: { id: track.id, title: track.title, artist: cat.artist, page: track.page || null,
             cover: track.cover ? new URL(track.cover, env.SITE_ORIGIN + "/").href : null },
    email: (session.customer_details && session.customer_details.email) || null,
    expires: new Date(expiresAt * 1000).toISOString(),
    files,
  }, 200, cors);
}

async function file(url, env) {
  const p = await verify(env, url.searchParams.get("token"));
  if (!p || !FORMATS[p.f] || !TRACK_ID.test(p.t || "")) return page("This download link isn't valid.", 403);
  if (Math.floor(Date.now() / 1000) > p.e) {
    return page("This download link has expired. Go back to your download page and click the button again.", 410);
  }
  const obj = await env.BUCKET.get(objectKey(p.t, p.f));
  if (!obj) return page("File not found.", 404);

  const cat = await loadCatalog(env).catch(() => null);
  const title = (cat && cat.tracks.get(p.t) && cat.tracks.get(p.t).title) || p.t;
  const artist = (cat && cat.artist) || "Luke Schnipper";
  const name = `${artist} - ${title}.${FORMATS[p.f].ext || p.f}`.replace(/[\/\\:*?"<>|]/g, "-");
  const ascii = name.replace(/[^\x20-\x7e]/g, "_");
  return new Response(obj.body, {
    headers: {
      "Content-Type": FORMATS[p.f].type,
      "Content-Length": String(obj.size),
      "Content-Disposition": `attachment; filename="${ascii}"; filename*=UTF-8''${encodeURIComponent(name)}`,
      "Cache-Control": "private, no-store",
    },
  });
}

// ---------- helpers ----------

async function trackIdFromPaymentLink(env, paymentLinkId, cat) {
  if (!/^plink_[A-Za-z0-9]+$/.test(paymentLinkId)) return null;
  const link = await stripe(env, "GET", `payment_links/${paymentLinkId}`);
  const norm = u => { try { const x = new URL(u); return x.host.toLowerCase() + x.pathname.replace(/\/+$/, ""); } catch { return ""; } };
  const target = norm(link.url);
  for (const t of cat.tracks.values()) {
    if (t.payment_link && norm(t.payment_link) === target) return t.id;
  }
  return null;
}

function objectKey(trackId, fmt) {
  return `tracks/${trackId}/${trackId}.${FORMATS[fmt].ext || fmt}`;
}

async function loadCatalog(env) {
  const res = await fetch(env.CATALOG_URL, { cf: { cacheTtl: 60, cacheEverything: true } });
  if (!res.ok) throw new Error(`catalog fetch failed: ${res.status}`);
  const cat = await res.json();
  return {
    currency: String(cat.currency || "gbp").toLowerCase(),
    artist: cat.artist || "Luke Schnipper",
    tracks: new Map((cat.tracks || []).filter(t => TRACK_ID.test(t.id || "")).map(t => [t.id, t])),
  };
}

async function stripe(env, method, path, params) {
  if (!env.STRIPE_SECRET_KEY) throw new Error("STRIPE_SECRET_KEY is not set");
  const init = { method, headers: { Authorization: `Bearer ${env.STRIPE_SECRET_KEY}` } };
  if (params) {
    init.body = new URLSearchParams(params);
    init.headers["Content-Type"] = "application/x-www-form-urlencoded";
  }
  const res = await fetch(`${env.STRIPE_API || "https://api.stripe.com"}/v1/${path}`, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(`Stripe ${res.status}: ${body.error ? body.error.message : "unknown error"}`);
    err.status = res.status;
    throw err;
  }
  return body;
}

function corsHeaders(request, env) {
  const allowed = [env.SITE_ORIGIN, ...String(env.EXTRA_ORIGINS || "").split(",")].map(s => s.trim()).filter(Boolean);
  const origin = request.headers.get("Origin");
  if (!origin || !allowed.includes(origin)) return { Vary: "Origin" };
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    Vary: "Origin",
  };
}

function json(data, status, headers) {
  return new Response(JSON.stringify(data), { status, headers: { ...headers, "Content-Type": "application/json" } });
}

function page(message, status) {
  const esc = message.replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  return new Response(
    `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">` +
    `<title>Download</title><body style="font:16px system-ui;background:#0e0f13;color:#e8eaf0;display:grid;place-items:center;min-height:100vh;margin:0;padding:24px;text-align:center">` +
    `<div><p>${esc}</p><p><a style="color:#7dd3fc" href="https://lukeschnipper.xyz/store.html">Back to the store</a></p></div>`,
    { status, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
}

// Download tokens: base64url(JSON payload) + "." + base64url(HMAC-SHA256).
const enc = new TextEncoder();
const b64u = buf => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const unb64u = s => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), c => c.charCodeAt(0));

async function hmacKey(env) {
  if (!env.DOWNLOAD_SIGNING_KEY) throw new Error("DOWNLOAD_SIGNING_KEY is not set");
  return crypto.subtle.importKey("raw", enc.encode(env.DOWNLOAD_SIGNING_KEY), { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
}

async function sign(env, payload) {
  const body = b64u(enc.encode(JSON.stringify(payload)));
  const sig = await crypto.subtle.sign("HMAC", await hmacKey(env), enc.encode(body));
  return `${body}.${b64u(sig)}`;
}

async function verify(env, token) {
  const [body, sig] = String(token || "").split(".");
  if (!body || !sig) return null;
  try {
    if (!(await crypto.subtle.verify("HMAC", await hmacKey(env), unb64u(sig), enc.encode(body)))) return null;
    return JSON.parse(new TextDecoder().decode(unb64u(body)));
  } catch {
    return null;
  }
}
