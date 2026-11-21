"use strict";
// Signing a person in, for every page this server serves.
//
// A page loads this from the server's root and defines two functions:
// say(text), which shows a message, and showSignIn(), which shows the
// way to sign in. Every page signs in through the settings page's
// client and its address, the one redirect address the operator
// registers, and the settings page sends the person back to the page
// they started from.
//
// While the person holds a token, the page's nav ends with their
// account: a button with their initials and name, which opens a panel
// saying who the tokens name, when the token expires and which roles
// this server finds in it, as GET api/me answers. The panel's link signs
// them out: it forgets the tokens and ends their session at the identity
// provider, which sends them back to the settings page, the address the
// operator registers for after a sign-out. Signing in again then asks
// the provider afresh, so a token taken out before a role was granted
// is replaced by one that carries it.

const ROOT = new URL(".", document.currentScript.src);
const TOKEN = "bugflow.settings.token";
const ID_TOKEN = "bugflow.settings.id_token";
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
  const tokens = await answered.json();
  store(TOKEN, tokens.access_token);
  store(ID_TOKEN, tokens.id_token || null);
  showAccount();
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
    showAccount();
    showSignIn();
    throw new Error("sign in again: the token was not accepted");
  }
  if (!answered.ok) {
    const detail = await answered.json().catch(() => ({}));
    throw new Error(detail.detail || ("the server answered " + answered.status));
  }
  return answered.json();
}

// Forget the token and end the person's session at the identity
// provider, which sends them back to the settings page. A provider that
// names no end of session is skipped: the token is forgotten all the
// same, and the settings page offers to sign in.
async function signOut() {
  const hint = fetched(ID_TOKEN);
  store(TOKEN, null);
  store(ID_TOKEN, null);
  showAccount();
  const { config, discovery } = await provider();
  if (!discovery.end_session_endpoint) {
    location.assign(redirectUri());
    return;
  }
  const query = new URLSearchParams({
    client_id: config.client_id,
    post_logout_redirect_uri: redirectUri(),
  });
  if (hint) query.set("id_token_hint", hint);
  location.assign(discovery.end_session_endpoint + "?" + query);
}

// The claims a token carries, or none where it is not a JWT.
function claimsOf(token) {
  try {
    const part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(part + "=".repeat((4 - part.length % 4) % 4));
    const bytes = Uint8Array.from(raw, c => c.charCodeAt(0));
    return JSON.parse(new TextDecoder().decode(bytes)) || {};
  } catch (e) {
    return {};
  }
}

// The person's name, from the ID token where it says, then their
// username, then the access token's subject.
function nameOf(id, access) {
  const given = [id.given_name, id.family_name].filter(Boolean).join(" ");
  return id.name || given || id.preferred_username || access.sub || "Signed in";
}

// Up to two initials: the first letters of the name's first and last
// words.
function initialsOf(name) {
  const words = name.split(/[\s@._-]+/).filter(Boolean);
  if (!words.length) return "?";
  const first = Array.from(words[0])[0];
  const last = words.length > 1 ? Array.from(words[words.length - 1])[0] : "";
  return (first + last).toUpperCase();
}

function part(tag, className, text) {
  const one = document.createElement(tag);
  if (className) one.className = className;
  if (text !== undefined) one.textContent = text;
  return one;
}

// Fill the panel's facts: what the tokens say at once, then what the
// server reads from the access token when it answers.
async function fillAccount(facts) {
  const access = claimsOf(fetched(TOKEN) || "");
  const id = claimsOf(fetched(ID_TOKEN) || "");
  const fact = (term, value) => {
    facts.append(part("dt", "", term), part("dd", "", value));
  };
  facts.replaceChildren();
  if (id.preferred_username) fact("Username", id.preferred_username);
  if (access.iss || id.iss) fact("Issuer", access.iss || id.iss);
  if (access.exp) fact("Expires", new Date(access.exp * 1000).toLocaleString());
  const roles = part("dd", "", "reading…");
  facts.append(part("dt", "", "Roles here"), roles);
  try {
    const me = await api("GET", "api/me");
    fact("Subject", me.subject);
    fact("Client", me.client);
    roles.textContent = me.roles.length ? me.roles.join(", ")
                                        : "none this server reads";
  } catch (error) {
    roles.textContent = error.message;
  }
}

// End the page's nav with the person's account while a token is held,
// and take it and its panel away when none is.
function showAccount() {
  let account = document.getElementById("account");
  if (!fetched(TOKEN)) {
    if (account) account.remove();
    document.getElementById("account-panel")?.remove();
    return;
  }
  const nav = document.querySelector("nav");
  if (account || !nav) return;
  const access = claimsOf(fetched(TOKEN));
  const id = claimsOf(fetched(ID_TOKEN) || "");
  const name = nameOf(id, access);
  account = part("div", "account");
  account.id = "account";
  const button = part("button", "account-button");
  button.type = "button";
  button.setAttribute("popovertarget", "account-panel");
  button.setAttribute("aria-label", "Account: " + name);
  button.append(part("span", "avatar", initialsOf(name)),
                part("span", "account-name", name));
  const panel = part("div", "account-panel");
  panel.id = "account-panel";
  panel.setAttribute("popover", "");
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", "Account");
  const head = part("div", "account-head");
  head.append(part("span", "avatar", initialsOf(name)), part("strong", "", name));
  const facts = part("dl", "facts");
  const signOutLink = part("a", "account-signout", "Sign out");
  signOutLink.id = "signout";
  signOutLink.href = redirectUri();
  signOutLink.addEventListener("click", event => {
    event.preventDefault();
    signOut().catch(error => say(error.message));
  });
  panel.append(head, facts, signOutLink);
  panel.addEventListener("toggle", event => {
    if (event.newState === "open") fillAccount(facts);
  });
  // The panel is the body's, not the nav's, so a theme's rules for the
  // nav's links do not reach it.
  account.append(button);
  nav.append(account);
  document.body.append(panel);
}

showAccount();
