"use strict";
/* ResumeWise web app. No libraries. All user text goes through textContent, never as markup. */

var csrf = "";
/* ---------- languages ---------- */
/* t("English text") gives the text in the chosen language. An unknown text stays English.
   Texts with {0} {1} are templates, so "Step 3 of 8" is found by "Step {0} of {1}". Dictionaries: i18n.js */
var LANGS = [["en", "English"], ["hi", "हिन्दी"], ["mr", "मराठी"], ["te", "తెలుగు"]];
var I18N = window.I18N || {}, LANG = "en", TPL = {};
function readLang() {
  var saved = null;
  try { saved = window.localStorage.getItem("rw_lang"); } catch (e) { /* storage blocked */ }
  if (!saved) saved = (navigator.language || "en").slice(0, 2).toLowerCase();
  return LANGS.some(function (l) { return l[0] === saved; }) ? saved : "en";
}
function setLang(code) {
  LANG = code; document.documentElement.lang = code;
  try { window.localStorage.setItem("rw_lang", code); } catch (e) { /* storage blocked */ }
}
function templatesFor(dict) {
  if (TPL[LANG]) return TPL[LANG];
  var list = [];
  Object.keys(dict).forEach(function (key) {
    if (!/\{\d\}/.test(key)) return;
    var parts = key.split(/\{(\d)\}/), idx = [], re = "^";
    parts.forEach(function (piece, i) { if (i % 2) { idx.push(+piece); re += "(.+?)"; } else re += piece.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); });
    list.push({ re: new RegExp(re + "$"), idx: idx, key: key });
  });
  TPL[LANG] = list;
  return list;
}
function t(text) {
  if (LANG === "en" || typeof text !== "string" || !text) return text;
  var dict = I18N[LANG] || {};
  var core = text.replace(/^\s+|\s+$/g, "");
  if (!core) return text;
  var lead = text.slice(0, text.indexOf(core)), tail = text.slice(lead.length + core.length), hit = dict[core];
  if (hit === undefined) {
    var list = templatesFor(dict);
    for (var i = 0; i < list.length && hit === undefined; i++) {
      var m = list[i].re.exec(core);
      if (m) hit = dict[list[i].key].replace(/\{(\d)\}/g, function (_, n) { var at = list[i].idx.indexOf(+n); return at < 0 ? "" : t(m[at + 1]); });
    }
  }
  if (hit === undefined) {
    if (window.RW_I18N_DEBUG && /[A-Za-z]{3}/.test(core)) (window.RW_MISSING = window.RW_MISSING || {})[core] = 1;
    return text;
  }
  return lead + hit + tail;
}
function langPicker() {
  var sel = h("select", { class: "langsel", "aria-label": "Language" });
  LANGS.forEach(function (l) { var o = h("option", { value: l[0], text: l[1] }); if (l[0] === LANG) o.selected = true; sel.appendChild(o); });
  sel.addEventListener("change", function () { setLang(sel.value); if (state.user) renderShell(); else location.reload(); });
  return sel;
}
LANG = readLang(); document.documentElement.lang = LANG;

var state = { user: null, profile: null, tab: "cv", templates: [], run: null, flash: null };
var root = document.getElementById("app");

/* ---------- small helpers ---------- */
function h(tag, props) {
  var el = document.createElement(tag);
  props = props || {};
  Object.keys(props).forEach(function (k) {
    var v = props[k];
    if (v === null || v === undefined || v === false) return;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = t(v);
    else if (k.indexOf("on") === 0) el.addEventListener(k.slice(2), v);
    else if (k === "placeholder" || k === "title" || k === "aria-label" || k === "alt") el.setAttribute(k, t(v));
    else el.setAttribute(k, v === true ? "" : v);
  });
  function add(c) {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) { c.forEach(add); return; }
    el.appendChild(typeof c === "string" ? document.createTextNode(t(c)) : c);
  }
  for (var i = 2; i < arguments.length; i++) add(arguments[i]);
  return el;
}
function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }
function msg(kind, text) { return h("div", { class: "msg " + kind, role: kind === "err" ? "alert" : "status", text: text }); }

function api(method, path, body) {
  var opts = { method: method, credentials: "same-origin", headers: {} };
  if (method !== "GET") opts.headers["X-CSRFToken"] = csrf;
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  return fetch(path, opts).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (data) {
      if (data && data.csrf) csrf = data.csrf;
      if (!r.ok) {
        var e = new Error(data.error || ("Something went wrong (" + r.status + ")"));
        e.status = r.status; e.data = data; throw e;
      }
      return data;
    });
  });
}
function errBox(e) {
  var box = msg("err", t(e.message));
  if (e.data && e.data.details) box.appendChild(h("ul", { class: "plain" }, e.data.details.map(function (d) { return h("li", { text: d }); })));
  if (e.data && e.data.pending) box.appendChild(h("div", { class: "small", text: "Pending lines: " + e.data.pending.join(", ") }));
  return box;
}
function show(el, node) { clear(el); if (node) el.appendChild(node); }

/* ---------- start ---------- */
var HASH_ACTION = /^#(reset|verify|magic)=(.+)$/;
function takeHashAction() {
  var m = HASH_ACTION.exec(location.hash || "");
  if (m) history.replaceState(null, "", location.pathname);  // keep one-time tokens out of the address bar and history
  return m ? { kind: m[1], value: m[2] } : null;
}
function afterAuth(res) {
  if (res && res.needs_2fa) return viewTwoFactor();
  state.user = res;
  return enterApp();
}
function runHashAction(act) {
  if (act.kind === "reset") {
    var dot = act.value.indexOf(".");
    return viewReset(act.value.slice(0, dot), act.value.slice(dot + 1));
  }
  if (act.kind === "verify") {
    return api("POST", "/v1/auth/verify", { token: act.value }).then(function () {
      if (state.user) { state.user.email_verified = true; state.flash = msg("ok", "Email confirmed. Thank you!"); return enterApp(); }
      viewLogin(msg("ok", "Email confirmed. You can log in now."));
    }, function (e) { if (state.user) { state.flash = errBox(e); return enterApp(); } viewLogin(errBox(e)); });
  }
  return api("POST", "/v1/auth/magic", { token: act.value }).then(afterAuth, function (e) { viewLogin(errBox(e)); });
}
var LEGAL_HASH = /^#(terms|privacy|refunds|faq)$/;
window.addEventListener("hashchange", function () {
  var lg = LEGAL_HASH.exec(location.hash || "");
  if (lg) return showLegal(lg[1]);
  var act = takeHashAction();
  if (act && csrf) runHashAction(act);  // link opened while the app is already open
});
var providers = {};
function start() {
  var lg = LEGAL_HASH.exec(location.hash || "");
  if (lg) return showLegal(lg[1]);
  var act = takeHashAction();
  var signin = /^#signin=(\w+)$/.exec(location.hash || "");
  if (signin) history.replaceState(null, "", location.pathname);
  var bill = /^#billing=(paid|pending|failed)$/.exec(location.hash || "");
  if (bill) history.replaceState(null, "", location.pathname);
  api("GET", "/v1/auth/csrf").then(function (d) { csrf = d.csrf; return api("GET", "/v1/auth/providers").catch(function () { return {}; }); })
    .then(function (p) { providers = p || {}; return api("GET", "/v1/auth/me").catch(function () { return null; }); })
    .then(function (user) {
      if (user) state.user = user;
      if (act) return runHashAction(act);
      if (user && bill) {
        state.tab = "acct";
        state.flash = msg(bill[1] === "paid" ? "ok" : bill[1] === "pending" ? "info" : "err",
          bill[1] === "paid" ? "Payment received. Thank you! Your Pro plan is on." :
          bill[1] === "pending" ? "We have not received the payment yet. If you paid, wait a few minutes and reload this page." :
          "The payment could not be checked. If money was taken, write to us with your payment id.");
      }
      if (user) return enterApp();
      if (signin && signin[1] === "2fa") return viewTwoFactor();
      if (signin) return viewLogin(msg("err", signin[1] === "denied" ? "Sign-in was cancelled." : "That sign-in did not work. Please try again, or use your email."));
      viewSignup();
    })
    .catch(function () { show(root, h("div", { class: "wrap" }, msg("err", "Cannot reach the server. Is it running?"))); });
}

/* ---------- sign up / log in / forgot / reset ---------- */
var EMAIL_OK = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
var authEmail = "";

function field(id, label, control, extra) {
  var box = h("div", { class: "field" },
    h("div", { class: "flabel" }, h("label", { for: id, text: label }), extra || null),
    control,
    h("div", { class: "ferr", id: id + "-err", role: "alert" }));
  box.addEventListener("input", function () { fieldError(id, ""); });  // typing clears the old error
  return box;
}
function fieldError(id, text) {
  var err = document.getElementById(id + "-err"), input = document.getElementById(id);
  if (err) err.textContent = text || "";
  if (input) { if (text) input.setAttribute("aria-invalid", "true"); else input.removeAttribute("aria-invalid"); }
  return !text;
}
function textField(id, label, type, autocomplete, extra) {
  var input = h("input", { type: type, id: id, autocomplete: autocomplete, required: true, maxlength: type === "email" ? "254" : "80" });
  return { input: input, node: field(id, label, input, extra) };
}
function passwordField(id, label, autocomplete, extra) {
  var input = h("input", { type: "password", id: id, autocomplete: autocomplete, required: true, maxlength: "128" });
  var eye = h("button", { type: "button", class: "eye", "aria-label": "Show password", text: "Show", onclick: function () {
    var shown = input.type === "text";
    input.type = shown ? "password" : "text";
    eye.textContent = shown ? "Show" : "Hide";
    eye.setAttribute("aria-label", t(shown ? "Show password" : "Hide password"));
  } });
  return { input: input, node: field(id, label, h("div", { class: "pw" }, input, eye), extra) };
}

/* Guidance only. The server has the final say (it also rejects common passwords). */
function pwChecks(pw, email) {
  var local = (email || "").split("@")[0].toLowerCase();
  return [
    { text: "At least 10 characters", ok: pw.length >= 10 },
    { text: "Not only numbers", ok: pw.length > 0 && !/^\d+$/.test(pw) },
    { text: "Not similar to your email", ok: pw.length > 0 && !(local.length >= 3 && pw.toLowerCase().indexOf(local) >= 0) }
  ];
}
function pwScore(pw) {
  if (!pw) return 0;
  var s = 0;
  if (pw.length >= 10) s++;
  if (pw.length >= 14) s++;
  var kinds = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter(function (r) { return r.test(pw); }).length;
  if (kinds >= 3) s++;
  if (kinds >= 4 && pw.length >= 12) s++;
  if (pw.length < 10 || /^\d+$/.test(pw)) s = Math.min(s, 1);
  return Math.max(1, Math.min(s, 4));
}
function strengthMeter(passInput, getEmail) {
  var bars = h("div", { class: "bars", "data-s": "0" }, h("span"), h("span"), h("span"), h("span"));
  var label = h("span", { class: "slabel small" });
  var list = h("ul", { class: "rules" });
  function update() {
    var pw = passInput.value, names = ["", "Weak", "Fair", "Good", "Strong"], sc = pwScore(pw);
    bars.setAttribute("data-s", String(sc));
    label.textContent = names[sc];
    clear(list);
    pwChecks(pw, getEmail()).forEach(function (c) { list.appendChild(h("li", { class: c.ok ? "ok" : "", text: (c.ok ? "✓ " : "• ") + c.text })); });
  }
  passInput.addEventListener("input", update);
  update();
  return { node: h("div", { class: "meter" }, h("div", { class: "row tight" }, bars, label), list), update: update };
}

function busy(btn, label, work) {
  btn.disabled = true; btn.textContent = t("Please wait...");
  return work().then(function (r) { btn.disabled = false; btn.textContent = t(label); return r; },
    function (e) { btn.disabled = false; btn.textContent = t(label); throw e; });
}
function passkeysSupported() { return !!(window.PublicKeyCredential && navigator.credentials && providers.passkeys); }
function socialBlock(mode) {
  var verb = mode === "signup" ? "Sign up with " : "Continue with ";
  var items = [];
  if (providers.google) items.push(h("a", { class: "gbtn", href: "/v1/auth/google/start" }, h("span", { class: "g", "aria-hidden": "true", text: "G" }), h("span", { text: verb + "Google" })));
  if (providers.linkedin) items.push(h("a", { class: "gbtn", href: "/v1/auth/linkedin/start" }, h("span", { class: "g li", "aria-hidden": "true", text: "in" }), h("span", { text: verb + "LinkedIn" })));
  if (mode === "login" && passkeysSupported()) items.push(h("button", { type: "button", class: "gbtn", id: "passkey-login", onclick: passkeyLogin },
    h("span", { class: "g pk", "aria-hidden": "true", text: "••" }), h("span", { text: "Sign in with a passkey" })));
  if (!items.length) return null;
  return h("div", { class: "social" }, items, h("div", { id: "social-msg" }), h("div", { class: "or" }, h("span", { text: "or use your email" })));
}
function linkButton(text, fn) { return h("button", { type: "button", class: "link", text: text, onclick: fn }); }

function authShell(title, subtitle, content) {
  var points = ["Never adds anything that is not in your CV", "You approve every new line before download", "Your CV is deleted after 30 days"];
  return h("main", { class: "split" },
    h("aside", { class: "side" },
      h("div", { class: "logo", text: "ResumeWise" }),
      h("div", null,
        h("h2", { text: "Your CV, fitted to each job." }),
        h("p", { class: "tagline", text: "Nothing made up." })),
      h("ol", { class: "points" }, points.map(function (p, i) { return h("li", null, h("span", { class: "n", text: "0" + (i + 1) }), p); }))),
    h("section", { class: "formside" },
      h("div", { class: "authbox" },
        h("div", { class: "authtop" }, h("div", { class: "mbrand brand", text: "ResumeWise" }), langPicker()),
        h("h1", { text: title }),
        subtitle ? h("p", { class: "muted", text: subtitle }) : null,
        content, legalLinks())));
}

