/* Optional sign-in with GitHub, your own Nebius key, and a short history of your cases.
   Anonymous use works exactly as before; nothing here is needed to convene the jury.
   The server keeps no accounts: credentials live in encrypted httpOnly cookies this script
   cannot read, and the case history lives in this browser's localStorage. See /privacy.html. */
(() => {
  const CASES = "pj_cases";
  const MAX_CASES = 12;
  const avatarUrl = (u) => (/^https:\/\/avatars\.githubusercontent\.com\//.test(String(u || "")) ? safeUrl(u) : "");

  async function call(method, path, body) {
    const res = await fetch(path, {
      method,
      headers: body ? { "content-type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
    return data;
  }

  /* ---------- who is here ---------- */

  async function loadMe() {
    let me;
    try { me = await call("GET", "/api/me"); } catch { return; }
    $("account").hidden = !me.auth;
    $("signin").hidden = !!me.user;
    $("me").hidden = !me.user;
    if (me.user) {
      $("me-login").textContent = me.user.login;
      const src = avatarUrl(me.user.avatar);
      if (src) $("me-avatar").src = src; else $("me-avatar").hidden = true;
      loadRepos();
    }
    $("credit-state").textContent = me.byok ? "your key" : "demo";
    $("byok-clear").hidden = !me.byok;
    $("byok-open").textContent = me.byok ? "Your Nebius key is in use" : "Use your own Nebius key";
  }

  async function loadRepos() {
    try {
      const { repos } = await call("GET", "/api/me/repos");
      $("my-repos").innerHTML = repos.map((r) => `<option value="${safe(r.url)}">${safe(r.name)}</option>`).join("");
      if (repos.length) $("composer-hint").textContent =
        "Pick one of your public repositories from the list, or paste any public GitHub address. About two minutes.";
    } catch (err) {
      // the list is a convenience; pasting still works. A revoked sign-in is shown as signed out.
      if (/expired/.test(err.message)) loadMe();
    }
  }

  $("signout").addEventListener("click", async () => {
    try { await call("POST", "/api/auth/logout"); } finally { location.href = "/"; }
  });

  /* ---------- bring your own key ---------- */

  $("byok-open").addEventListener("click", () => {
    $("byok-form").hidden = !$("byok-form").hidden;
    if (!$("byok-form").hidden) $("byok-key").focus();
  });

  $("byok-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const key = $("byok-key").value.trim();
    $("byok-key").value = "";  // never left sitting in the page
    if (!key) return;
    $("byok-note").textContent = "Checking the key with Nebius…";
    try {
      await call("POST", "/api/byok", { key });
      $("byok-note").textContent = "Your key is in use. Model calls of your runs now bill to it.";
      loadMe();
    } catch (err) {
      $("byok-note").textContent = err.message;
    }
  });

  $("byok-clear").addEventListener("click", async () => {
    await call("DELETE", "/api/byok").catch(() => null);
    $("byok-note").textContent = "Back on the demo credits. The key is gone from this browser.";
    loadMe();
  });

  /* ---------- your cases, in this browser only ---------- */

  const readCases = () => { try { return JSON.parse(localStorage.getItem(CASES) || "[]"); } catch { return []; } };

  window.saveCase = (target, result) => {
    if (!result) return;
    const entry = {
      target, name: result.name, at: new Date().toISOString(), findings: result.findings,
      claims: (result.claims || []).map((c) => ({
        title: c.title, verdict: c.verdict, kind: c.proof_kind, file: c.file,
        known: c.known && c.known.status ? { status: c.known.status, url: (c.known.ref || {}).url || "" } : null,
      })),
    };
    try { localStorage.setItem(CASES, JSON.stringify([entry, ...readCases()].slice(0, MAX_CASES))); } catch { /* full or blocked */ }
    renderHistory();
  };

  function renderHistory() {
    const cases = readCases();
    $("history-box").hidden = !cases.length;
    $("history").innerHTML = cases.map((c, i) => `
      <li><button class="case" type="button" data-i="${i}">
        <b>${safe(c.name || c.target)}</b>
        <i>${safe(new Date(c.at).toLocaleDateString())} · ${c.claims.filter((x) => x.verdict === "REPRODUCED").length} confirmed</i>
      </button></li>`).join("") +
      (cases.length ? `<li><button class="linkish" id="history-clear" type="button">Clear this list</button></li>` : "");
    document.querySelectorAll("#history .case").forEach((b) =>
      b.addEventListener("click", () => showCase(cases[Number(b.dataset.i)])));
    const clear = $("history-clear");
    if (clear) clear.addEventListener("click", () => { localStorage.removeItem(CASES); renderHistory(); });
  }

  function showCase(c) {
    setMode("repo");
    clearTimeline();
    $("target").value = c.target;
    const label = { REPRODUCED: "CONFIRMED", NOT_REPRODUCED: "FALSE ALARM", UNVERIFIED: "NEEDS A HUMAN" };
    const s = step("&#9634;", safe(c.name || c.target),
      `${safe(new Date(c.at).toLocaleString())} · ${c.findings} findings became ${c.claims.length} claims. ` +
      "A summary kept in this browser — press Convene the jury to run it again.");
    const list = document.createElement("div");
    list.className = "claims";
    list.innerHTML = c.claims.map((x) => `
      <article class="claim ${x.verdict === "REPRODUCED" ? "reproduced" : ""}">
        <div class="claim-head"><h3>${safe(x.title)}</h3>
          <span class="chip ${safe(String(x.verdict || "").toLowerCase())}">${safe(
            x.verdict === "REPRODUCED" && x.kind === "dynamic" ? "CONFIRMED · RAN IT" : label[x.verdict] || x.verdict)}</span></div>
        <p class="where">${safe(x.file)}</p>
        ${x.known ? `<p class="upstream ${safe(x.known.status)}">upstream: ${safe(x.known.status)}${x.known.url
          ? ` · <a href="${safeUrl(x.known.url)}" target="_blank" rel="noreferrer noopener">link</a>` : ""}</p>` : ""}
      </article>`).join("");
    s.body.appendChild(list);
    s.done();
  }

  if (new URLSearchParams(location.search).get("signin") === "failed") {
    fail("GitHub sign-in did not complete. You can keep using Polyjury without it.");
    history.replaceState(null, "", "/");
  }
  renderHistory();
  loadMe();
})();
