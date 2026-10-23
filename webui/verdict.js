/* The answer first, the evidence below it. A finished case used to end with its verdict and
   the fix prompt at the very bottom, after every juror card and proof; a reader who did not
   scroll never saw what to do. This card is put at the top of the timeline once a case is
   done, and every line in it jumps to the claim card that backs it. Loaded before app.js;
   it only uses app.js helpers ($, safe) when a case finishes, by which time both are loaded. */

function verdictTop(claims, findingsTotal, prompt, fixes) {
  const old = document.getElementById("verdict-top");
  if (old) old.remove();
  const confirmed = claims.map((c, i) => ({ c, i })).filter(({ c }) => c.verdict === "REPRODUCED");
  const fixedTitles = new Set((fixes || []).filter((f) => f.result && f.result.fixed).map((f) => f.title));
  const card = document.createElement("section");
  card.id = "verdict-top";
  card.className = "verdict-top";
  const head = confirmed.length
    ? `${confirmed.length} of ${claims.length} claims reproduced`
    : `None of ${claims.length} claims could be reproduced`;
  const rows = confirmed.map(({ c, i }) => {
    const sim = (c.models || []).includes("polyjury-simulator");
    const how = sim ? "simulated" : c.proof_kind === "dynamic" ? "ran it" : "read it";
    const k = c.known && c.known.status;
    const up = k === "known" || k === "fixed" ? " · already reported upstream" : k === "new" ? " · not reported yet" : "";
    const fixed = fixedTitles.has(c.title) ? " · patch proved" : "";
    // the simulator's title is a question; its first measured collision is the answer
    const hit = sim && /^\s*(\w+) = \S+ rad[^:]*: (\S+) hits (\S+), hull depth ([\d.]+) mm/m.exec(c.evidence || "");
    const found = hit ? `<em>moving only ${safe(hit[1])}, still inside its limit: ${safe(hit[2])} and ${safe(hit[3])} overlap by ${safe(hit[4])} mm</em>` : "";
    return `<li><a href="#c-${i}">${safe(c.title)}</a>${found}<span>${how}${up}${fixed}</span></li>`;
  }).join("");
  card.innerHTML = `
    <p class="eyebrow">Verdict</p>
    <h2>${head}</h2>
    <p class="said">${findingsTotal} findings from the jury · ${claims.length - confirmed.length} did not survive a proof</p>
    ${rows ? `<ol>${rows}</ol>` : ""}
    <div class="verdict-actions">
      ${prompt ? `<button class="primary" type="button" id="verdict-copy">Copy the fix prompt</button>` : ""}
      <a class="toggle" href="#c-0">See the evidence ↓</a>
    </div>`;
  $("timeline").prepend(card);
  const copy = card.querySelector("#verdict-copy");
  if (copy) copy.addEventListener("click", async () => {
    await navigator.clipboard.writeText(prompt);
    copy.textContent = "Copied";
    setTimeout(() => (copy.textContent = "Copy the fix prompt"), 1600);
  });
  card.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* The empty screen offers the two finished cases and a live run that needs no typing. */
const SAMPLE = "https://github.com/google-deepmind/mujoco_menagerie/tree/main/robotstudio_so101";

function wireIdle() {
  document.querySelectorAll("[data-open]").forEach((b) =>
    b.addEventListener("click", () => setMode(b.dataset.open)));
  const fill = document.getElementById("try-sample");
  if (fill) fill.addEventListener("click", () => {
    $("target").value = SAMPLE;
    $("target").focus();
    $("composer-hint").textContent =
      "DeepMind's model of the SO-101 robot arm. Press Convene the jury — about three minutes, on our demo credits.";
  });
}