function viewLogin(notice) {
  var out = h("div", null, notice || null);
  var email = textField("email", "Email", "email", "email"); email.input.value = authEmail;
  var pass = passwordField("password", "Password", "current-password",
    linkButton("Forgot password?", function () { authEmail = email.input.value; viewForgot(); }));
  var remember = h("input", { type: "checkbox", id: "remember", checked: true });
  var submit = h("button", { class: "primary wide", type: "submit", text: "Log in" });
  var form = h("form", { novalidate: true }, email.node, pass.node,
    h("label", { class: "check", for: "remember" }, remember, h("span", { text: "Keep me signed in for 30 days" })),
    submit);
  form.addEventListener("submit", function (ev) {
    ev.preventDefault(); show(out, null);
    var ok = fieldError("email", EMAIL_OK.test(email.input.value.trim()) ? "" : "Enter a valid email");
    ok = fieldError("password", pass.input.value ? "" : "Enter your password") && ok;
    if (!ok) return;
    authEmail = email.input.value;
    busy(submit, "Log in", function () {
      return api("POST", "/v1/auth/login", { email: email.input.value, password: pass.input.value, remember: remember.checked }).then(afterAuth);
    }).catch(function (e) { show(out, errBox(e)); });
  });
  show(root, authShell("Welcome back", "Log in to continue with your CV.",
    h("div", null, out, socialBlock("login"), form,
      h("p", { class: "switch muted" }, linkButton("Email me a login link instead", function () { authEmail = email.input.value; viewMagic(); })),
      h("p", { class: "switch muted" }, "New to ResumeWise? ", linkButton("Create account", function () { authEmail = email.input.value; viewSignup(); })))));
  (authEmail ? pass.input : email.input).focus();
}

/* ---------- bot check: our own proof of work (server side: packs/botcheck.py) ---------- */
function sha256Zeros(str) {  // number of leading zero bits of sha256(str); plain JS so it also works on http:// (phone on Wi-Fi)
  var K = sha256Zeros.K;
  if (!K) {
    K = sha256Zeros.K = new Uint32Array(64); var n = 2, i = 0;
    while (i < 64) { var prime = true; for (var d = 2; d * d <= n; d++) if (n % d === 0) { prime = false; break; }
      if (prime) { K[i++] = Math.floor((Math.pow(n, 1 / 3) % 1) * 4294967296); } n++; }
  }
  var bytes = []; for (var c = 0; c < str.length; c++) bytes.push(str.charCodeAt(c) & 255);
  var len = bytes.length; bytes.push(128); while (bytes.length % 64 !== 56) bytes.push(0);
  var hi = Math.floor(len * 8 / 4294967296), lo = (len * 8) >>> 0;
  bytes.push(hi >>> 24 & 255, hi >>> 16 & 255, hi >>> 8 & 255, hi & 255, lo >>> 24 & 255, lo >>> 16 & 255, lo >>> 8 & 255, lo & 255);
  var H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19], W = new Uint32Array(64);
  function rr(x, k) { return (x >>> k) | (x << (32 - k)); }
  for (var off = 0; off < bytes.length; off += 64) {
    for (var t = 0; t < 16; t++) W[t] = (bytes[off + 4 * t] << 24) | (bytes[off + 4 * t + 1] << 16) | (bytes[off + 4 * t + 2] << 8) | bytes[off + 4 * t + 3];
    for (t = 16; t < 64; t++) { var s0 = rr(W[t - 15], 7) ^ rr(W[t - 15], 18) ^ (W[t - 15] >>> 3), s1 = rr(W[t - 2], 17) ^ rr(W[t - 2], 19) ^ (W[t - 2] >>> 10); W[t] = (W[t - 16] + s0 + W[t - 7] + s1) | 0; }
    var a = H[0], b = H[1], c2 = H[2], d2 = H[3], e = H[4], f = H[5], g = H[6], hh = H[7];
    for (t = 0; t < 64; t++) {
      var S1 = rr(e, 6) ^ rr(e, 11) ^ rr(e, 25), ch = (e & f) ^ (~e & g), t1 = (hh + S1 + ch + K[t] + W[t]) | 0;
      var S0 = rr(a, 2) ^ rr(a, 13) ^ rr(a, 22), mj = (a & b) ^ (a & c2) ^ (b & c2), t2 = (S0 + mj) | 0;
      hh = g; g = f; f = e; e = (d2 + t1) | 0; d2 = c2; c2 = b; b = a; a = (t1 + t2) | 0;
    }
    H[0] = (H[0] + a) | 0; H[1] = (H[1] + b) | 0; H[2] = (H[2] + c2) | 0; H[3] = (H[3] + d2) | 0; H[4] = (H[4] + e) | 0; H[5] = (H[5] + f) | 0; H[6] = (H[6] + g) | 0; H[7] = (H[7] + hh) | 0;
  }
  var bits = 0;
  for (var w = 0; w < 8; w++) { var word = H[w] >>> 0; if (word === 0) { bits += 32; continue; } bits += Math.clz32(word); break; }
  return bits;
}
function solveChallenge(ch) {
  return new Promise(function (resolve) {
    var n = 0;
    (function chunk() {
      var end = n + 1500;
      for (; n < end; n++) if (sha256Zeros(ch.token + ":" + n) >= ch.bits) { resolve(n); return; }
      setTimeout(chunk, 0);  // let the page breathe between chunks
    })();
  });
}
function startBotCheck(form) {
  var trap = h("input", { type: "text", name: "website", tabindex: "-1", autocomplete: "off", "aria-hidden": "true" });
  form.appendChild(h("div", { class: "hp", "aria-hidden": "true" }, trap));
  var current = null;
  function fresh() {
    var started = Date.now();
    current = api("GET", "/v1/auth/challenge").then(function (ch) {
      return solveChallenge(ch).then(function (nonce) {
        var wait = Math.max(0, (ch.min_wait + 0.4) * 1000 - (Date.now() - started));
        return new Promise(function (r) { setTimeout(function () { r({ bot_token: ch.token, bot_nonce: nonce, at: Date.now() }); }, wait); });
      });
    });
    current.catch(function () { /* the submit will report it */ });
  }
  fresh();
  return {
    get: function () {  // one answer per token: start the next one right away
      var p = current.then(function (r) { return r.at < Date.now() - 50 * 60 * 1000 ? Promise.reject(new Error("stale")) : r; });
      return p.catch(function () { fresh(); return current; }).then(function (r) {
        fresh();
        return { bot_token: r.bot_token, bot_nonce: r.bot_nonce, website: trap.value };
      });
    }
  };
}

function viewMagic() {
  var out = h("div");
  var email = textField("email", "Email", "email", "email"); email.input.value = authEmail;
  var submit = h("button", { class: "primary wide", type: "submit", text: "Send login link" });
  var form = h("form", { novalidate: true }, email.node, submit);
  var bot = startBotCheck(form);
  form.addEventListener("submit", function (ev) {
    ev.preventDefault(); show(out, null);
    if (!fieldError("email", EMAIL_OK.test(email.input.value.trim()) ? "" : "Enter a valid email")) return;
    authEmail = email.input.value;
    busy(submit, "Send login link", function () { return bot.get().then(function (b) { return api("POST", "/v1/auth/magic/send", Object.assign({ email: email.input.value }, b)); }); })
      .then(function () {
        show(root, authShell("Check your email", null, h("div", null,
          msg("ok", "If " + authEmail + " has an account, a login link is on its way. It works once, for 15 minutes."),
          h("p", { class: "muted small", text: "Testing on your own computer? The email is printed in the server window." }),
          h("p", { class: "switch" }, linkButton("Back to log in", function () { viewLogin(); })))));
      }).catch(function (e) { show(out, errBox(e)); });
  });
  show(root, authShell("Log in with an email link", "No password needed. We email you a one-time link.",
    h("div", null, out, form, h("p", { class: "switch" }, linkButton("Back to log in", function () { authEmail = email.input.value; viewLogin(); })))));
  email.input.focus();
}

function viewTwoFactor() {
  var out = h("div");
  var recovery = false;
  var code = h("input", { type: "text", id: "code", inputmode: "numeric", autocomplete: "one-time-code", required: true, maxlength: "20" });
  var label = h("label", { for: "code", text: "6-digit code" });
  var toggle = linkButton("Use a recovery code instead", function () {
    recovery = !recovery;
    label.textContent = recovery ? "Recovery code" : "6-digit code";
    toggle.textContent = t(recovery ? "Use my authenticator app instead" : "Use a recovery code instead");
    code.setAttribute("inputmode", recovery ? "text" : "numeric"); code.value = ""; code.focus();
  });
  var submit = h("button", { class: "primary wide", type: "submit", text: "Verify" });
  var form = h("form", { novalidate: true }, h("div", { class: "field" }, label, code, h("div", { class: "ferr", id: "code-err", role: "alert" })), submit);
  form.addEventListener("submit", function (ev) {
    ev.preventDefault(); show(out, null);
    if (!fieldError("code", code.value.trim() ? "" : "Enter the code")) return;
    busy(submit, "Verify", function () { return api("POST", "/v1/auth/2fa/verify", { code: code.value }).then(afterAuth); })
      .catch(function (e) { show(out, errBox(e)); if (e.status === 429 || e.status === 400) setTimeout(function () { viewLogin(); }, 1500); });
  });
  show(root, authShell("Two-step verification", "Open your authenticator app and enter the 6-digit code for ResumeWise.",
    h("div", null, out, form, h("p", { class: "switch" }, toggle), h("p", { class: "switch" }, linkButton("Back to log in", function () { viewLogin(); })))));
  code.focus();
}

