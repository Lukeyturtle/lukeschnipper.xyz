// Embedded Stripe Checkout form for the store pages (loads after store/config.js).
//
// Needs window.STORE_API (the Cloudflare Worker) and window.STRIPE_PUBLISHABLE_KEY,
// plus https://js.stripe.com/dahlia/stripe.js in the page <head> — Stripe.js must always
// be loaded from Stripe, never bundled or self-hosted.

// Appearance: matches the site's dark theme. (Checkout Studio's default palette put
// near-black text on a blue background — about 1.6:1 contrast, effectively unreadable.)
window.STORE_CHECKOUT_APPEARANCE = {
  "theme": "night",
  "labels": "auto",
  "inputs": "spaced",
  "variables": {
    "borderRadius": "10px",
    "colorBackground": "#1b1e27",
    "colorText": "#e8eaf0",
    "colorPrimary": "#7dd3fc",
    "colorDanger": "#f87171",
    "colorSuccess": "#34d399",
    "fontFamily": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
    "fontSizeBase": "16px",
    "spacingUnit": "4px"
  }
};

// True when this browser can actually open a checkout form.
window.storeCheckoutReady = () =>
  !!(window.Stripe && window.STORE_API && /^pk_(test|live)_/.test(window.STRIPE_PUBLISHABLE_KEY || ""));

// Starts a Checkout Session for one track and mounts the payment form into `selector`.
// Rejects with a readable message if the session can't be created; after a successful
// payment Stripe sends the buyer to the session's return_url (the download page).
window.mountStoreCheckout = async function (trackId, selector, opts) {
  const gift = !!(opts && opts.gift);
  const stripe = Stripe(window.STRIPE_PUBLISHABLE_KEY, { betas: ["custom_checkout_payment_form_1"] });

  const clientSecret = fetch(`${window.STORE_API}/checkout`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: trackId, gift }),
  }).then(async (response) => {
    const json = await response.json().catch(() => ({}));
    if (!response.ok || !json.client_secret) throw new Error(json.error || "Couldn't start checkout.");
    return json.client_secret;
  });

  const checkout = stripe.initCheckoutFormSdk({ clientSecret, appearance: window.STORE_CHECKOUT_APPEARANCE });
  await clientSecret;  // fail before mounting if the session request went wrong

  const form = checkout.createForm({ layout: "expanded" });
  form.mount(selector);

  const loadActionsResult = await checkout.loadActions();
  if (loadActionsResult.type !== "success") {
    // Without actions the form would render but the Pay button would do nothing.
    form.unmount?.();
    throw new Error("Couldn't load the payment form. Please refresh and try again.");
  }
  form.on("confirm", async (event) => {
    try {
      await loadActionsResult.actions.confirm({ formConfirmEvent: event });
    } catch (error) {
      console.error("Payment confirmation error:", error);
    }
  });

  // Optional discount-code box: applies via the Checkout SDK; the form's total updates itself.
  const applyBtn = document.getElementById("promo-apply");
  const input = document.getElementById("promo-input");
  const msg = document.getElementById("promo-msg");
  const promoBox = document.querySelector(".promo");
  if (applyBtn && input && !loadActionsResult.actions.applyPromotionCode && promoBox) {
    promoBox.hidden = true;  // this SDK build can't apply codes — don't show a dead control
  }
  if (applyBtn && input && loadActionsResult.actions.applyPromotionCode) {
    const apply = async () => {
      const code = input.value.trim();
      if (!code) return;
      applyBtn.disabled = true; if (msg) { msg.textContent = "Checking…"; msg.className = "promo-msg"; }
      try {
        const res = await loadActionsResult.actions.applyPromotionCode(code);
        if (res && res.type === "error") {
          if (msg) { msg.textContent = res.error?.message || "That code isn't valid."; msg.className = "promo-msg bad"; }
        } else if (msg) {
          msg.textContent = "Code applied."; msg.className = "promo-msg good";
        }
      } catch (e) {
        if (msg) { msg.textContent = "That code isn't valid."; msg.className = "promo-msg bad"; }
      }
      applyBtn.disabled = false;
    };
    applyBtn.addEventListener("click", apply);
    input.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); apply(); } });
  }
};
