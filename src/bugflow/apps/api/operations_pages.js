"use strict";
// What every operations page shares: how it shows money, moments,
// tables and allowances, and how it signs a person in and reads a
// route. A page loads ../sign-in.js and then this, and calls
// openPage(path, render), where render(held) shows what the route answered.

function say(text) { document.getElementById("message").textContent = text; }

function showSignIn() {
  document.getElementById("signedin").hidden = true;
  document.getElementById("signedout").hidden = false;
}

function element(tag, className, text) {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (text !== undefined) made.textContent = text;
  return made;
}

function link(text, href) {
  const made = element("a", "", text);
  made.href = href;
  return made;
}

function dollars(usd) {
  if (usd === null || usd === undefined) return "";
  return "$" + usd.toFixed(usd !== 0 && Math.abs(usd) < 0.01 ? 6 : 2);
}

function when(at) {
  return at ? new Date(at).toISOString().replace("T", " ").slice(0, 19) + "Z"
            : "";
}

function day(at) { return new Date(at).toISOString().slice(0, 10); }

function heading(table, names) {
  const row = table.insertRow();
  names.forEach(([name, className]) => {
    row.append(element("th", className || "", name));
  });
}

// Add a cell for each [value, className]; a value is text or a node.
function cells(row, values) {
  values.forEach(([value, className]) => {
    const cell = element("td", className || "");
    if (value instanceof Node) cell.append(value);
    else cell.textContent = value;
    row.append(cell);
  });
}

function empty(table, text) {
  table.insertRow().append(element("td", "muted", text));
}

// A layer or an agent as a cell shows it, where empty names none.
function named(value) { return [value || "none", value ? "" : "muted"]; }

function scopeName(scope) {
  const parts = [];
  if (scope.repo) parts.push(scope.forge + ":" + scope.repo);
  else if (scope.owner) parts.push(scope.forge + ":" + scope.owner + "/*");
  else if (scope.forge) parts.push(scope.forge);
  if (scope.layer) parts.push("layer " + scope.layer);
  if (scope.agent_id) parts.push("agent " + scope.agent_id);
  return parts.join(", ") || "everything";
}

// This page's address with some parameters changed; null removes one.
function here(changes, anchor) {
  const params = new URLSearchParams(location.search);
  Object.entries(changes).forEach(([key, value]) => {
    value === null ? params.delete(key) : params.set(key, value);
  });
  return "?" + params + (anchor ? "#" + anchor : "");
}

// The repository page's address for one repository, with any of its
// parameters.
function repositoryPage(forge, repo, more) {
  return "repository?" + new URLSearchParams(
    Object.assign({ forge, repo }, more || {}));
}

function renderAllowances(table, allowances, none) {
  table.replaceChildren();
  if (!allowances.length) {
    empty(table, none);
    return;
  }
  heading(table, [["Scope"], ["Per"], ["Period measured"],
                  ["Allowed", "num"], ["Spent", "num"], ["Left", "num"],
                  ["Room"]]);
  allowances.forEach(one => {
    const row = table.insertRow();
    const period = one.since
      ? when(one.since) + " to " + when(one.until)
      : one.unmeasured;
    const room = one.has_room === null ? element("td", "muted", "unmeasured")
      : one.has_room ? element("td", "ok", "has room")
      : element("td", "bad", one.over_usd > 0
          ? "over by " + dollars(one.over_usd) : "spent");
    cells(row, [[scopeName(one.scope)], [one.per], [period],
                [one.allowed_usd === null ? "no limit"
                                          : dollars(one.allowed_usd), "num"],
                [dollars(one.spent_usd), "num"],
                [dollars(one.left_usd), "num"]]);
    row.append(room);
  });
}

// Fill the period form from what was read, and read another period
// when it is sent. A period ends at the midnight after its last day.
function choosePeriod(held) {
  document.getElementById("since").value = day(held.since);
  document.getElementById("until").value = day(new Date(held.until) - 1);
  document.getElementById("period").addEventListener("submit", event => {
    event.preventDefault();
    const since = document.getElementById("since").value;
    const through = new Date(document.getElementById("until").value +
                             "T00:00:00Z");
    through.setUTCDate(through.getUTCDate() + 1);
    location.assign(here({ since: since + "T00:00:00Z",
                           until: through.toISOString() }));
  });
}

// The period this page's address names, as a route's query takes it.
function periodQuery(params) {
  const query = new URLSearchParams();
  ["since", "until"].forEach(key => {
    if (params.has(key)) query.set(key, params.get(key));
  });
  return query;
}

// Sign in if need be, read the route at path, and show it.
async function openPage(path, render) {
  document.getElementById("signin").addEventListener("click", () =>
    signIn().catch(error => say(error.message)));
  try {
    if (!fetched(TOKEN)) {
      showSignIn();
      return;
    }
    const held = await api("GET", path);
    document.getElementById("signedout").hidden = true;
    document.getElementById("signedin").hidden = false;
    render(held);
    if (location.hash) {
      document.getElementById(location.hash.slice(1))?.scrollIntoView();
    }
  } catch (error) {
    say(error.message);
  }
}

// What a spend row's runs are, as a sentence names them.
function rowName(layer, agent) {
  if (!layer && !agent) return "facts naming no layer or agent";
  return [layer ? "layer " + layer : "no layer",
          agent ? "agent " + agent : "no agent"].join(", ");
}

// List runs, latest first, each opening its own page. Runs that name
// their repository show it.
function renderRunList(table, runs, none) {
  table.replaceChildren();
  if (!runs.length) {
    empty(table, none);
    return;
  }
  const repositories = runs[0].repo !== undefined;
  heading(table, [["Last fact"]].concat(
    repositories ? [["Repository"]] : [],
    [["Workflow"], ["Run"], ["Spent", "num"], ["Facts", "num"]]));
  runs.forEach(one => {
    cells(table.insertRow(), [[when(one.last), "mono"]].concat(
      repositories ? [[link(one.forge + ":" + one.repo,
                            repositoryPage(one.forge, one.repo))]] : [],
      [[one.workflow_id, "mono"],
       [link(one.run_id, "run?" + new URLSearchParams({
          workflow: one.workflow_id, run: one.run_id })), "mono"],
       [dollars(one.usd), "num"], [String(one.facts), "num"]]));
  });
}