/* ---------- passkeys (WebAuthn) ---------- */
function b64uToBuf(text) {
  var s = text.replace(/-/g, "+").replace(/_/g, "/"); while (s.length % 4) s += "=";
  var bin = atob(s), a = new Uint8Array(bin.length);
  for (var i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i);
  return a.buffer;
}
function bufToB64u(buf) {
  var a = new Uint8Array(buf), s = "";
  for (var i = 0; i < a.length; i++) s += String.fromCharCode(a[i]);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function passkeyError(e) {
  if (e && e.name === "NotAllowedError") return new Error("Passkey cancelled or timed out.");
  if (e && e.name === "SecurityError") return new Error("Passkeys need the site address to be a name, not numbers. Open http://localhost:8000 instead of 127.0.0.1.");
  if (e && e.name === "InvalidStateError") return new Error("This device already has a passkey for your account.");
  return e;
}
function passkeyLogin() {
  var box = document.getElementById("social-msg"), btn = document.getElementById("passkey-login");
  show(box, null); btn.disabled = true;
  api("POST", "/v1/auth/passkey/login/options", {}).then(function (o) {
    return navigator.credentials.get({ publicKey: { challenge: b64uToBuf(o.challenge), rpId: o.rpId, userVerification: o.userVerification, timeout: o.timeout, allowCredentials: [] } });
  }).then(function (cred) {
    var r = cred.response;
    return api("POST", "/v1/auth/passkey/login", { id: cred.id, response: {
      clientDataJSON: bufToB64u(r.clientDataJSON), authenticatorData: bufToB64u(r.authenticatorData),
      signature: bufToB64u(r.signature), userHandle: r.userHandle ? bufToB64u(r.userHandle) : "" } });
  }).then(afterAuth).catch(function (e) { btn.disabled = false; show(box, errBox(passkeyError(e))); });
}
function passkeyAdd(name) {
  return api("POST", "/v1/auth/passkey/register/options", {}).then(function (o) {
    return navigator.credentials.create({ publicKey: {
      challenge: b64uToBuf(o.challenge), rp: o.rp, timeout: o.timeout, attestation: o.attestation,
      user: { id: b64uToBuf(o.user.id), name: o.user.name, displayName: o.user.displayName },
      pubKeyCredParams: o.pubKeyCredParams, authenticatorSelection: o.authenticatorSelection,
      excludeCredentials: o.excludeCredentials.map(function (c) { return { type: c.type, id: b64uToBuf(c.id) }; }) } });
  }).then(function (cred) {
    return api("POST", "/v1/auth/passkey/register", { id: cred.id, name: name, response: {
      clientDataJSON: bufToB64u(cred.response.clientDataJSON), attestationObject: bufToB64u(cred.response.attestationObject) } });
  }).catch(function (e) { throw passkeyError(e); });
}

function viewSignup() {
  var out = h("div");
  var name = textField("name", "Full name", "text", "name");
  var email = textField("email", "Email", "email", "email"); email.input.value = authEmail;
  var pass = passwordField("password", "Password", "new-password");
  var meter = strengthMeter(pass.input, function () { return email.input.value; });
  email.input.addEventListener("input", meter.update);
  var terms = h("input", { type: "checkbox", id: "terms" });
  var submit = h("button", { class: "primary wide", type: "submit", text: "Create account" });
  terms.addEventListener("change", function () { document.getElementById("terms-err").textContent = ""; });
  var form = h("form", { novalidate: true }, name.node, email.node, pass.node, meter.node,
    h("details", { class: "data" }, h("summary", { text: "How we handle your data" }),
      h("ul", { class: "plain small" }, [
        "Your CV is stored for 30 days, then deleted. You can delete it yourself any time.",
        "For AI tailoring, only the numbered CV lines and the job text are sent. Your name, contact details and photo are never sent.",
        "Anything the AI adds that is not in your CV is marked, and nothing is downloaded until you decide on it."
      ].map(function (t) { return h("li", { text: t }); }))),
    h("label", { class: "check", for: "terms" }, terms, h("span", { text: "I understand how my data is used and agree to the Terms and Privacy Policy" })),
    h("div", { class: "ferr", id: "terms-err", role: "alert" }),
    submit);
  var bot = startBotCheck(form);
  form.addEventListener("submit", function (ev) {
    ev.preventDefault(); show(out, null);
    var ok = fieldError("name", name.input.value.trim() ? "" : "Enter your name");
    ok = fieldError("email", EMAIL_OK.test(email.input.value.trim()) ? "" : "Enter a valid email") && ok;
    ok = fieldError("password", pwChecks(pass.input.value, email.input.value).every(function (c) { return c.ok; }) ? "" : "Please meet all the password rules") && ok;
    document.getElementById("terms-err").textContent = terms.checked ? "" : "Please accept to continue";
    if (!ok || !terms.checked) return;
    authEmail = email.input.value;
    busy(submit, "Create account", function () {
      return bot.get().then(function (b) { return api("POST", "/v1/auth/register", Object.assign({ name: name.input.value, email: email.input.value, password: pass.input.value, accept_terms: true }, b)); })
        .then(function (user) { state.user = user; return enterApp(); });
    }).catch(function (e) { show(out, errBox(e)); });
  });
  show(root, authShell("Create your account", "Free to try. It takes a minute.",
    h("div", null, out, socialBlock("signup"), form,
      h("p", { class: "switch muted" }, "Already have an account? ", linkButton("Log in", function () { authEmail = email.input.value; viewLogin(); })))));
  name.input.focus();
}

function viewForgot() {
  var out = h("div");
  var email = textField("email", "Email", "email", "email"); email.input.value = authEmail;
  var submit = h("button", { class: "primary wide", type: "submit", text: "Send reset link" });
  var form = h("form", { novalidate: true }, email.node, submit);
  var bot = startBotCheck(form);
  form.addEventListener("submit", function (ev) {
    ev.preventDefault(); show(out, null);
    if (!fieldError("email", EMAIL_OK.test(email.input.value.trim()) ? "" : "Enter a valid email")) return;
    authEmail = email.input.value;
    busy(submit, "Send reset link", function () { return bot.get().then(function (b) { return api("POST", "/v1/auth/forgot", Object.assign({ email: email.input.value }, b)); }); })
      .then(viewForgotSent).catch(function (e) { show(out, errBox(e)); });
  });
  show(root, authShell("Forgot your password?", "Enter your email and we will send you a link to choose a new one.",
    h("div", null, out, form, h("p", { class: "switch" }, linkButton("Back to log in", function () { authEmail = email.input.value; viewLogin(); })))));
  email.input.focus();
}
function viewForgotSent() {
  show(root, authShell("Check your email", null,
    h("div", null,
      msg("ok", "If " + authEmail + " has an account, a reset link is on its way. It works once, for 1 hour."),
      h("p", { class: "muted small", text: "Nothing in your inbox? Check spam. Testing on your own computer? The email is printed in the server window." }),
      h("p", { class: "switch" }, linkButton("Back to log in", function () { viewLogin(); })))));
}

function viewReset(uid, token) {
  var out = h("div");
  var pass = passwordField("password", "New password", "new-password");
  var again = passwordField("password2", "Repeat new password", "new-password");
  var meter = strengthMeter(pass.input, function () { return authEmail; });
  var submit = h("button", { class: "primary wide", type: "submit", text: "Change password" });
  var form = h("form", { novalidate: true }, pass.node, meter.node, again.node, submit);
  form.addEventListener("submit", function (ev) {
    ev.preventDefault(); show(out, null);
    var ok = fieldError("password", pwChecks(pass.input.value, "").every(function (c) { return c.ok; }) ? "" : "Please meet all the password rules");
    ok = fieldError("password2", again.input.value === pass.input.value ? "" : "The two passwords do not match") && ok;
    if (!ok) return;
    busy(submit, "Change password", function () { return api("POST", "/v1/auth/reset", { uid: uid, token: token, password: pass.input.value }); })
      .then(function () { viewLogin(msg("ok", "Password changed. Log in with your new password.")); })
      .catch(function (e) { show(out, errBox(e)); });
  });
  show(root, authShell("Choose a new password", "Pick something you have not used before.",
    h("div", null, out, form, h("p", { class: "switch" }, linkButton("Back to log in", function () { viewLogin(); })))));
  pass.input.focus();
}

/* ---------- tab 4: jobs (save a job, match, cover letter, interview practice) ---------- */
var JOB_STATUS = [["saved", "Saved"], ["applied", "Applied"], ["interview", "Interview"], ["offer", "Offer"], ["rejected", "Rejected"]];
function statusSelect(current, onchange, id) {
  var sel = h("select", { id: id, "aria-label": "Status" });
  JOB_STATUS.forEach(function (o) { var op = h("option", { value: o[0], text: o[1] }); if (o[0] === current) op.selected = true; sel.appendChild(op); });
  sel.addEventListener("change", function () { onchange(sel.value); });
  return sel;
}
function scoreBadge(score) {
  return h("span", { class: "badge", text: score === null || score === undefined ? "no score" : score + "% match" });
}
function pad2(n) { return n < 10 ? "0" + n : String(n); }
function dayPlus(n) {
  var d = new Date(); d.setDate(d.getDate() + n);
  return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate());
}
function followBadge(j) {
  if (j.status !== "applied" || !j.follow_up_on) return null;
  return h("span", { class: j.due ? "badge due" : "badge", text: j.due ? "Follow up now" : "Follow up on " + j.follow_up_on });
}
function dueBanner(box, out) {
  api("GET", "/v1/jobs/due").then(function (d) {
    if (!d.jobs.length) return;
    var card = h("div", { class: "card due" }, h("h2", { text: "Time to follow up" }),
      h("p", { class: "muted small", text: "You applied a while ago and did not hear back. A short, polite message to the recruiter is normal." }));
    d.jobs.forEach(function (j) {
      card.appendChild(h("div", { class: "line jobrow" },
        h("div", { class: "grow" }, h("div", { class: "t", text: j.title + (j.company ? " - " + j.company : "") }),
          h("div", { class: "muted small", text: "Applied " + (j.days_since_applied === null ? "" : j.days_since_applied + " days ago") })),
        h("button", { type: "button", text: "Open", onclick: function () { state.jobId = j.id; refresh(); } }),
        h("button", { type: "button", text: "Remind me in 3 days", onclick: function () {
          api("PATCH", "/v1/jobs/" + j.id, { follow_up_on: dayPlus(3) }).then(function () { refresh(); }).catch(function (e) { show(out, errBox(e)); });
        } })));
    });
    box.appendChild(card);
  }).catch(function () { /* the banner is optional */ });
}
function viewJobs(body) {
  if (state.jobId) return viewJobDetail(body);
  var out = h("div"), list = h("div"), dueBox = h("div");
  body.appendChild(dueBox); dueBanner(dueBox, out);
  var title = h("input", { type: "text", id: "j-title", placeholder: "Python Developer", maxlength: "200" });
  var company = h("input", { type: "text", id: "j-company", placeholder: "Acme Technologies", maxlength: "200" });
  var link = h("input", { type: "text", id: "j-url", placeholder: "https://... (optional)", maxlength: "500" });
  var text = h("textarea", { id: "j-text", rows: "8", maxlength: "8000", placeholder: "Paste the job description here" });
  var save = h("button", { class: "primary", type: "button", text: "Save job and check match", onclick: function () {
    save.disabled = true;
    api("POST", "/v1/jobs", { title: title.value, company: company.value, url: link.value, job_text: text.value, profile_id: state.profile.id }).then(function (j) {
      state.jobId = j.id; refresh();
    }).catch(function (e) { show(out, errBox(e)); save.disabled = false; });
  } });
  body.appendChild(h("div", { class: "card" }, h("h2", { text: "Save a job" }),
    h("p", { class: "muted small", text: "Copy the job description from the job site and paste it. We check how much of it your CV covers. Nothing is made up and no AI is used here." }),
    h("label", { for: "j-title", text: "Job title" }), title, h("label", { for: "j-company", text: "Company (optional)" }), company,
    h("label", { for: "j-url", text: "Link (optional)" }), link, h("label", { for: "j-text", text: "Job description" }), text, h("div", { class: "row" }, save), out));
  body.appendChild(h("div", { class: "card" }, h("h2", { text: "My jobs" }), list));
  api("GET", "/v1/jobs").then(function (d) {
    if (!d.jobs.length) { show(list, h("p", { class: "muted", text: "No jobs saved yet." })); return; }
    clear(list);
    d.jobs.forEach(function (j) {
      list.appendChild(h("div", { class: "line jobrow" },
        h("div", { class: "grow" }, h("div", { class: "t", text: j.title + (j.company ? " - " + j.company : "") }), h("div", { class: "muted small", text: "Saved " + j.created.slice(0, 10) })),
        followBadge(j), scoreBadge(j.score),
        statusSelect(j.status, function (v) { api("PATCH", "/v1/jobs/" + j.id, { status: v }).then(function () { refresh(); }).catch(function (e) { show(out, errBox(e)); }); }, "st-" + j.id),
        h("button", { type: "button", text: "Open", onclick: function () { state.jobId = j.id; refresh(); } })));
    });
  }).catch(function (e) { show(list, errBox(e)); });
}
function downloadText(name, content) {
  var url = URL.createObjectURL(new Blob([content], { type: "text/plain;charset=utf-8" }));
  var a = h("a", { href: url, download: name }); document.body.appendChild(a); a.click(); document.body.removeChild(a);
  setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
}
function viewJobDetail(body) {
  var out = h("div");
  body.appendChild(h("p", { class: "muted", text: "Loading..." }));
  api("GET", "/v1/jobs/" + state.jobId + "?profile_id=" + encodeURIComponent(state.profile.id)).then(function (job) {
    clear(body);
    var top = h("div", { class: "card" },
      h("div", { class: "row" }, h("button", { type: "button", text: "Back to my jobs", onclick: function () { state.jobId = null; refresh(); } }),
        h("button", { type: "button", class: "small danger", text: "Delete this job", onclick: function () {
          if (!window.confirm(t("Delete this job and your notes and answers?"))) return;
          api("DELETE", "/v1/jobs/" + job.id).then(function () { state.jobId = null; refresh(); }).catch(function (e) { show(out, errBox(e)); });
        } })),
      h("h2", { text: job.title + (job.company ? " - " + job.company : "") }));
    if (job.url) top.appendChild(h("p", null, h("a", { href: job.url, target: "_blank", rel: "noopener noreferrer", text: "Open the job page" })));
    var notes = h("textarea", { id: "j-notes", rows: "3", maxlength: "4000", placeholder: "Your notes: who you spoke to, deadline, follow-up date..." });
    notes.value = job.notes || "";
    top.appendChild(h("label", { for: "st-d", text: "Where are you with this job?" }));
    top.appendChild(statusSelect(job.status, function (v) { api("PATCH", "/v1/jobs/" + job.id, { status: v }).then(function () { refresh(); }).catch(function (e) { show(out, errBox(e)); }); }, "st-d"));
    if (job.status === "applied" || job.follow_up_on) {
      var day = h("input", { type: "date", id: "j-follow", min: dayPlus(0), max: dayPlus(365) });
      day.value = job.follow_up_on || "";
      var mail = h("input", { type: "checkbox", id: "j-remind" }); mail.checked = !!job.remind_email;
      function saveFollow(value, note) {
        api("PATCH", "/v1/jobs/" + job.id, { follow_up_on: value, remind_email: mail.checked }).then(function (r) {
          day.value = r.follow_up_on || ""; show(out, msg("ok", note));
        }).catch(function (e) { show(out, errBox(e)); });
      }
      top.appendChild(h("label", { for: "j-follow", text: "Follow up on" })); top.appendChild(day);
      top.appendChild(h("label", { class: "check", for: "j-remind" }, mail, h("span", { text: "Email me a reminder on that day" })));
      top.appendChild(h("div", { class: "row" },
        h("button", { type: "button", text: "Save follow-up", onclick: function () { saveFollow(day.value, "Follow-up saved."); } }),
        h("button", { type: "button", text: "In 3 days", onclick: function () { saveFollow(dayPlus(3), "Follow-up saved."); } }),
        h("button", { type: "button", text: "In 7 days", onclick: function () { saveFollow(dayPlus(7), "Follow-up saved."); } })));
      if (job.applied_on) top.appendChild(h("p", { class: "muted small", text: "Applied on " + job.applied_on }));
    }
    top.appendChild(h("label", { for: "j-notes", text: "Notes" })); top.appendChild(notes);
    top.appendChild(h("div", { class: "row" }, h("button", { type: "button", text: "Save notes", onclick: function () {
      api("PATCH", "/v1/jobs/" + job.id, { notes: notes.value }).then(function () { show(out, msg("ok", "Notes saved.")); }).catch(function (e) { show(out, errBox(e)); });
    } })));
    top.appendChild(out);
    body.appendChild(top);

    var m = job.match, mc = h("div", { class: "card" }, h("h2", { text: "How your CV matches" }));
    mc.appendChild(h("p", { class: "bigscore", text: m.score + " / 100" }));
    mc.appendChild(h("p", { class: "muted small", text: "Counts only words that are really in your CV lines. It is our own check, not a real company's system." }));
    mc.appendChild(h("h3", { text: "Your CV already shows" }));
    if (!m.covered.length) mc.appendChild(h("p", { class: "muted", text: "Nothing yet." }));
    m.covered.forEach(function (c) { mc.appendChild(h("div", { class: "line" }, h("div", { class: "t", text: c.name + (c.required ? " (required)" : "") }), h("div", { class: "muted small", text: "From your CV: " + c.line }))); });
    mc.appendChild(h("h3", { text: "Not in your CV" }));
    if (!m.missing.length) mc.appendChild(h("p", { class: "muted", text: "Nothing missing." }));
    else mc.appendChild(h("p", { class: "muted small", text: "Add one only if it is true for you: use the line editor in tab 1. Otherwise be honest about it." }));
    m.missing.forEach(function (x) { mc.appendChild(h("div", { class: "line" }, h("div", { class: "t", text: x.name + (x.required ? " (required)" : "") }))); });
    body.appendChild(mc);

    /* cover letter */
    var cout = h("div"), manager = h("input", { type: "text", id: "cl-mgr", placeholder: "Ms Rao (optional)", maxlength: "80" });
    var why = h("textarea", { id: "cl-why", rows: "3", maxlength: "1200", placeholder: "Optional. Your own words: why this company, why this role. It is added as written." });
    var cl = h("div", { class: "card" }, h("h2", { text: "Cover letter" }),
      h("p", { class: "muted small", text: "Built from your CV lines that match this job. It never mentions a skill your CV does not show. You can edit everything." }),
      h("label", { for: "cl-mgr", text: "Hiring manager name" }), manager, h("label", { for: "cl-why", text: "Your own paragraph" }), why);
    cl.appendChild(h("div", { class: "row" }, h("button", { class: "primary", type: "button", text: "Write cover letter", onclick: function () {
      api("POST", "/v1/jobs/" + job.id + "/cover-letter", { profile_id: state.profile.id, why: why.value, manager: manager.value }).then(function (r) {
        clear(cout);
        var box = h("textarea", { id: "cl-text", rows: "18", "aria-label": "Cover letter" }); box.value = r.text;
        cout.appendChild(box);
        if (r.left_out.length) cout.appendChild(h("p", { class: "muted small", text: "Left out because your CV does not show it: " + r.left_out.join(", ") + "." }));
        var note = h("span", { class: "small muted" });
        cout.appendChild(h("div", { class: "row" },
          h("button", { type: "button", text: "Copy", onclick: function () {
            var p = navigator.clipboard && navigator.clipboard.writeText ? navigator.clipboard.writeText(box.value) : Promise.reject();
            p.then(function () { note.textContent = t("Copied."); }).catch(function () { box.select(); note.textContent = t("Press Ctrl+C to copy."); });
          } }),
          h("button", { type: "button", text: "Download (.txt)", onclick: function () { downloadText("cover-letter.txt", box.value); } }), note));
      }).catch(function (e) { show(cout, errBox(e)); });
    } })));
    cl.appendChild(cout); body.appendChild(cl);

    /* interview practice */
    var iout = h("div"), iv = h("div", { class: "card" }, h("h2", { text: "Interview practice" }),
      h("p", { class: "muted small", text: "Questions made from this job and your CV. Write your answers; they are saved here so you can read them before the interview." }));
    iv.appendChild(h("div", { class: "row" }, h("button", { class: "primary", type: "button", text: "Show practice questions", onclick: function () { loadInterview(job.id, iout); } })));
    iv.appendChild(iout); body.appendChild(iv);
  }).catch(function (e) { clear(body); body.appendChild(errBox(e)); body.appendChild(h("button", { type: "button", text: "Back", onclick: function () { state.jobId = null; refresh(); } })); });
}
function loadInterview(jobId, area) {
  api("GET", "/v1/jobs/" + jobId + "/interview?profile_id=" + encodeURIComponent(state.profile.id)).then(function (d) {
    clear(area);
    var boxes = {};
    d.questions.forEach(function (q, i) {
      var ta = h("textarea", { id: "iq-" + i, rows: "4", maxlength: "2000", placeholder: "Your answer" }); ta.value = q.answer || ""; boxes[q.id] = ta;
      var card = h("div", { class: "entry" }, h("div", { class: "muted small", text: (i + 1) + ". " + t(q.kind) }), h("h3", { text: q.question }), h("p", { class: "muted small", text: "Tip: " + q.tip }));
      if (q.cv_line) card.appendChild(h("p", { class: "small", text: "On your CV: " + q.cv_line }));
      card.appendChild(ta); area.appendChild(card);
    });
    var status = h("div");
    area.appendChild(h("div", { class: "row" }, h("button", { class: "primary", type: "button", text: "Save my answers", onclick: function () {
      var answers = {}; Object.keys(boxes).forEach(function (k) { answers[k] = boxes[k].value; });
      api("PUT", "/v1/jobs/" + jobId + "/interview", { profile_id: state.profile.id, answers: answers }).then(function () { show(status, msg("ok", "Answers saved.")); }).catch(function (e) { show(status, errBox(e)); });
    } })));
    area.appendChild(status);
  }).catch(function (e) { show(area, errBox(e)); });
}


