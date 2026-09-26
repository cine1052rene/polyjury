/* The browser runs the court: one short request per step, so the work is visible
   and nothing has to be remembered on the server between serverless calls. */
const $ = (id) => document.getElementById(id);
const safe = (t) => (t || "").replace(/[<>]/g, "");

let REVIEWERS = [];
let MODE = "repo";
const state = { target: "", bundle: "", claims: [], cited: new Set() };

const MODES = {
  repo: { title: "Repository", note: "One AI wrote your code. Don't let one AI judge it.",
          hint: "Your own project, please. A verdict takes about two minutes." },
  snippet: { title: "Single file", note: "Paste what your assistant wrote and let the jury read it.",
             hint: "Nothing is stored. Proofs still run in a sandbox, never in your browser." },
  recorded: { title: "Recorded verdict", note: "A finished case on a real public repository.",
              hint: "Replayed at reading speed — every verdict below actually happened." },
};

async function api(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

/* ---------- timeline ---------- */

function clearTimeline() {
  $("timeline").innerHTML = "";
  $("citations").innerHTML = "";
  state.cited = new Set();
}

function step(mark, title, said) {
  const el = document.createElement("section");
  el.className = "step live";
  el.innerHTML = `<div class="step-mark">${mark}</div>
    <div class="step-body"><h2>${title}</h2><p class="said">${said || ""}</p></div>`;
  $("timeline").appendChild(el);
  el.scrollIntoView({ behavior: "smooth", block: "end" });
  return {
    body: el.querySelector(".step-body"),
    say: (text) => { el.querySelector(".said").innerHTML = text; },
    done: () => el.classList.remove("live"),
  };
}

function renderFiles(into, repo) {
  const ul = document.createElement("ul");
  ul.className = "files";
  ul.innerHTML = repo.files.map((f) => `<li>${safe(f)}</li>`).join("");
  into.appendChild(ul);
}

function short(model) { return model.split("/").pop(); }

function jurorBench(into) {
  const grid = document.createElement("div");
  grid.className = "panel-grid";
  REVIEWERS.forEach((m) => {
    const card = document.createElement("article");
    card.className = "model";
    card.id = `m-${short(m)}`;
    card.innerHTML = `<h3>${safe(short(m))}</h3><p class="meta">reading…</p>`;
    grid.appendChild(card);
  });
  into.appendChild(grid);
}

function renderReview(model, result) {
  const card = $(`m-${short(model)}`);
  if (!card) return;
  if (result.error || !result.findings.length) {
    card.classList.add("failed");
    card.querySelector(".meta").textContent = result.error || "no findings";
    return;
  }
  card.classList.add("done");
  const n = result.findings.length;
  card.querySelector(".meta").textContent =
    `${n} finding${n === 1 ? "" : "s"} in ${result.seconds}s${result.repaired ? " · answer normalised" : ""}`;
  const list = document.createElement("ul");
  list.innerHTML = result.findings
    .map((f) => `<li><b>${safe((f.severity || "").toUpperCase())}</b> ${safe(f.what_breaks)}</li>`)
    .join("");
  card.appendChild(list);
}

function claimCard(claim, index) {
  const el = document.createElement("article");
  el.className = "claim";
  el.id = `c-${index}`;
  const votes = new Set(claim.models || []).size;
  el.innerHTML = `
    <div class="claim-head">
      <h3>${safe(claim.title)}</h3>
      <span class="chip running" id="v-${index}">PROVING…</span>
    </div>
    <p class="why">${safe(claim.what_breaks)}</p>
    <p class="where">${safe(claim.file)} ${claim.where ? "· " + safe(claim.where) : ""}</p>
    <p class="votes">raised by ${votes} of ${REVIEWERS.length} jurors</p>
    <div id="proof-${index}"></div>`;
  return el;
}

function renderVerdict(index, claim) {
  const chip = $(`v-${index}`);
  const label = { REPRODUCED: "CONFIRMED", NOT_REPRODUCED: "FALSE ALARM", UNVERIFIED: "NEEDS A HUMAN" };
  chip.className = `chip ${claim.verdict.toLowerCase()}`;
  chip.textContent =
    claim.verdict === "REPRODUCED"
      ? (claim.proof_kind === "dynamic" ? "CONFIRMED · RAN IT" : "LIKELY · READ IT")
      : label[claim.verdict] || claim.verdict;
  if (claim.verdict === "REPRODUCED") $(`c-${index}`).classList.add("reproduced");
  $(`proof-${index}`).innerHTML = `
    <details>
      <summary>What the run showed${claim.runner ? " · " + safe(claim.runner) : ""}</summary>
      <p class="why">${safe(claim.what_it_proves)}</p>
      <pre>${safe(claim.evidence) || "no output"}</pre>
    </details>
    ${claim.script ? `<details><summary>The proof Nemotron wrote</summary><pre>${safe(claim.script)}</pre></details>` : ""}`;
}

function summary(into, claims, findingsTotal) {
  const confirmed = claims.filter((c) => c.verdict === "REPRODUCED");
  const ran = confirmed.filter((c) => c.proof_kind === "dynamic");
  const line = document.createElement("p");
  line.className = "verdict-line";
  line.innerHTML =
    `${findingsTotal} findings from ${REVIEWERS.length} jurors became ${claims.length} claims, ` +
    `and <b>${ran.length} were reproduced by actually running the code</b>` +
    `${confirmed.length > ran.length ? `, ${confirmed.length - ran.length} supported by reading it` : ""}. ` +
    `${claims.length - confirmed.length} did not survive.`;
  into.appendChild(line);
  return confirmed;
}

function fixPromptBlock(into, prompt) {
  if (!prompt) return;
  const btn = document.createElement("button");
  btn.className = "primary copy";
  btn.textContent = "Copy the fix prompt";
  const pre = document.createElement("pre");
  pre.className = "prompt-box";
  pre.textContent = prompt;
  btn.addEventListener("click", async () => {
    await navigator.clipboard.writeText(prompt);
    btn.textContent = "Copied";
    setTimeout(() => (btn.textContent = "Copy the fix prompt"), 1600);
  });
  into.appendChild(btn);
  into.appendChild(pre);
}

/* ---------- sources drawer ---------- */

function citationSlot(claim) {
  const el = document.createElement("article");
  el.className = "cite";
  el.innerHTML = `<h3>${safe(claim.title)}</h3><p class="pending">looking for the standard behind this…</p>`;
  $("citations").appendChild(el);
  return el;
}

function renderCitation(el, data) {
  if (data.error || !data.sources.length) {
    el.innerHTML = `<h3>${safe(data.claim)}</h3>
      <p class="pending">${safe(data.error) || "nothing authoritative found for this one"}</p>`;
    return;
  }
  el.innerHTML = `
    <h3>${safe(data.claim)}</h3>
    <p class="q">searched: ${safe(data.query)}</p>
    ${data.why_it_matters ? `<p class="why">${safe(data.why_it_matters)}</p>` : ""}
    <ol>${data.sources.map((s) => `
      <li><a href="${safe(s.url)}" target="_blank" rel="noreferrer noopener">${safe(s.title) || s.url}</a>
      <p>${safe(s.snippet)}</p></li>`).join("")}</ol>`;
}

async function gatherSources(claims) {
  for (const claim of claims) {
    if (state.cited.has(claim.title)) continue;
    state.cited.add(claim.title);
    const slot = citationSlot(claim);
    try {
      renderCitation(slot, await api("/api/sources", { claim }));
    } catch (err) {
      renderCitation(slot, { claim: claim.title, error: err.message, sources: [] });
    }
  }
}

/* ---------- the run ---------- */

async function runRepo(target) {
  state.target = target;
  const s1 = step("1", "Fetching the code", "downloading and choosing the files worth reading…");
  const repo = await api("/api/collect", { target });
  state.bundle = repo.bundle;
  s1.say(`<b>${safe(repo.name)}</b> — ${repo.files.length} files go before the jury.`);
  renderFiles(s1.body, repo);
  s1.done();

  const s2 = step("2", "The jury reads it — separately",
                  "each juror gets the same code and never sees the others' answers");
  jurorBench(s2.body);
  const reviews = await Promise.all(
    REVIEWERS.map((model) =>
      api("/api/review", { bundle: state.bundle, model })
        .then((r) => { renderReview(model, r); return r; })
        .catch((err) => { renderReview(model, { error: err.message, findings: [] }); return { findings: [] }; })
    )
  );
  s2.done();
  const findings = reviews.flatMap((r) => r.findings || []);
  if (!findings.length) throw new Error("No juror returned anything usable for this repository.");

  const s3 = step("3", "Nemotron presides", "merging duplicates, dropping what cannot be checked…");
  const merged = await api("/api/merge", { findings });
  state.claims = merged.claims;
  s3.say(`${findings.length} raw findings became ${merged.claims.length} claims` +
         (merged.dropped.length ? `, ${merged.dropped.length} dropped as unverifiable.` : "."));
  s3.done();

  const s4 = step("4", "Every claim has to prove itself",
                  "Nemotron writes a script for each claim, and the script is executed");
  const list = document.createElement("div");
  list.className = "claims";
  state.claims.forEach((c, i) => list.appendChild(claimCard(c, i)));
  s4.body.appendChild(list);
  gatherSources(state.claims);

  const proved = await Promise.all(
    state.claims.map((claim, i) =>
      api("/api/prove", { target, bundle: state.bundle, claim })
        .then((c) => { renderVerdict(i, c); return c; })
        .catch((err) => {
          const c = { ...claim, verdict: "UNVERIFIED", evidence: err.message };
          renderVerdict(i, c);
          return c;
        })
    )
  );
  s4.done();

  const s5 = step("5", "Verdict", "");
  summary(s5.body, proved, findings.length);
  const { prompt } = await api("/api/fix-prompt", { findings: proved });
  fixPromptBlock(s5.body, prompt);
  s5.done();
}

async function replay(path) {
  const data = await fetch(path).then((r) => r.json());
  REVIEWERS = data.reviewers;
  const s1 = step("1", "Fetching the code", "");
  s1.say(`<b>${safe(data.repo.name)}</b> — ${data.repo.files.length} files went before the jury.`);
  renderFiles(s1.body, data.repo);
  s1.done();

  const s2 = step("2", "The jury reads it — separately", "");
  jurorBench(s2.body);
  for (const r of data.reviews) {
    await new Promise((f) => setTimeout(f, 600));
    renderReview(r.model, r);
  }
  s2.done();

  await new Promise((f) => setTimeout(f, 600));
  const s3 = step("3", "Nemotron presides", "");
  s3.say(`${data.findings_total} raw findings became ${data.claims.length} claims` +
         (data.dropped ? `, ${data.dropped} dropped as unverifiable.` : "."));
  s3.done();

  const s4 = step("4", "Every claim has to prove itself", "");
  const list = document.createElement("div");
  list.className = "claims";
  data.claims.forEach((c, i) => list.appendChild(claimCard(c, i)));
  s4.body.appendChild(list);
  gatherSources(data.claims);
  for (let i = 0; i < data.claims.length; i += 1) {
    await new Promise((f) => setTimeout(f, 700));
    renderVerdict(i, data.claims[i]);
  }
  s4.done();

  const s5 = step("5", "Verdict", "");
  summary(s5.body, data.claims, data.findings_total);
  fixPromptBlock(s5.body, data.fix_prompt);
  s5.done();
}

/* ---------- shell ---------- */

function setMode(mode) {
  MODE = mode;
  document.querySelectorAll(".mode").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  $("mode-title").textContent = MODES[mode].title;
  $("mode-note").textContent = MODES[mode].note;
  $("composer-hint").textContent = MODES[mode].hint;
  $("row-repo").hidden = mode !== "repo";
  $("row-snippet").hidden = mode !== "snippet";
  $("run-form").hidden = mode === "recorded";
  if (mode === "recorded") {
    clearTimeline();
    replay("/example.json").catch((err) => fail(err.message));
  }
}

function fail(message) {
  const box = $("error");
  box.textContent = message;
  box.removeAttribute("hidden");
}

document.querySelectorAll(".mode").forEach((btn) =>
  btn.addEventListener("click", () => setMode(btn.dataset.mode)));

$("sources-toggle").addEventListener("click", () => {
  const open = $("drawer").hidden;
  $("drawer").hidden = !open;
  document.body.classList.toggle("with-drawer", open);
  $("sources-toggle").setAttribute("aria-pressed", String(open));
});
$("drawer-close").addEventListener("click", () => {
  $("drawer").hidden = true;
  document.body.classList.remove("with-drawer");
  $("sources-toggle").setAttribute("aria-pressed", "false");
});

$("run-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("error").setAttribute("hidden", "");
  const buttons = [...document.querySelectorAll(".primary")];
  buttons.forEach((b) => { b.disabled = true; });
  clearTimeline();
  try {
    if (MODE === "repo") {
      const target = $("target").value.trim();
      if (!target) throw new Error("Paste a public GitHub repository URL.");
      await runRepo(target);
    } else {
      throw new Error("Pasting a single file is not wired up yet — use a repository for now.");
    }
  } catch (err) {
    fail(err.message);
  } finally {
    buttons.forEach((b) => { b.disabled = false; });
  }
});

fetch("/api/models")
  .then((r) => r.json())
  .then((d) => {
    REVIEWERS = d.reviewers;
    $("juror-count").textContent = String(d.reviewers.length);
    $("sandbox-state").textContent = d.sandbox ? "Nebius microVM" : "offline";
    $("sandbox-dot").classList.toggle("off", !d.sandbox);
  })
  .catch(() => { REVIEWERS = []; });
