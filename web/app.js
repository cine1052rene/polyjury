(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const MIN_QUOTE = 15;   // mirrors the server rule (characters, spaces ignored)
  const MIN_REASON = 10;
  const state = {
    lang: loadPref("fd-lang", "en"),
    city: null,
    cities: [],
    caseData: null,
    suspectId: null,
    evidence: null,
    results: [],
    queries: [],
    opened: [],
    startedAt: Date.now(),
    done: false,
  };

  function loadPref(key, fallback) {
    try { return localStorage.getItem(key) || fallback; } catch { return fallback; }
  }
  function savePref(key, value) {
    try { localStorage.setItem(key, value); } catch { /* storage unavailable */ }
  }
  function t(key, ...args) {
    const v = (window.I18N[state.lang] || window.I18N.en)[key] ?? window.I18N.en[key] ?? key;
    return typeof v === "function" ? v(...args) : v;
  }
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else if (v !== undefined && v !== null && v !== false) node.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) {
      if (c !== null && c !== undefined) node.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return node;
  }
  async function api(path, body) {
    const res = await fetch(path, body ? {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    } : undefined);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const d = data.detail;
      const err = new Error(d && d.code ? (t(`err_${d.code}`) || d.message) : (typeof d === "string" ? d : t("error")));
      err.code = d && d.code;
      throw err;
    }
    return data;
  }
  function fmtDate(value) {
    if (!value) return t("unknownDate");
    const d = new Date(value);
    return isNaN(d) ? value : d.toLocaleDateString(state.lang === "ko" ? "ko-KR" : "en-GB",
      { year: "numeric", month: "short", day: "numeric" });
  }
  const compact = (s) => (s || "").replace(/\s+/g, "");
  const verdictKey = () => `fd-verdict-${state.caseData && state.caseData.id}`;

  // ---- static text -------------------------------------------------------
  function applyI18n() {
    document.documentElement.lang = state.lang;
    document.querySelectorAll("[data-i18n]").forEach((node) => { node.textContent = t(node.dataset.i18n); });
    $("lang-toggle").textContent = state.lang === "en" ? "한국어" : "English";
    $("search-input").placeholder = state.lang === "en" ? "e.g. tube closures" : "예: 운행 중단";
    $("quote-input").placeholder = t("quotePlaceholder");
    $("reason-input").placeholder = t("reasonPlaceholder");
    renderCityTabs();
    renderRequirements();
    if (state.caseData) renderCase();
    if (state.evidence) renderEvidence();
  }

  // ---- cities & case -----------------------------------------------------
  function renderCityTabs() {
    $("city-tabs").replaceChildren(...state.cities.map((c) => el("button", {
      type: "button", class: `tab${c.id === state.city ? " active" : ""}`,
      "aria-pressed": String(c.id === state.city), disabled: !c.case_date,
      onclick: () => selectCity(c.id),
    }, state.lang === "ko" ? c.name_local : c.name)));
  }

  async function selectCity(cityId) {
    if (state.city === cityId && state.caseData) return;
    Object.assign(state, { city: cityId, caseData: null, suspectId: null, evidence: null,
      results: [], queries: [], opened: [], startedAt: Date.now(), done: false });
    savePref("fd-city", cityId);
    renderCityTabs();
    $("case-title").textContent = t("loading");
    ["case-setup", "case-brief", "case-meta", "search-status", "accuse-error"].forEach((id) => { $(id).textContent = ""; });
    $("suspects").replaceChildren();
    $("results").replaceChildren();
    $("quote-input").value = "";
    $("reason-input").value = "";
    $("verdict").hidden = true;
    renderEvidence();
    try {
      state.caseData = await api(`/api/case/${cityId}`);
    } catch {
      $("case-title").textContent = t("noCase");
      return;
    }
    const saved = loadPref(verdictKey(), "");
    if (saved) {
      try {
        const prev = JSON.parse(saved);
        state.done = true;
        state.suspectId = prev.accused && prev.accused.id;
        $("verdict").hidden = false;
        renderVerdict(prev);
      } catch { /* ignore broken storage */ }
    }
    renderCase();
  }

  function renderCase() {
    const c = state.caseData;
    $("case-meta").textContent = `${c.city_name} · ${fmtDate(c.date)}`;
    $("case-title").textContent = c.title;
    $("case-setup").textContent = c.setup;
    $("case-brief").textContent = c.brief;
    $("suspects").replaceChildren(...c.suspects.map((s) => {
      const selected = s.id === state.suspectId;
      return el("button", {
        type: "button", role: "radio", "aria-checked": String(selected),
        class: `suspect${selected ? " selected" : ""}`, disabled: state.done,
        onclick: () => { state.suspectId = s.id; renderCase(); },
      },
      el("span", { class: "suspect-id" }, s.id),
      el("span", { class: "suspect-body" },
        el("strong", {}, s.name),
        el("span", { class: "alibi" }, `“${s.alibi}”`)));
    }));
    updateAccuse();
  }

  // ---- investigation -----------------------------------------------------
  async function onSearch(ev) {
    ev.preventDefault();
    const query = $("search-input").value.trim();
    if (query.length < 2 || !state.city) return;
    $("search-status").textContent = t("searching");
    $("results").replaceChildren();
    try {
      const data = await api("/api/search", { city: state.city, query });
      if (!state.queries.includes(data.query)) state.queries.push(data.query);
      $("search-status").textContent = data.results.length ? t("results", data.results.length, data.query) : t("noResults");
      state.results = data.results;
      renderResults();
    } catch (err) {
      $("search-status").textContent = err.message;
    }
  }

  function markOpened(url) {
    if (!state.opened.includes(url)) state.opened.push(url);
  }

  function renderResult(r) {
    const isPinned = state.evidence && state.evidence.url === r.url;
    return el("li", { class: `result${isPinned ? " pinned" : ""}` },
      el("div", { class: "result-meta" }, `${r.domain} · ${t("published")} ${fmtDate(r.published)}`),
      el("a", { href: r.url, target: "_blank", rel: "noopener noreferrer", class: "result-title",
        onclick: () => markOpened(r.url) }, r.title || r.url),
      el("p", { class: "result-snippet" }, r.snippet),
      el("div", { class: "result-actions" },
        el("a", { href: r.url, target: "_blank", rel: "noopener noreferrer", class: "ghost small-btn",
          onclick: () => markOpened(r.url) }, t("open")),
        el("button", { type: "button", class: isPinned ? "small-btn" : "ghost small-btn", disabled: state.done,
          onclick: () => { state.evidence = isPinned ? null : r; renderEvidence(); } },
          isPinned ? t("pinned") : t("pin"))));
  }

  function renderResults() {
    $("results").replaceChildren(...state.results.map(renderResult));
  }

  function renderEvidence() {
    const card = $("evidence-card");
    const e = state.evidence;
    $("evidence-empty").hidden = Boolean(e);
    card.hidden = !e;
    $("proof").hidden = !e || state.done;
    if (e) {
      card.replaceChildren(
        el("div", { class: "result-meta" }, `${e.domain} · ${t("published")} ${fmtDate(e.published)}`),
        el("a", { href: e.url, target: "_blank", rel: "noopener noreferrer", class: "result-title",
          onclick: () => markOpened(e.url) }, e.title || e.url),
        el("div", { class: "section-label" }, t("sourceText")),
        el("div", { class: "evidence-text", tabindex: "0" }, e.text || e.snippet),
        el("button", { type: "button", class: "ghost small-btn", disabled: state.done,
          onclick: () => { state.evidence = null; renderEvidence(); } }, t("unpin")));
    }
    updateAccuse();
    renderResults();
  }

  // ---- requirements gate -------------------------------------------------
  function requirements() {
    return [
      { id: "suspect", met: Boolean(state.suspectId) },
      { id: "evidence", met: Boolean(state.evidence && state.evidence.token) },
      { id: "quote", met: compact($("quote-input").value).length >= MIN_QUOTE },
      { id: "reason", met: $("reason-input").value.trim().length >= MIN_REASON },
    ];
  }

  function renderRequirements() {
    $("requirements").replaceChildren(...requirements().map((r) =>
      el("li", { class: r.met ? "met" : "" }, `${r.met ? "✓" : "○"} ${t(`req_${r.id}`)}`)));
  }

  function updateAccuse() {
    renderRequirements();
    $("accuse-btn").disabled = state.done || !state.caseData || !requirements().every((r) => r.met);
  }

  // ---- accusation --------------------------------------------------------
  async function onAccuse() {
    if (state.done || !requirements().every((r) => r.met)) return;
    const btn = $("accuse-btn");
    btn.disabled = true;
    $("accuse-error").textContent = "";
    const verdict = $("verdict");
    verdict.hidden = false;
    verdict.replaceChildren(el("p", { class: "judging" }, t("judging")));
    verdict.scrollIntoView({ behavior: "smooth", block: "start" });
    try {
      const result = await api("/api/accuse", {
        case_id: state.caseData.id,
        suspect_id: state.suspectId,
        evidence_token: state.evidence.token,
        quote: $("quote-input").value,
        reasoning: $("reason-input").value,
        process: { elapsed_sec: Math.round((Date.now() - state.startedAt) / 1000),
          queries: state.queries, opened: state.opened },
      });
      state.done = true;
      savePref(verdictKey(), JSON.stringify(result));
      renderVerdict(result);
      renderCase();
      renderEvidence();
    } catch (err) {
      verdict.hidden = true;
      $("accuse-error").textContent = err.message;
      if (err.code === "already_submitted") {
        state.done = true;
        renderCase();
        renderEvidence();
      } else {
        updateAccuse();
      }
    }
  }

  function renderVerdict(r) {
    const ev = r.evidence_check || {};
    const rv = r.reveal;
    $("verdict").replaceChildren(
      el("div", { class: `verdict-head ${r.correct ? "win" : "lose"}` },
        el("h2", {}, r.correct ? t("solved") : t("wrong")),
        el("div", { class: "score" }, el("span", {}, t("score")), el("strong", {}, String(r.score)))),
      el("p", { class: ev.supports_accusation ? "ok" : "bad" },
        `${ev.supports_accusation ? t("evidenceSupported") : t("evidenceRejected")} — ${ev.reason || ""}`),
      el("p", { class: ev.reasoning_sound ? "ok" : "bad" }, ev.reasoning_sound ? t("reasoningSound") : t("reasoningWeak")),
      el("h3", { class: "section-label" }, t("badges")),
      el("ul", { class: "badges" }, r.badges.map((b) =>
        el("li", { class: b.earned ? "earned" : "" }, `${b.earned ? "✓" : "○"} ${t(`badge_${b.id}`)}`))),
      el("div", { class: "reveal" },
        el("p", {}, el("span", { class: "section-label" }, t("culprit")), " ", el("strong", {}, `${rv.culprit_id} · ${rv.culprit}`)),
        el("p", {}, el("span", { class: "section-label" }, t("realFact")), " ", rv.fact_en),
        el("blockquote", {}, rv.quote),
        el("p", { class: "small" }, `${t("source")}: `,
          el("a", { href: rv.source_url, target: "_blank", rel: "noopener noreferrer" }, rv.source_domain),
          rv.published ? ` · ${fmtDate(rv.published)}` : ""),
        el("p", {}, el("span", { class: "section-label" }, t("whyImpossible")), " ", rv.why_impossible)),
      el("p", { class: "muted small" }, t("comeBack")));
  }

  // ---- boot --------------------------------------------------------------
  async function boot() {
    $("lang-toggle").addEventListener("click", () => {
      state.lang = state.lang === "en" ? "ko" : "en";
      savePref("fd-lang", state.lang);
      applyI18n();
    });
    $("search-form").addEventListener("submit", onSearch);
    $("accuse-btn").addEventListener("click", onAccuse);
    $("quote-input").addEventListener("input", updateAccuse);
    $("reason-input").addEventListener("input", updateAccuse);
    applyI18n();
    try {
      state.cities = await api("/api/cities");
    } catch {
      $("case-title").textContent = t("error");
      return;
    }
    renderCityTabs();
    const preferred = loadPref("fd-city", "");
    const withCase = state.cities.filter((c) => c.case_date);
    const first = withCase.find((c) => c.id === preferred) || withCase[0];
    if (first) selectCity(first.id); else $("case-title").textContent = t("noCase");
  }

  boot();
})();