/* ---------- Terms, Privacy, FAQ (texts in legal.js) ---------- */
function showLegal(kind) {
  var L = window.LEGAL;
  if (!L || !L[kind]) { history.replaceState(null, "", location.pathname); return start(); }
  var doc = L[kind], page = h("main", { class: "legalpage" });
  page.appendChild(h("button", { type: "button", text: "Back", onclick: function () { history.replaceState(null, "", location.pathname); start(); } }));
  page.appendChild(h("h1", { text: doc.title }));
  page.appendChild(h("div", { class: "msg info", role: "status", text: L.draft }));
  page.appendChild(h("p", { class: "muted", text: doc.intro }));
  (doc.sections || []).forEach(function (sec) {
    page.appendChild(h("h2", { text: sec[0] }));
    sec[1].forEach(function (p) { page.appendChild(h("p", { text: p })); });
  });
  (doc.items || []).forEach(function (qa) {
    page.appendChild(h("h3", { text: qa[0] }));
    page.appendChild(h("p", { text: qa[1] }));
  });
  page.appendChild(h("p", { class: "muted small", text: "Owner: " + L.owner.name + " | " + L.owner.place + " | " + L.owner.email + " | Last updated " + L.owner.updated }));
  page.appendChild(legalLinks());
  show(root, page);
  window.scrollTo(0, 0);
}
function legalLinks(withFeedback) {
  var row = h("p", { class: "legal small" });
  [["Terms of Use", "#terms"], ["Privacy Policy", "#privacy"], ["Refund and Cancellation", "#refunds"], ["Questions and answers", "#faq"]].forEach(function (x, i) {
    if (i) row.appendChild(document.createTextNode(" · "));
    row.appendChild(linkButton(x[0], function () { location.hash = x[1]; }));
  });
  if (withFeedback) {
    row.appendChild(document.createTextNode(" · "));
    row.appendChild(linkButton("Send feedback", function () { state.tab = "help"; state.jobId = null; renderShell(); }));
  }
  return row;
}
function feedbackCard() {
  var kind = h("select", { id: "fb-kind", "aria-label": "Kind" });
  [["idea", "An idea"], ["problem", "A problem"], ["other", "Something else"]].forEach(function (o) { kind.appendChild(h("option", { value: o[0], text: o[1] })); });
  var text = h("textarea", { id: "fb-text", rows: "4", maxlength: "2000", placeholder: "What went wrong, or what would help you? Do not write passwords." });
  var out = h("div");
  var send = h("button", { class: "primary", type: "button", text: "Send feedback", onclick: function () {
    send.disabled = true;
    api("POST", "/v1/feedback", { kind: kind.value, message: text.value, page: state.tab }).then(function () {
      text.value = ""; show(out, msg("ok", "Thank you. We read every message."));
    }).catch(function (e) { show(out, errBox(e)); }).then(function () { send.disabled = false; });
  } });
  return h("div", { class: "card" }, h("h2", { text: "Send feedback" }),
    h("p", { class: "muted small", text: "Found a mistake, or have an idea? Tell us. Only the owner reads it." }),
    h("label", { for: "fb-kind", text: "Kind" }), kind, h("label", { for: "fb-text", text: "Your message" }), text, h("div", { class: "row" }, send), out);
}
function dataCard() {
  return h("div", { class: "card" }, h("h2", { text: "Your data, in plain words" }),
    h("ul", { class: "plain" }, [
      "Only you can see your CV. The owner sees numbers, not CV text.",
      "CVs and jobs are deleted 30 days after you last work on them. You can delete them any time.",
      "The AI sees only numbered CV lines and the job text, and only when you press the AI button.",
      "Download everything or delete your account in the Account tab."
    ].map(function (x) { return h("li", { text: x }); })),
    h("div", { class: "row" }, h("button", { type: "button", text: "Open my account settings", onclick: function () { state.tab = "acct"; renderShell(); } })),
    legalLinks());
}

/* ---------- help: fresher guide, examples, checklist ---------- */
function viewHelp(body) {
  var wrap = h("div", { class: "help" });
  wrap.appendChild(feedbackCard());
  wrap.appendChild(dataCard());
  function list(items, ordered) { return h(ordered ? "ol" : "ul", { class: "plain" }, items.map(function (x) { return h("li", { text: t(x) }); })); }
  wrap.appendChild(h("div", { class: "card" }, h("h2", { text: t("Writing your first CV: 6 steps") }),
    h("p", { class: "muted small", text: t("No experience? That is fine. Employers hiring freshers look at your education, skills and projects.") }),
    list([
      "Details: full name, a professional email (like firstname.lastname@gmail.com), phone, city, and a LinkedIn or GitHub link if you have one.",
      "Summary (optional): one or two lines. Your degree, what you are good at, and the kind of role you want.",
      "Education: latest first. Degree, college, years, and marks if they are good.",
      "Skills: only what you can really do and talk about. Group them, for example Languages, Tools, Databases.",
      "Projects: two or three projects with two or three points each. Say what you built, with which tools, and what came out of it.",
      "More (optional): certifications, achievements, languages you speak."
    ], true),
    h("div", { class: "row" }, h("button", { class: "primary", type: "button", text: t("Build my CV from scratch"), onclick: function () { state.tab = "cv"; state.wizard = wizNew(); refresh(); } }))));

  var ex = h("div", { class: "card" }, h("h2", { text: t("What a strong line looks like") }),
    h("p", { class: "muted small", text: t("These are examples only. Write your own real facts and numbers. Never copy a number that is not true for you.") }));
  [["Worked on testing of web modules", "Tested 12 web modules and logged 40 defects"],
   ["I made a website for college", "Built a college event website with Django; 300 students registered"],
   ["Responsible for database", "Designed a 6-table SQL database and wrote 25 report queries"]].forEach(function (p) {
    ex.appendChild(h("div", { class: "ba" }, h("div", { class: "bad", text: t("Weak") + ": " + t(p[0]) }), h("div", { class: "good", text: t("Stronger") + ": " + t(p[1]) })));
  });
  ex.appendChild(list(["Start with one strong verb: Built, Tested, Designed, Wrote, Improved, Led.", "Add a number: how many, how much, how long. Only if it is true.", "Say the result: what changed because of your work."]));
  wrap.appendChild(ex);

  var sample = h("div", { class: "sample", role: "img", "aria-label": t("Sample CV") });
  sample.appendChild(h("p", { text: "Riya Kulkarni" }));
  sample.appendChild(h("p", { text: "Thane, Maharashtra | riya.k@example.com | +91 90000 00000" }));
  [["EDUCATION", ["MCA, Mumbai University, 2024-2026, CGPA 8.2", "BSc IT, Thane College, 2021-2024, 78%"]],
   ["SKILLS", ["Languages: Python, JavaScript, SQL", "Tools: Django, Git, Selenium, Postman"]],
   ["PROJECTS", ["Event Booking Website | Django, SQLite", "Built booking, login and admin pages; 300 students registered", "Wrote 80 test cases and fixed 25 bugs before launch"]],
   ["EXPERIENCE", ["Software Tester Intern | Acme Technologies | Jun 2025 - Aug 2025", "Tested 12 web modules and logged 40 defects"]]].forEach(function (sec) {
    sample.appendChild(h("h4", { text: t(sec[0]) }));
    sec[1].forEach(function (line) { sample.appendChild(h("p", { text: line })); });
  });
  wrap.appendChild(h("div", { class: "card" }, h("h2", { text: t("Sample CV (made-up person)") }), h("p", { class: "muted small", text: t("Only to show the shape: short sections, real facts, numbers where true.") }), sample));

  wrap.appendChild(h("div", { class: "card" }, h("h2", { text: t("Before you send it: checklist") }), list([
    "One page is enough for a fresher. Two pages at most.",
    "Use a photo only if the job post asks for one.",
    "Same facts everywhere: CV, LinkedIn and what you say in the interview. Companies check.",
    "Never write a skill or a job you do not have. You will be asked about every line.",
    "Read it once aloud to catch spelling mistakes. Ask a friend to read it too.",
    "Save the PDF as FirstName_LastName_CV.pdf. Check the scanner score in tab 2.",
    "For each job, save it in the Jobs tab, see what your CV is missing, and write a cover letter."
  ])));
  show(body, wrap);
}

