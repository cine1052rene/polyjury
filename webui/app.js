/* The browser drives the pipeline: one short request per step, so progress is
   visible and nothing has to be remembered on the server between calls. */
const $ = (id) => document.getElementById(id);
const show = (id) => $(id).removeAttribute("hidden");

let REVIEWERS = [];
const state = { target: "", bundle: "", claims: [] };

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

function short(model) {
  return model.split("/").pop();
}

function fail(message) {
  const box = $("error");
  box.textContent = message;
  box.removeAttribute("hidden");
}

function renderCollected(repo) {
  $("collect-note").textContent =
    `${repo.name} — ${repo.files.length} files the panel will read.`;
  $("files").innerHTML = repo.files.map((f) => `<li>${f}</li>`).join("");
  show("stage-collect");
}

function modelCard(model) {
  const card = document.createElement("article");
  card.className = "model";
  card.id = `m-${short(model)}`;
  card.innerHTML = `<h3>${short(model)}</h3><p class="meta">reading…</p>`;
  return card;
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
  card.querySelector(".meta").textContent =
    `${result.findings.length} findings in ${result.seconds}s${result.repaired ? " (answer normalised)" : ""}`;
  const list = document.createElement("ul");
  list.innerHTML = result.findings
    .map((f) => `<li><b>${(f.severity || "").toUpperCase()}</b> ${f.what_breaks || ""}</li>`)
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
      <h3>${claim.title}</h3>
      <span class="chip running" id="v-${index}">PROVING…</span>
    </div>
    <p class="why">${claim.what_breaks || ""}</p>
    <p class="where">${claim.file || ""} ${claim.where ? "· " + claim.where : ""}</p>
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
  const box = $(`proof-${index}`);
  box.innerHTML = `
    <details>
      <summary>What the run showed${claim.runner ? " (" + claim.runner + ")" : ""}</summary>
      <p class="why">${claim.what_it_proves || ""}</p>
      <pre>${(claim.evidence || "no output").replace(/[<>]/g, "")}</pre>
    </details>`;
}

async function run(target) {
  state.target = target;
  const repo = await api("/api/collect", { target });
  state.bundle = repo.bundle;
  renderCollected(repo);

  show("stage-panel");
  const panel = $("panel");
  panel.innerHTML = "";
  REVIEWERS.forEach((m) => panel.appendChild(modelCard(m)));

  const reviews = await Promise.all(
    REVIEWERS.map((model) =>
      api("/api/review", { bundle: state.bundle, model })
        .then((r) => { renderReview(model, r); return r; })
        .catch((err) => { renderReview(model, { error: err.message, findings: [] }); return { findings: [] }; })
    )
  );
  const findings = reviews.flatMap((r) => r.findings || []);
  if (!findings.length) throw new Error("No juror returned anything usable for this repository.");

  show("stage-chair");
  const merged = await api("/api/merge", { findings });
  state.claims = merged.claims;
  $("chair-note").textContent =
    `${findings.length} raw findings from the panel became ${merged.claims.length} claims` +
    (merged.dropped.length ? `, ${merged.dropped.length} dropped as unverifiable.` : ".");

  show("stage-proof");
  const list = $("claims");
  list.innerHTML = "";
  state.claims.forEach((c, i) => list.appendChild(claimCard(c, i)));

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

  const confirmed = proved.filter((c) => c.verdict === "REPRODUCED");
  const ran = confirmed.filter((c) => c.proof_kind === "dynamic");
  show("stage-done");
  $("score").innerHTML =
    `${findings.length} findings from ${REVIEWERS.length} jurors became ${proved.length} claims, ` +
    `and <b>${ran.length} were reproduced by actually running the code</b>` +
    `${confirmed.length > ran.length ? `, ${confirmed.length - ran.length} supported by reading it` : ""}. ` +
    `${proved.length - confirmed.length} did not survive.`;
  const { prompt } = await api("/api/fix-prompt", { findings: proved });
  $("fix-prompt").textContent = prompt || "Nothing was confirmed — there is nothing to fix.";
  $("copy-btn").hidden = !prompt;
}

$("run-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("error").setAttribute("hidden", "");
  const btn = $("run-btn");
  btn.disabled = true;
  btn.textContent = "Working…";
  try {
    await run($("target").value.trim());
  } catch (err) {
    fail(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Verify";
  }
});

$("copy-btn").addEventListener("click", async () => {
  await navigator.clipboard.writeText($("fix-prompt").textContent);
  $("copy-btn").textContent = "Copied";
  setTimeout(() => ($("copy-btn").textContent = "Copy the fix prompt"), 1600);
});

fetch("/api/models")
  .then((r) => r.json())
  .then((d) => { REVIEWERS = d.reviewers; })
  .catch(() => { REVIEWERS = []; });
