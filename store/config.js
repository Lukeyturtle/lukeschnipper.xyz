// Address of the store API (the Cloudflare Worker in store-worker/).
// Filled in by store-worker/setup.sh after the first deploy. While it's empty,
// the store shows the tracks with previews but the Buy buttons say "coming soon".
window.STORE_API = location.hostname === "localhost" ? "http://localhost:8788" : "";

// Stripe publishable key (pk_test_... while testing, pk_live_... when you go live).
// Safe to keep in the repo — it's the public key. The secret key lives only in Cloudflare.
// While it's empty, the Buy buttons say "coming soon".
window.STRIPE_PUBLISHABLE_KEY = "pk_live_51RWbIHHKUmTg9Mi6MSNgb6oblhj4AqXsRLnpoMjs4vsXLZy7Dt1UJ4kM8FFMqGux1CS8X5TdjBDxOPcQSI6QAzTI00h4DO86j6";