/* ---------- owner dashboard (staff only) ---------- */
function viewAdmin(body) {
  show(body, h("p", { class: "muted", text: "Loading..." }));
  api("GET", "/v1/admin/stats").then(function (d) {
    clear(body);
    function stat(label, value, note) {
      return h("div", { class: "stat" }, h("div", { class: "num", text: String(value) }), h("div", { class: "muted small", text: label }), note ? h("div", { class: "muted small", text: note }) : null);
    }
    body.appendChild(h("div", { class: "card" }, h("h2", { text: "People" }), h("div", { class: "stats" },
      stat("accounts", d.users.total), stat("new in 24 hours", d.users.new_24h), stat("new in 7 days", d.users.new_7d), stat("email confirmed", d.users.email_verified))));
    body.appendChild(h("div", { class: "card" }, h("h2", { text: "Work" }), h("div", { class: "stats" },
      stat("CVs kept now", d.cvs.active), stat("CVs made in 24 hours", d.cvs.new_24h), stat("jobs saved", d.jobs.saved))));
    var rupees = (d.ai.spent_24h_paise / 100).toFixed(2), cap = (d.ai.budget_paise / 100).toFixed(0);
    body.appendChild(h("div", { class: "card" }, h("h2", { text: "AI" }), h("div", { class: "stats" },
      stat("runs in 24 hours", d.ai.runs_24h, "limit " + d.ai.per_user_limit + " per person per day"), stat("spent in 24 hours (Rs)", rupees, "daily cap Rs " + cap))));
    var err = h("div", { class: "card" }, h("h2", { text: "Errors" }), h("p", { class: "muted small", text: d.errors.count_24h + " in the last 24 hours. Only the page, the error type and a short message are kept, never what the person typed." }));
    if (!d.errors.recent.length) err.appendChild(h("p", { class: "muted", text: "No errors. Good." }));
    d.errors.recent.forEach(function (e) {
      err.appendChild(h("div", { class: "line" }, h("div", { class: "t" }, h("div", { text: e.method + " " + e.path + " - " + e.kind }), h("div", { class: "muted small", text: e.time.replace("T", " ").slice(0, 19) + (e.message ? " - " + e.message : "") }))));
    });
    body.appendChild(err);
  }).catch(function (e) { show(body, errBox(e)); });
}

/* ---------- tab 5: account (email, two-step, passkeys) ---------- */
function viewAccount(body) {
  var u = state.user, out = h("div");
  var emailBox = h("div", { class: "card" }, h("h2", { text: "Email" }),
    h("p", null, u.email, " ", h("span", { class: "badge " + (u.email_verified ? "supported" : "reworded"), text: u.email_verified ? "Confirmed" : "Not confirmed" })));
  if (!u.email_verified) {
    var sent = h("div");
    emailBox.appendChild(h("button", { type: "button", text: "Send confirmation email", onclick: function () {
      show(sent, null);
      api("POST", "/v1/auth/verify/send", {}).then(function (d) { show(sent, msg("ok", d.status)); }).catch(function (e) { show(sent, errBox(e)); });
    } }));
    emailBox.appendChild(sent);
  }
  var plan = h("div", { class: "card" });
  var tfa = h("div", { class: "card" }), pk = h("div", { class: "card" });
  var pw = h("div", { class: "card" }), data = h("div", { class: "card" }), danger = h("div", { class: "card danger-zone" });
  show(body, h("div", null, out, emailBox, plan, pw, tfa, pk, data, danger));
  renderPlan(plan);
  renderPassword(pw);
  renderTwoFactor(tfa);
  renderPasskeys(pk);
  renderMyData(data);
  renderDeleteAccount(danger);
}

function renderPlan(box) {
  box.appendChild(h("h2", { text: "Your plan" }));
  var out = h("div");
  api("GET", "/v1/billing").then(function (d) {
    var line = d.plan === "pro" ? "Pro until " + d.pro_until.slice(0, 10) : d.plan === "free" ? "Free plan" : "Everything is open for now.";
    box.appendChild(h("p", null, h("span", { class: "badge " + (d.plan === "pro" ? "supported" : ""), text: line })));
    box.appendChild(h("p", { class: "muted small", text: "AI tailoring: " + d.limits.ai_per_day + " per day (used " + d.usage.ai_today + " today). Saved jobs: up to " + d.limits.max_jobs + " (you have " + d.usage.jobs + ")." }));
    if (d.enabled) {
      d.plans.forEach(function (p) {
        var b = h("button", { type: "button", class: p.days === 30 ? "primary" : "", text: "Get " + p.label + " for Rs " + p.price_rupees, onclick: function () {
          b.disabled = true;
          api("POST", "/v1/billing/checkout", { plan: p.key }).then(function (r) { window.location.href = r.url; })
            .catch(function (e) { show(out, errBox(e)); b.disabled = false; });
        } });
        box.appendChild(h("div", { class: "row" }, b));
      });
      box.appendChild(h("p", { class: "muted small", text: "You pay on Razorpay's secure page (UPI, card or net banking). We never see your card or UPI details. It does not renew by itself." }));
    } else {
      box.appendChild(h("p", { class: "muted small", text: "Paid plans are not open yet." }));
    }
    if (d.payments.length) {
      box.appendChild(h("h3", { text: "Payments" }));
      d.payments.forEach(function (p) {
        box.appendChild(h("div", { class: "muted small", text: p.date + " | " + p.plan + " | Rs " + p.amount_rupees + " | " + p.status }));
      });
    }
    box.appendChild(h("p", { class: "small" }, linkButton("Refund and Cancellation", function () { location.hash = "#refunds"; })));
  }).catch(function (e) { box.appendChild(errBox(e)); });
  box.appendChild(out);
}

function qrSvg(rows) {  // draws the QR the server computed; SVG built node by node (no markup strings, no inline style)
  var NS = "http://www.w3.org/2000/svg", quiet = 4, n = rows.length, size = n + 2 * quiet;
  var svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 " + size + " " + size);
  svg.setAttribute("class", "qr");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "QR code for your authenticator app");
  svg.setAttribute("shape-rendering", "crispEdges");
  var bg = document.createElementNS(NS, "rect");
  bg.setAttribute("width", size); bg.setAttribute("height", size); bg.setAttribute("fill", "#fff");
  svg.appendChild(bg);
  var d = [];
  rows.forEach(function (row, y) {
    var x = 0;
    while (x < n) {  // one path segment per run of dark modules keeps the SVG small
      if (row.charAt(x) === "1") {
        var start = x;
        while (x < n && row.charAt(x) === "1") x++;
        d.push("M" + (start + quiet) + " " + (y + quiet) + "h" + (x - start) + "v1h-" + (x - start) + "z");
      } else x++;
    }
  });
  var path = document.createElementNS(NS, "path");
  path.setAttribute("d", d.join("")); path.setAttribute("fill", "#000");
  svg.appendChild(path);
  return svg;
}

function renderPassword(box) {
  show(box, null);
  var hasPw = state.user.has_password;
  box.appendChild(h("h2", { text: hasPw ? "Password" : "Set a password" }));
  box.appendChild(h("p", { class: "muted", text: hasPw
    ? "Changing it signs you out on all your other devices."
    : "You signed in without a password. You can add one so you can also log in with your email." }));
  var out = h("div"), cur = null;
  var form = h("form", { class: "stack", autocomplete: "off" });
  if (hasPw) { cur = passwordField("pw-cur", "Current password", "current-password"); form.appendChild(cur.node); }
  var next = passwordField("pw-new", "New password", "new-password");
  form.appendChild(next.node);
  var go = h("button", { type: "submit", class: "primary", text: hasPw ? "Change password" : "Set password" });
  form.appendChild(go);
  form.addEventListener("submit", function (ev) {
    ev.preventDefault(); show(out, null);
    var body = { "new": next.input.value };
    if (cur) body.current = cur.input.value;
    busy(go, go.textContent, function () { return api("POST", "/v1/auth/password", body); })
      .then(function () { state.user.has_password = true; renderPassword(box); box.appendChild(msg("ok", "Password saved.")); })
      .catch(function (e) { show(out, errBox(e)); });
  });
  box.appendChild(form); box.appendChild(out);
}

function renderMyData(box) {
  show(box, null);
  box.appendChild(h("h2", { text: "Your data" }));
  box.appendChild(h("p", { class: "muted", text: "Download everything we keep about you (account, CVs, jobs, results) as one file. Passwords and secret keys are never included." }));
  box.appendChild(h("a", { class: "button", href: "/v1/me/export", download: "resumewise-my-data.json", text: "Download my data" }));
}

function renderDeleteAccount(box) {
  show(box, null);
  box.appendChild(h("h2", { text: "Delete account" }));
  box.appendChild(h("p", { class: "muted", text: "This permanently deletes your account, CVs, jobs and results. It cannot be undone. Download your data first if you want a copy." }));
  var out = h("div"), form = h("form", { class: "stack", autocomplete: "off" });
  var email = textField("del-email", "Type your email to confirm", "email", "off");
  form.appendChild(email.node);
  var pass = null, code = null;
  if (state.user.has_password) { pass = passwordField("del-pw", "Password", "current-password"); form.appendChild(pass.node); }
  if (state.user.totp_enabled) {
    code = h("input", { type: "text", id: "del-code", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "20", required: true });
    form.appendChild(field("del-code", "Code from your authenticator app", code));
  }
  var go = h("button", { type: "submit", class: "danger", text: "Delete my account" });
  form.appendChild(go);
  form.addEventListener("submit", function (ev) {
    ev.preventDefault(); show(out, null);
    var body = { confirm_email: email.input.value };
    if (pass) body.password = pass.input.value;
    if (code) body.code = code.value;
    busy(go, "Delete my account", function () { return api("POST", "/v1/auth/delete", body); })
      .then(function () {
        state = { user: null, profile: null, tab: "cv", templates: [], run: null };
        return api("GET", "/v1/auth/csrf").then(function (d) { csrf = d.csrf; viewLogin(msg("ok", "Your account and data were deleted.")); });
      })
      .catch(function (e) { show(out, errBox(e)); });
  });
  box.appendChild(form); box.appendChild(out);
}

function codePrompt(label, run) {  // small inline form: asks for a code, then runs run(code)
  var out = h("div");
  var code = h("input", { type: "text", inputmode: "numeric", autocomplete: "one-time-code", "aria-label": label, maxlength: "20" });
  var go = h("button", { type: "submit", class: "primary", text: "Confirm" });
  var form = h("form", { class: "row" }, code, go);
  form.addEventListener("submit", function (ev) {
    ev.preventDefault(); show(out, null);
    busy(go, "Confirm", function () { return run(code.value); }).catch(function (e) { show(out, errBox(e)); });
  });
  return h("div", null, h("p", { class: "muted small", text: label }), form, out);
}

function renderTwoFactor(box) {
  var dz = document.querySelector(".danger-zone");
  if (dz) renderDeleteAccount(dz);  // the delete form asks for a code only while 2FA is on
  show(box, null);
  box.appendChild(h("h2", { text: "Two-step verification" }));
  if (state.user.totp_enabled) {
    var area = h("div");
    box.appendChild(h("p", null, h("span", { class: "badge supported", text: "On" }), " Logging in needs a code from your authenticator app."));
    box.appendChild(h("div", { class: "row" },
      h("button", { type: "button", text: "New recovery codes", onclick: function () {
        show(area, codePrompt("Enter a code from your app to get 8 new recovery codes (the old ones stop working).", function (c) {
          return api("POST", "/v1/auth/2fa/recovery", { code: c }).then(function (d) { showRecovery(area, d.recovery_codes, function () { renderTwoFactor(box); }); });
        }));
      } }),
      h("button", { type: "button", class: "danger", text: "Turn off", onclick: function () {
        show(area, codePrompt("Enter a code from your app (or a recovery code) to turn this off.", function (c) {
          return api("POST", "/v1/auth/2fa/disable", { code: c }).then(function () { state.user.totp_enabled = false; renderTwoFactor(box); });
        }));
      } })));
    box.appendChild(area);
    return;
  }
  var area2 = h("div");
  box.appendChild(h("p", { class: "muted", text: "Adds a 6-digit code from an app like Google Authenticator, Microsoft Authenticator or Authy to every password login." }));
  box.appendChild(h("button", { type: "button", class: "primary", text: "Set up", onclick: function () {
    show(area2, null);
    api("POST", "/v1/auth/2fa/setup", {}).then(function (d) {
      show(area2, h("div", null,
        h("p", null, "1. In your authenticator app choose “add account” and scan this QR code:"),
        qrSvg(d.qr),
        h("p", { class: "small muted" }, "Cannot scan? Choose “enter a setup key” and type this key instead:"),
        h("p", null, h("code", { class: "key", text: d.secret.replace(/(.{4})/g, "$1 ").trim() })),
        h("p", { class: "small" }, "On this phone? ", h("a", { href: d.uri, text: "Open it in your authenticator app" }), "."),
        h("p", null, "2. Enter the 6-digit code the app shows now:"),
        codePrompt("Code from the app", function (c) {
          return api("POST", "/v1/auth/2fa/enable", { code: c }).then(function (r) {
            state.user.totp_enabled = true;
            showRecovery(area2, r.recovery_codes, function () { renderTwoFactor(box); });
          });
        })));
    }).catch(function (e) { show(area2, errBox(e)); });
  } }));
  box.appendChild(area2);
}
function showRecovery(area, codes, done) {
  show(area, h("div", { class: "recovery" },
    msg("info", "Save these recovery codes now. Each works once if you lose your phone. They will not be shown again."),
    h("ul", { class: "codes" }, codes.map(function (c) { return h("li", null, h("code", { text: c })); })),
    h("button", { type: "button", class: "primary", text: "I have saved them", onclick: done })));
}

