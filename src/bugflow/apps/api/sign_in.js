"use strict";
// Signing a person in, for every page this server serves.
//
// A page loads this from the server's root and defines two functions:
// say(text), which shows a message, and showSignIn(), which shows the
// way to sign in. Every page signs in through the settings page's
// client and its address, the one redirect address the operator
// registers, and the settings page sends the person back to the page
// they started from.

const ROOT = new URL(".", document.currentScript.src);
const TOKEN = "bugflow.settings.token";
const VERIFIER = "bugflow.settings.verifier";
const STATE = "bugflow.settings.state";
const RETURN = "bugflow.settings.return";

function store(key, value) {
  try { value === null ? sessionStorage.removeItem(key)
                       : sessionStorage.setItem(key, value); }
  catch (e) { /* a page without storage signs in each time */ }
}
function fetched(key) {
  try { return sessionStorage.getItem(key); } catch (e) { return null; }
}

function random(bytes) {
  const raw = crypto.getRandomValues(new Uint8Array(bytes));
  return base64url(raw);
}
function base64url(raw) {
  return btoa(String.fromCharCode(...new Uint8Array(raw)))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
async function challenge(verifier) {
  const digest = await crypto.subtle.digest(
    "SHA-256", new TextEncoder().encode(verifier));
  return base64url(digest);
}

async function provider() {
  const answered = await fetch(new URL("settings/config", ROOT));
  if (!answered.ok) {
    throw new Error("this server's pages have no sign-in client: " +
                    "its operator sets SETTINGS_CLIENT_ID");
  }
  const config = await answered.json();
  const discovery = await (await fetch(
    config.issuer.replace(/\/$/, "") + "/.well-known/openid-configuration"
  )).json();
  return { config, discovery };
}

// The settings page's address, where every sign-in comes back to.
function redirectUri() {
  return new URL("settings", ROOT).href;
}

async function signIn() {
  const { config, discovery } = await provider();
  const verifier = random(48), state = random(16);
  store(VERIFIER, verifier);
  store(STATE, state);
  store(RETURN, location.href);
  const query = new URLSearchParams({
    response_type: "code",
    client_id: config.client_id,
    redirect_uri: redirectUri(),
    scope: config.scope,
    state,
    code_challenge: await challenge(verifier),
    code_challenge_method: "S256",
  });
  location.assign(discovery.authorization_endpoint + "?" + query);
}

// Finish a sign-in the identity provider came back from. Returns true
// when the person is being sent on to the page they started from.
async function finishSignIn(params) {
  const state = fetched(STATE), verifier = fetched(VERIFIER);
  if (!state || !verifier || params.get("state") !== state) {
    history.replaceState(null, "", redirectUri());
    throw new Error("the sign-in came back with a state this page did not send");
  }
  const { config, discovery } = await provider();
  const answered = await fetch(discovery.token_endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code: params.get("code"),
      redirect_uri: redirectUri(),
      client_id: config.client_id,
      code_verifier: verifier,
    }),
  });
  if (!answered.ok) throw new Error("the identity provider refused the sign-in");
  store(TOKEN, (await answered.json()).access_token);
  store(VERIFIER, null);
  store(STATE, null);
  const back = fetched(RETURN);
  store(RETURN, null);
  if (back && new URL(back).pathname !== new URL(redirectUri()).pathname) {
    location.assign(back);
    return true;
  }
  history.replaceState(null, "", redirectUri());
  return false;
}

// Call the server's API at a path from its root.
async function api(method, path, body) {
  const answered = await fetch(new URL(path, ROOT), {
    method,
    headers: Object.assign(
      { Authorization: "Bearer " + fetched(TOKEN) },
      body ? { "Content-Type": "application/json" } : {}),
    body: body ? JSON.stringify(body) : undefined,
  });
  if (answered.status === 401) {
    store(TOKEN, null);
    showSignIn();
    throw new Error("sign in again: the token was not accepted");
  }
  if (!answered.ok) {
    const detail = await answered.json().catch(() => ({}));
    throw new Error(detail.detail || ("the server answered " + answered.status));
  }
  return answered.json();
}
