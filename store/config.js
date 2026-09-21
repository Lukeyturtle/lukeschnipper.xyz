// Address of the store API (the Cloudflare Worker in store-worker/).
// Filled in by store-worker/setup.sh after the first deploy. While it's empty,
// the store shows the tracks with previews but the Buy buttons say "coming soon".
window.STORE_API = location.hostname === "localhost" ? "http://localhost:8788" : "";