function renderPasskeys(box) {
  show(box, null);
  box.appendChild(h("h2", { text: "Passkeys" }));
  box.appendChild(h("p", { class: "muted", text: "Log in with your fingerprint, face or screen lock. No password to remember or steal." }));
  var list = h("div"), out = h("div");
  box.appendChild(list);
  api("GET", "/v1/auth/passkeys").then(function (d) {
    if (!d.passkeys.length) list.appendChild(h("p", { class: "muted small", text: "No passkeys yet." }));
    d.passkeys.forEach(function (p) {
      list.appendChild(h("div", { class: "line" }, h("span", { class: "t", text: p.name + " · added " + p.created_at.slice(0, 10) + (p.last_used_at ? " · last used " + p.last_used_at.slice(0, 10) : "") }),
        h("button", { type: "button", class: "small danger", text: "Remove", onclick: function () {
          api("DELETE", "/v1/auth/passkeys/" + p.id).then(function () { renderPasskeys(box); }).catch(function (e) { show(out, errBox(e)); });
        } })));
    });
  }).catch(function (e) { show(out, errBox(e)); });
  if (!passkeysSupported()) { box.appendChild(msg("info", "This browser does not support passkeys.")); return; }
  var name = h("input", { type: "text", id: "pkname", maxlength: "60", placeholder: "Name, for example My phone", "aria-label": "Passkey name" });
  var add = h("button", { type: "button", class: "primary", text: "Add a passkey on this device" });
  add.addEventListener("click", function () {
    show(out, null);
    busy(add, "Add a passkey on this device", function () { return passkeyAdd(name.value); })
      .then(function () { renderPasskeys(box); }).catch(function (e) { show(out, errBox(e)); });
  });
  box.appendChild(h("div", { class: "row" }, name, add));
  box.appendChild(out);
}

function logout() {
  api("POST", "/v1/auth/logout", {}).catch(function () {}).then(function () {
    state = { user: null, profile: null, tab: "cv", templates: [], run: null };
    viewLogin();
  });
}

/* ---------- app shell ---------- */
function enterApp() {
  return api("GET", "/v1/profiles").then(function (d) {
    if (d.profiles.length) return loadProfile(d.profiles[0].id);
    state.profile = null;
  }).catch(function () {}).then(renderShell);
}
function loadProfile(id) {
  return api("GET", "/v1/profiles/" + id).then(function (p) { state.profile = p; state.run = null; });
}
function renderShell() {
  var body = h("div", { id: "body" });
  var tabs = h("div", { class: "tabs", role: "tablist" });
  [["cv", "1. My CV"], ["tpl", "2. Templates and download"], ["ai", "3. Tailor to a job"], ["jobs", "4. Jobs"], ["acct", "5. Account"], ["help", "Help"]].concat(state.user.is_staff ? [["admin", "Admin"]] : []).forEach(function (t) {
    tabs.appendChild(h("button", { class: "tab", role: "tab", type: "button", "aria-selected": String(state.tab === t[0]), text: t[1],
      onclick: function () { state.tab = t[0]; state.jobId = null; renderShell(); } }));
  });
  show(root, h("div", null,
    h("div", { class: "bar" }, h("span", { class: "brand", text: "ResumeWise" }),
      h("span", { class: "row" }, langPicker(), h("span", { class: "muted small", text: state.user.name || state.user.email }), h("button", { type: "button", text: "Log out", onclick: logout }))),
    h("div", { class: "wrap" }, verifyBanner(), state.flash || null, tabs, body, legalLinks(true))));
  state.flash = null;
  var on = tabs.querySelector("[aria-selected=true]");
  if (on && on.scrollIntoView) { try { on.scrollIntoView({ inline: "center", block: "nearest" }); } catch (e) { /* old browser */ } }
  if (state.tab === "acct") return viewAccount(body);
  if (state.tab === "help") return viewHelp(body);
  if (state.tab === "admin" && state.user.is_staff) return viewAdmin(body);
  if (state.tab === "cv") viewCv(body);
  else if (!state.profile) show(body, msg("info", "Add your CV first (tab 1)."));
  else if (state.tab === "tpl") viewTemplates(body);
  else if (state.tab === "jobs") viewJobs(body);
  else viewTailor(body);
}
function verifyBanner() {
  if (state.user.email_verified) return null;
  var note = h("span", { class: "small" });
  return h("div", { class: "msg info row" }, h("span", { text: "Please confirm your email. We sent you a link. AI tailoring unlocks after that." }),
    h("button", { type: "button", class: "small", text: "Resend", onclick: function () {
      api("POST", "/v1/auth/verify/send", {}).then(function (d) { note.textContent = t(d.status); }).catch(function (e) { note.textContent = t(e.message); });
    } }), note);
}
function refresh() { renderShell(); }

/* ---------- tab 1: my CV ---------- */
function viewCv(body) {
  if (state.wizard) return viewWizard(body);
  var out = h("div");
  var file = h("input", { type: "file", id: "file", accept: ".pdf,.docx,.txt" });
  var paste = h("textarea", { id: "paste", placeholder: "Or paste your CV text here" });
  var upBtn = h("button", { class: "primary", type: "button", text: "Upload CV", onclick: function () {
    if (!file.files.length) { show(out, msg("err", "Choose a PDF, DOCX or TXT file first.")); return; }
    var fd = new FormData(); fd.append("file", file.files[0]);
    upBtn.disabled = true; show(out, msg("info", "Reading your file..."));
    api("POST", "/v1/profiles/upload", fd).then(function (d) {
      state.profile = null; return loadProfile(d.id).then(function () { state.uploadAts = d.ats; state.uploadOcr = !!d.ocr; refresh(); });
    }).catch(function (e) { show(out, errBox(e)); }).then(function () { upBtn.disabled = false; });
  } });
  var pasteBtn = h("button", { type: "button", text: "Use pasted text", onclick: function () {
    api("POST", "/v1/profiles", { resume_text: paste.value }).then(function (d) {
      return loadProfile(d.id).then(function () { state.uploadAts = null; state.uploadOcr = false; refresh(); });
    }).catch(function (e) { show(out, errBox(e)); });
  } });
  body.appendChild(h("div", { class: "card" }, h("h2", { text: "No CV yet?" }),
    h("p", { class: "muted small", text: "Answer a few simple questions and we build the CV for you. Only your own words are used." }),
    h("button", { class: "primary", type: "button", text: "Build my CV from scratch", onclick: function () { state.wizard = wizNew(); refresh(); } })));
  body.appendChild(h("div", { class: "card" }, h("h2", { text: state.profile ? "Replace with another CV" : "Add your CV" }),
    h("p", { class: "muted small", text: "PDF, DOCX or TXT, up to 2 MB. We keep only the text, not the file. Auto-deleted after 30 days." }),
    h("label", { for: "file", text: "File" }), file, h("div", { class: "row" }, upBtn),
    h("label", { for: "paste", text: "Or paste text" }), paste, h("div", { class: "row" }, pasteBtn), out));
  if (state.profile) {
    if (state.uploadOcr) body.appendChild(msg("info", "This PDF was a scan, so we read it with OCR. OCR can make mistakes (numbers, names, dates). Please check every line below before using it."));
    if (state.uploadAts) body.appendChild(atsCard("How your original file reads to a text scanner", state.uploadAts));
    body.appendChild(contactCard());
    body.appendChild(sectionsCard());
    body.appendChild(historyCard());
    body.appendChild(linkedinCard());
    body.appendChild(h("div", { class: "card" }, h("h3", { text: "Delete my CV" }),
      h("p", { class: "muted small", text: "Removes this CV, its history, photo and any tailoring results." }),
      h("button", { class: "danger", type: "button", text: "Delete this CV", onclick: function () {
        if (!window.confirm(t("Delete this CV and everything linked to it?"))) return;
        api("DELETE", "/v1/profiles/" + state.profile.id).then(function () { state.profile = null; state.uploadAts = null; state.uploadOcr = false; return enterApp(); }).catch(function (e) { window.alert(t(e.message)); });
      } })));
  }
}
function atsCard(title, report) {
  var list = h("ul", { class: "plain" }, report.findings.map(function (f) { return h("li", null, h("div", { text: "[" + t(f.level) + "] " + t(f.message) }), f.fix ? h("div", { class: "small muted", text: t("How to fix: ") + t(f.fix) }) : null); }));
  return h("div", { class: "card" }, h("h3", { text: title }), h("div", { class: "score", text: report.score + " / 100" }),
    report.findings.length ? list : msg("ok", "No problems found."),
    h("p", { class: "muted small", text: "This checks how a simple text scanner reads the CV. It is not a real company's system." }));
}
function contactCard() {
  var c = state.profile.parsed.contact || {};
  var out = h("div");
  var f = {
    name: h("input", { type: "text", id: "c-name", value: c.name || "" }),
    email: h("input", { type: "text", id: "c-email", value: c.email || "" }),
    phone: h("input", { type: "text", id: "c-phone", value: c.phone || "" }),
    location: h("input", { type: "text", id: "c-loc", value: c.location || "" }),
    links: h("input", { type: "text", id: "c-links", value: (c.links || []).join(", ") })
  };
  return h("div", { class: "card" }, h("h2", { text: "Your details" }),
    h("p", { class: "muted small", text: "These go at the top of your CV. Fix anything we guessed wrong." }),
    h("label", { for: "c-name", text: "Name" }), f.name, h("label", { for: "c-email", text: "Email" }), f.email,
    h("label", { for: "c-phone", text: "Phone" }), f.phone, h("label", { for: "c-loc", text: "Location" }), f.location,
    h("label", { for: "c-links", text: "Links (comma separated)" }), f.links,
    h("div", { class: "row" }, h("button", { class: "primary", type: "button", text: "Save details", onclick: function () {
      var links = f.links.value.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
      api("PATCH", "/v1/profiles/" + state.profile.id + "/contact", { name: f.name.value, email: f.email.value, phone: f.phone.value, location: f.location.value, links: links })
        .then(function () { return loadProfile(state.profile.id); }).then(function () { refresh(); })
        .catch(function (e) { show(out, errBox(e)); });
    } })), out);
}
function renderTips(box, tips) {
  clear(box);
  tips.forEach(function (tp) {
    var item = h("div", { class: "tip" }, h("div", { class: "small", text: tp.tip }));
    if (tp.verbs) item.appendChild(h("div", { class: "small muted", text: "Try starting with: " + tp.verbs.join(", ") }));
    (tp.asks || []).forEach(function (q) { item.appendChild(h("div", { class: "small muted", text: "Ask yourself: " + q })); });
    box.appendChild(item);
  });
}
function sectionsCard() {
  var card = h("div", { class: "card" }, h("h2", { text: "Your CV lines" }),
    h("p", { class: "muted small", text: "Edit, remove or add lines. Every change is saved and can be undone from History." }));
  var out = h("div"), tipBoxes = {}, summary = h("div");
  card.appendChild(summary);
  function changed(p) { state.profile.parsed = p.parsed || state.profile.parsed; return loadProfile(state.profile.id).then(refresh); }
  api("GET", "/v1/profiles/" + state.profile.id + "/review").then(function (r) {
    if (r.flagged) summary.appendChild(msg("info", r.flagged + " of " + r.total + " lines could be stronger. Tips are shown under each line. They only ask questions; add a number or detail only if it is true."));
    else if (r.total) summary.appendChild(msg("ok", "Your lines look strong. Nice."));
    if (r.repeated.length) summary.appendChild(h("p", { class: "muted small", text: "Many lines start with the same word (" + r.repeated.join(", ") + "). Vary the first word." }));
    r.lines.forEach(function (l) { if (tipBoxes[l.id]) renderTips(tipBoxes[l.id], l.tips); });
  }).catch(function () { /* tips are optional */ });
  state.profile.parsed.sections.forEach(function (s) {
    var wrap = h("div", { class: "sec" }, h("h3", { text: s.title || s.key }));
    s.items.forEach(function (it) {
      var row = h("div", { class: "line" }), tipBox = h("div", { class: "tips" });
      tipBoxes[it.id] = tipBox;
      function normal() {
        clear(row);
        row.appendChild(h("div", { class: "t", text: it.text }));
        row.appendChild(h("div", { class: "row" },
          h("button", { class: "small", type: "button", text: "Edit", onclick: editing }),
          h("button", { class: "small danger", type: "button", text: "Remove", onclick: function () {
            api("DELETE", "/v1/profiles/" + state.profile.id + "/items/" + encodeURIComponent(it.id)).then(changed).catch(function (e) { show(out, errBox(e)); });
          } })));
      }
      function editing() {
        clear(row);
        var inp = h("input", { type: "text", value: it.text, "aria-label": "Edit line" });
        row.appendChild(h("div", { class: "t" }, inp));
        row.appendChild(h("div", { class: "row" },
          h("button", { class: "small primary", type: "button", text: "Save", onclick: function () {
            api("PATCH", "/v1/profiles/" + state.profile.id + "/items/" + encodeURIComponent(it.id), { text: inp.value }).then(changed).catch(function (e) { show(out, errBox(e)); });
          } }), h("button", { class: "small", type: "button", text: "Cancel", onclick: normal })));
        var timer = null;
        inp.addEventListener("input", function () {  // live tips while typing
          clearTimeout(timer);
          timer = setTimeout(function () {
            api("POST", "/v1/bullets/check", { text: inp.value, section: s.key }).then(function (r) { renderTips(tipBox, r.tips); }).catch(function () {});
          }, 450);
        });
        inp.focus();
      }
      normal(); wrap.appendChild(row); wrap.appendChild(tipBox);
    });
    var add = h("input", { type: "text", placeholder: "Add a line to " + (s.title || s.key), "aria-label": "Add a line" });
    wrap.appendChild(h("div", { class: "row" }, h("div", { class: "grow" }, add),
      h("button", { class: "small", type: "button", text: "Add", onclick: function () {
        if (!add.value.trim()) return;
        api("POST", "/v1/profiles/" + state.profile.id + "/items", { section: s.key, text: add.value }).then(changed).catch(function (e) { show(out, errBox(e)); });
      } })));
    card.appendChild(wrap);
  });
  card.appendChild(out);
  return card;
}
function historyCard() {
  var list = h("div");
  return h("div", { class: "card" }, h("h3", { text: "History (undo)" }),
    h("button", { type: "button", text: "Show history", onclick: function () {
      api("GET", "/v1/profiles/" + state.profile.id + "/versions").then(function (d) {
        clear(list);
        if (!d.versions.length) { list.appendChild(h("p", { class: "muted", text: "No changes yet." })); return; }
        d.versions.forEach(function (v) {
          list.appendChild(h("div", { class: "line" }, h("div", { class: "t", text: new Date(v.created_at).toLocaleString() + " - " + v.reason }),
            h("button", { class: "small", type: "button", text: "Restore this", onclick: function () {
              api("POST", "/v1/profiles/" + state.profile.id + "/versions/" + v.id + "/restore", {}).then(function () { return loadProfile(state.profile.id); }).then(refresh).catch(function (e) { show(list, errBox(e)); });
            } })));
        });
      }).catch(function (e) { show(list, errBox(e)); });
    } }), list);
}

/* ---------- build from scratch (wizard) ---------- */
/* The hints below are only placeholders (grey example text). They are never sent: only what the person types is used. */
var WIZ_STEPS = [
  { key: "contact", title: "Your details", help: "This goes at the top of your CV. Only the name is required." },
  { key: "summary", title: "Summary (optional)", help: "One or two lines about you. Freshers can skip this or write a short career objective." },
  { key: "education", title: "Education", help: "Latest first. Add school, college or courses.", list: "education", add: "Add another education",
    fields: [["degree", "Degree / course", "MCA (Master of Computer Applications)"], ["school", "College / university", "Mumbai University"],
      ["years", "Years", "2024-2026"], ["score", "Marks (optional)", "CGPA 8.2 or 78%"]] },
  { key: "skills", one: "Skill group", title: "Skills", help: "Group them if you like. Only write what you can really do.", list: "skills", add: "Add another group",
    fields: [["group", "Group (optional)", "Languages"], ["items", "Skills, separated by commas", "Python, JavaScript, SQL"]] },
  { key: "projects", one: "Project", title: "Projects", help: "Fresher? Projects matter most. Say what you built and what happened.", list: "projects", add: "Add another project",
    fields: [["title", "Project name", "ResumeWise: resume helper"], ["tech", "Technologies (optional)", "Django, React, SQLite"],
      ["points", "What you did (one point per line)", "Built a parser that splits a CV into sections\nWrote 200 automated tests", true]] },
  { key: "experience", one: "Job", title: "Experience / internships (optional)", help: "No experience yet? Leave this empty and press Next.", list: "experience", add: "Add another job",
    fields: [["role", "Role", "Software Tester Intern"], ["company", "Company", "Acme Technologies, Mumbai"], ["dates", "Dates", "Jun 2025 - Aug 2025"],
      ["points", "What you did (one point per line)", "Tested 12 web modules and logged 40 defects\nWrote test cases in Excel", true]] },
  { key: "extras", title: "More (optional)", help: "One per line. Skip anything you do not have.",
    areas: [["certifications", "Certifications", "Python for Everybody (Coursera, 2025)"], ["achievements", "Achievements", "Won college hackathon 2025"],
      ["languages", "Languages", "English\nHindi\nMarathi"]] },
  { key: "review", title: "Check and create" }
];
function wizNew() {
  return { step: 0, data: { contact: { name: "", email: "", phone: "", location: "", links: "" }, role: "", summary: "",
    education: [{}], skills: [{}], projects: [{}], experience: [{}], certifications: "", achievements: "", languages: "" } };
}
function wizClean(data) {  // drop empty rows, turn text areas into lists
  function rows(list) { return list.filter(function (r) { return Object.keys(r).some(function (k) { return (r[k] || "").trim(); }); }); }
  function lines(t) { return (t || "").split("\n").map(function (x) { return x.trim(); }).filter(Boolean); }
  var out = { contact: data.contact, role: data.role, summary: data.summary };
  ["education", "skills", "projects", "experience"].forEach(function (k) {
    out[k] = rows(data[k]).map(function (r) { var c = {}; Object.keys(r).forEach(function (f) { c[f] = f === "points" ? lines(r[f]) : r[f]; }); return c; });
  });
  ["certifications", "achievements", "languages"].forEach(function (k) { out[k] = lines(data[k]); });
  return out;
}
function viewWizard(body) {
  var w = state.wizard, st = WIZ_STEPS[w.step], out = h("div");
  var dots = h("div", { class: "wiz-steps", "aria-label": "Progress" });
  WIZ_STEPS.forEach(function (x, i) {
    dots.appendChild(h("span", { class: "wiz-dot" + (i === w.step ? " on" : i < w.step ? " done" : ""), text: String(i + 1), title: x.title }));
  });
  var card = h("div", { class: "card" }, dots, h("p", { class: "muted small", text: "Step " + (w.step + 1) + " of " + WIZ_STEPS.length }), h("h2", { text: st.title }));
  if (st.help) card.appendChild(h("p", { class: "muted small", text: st.help }));
  function input(obj, key, label, ph, area, id) {
    var el = area ? h("textarea", { id: id, placeholder: ph, rows: "4" }) : h("input", { type: "text", id: id, placeholder: ph, maxlength: "400" });
    el.value = obj[key] || "";
    el.addEventListener("input", function () { obj[key] = el.value; });
    return [h("label", { for: id, text: label }), el];
  }
  if (st.key === "contact") {
    var c = w.data.contact;
    [input(c, "name", "Full name (required)", "Aarti Sharma", false, "w-name"), input(w.data, "role", "Job title you want (optional)", "Python Developer", false, "w-role"),
      input(c, "email", "Email", "aarti@example.com", false, "w-email"), input(c, "phone", "Phone", "+91 98200 11122", false, "w-phone"),
      input(c, "location", "City", "Thane, Maharashtra", false, "w-loc"), input(c, "links", "Links, separated by commas (LinkedIn, GitHub)", "linkedin.com/in/aarti, github.com/aarti", false, "w-links")
    ].forEach(function (pair) { card.appendChild(pair[0]); card.appendChild(pair[1]); });
  } else if (st.key === "summary") {
    card.appendChild(input(w.data, "summary", "About you", "MCA student who likes building web apps with Python and Django. Looking for a junior developer role.", true, "w-sum").reduce(function (box, n) { box.appendChild(n); return box; }, h("div")));
  } else if (st.list) {
    w.data[st.list].forEach(function (row, i) {
      var box = h("div", { class: "entry" }, h("h3", { text: (st.one || st.title.split(" (")[0]) + " " + (i + 1) }));
      st.fields.forEach(function (f) {
        input(row, f[0], f[1], f[2], f[3], "w-" + st.list + i + f[0]).forEach(function (n) { box.appendChild(n); });
      });
      if (w.data[st.list].length > 1) box.appendChild(h("div", { class: "row" }, h("button", { class: "small danger", type: "button", text: "Remove this one",
        onclick: function () { w.data[st.list].splice(i, 1); refresh(); } })));
      card.appendChild(box);
    });
    card.appendChild(h("div", { class: "row" }, h("button", { type: "button", text: st.add, onclick: function () {
      if (w.data[st.list].length >= 8) { show(out, msg("err", "That is the maximum for this section.")); return; }
      w.data[st.list].push({}); refresh();
    } })));
  } else if (st.areas) {
    st.areas.forEach(function (a) { input(w.data, a[0], a[1], a[2], true, "w-" + a[0]).forEach(function (n) { card.appendChild(n); }); });
  } else {  // review
    var d = wizClean(w.data), n = 0;
    function block(title, lines) {
      if (!lines.length) return;
      n += lines.length;
      card.appendChild(h("div", { class: "sec" }, h("h3", { text: title }), lines.map(function (t) { return h("div", { class: "line" }, h("div", { class: "t", text: t })); })));
    }
    block("Contact", [d.contact.name + (d.role ? " - " + d.role : ""), [d.contact.email, d.contact.phone, d.contact.location, d.contact.links].filter(Boolean).join(" | ")].filter(Boolean));
    block("Summary", d.summary.trim() ? [d.summary.trim()] : []);
    block("Education", d.education.map(function (r) { return [r.degree, r.school, r.years, r.score].filter(Boolean).join(" | "); }));
    block("Skills", d.skills.map(function (r) { return r.group ? r.group + ": " + (r.items || "") : (r.items || ""); }));
    block("Projects", [].concat.apply([], d.projects.map(function (r) { return [[r.title, r.tech].filter(Boolean).join(" | ")].concat(r.points); })));
    block("Experience", [].concat.apply([], d.experience.map(function (r) { return [[r.role, r.company, r.dates].filter(Boolean).join(" | ")].concat(r.points); })));
    block("Certifications", d.certifications); block("Achievements", d.achievements); block("Languages", d.languages);
    if (!d.summary.trim() && n < 1 + 1) card.appendChild(msg("err", "Nothing to build yet. Go Back and add at least your education, a skill or a project."));
    card.appendChild(h("p", { class: "muted small", text: "Only what you typed is used. Nothing is added for you. After creating you can still edit every line, pick a template and download." }));
  }
  var back = h("button", { type: "button", text: "Back", onclick: function () { if (w.step > 0) { w.step--; refresh(); } else { state.wizard = null; refresh(); } } });
  var next;
  if (st.key === "review") {
    next = h("button", { class: "primary", type: "button", text: "Create my CV", onclick: function () {
      next.disabled = true; show(out, msg("info", "Creating your CV..."));
      api("POST", "/v1/profiles/build", wizClean(w.data)).then(function (d) {
        state.wizard = null; state.uploadAts = null; state.uploadOcr = false;
        return loadProfile(d.id).then(function () { state.tab = "tpl"; state.flash = msg("ok", "Your CV is ready. Pick a template, check the preview, then download."); refresh(); });
      }).catch(function (e) { show(out, errBox(e)); next.disabled = false; });
    } });
  } else {
    next = h("button", { class: "primary", type: "button", text: "Next", onclick: function () {
      if (st.key === "contact" && !w.data.contact.name.trim()) { show(out, msg("err", "Please type your name.")); return; }
      w.step++; refresh();
    } });
  }
  card.appendChild(out);
  card.appendChild(h("div", { class: "row wiz-nav" }, back, next, h("button", { class: "link", type: "button", text: "Cancel", onclick: function () {
    if (window.confirm(t("Throw away what you typed?"))) { state.wizard = null; refresh(); } } })));
  body.appendChild(card);
  var touch = window.matchMedia && window.matchMedia("(pointer:coarse)").matches;
  var first = card.querySelector("input,textarea"); if (first && !touch) first.focus();
  if (touch && w.shown !== w.step) window.scrollTo(0, 0);
  w.shown = w.step;
}

/* The CV page is a fixed A4 sheet (794 px wide). On a phone we show the whole sheet scaled down instead of cropping it. */
function mountPreview(box, url) {
  var frame = h("iframe", { class: "preview", src: url, sandbox: "", title: "CV preview" });
  var wrap = h("div", { class: "pvwrap" }, frame);
  function fit() {
    var avail = wrap.parentNode ? wrap.parentNode.clientWidth : 0;
    if (!avail || avail >= 794) { frame.classList.remove("scaled"); frame.style.removeProperty("transform"); wrap.style.removeProperty("height"); return; }
    var k = avail / 794;
    frame.classList.add("scaled");
    frame.style.transform = "scale(" + k.toFixed(4) + ")";
    wrap.style.height = Math.round(1160 * k) + "px";
  }
  show(box, wrap);
  fit();
  window.addEventListener("resize", function onResize() { if (!wrap.isConnected) { window.removeEventListener("resize", onResize); return; } fit(); });
}

function copyButton(getText, note) {
  return h("button", { class: "small", type: "button", text: "Copy", onclick: function () {
    var txt = getText();
    var p = navigator.clipboard && navigator.clipboard.writeText ? navigator.clipboard.writeText(txt) : Promise.reject();
    p.then(function () { note.textContent = t("Copied."); }).catch(function () { note.textContent = t("Press Ctrl+C to copy."); });
  } });
}

/* ---------- share link card (templates tab) ---------- */
function shareCard() {
  var box = h("div"), base = "/v1/profiles/" + state.profile.id + "/share";
  function draw(st) {
    clear(box);
    var tplSel = h("select", { id: "sh-tpl", "aria-label": "Template for the shared page" });
    state.templates.forEach(function (x) { var o = h("option", { value: x.id, text: x.name }); if (x.id === st.template) o.selected = true; tplSel.appendChild(o); });
    var contact = h("input", { type: "checkbox", id: "sh-contact" }); contact.checked = !!st.show_contact;
    var photo = h("input", { type: "checkbox", id: "sh-photo" }); photo.checked = !!st.show_photo;
    var err = h("div");
    function save() {
      return api("PUT", base, { template: tplSel.value, show_contact: contact.checked, show_photo: photo.checked }).then(draw).catch(function (e) { show(err, errBox(e)); });
    }
    var opts = h("div", null,
      h("label", { for: "sh-tpl", text: "Template for the shared page" }), tplSel,
      h("label", { class: "check", for: "sh-contact" }, contact, h("span", { text: "Show my email and phone on the page" })),
      h("label", { class: "check", for: "sh-photo" }, photo, h("span", { text: "Show my photo (only if the template has one)" })));
    if (!st.shared) {
      box.appendChild(h("p", { class: "muted small", text: "Make a private web address for this CV. Anyone who has the address can read it without signing in. Your email, phone and photo stay hidden unless you tick them." }));
      box.appendChild(opts);
      box.appendChild(h("div", { class: "row" }, h("button", { class: "primary", type: "button", text: "Create share link", onclick: save })));
    } else {
      var url = location.origin + st.path;
      var field = h("input", { type: "text", id: "sh-url", readonly: true, "aria-label": "Share link" }); field.value = url;
      var note = h("span", { class: "small muted" });
      box.appendChild(h("label", { for: "sh-url", text: "Your share link" }));
      box.appendChild(field);
      box.appendChild(h("div", { class: "row" }, copyButton(function () { return url; }, note),
        h("a", { class: "btn", href: st.path, target: "_blank", rel: "noopener", text: "Open" }), note));
      box.appendChild(h("p", { class: "muted small", text: "Opened " + st.views + " times." }));
      box.appendChild(opts);
      box.appendChild(h("div", { class: "row" },
        h("button", { class: "small", type: "button", text: "Save options", onclick: save }),
        h("button", { class: "small danger", type: "button", text: "Turn off link", onclick: function () {
          api("DELETE", base).then(draw).catch(function (e) { show(err, errBox(e)); });
        } })));
      box.appendChild(h("p", { class: "muted small", text: "Search engines are told not to list this page. It stops working when you turn it off or when the CV is deleted after 30 days." }));
    }
    box.appendChild(err);
  }
  api("GET", base).then(draw).catch(function (e) { show(box, errBox(e)); });
  return h("div", { class: "card" }, h("h2", { text: "Share your CV with a link" }), box);
}

/* ---------- LinkedIn tips card (my CV tab) ---------- */
function linkedinCard() {
  var out = h("div"), target = h("input", { type: "text", id: "li-target", maxlength: "80", placeholder: "e.g. Junior QA Engineer (optional)" });
  function copyRow(text, label) {
    var note = h("span", { class: "small muted" });
    return h("div", { class: "row" }, copyButton(function () { return text; }, note), note);
  }
  function draw(r) {
    clear(out);
    if (r.headlines.length) {
      out.appendChild(h("h3", { text: "Headline options" }));
      r.headlines.forEach(function (x) {
        out.appendChild(h("div", { class: "line" }, h("div", { class: "t" }, h("div", { class: "muted small", text: x.label }), x.text), copyRow(x.text)));
      });
    }
    if (r.about) {
      var about = h("textarea", { id: "li-about", rows: "10", "aria-label": "About draft" }); about.value = r.about;
      out.appendChild(h("h3", { text: "About draft (from your CV lines only)" }));
      out.appendChild(about);
      out.appendChild(copyRow(r.about));
    }
    if (r.skills.length) {
      out.appendChild(h("h3", { text: "Skills to add" }));
      out.appendChild(h("p", { text: r.skills.join(", ") }));
      out.appendChild(copyRow(r.skills.join(", ")));
    }
    if (r.featured.length) {
      out.appendChild(h("h3", { text: "Featured: your projects" }));
      out.appendChild(h("ul", { class: "plain" }, r.featured.map(function (f) { return h("li", { text: f.title + (f.links.length ? " (" + f.links.join(", ") + ")" : "") }); })));
    }
    out.appendChild(h("h3", { text: "Checklist" }));
    out.appendChild(h("ul", { class: "plain" }, r.checklist.map(function (c) { return h("li", { text: (c.level === "todo" ? "[ ] " : "[i] ") + c.text }); })));
  }
  function load() {
    api("GET", "/v1/profiles/" + state.profile.id + "/linkedin?target=" + encodeURIComponent(target.value)).then(draw).catch(function (e) { show(out, errBox(e)); });
  }
  return h("div", { class: "card" }, h("h2", { text: "LinkedIn profile tips" }),
    h("p", { class: "muted small", text: "Ready text for your LinkedIn profile, made only from your CV. Nothing is invented and no AI is used. Check every line before you paste it." }),
    h("label", { for: "li-target", text: "Role you are aiming for" }), target,
    h("div", { class: "row" }, h("button", { class: "primary", type: "button", text: "Show LinkedIn tips", onclick: load })), out);
}

/* ---------- tab 2: templates ---------- */
function viewTemplates(body) {
  var out = h("div"), previewBox = h("div"), atsBox = h("div"), grid = h("div", { class: "grid" });
  function reloadPreview() {
    var url = "/v1/profiles/" + state.profile.id + "/render?template=" + encodeURIComponent(state.profile.template) + "&t=" + Date.now();
    mountPreview(previewBox, url);
    api("GET", "/v1/profiles/" + state.profile.id + "/ats?template=" + encodeURIComponent(state.profile.template))
      .then(function (r) { show(atsBox, atsCard("Scanner check for this template", r)); }).catch(function (e) { show(atsBox, errBox(e)); });
  }
  function drawCards() {
    clear(grid);
    state.templates.forEach(function (t) {
      var on = t.id === state.profile.template;
      grid.appendChild(h("div", { class: "tpl" + (on ? " on" : "") }, h("h3", { text: t.name }),
        h("p", { class: "small", text: t.description }), h("p", { class: "muted small", text: t.ats_note }),
        h("span", { class: "badge " + (t.photo ? "reworded" : "supported"), text: t.photo ? "With photo" : "No photo" }), " ",
        h("button", { class: "small " + (on ? "" : "primary"), type: "button", disabled: on, text: on ? "Selected" : "Use this", onclick: function () {
          api("PATCH", "/v1/profiles/" + state.profile.id + "/template", { template: t.id }).then(function () { state.profile.template = t.id; drawCards(); reloadPreview(); drawPhoto(); }).catch(function (e) { show(out, errBox(e)); });
        } })));
    });
  }
  var photoBox = h("div");
  function drawPhoto() {
    var t = state.templates.filter(function (x) { return x.id === state.profile.template; })[0];
    clear(photoBox);
    if (!t || !t.photo) return;
    var file = h("input", { type: "file", accept: "image/png,image/jpeg", "aria-label": "Photo" });
    photoBox.appendChild(h("div", { class: "card" }, h("h3", { text: "Your photo" }),
      h("p", { class: "muted small", text: "JPEG or PNG, up to 1 MB. Location and camera data are removed. The photo is never sent to the AI." }),
      file, h("div", { class: "row" },
        h("button", { class: "primary small", type: "button", text: "Upload photo", onclick: function () {
          if (!file.files.length) return;
          var fd = new FormData(); fd.append("photo", file.files[0]);
          api("POST", "/v1/profiles/" + state.profile.id + "/photo", fd).then(function () { state.profile.has_photo = true; reloadPreview(); show(out, msg("ok", "Photo saved.")); }).catch(function (e) { show(out, errBox(e)); });
        } }),
        state.profile.has_photo ? h("button", { class: "small danger", type: "button", text: "Remove photo", onclick: function () {
          api("DELETE", "/v1/profiles/" + state.profile.id + "/photo").then(function () { state.profile.has_photo = false; drawPhoto(); reloadPreview(); }).catch(function (e) { show(out, errBox(e)); });
        } }) : null)));
  }
  var base = "/v1/profiles/" + state.profile.id;
  body.appendChild(h("div", { class: "card" }, h("h2", { text: "Choose a template" }), grid, out));
  body.appendChild(photoBox);
  body.appendChild(h("div", { class: "card" }, h("h2", { text: "Preview and download" }),
    h("div", { class: "row" },
      h("a", { class: "primary", href: base + "/export?format=docx", text: "Download Word (.docx)" }),
      h("a", { class: "btn", href: base + "/render?template=" + encodeURIComponent(state.profile.template), target: "_blank", rel: "noopener", text: "Open to print / save as PDF" })),
    h("p", { class: "muted small", text: "For PDF: open the page, press Ctrl+P and choose Save as PDF." }), previewBox));
  body.appendChild(atsBox);
  function go() { drawCards(); drawPhoto(); reloadPreview(); body.appendChild(shareCard()); }
  if (state.templates.length) go();
  else api("GET", "/v1/templates").then(function (d) { state.templates = d.templates; go(); }).catch(function (e) { show(out, errBox(e)); });
}

/* ---------- tab 3: tailor ---------- */
function viewTailor(body) {
  var out = h("div"), result = h("div"), runsBox = h("div");
  var title = h("input", { type: "text", id: "jt", placeholder: "e.g. Junior QA Engineer" });
  var job = h("textarea", { id: "jd", placeholder: "Paste the job description here (up to 8000 characters)" });
  var go = h("button", { class: "primary", type: "button", text: "Tailor my CV", onclick: function () {
    if (!job.value.trim()) { show(out, msg("err", "Paste a job description first.")); return; }
    go.disabled = true; show(out, msg("info", "Working... this can take up to a minute."));
    api("POST", "/v1/profiles/" + state.profile.id + "/tailor", { job_text: job.value, job_title: title.value })
      .then(function (d) { show(out, null); return openRun(d.run_id); })
      .catch(function (e) { show(out, e.status === 503 ? msg("info", t(e.message) + ". " + t("The site owner needs to add the AI key. Everything else works without it.")) : errBox(e)); })
      .then(function () { go.disabled = false; });
  } });
  function openRun(id) {
    return api("GET", "/v1/runs/" + id).then(function (r) { state.run = r; drawRun(); });
  }
  function drawRun() {
    var r = state.run, base = "/v1/runs/" + r.id;
    clear(result);
    var card = h("div", { class: "card" }, h("h2", { text: "Review the result" }),
      h("p", { class: "muted small", text: "supported = your own line. reworded = same facts, new words. new = not in your CV: confirm only if it is true, or remove it." }));
    var secs = {};
    r.lines.forEach(function (l) {
      if (!secs[l.section]) { secs[l.section] = h("div", { class: "sec" }, h("h3", { text: l.section })); card.appendChild(secs[l.section]); }
      var row = h("div", { class: "line" + (l.decision === "removed" ? " removed" : "") });
      var left = h("div", { class: "t" }, h("span", { class: "badge " + l.label, text: l.label }), " ", l.text);
      if (l.reason) left.appendChild(h("div", { class: "muted small", text: l.reason }));
      var btns = h("div", { class: "row" });
      function decide(d) { return function () { api("PATCH", base + "/claims/" + encodeURIComponent(l.line_ref), { decision: d }).then(function () { return openRun(r.id); }).catch(function (e) { show(out, errBox(e)); }); }; }
      if (l.label === "new") {
        btns.appendChild(h("button", { class: "small" + (l.decision === "confirmed" ? " primary" : ""), type: "button", text: l.decision === "confirmed" ? "Confirmed" : "Confirm (it is true)", onclick: decide("confirmed") }));
        btns.appendChild(h("button", { class: "small danger", type: "button", text: l.decision === "removed" ? "Removed" : "Remove", onclick: decide("removed") }));
      } else {
        btns.appendChild(h("button", { class: "small", type: "button", text: l.decision === "removed" ? "Put back" : "Remove", onclick: decide(l.decision === "removed" ? "pending" : "removed") }));
      }
      row.appendChild(left); row.appendChild(btns); secs[l.section].appendChild(row);
    });
    if (r.gaps && r.gaps.length) {
      card.appendChild(h("div", { class: "sec" }, h("h3", { text: "Requirements your CV does not show" }),
        h("ul", { class: "plain" }, r.gaps.map(function (g) { return h("li", { text: g.requirement + ": " + g.advice }); }))));
    }
    result.appendChild(card);
    var exp = h("div", { class: "card" }, h("h2", { text: "Export" }));
    if (!r.can_export) {
      exp.appendChild(msg("info", r.pending.length + " new line(s) need your decision before you can export."));
    } else {
      exp.appendChild(h("div", { class: "row" },
        h("a", { class: "primary", href: base + "/export?format=docx", text: "Download Word (.docx)" }),
        h("a", { class: "btn", href: base + "/render?template=" + encodeURIComponent(state.profile.template), target: "_blank", rel: "noopener", text: "Open to print / save as PDF" })));
      var atsOut = h("div");
      exp.appendChild(h("div", { class: "row" }, h("button", { type: "button", text: "Check scanner readability", onclick: function () {
        api("GET", base + "/ats?template=" + encodeURIComponent(state.profile.template)).then(function (a) { show(atsOut, atsCard("Scanner check of the tailored CV", a)); }).catch(function (e) { show(atsOut, errBox(e)); });
      } })));
      exp.appendChild(atsOut);
    }
    result.appendChild(exp);
  }
  body.appendChild(h("div", { class: "card" }, h("h2", { text: "Tailor your CV to a job" }),
    h("p", { class: "muted small", text: "The AI only rewords what is already in your CV. Your name, contact details and photo are never sent to it." }),
    h("label", { for: "jt", text: "Job title (optional)" }), title, h("label", { for: "jd", text: "Job description" }), job,
    h("div", { class: "row" }, go), out));
  body.appendChild(result);
  body.appendChild(h("div", { class: "card" }, h("h3", { text: "Earlier results" }), runsBox));
  api("GET", "/v1/profiles/" + state.profile.id + "/runs").then(function (d) {
    if (!d.runs.length) { show(runsBox, h("p", { class: "muted", text: "None yet." })); return; }
    clear(runsBox);
    d.runs.forEach(function (r) {
      runsBox.appendChild(h("div", { class: "line" }, h("div", { class: "t", text: (r.job_title || "Untitled job") + " - " + new Date(r.created_at).toLocaleString() + " (" + r.status + ")" }),
        h("button", { class: "small", type: "button", text: "Open", onclick: function () { openRun(r.id).catch(function (e) { show(out, errBox(e)); }); } })));
    });
  }).catch(function () {});
  if (state.run) drawRun();
}

start();
