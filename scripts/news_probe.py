"""Experiment: can the Polyjury pipeline check a news claim instead of a codebase?

Same shape as the code verdict: three jurors split the claim into checkable parts,
Nemotron merges them, and each part is settled by a script that downloads official data
and computes the number, run in a Nebius Sandbox. Only computed evidence counts.

    python scripts/news_probe.py "claim text" [--out scratch/news/report.md]
"""
from __future__ import annotations

import argparse
from urllib.parse import urlparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from core.tavily_client import get_search  # noqa: E402
from polyjury.llm import chat, parse_json  # noqa: E402
from polyjury.panel import REVIEWERS  # noqa: E402

OFFICIAL = ["ourworldindata.org", "github.com", "raw.githubusercontent.com", "cdc.gov", "data.cdc.gov",
            "ons.gov.uk", "who.int", "gov.uk", "nhs.uk", "ecdc.europa.eu", "ec.europa.eu", "cancer.gov",
            "nih.gov", "ncbi.nlm.nih.gov", "kosis.kr", "kdca.go.kr", "fullfact.org", "reuters.com",
            "apnews.com", "healthdata.org"]

JUROR_PROMPT = """You are one of several independent fact-checkers. Read the claim and the search
results. Break the claim into the smallest parts that official statistics could settle by
calculation (a rate, a ratio, a before/after comparison). For each part say what it asserts,
which official dataset would settle it, and exactly what to compute. Also say what the claim
leaves undefined (which country, which years, what counts as the condition).
JSON only: {"parts":[{"assertion":str,"dataset":str,"compute":str,"undefined":str}],
 "first_impression":"likely true"|"likely false"|"cannot tell","why":str}"""

MERGE_PROMPT = """You chair a panel of fact-checkers who split the same claim independently.
Merge their parts into at most 4 checkable sub-claims, most important first. Put parts with
the same meaning together and list which checkers raised each. Where the numbers came from
matters most: if the checkers point to an original dataset or document behind the figures,
make "the original data actually yields these figures" the first sub-claim, so the figures can
be recomputed from their own source. Also write up to 3 web search queries that would find
the original numbers (counts, baselines, corrections). Do NOT settle anything by citing a
fact-checker's conclusion; only numbers count. JSON only:
{"subclaims":[{"assertion":str,"dataset":str,"compute":str,"checkers":[str]}],
 "undefined":[str],"origin_queries":[str]}"""

PROOF_PROMPT = """Write one Python 3 script that settles a sub-claim of a news claim by
COMPUTING it from numbers, never by quoting someone's conclusion. Guessing is not allowed.
Rules:
- The full text of the documents found for this claim is ALREADY in /work/sources/*.txt:
  line 1 is where it came from, the rest is the extracted text (tables included). Read the
  text from disk; never download these URLs again (the sites block scripts). Tables from PDFs
  are often flattened so several rows share one line, and numbers carry thousands separators
  ("1,048%"): match the row label, then parse the numbers that follow it, and print each parsed
  value next to the text it came from so a wrong parse is visible. Take the numbers from the
  exact row the passage names, and keep their sign: "5.7% decrease" is -5.7%. Every number you use from them must be located by
  searching the file text in the script, and you must print the exact line you found it in
  and the file's URL. A number you cannot find in a file must not be used.
- A fact-checker saying "false" is not evidence. Their quoted counts, baselines and
  corrections are: recompute the claimed percentage from them, both the way the claim did
  and with any corrected figures, and print both results.
- The machine also has network access, the standard library, pandas and requests.
- For extra data use only these official sources, found by search (you may use any URL on these hosts
  you are confident exists, e.g. Our World in Data grapher CSVs:
  https://ourworldindata.org/grapher/<slug>.csv?v=1&csvType=full&useColumnShortNames=true):
{sources}
- Print every URL you downloaded, the rows or values you used, and the computed ratio.
- A ratio of about 3x or 10x is what the claim asserts; compare against it explicitly.
- If a download fails or the data cannot answer the question, say so: that is INCONCLUSIVE.
- Wrap everything in try/except so the script always answers.
- The LAST line must be exactly one of:
    "VERDICT: SUPPORTED"     - the computed numbers match what the claim asserts
    "VERDICT: REFUTED"       - the computed numbers clearly contradict it
    "VERDICT: INCONCLUSIVE"  - the data could not be obtained or cannot decide it
Reply with PROVES: <one sentence> and one ```python block."""

AUDIT_PROMPT = """A script downloaded data to test part of a news claim. Read what it printed
and the verdict it gave. Does the printed evidence support that verdict? A verdict with no
downloaded numbers behind it, or numbers that point the other way, contradicts itself.
Answer one line: CONSISTENT, or CONTRADICTS: <why>."""


def search(query: str, n: int = 5, official: bool = False) -> list[dict]:
    try:
        return get_search().search(query, max_results=n, depth="advanced", include_answer=False,
                                   include_domains=OFFICIAL if official else None).sources
    except Exception as exc:  # noqa: BLE001
        print("  search failed:", exc)
        return []


def fmt(results: list[dict]) -> str:
    return "\n".join(f"- {r.get('title','')} <{r.get('url','')}>\n  {' '.join((r.get('content') or '').split())[:500]}"
                     for r in results)


def juror(model: str, claim: str, context: str) -> dict:
    t = time.time()
    try:
        raw, _ = chat(JUROR_PROMPT, f"CLAIM: {claim}\n\nSEARCH RESULTS:\n{context}", think=None,
                      model=model, max_tokens=4000, temperature=0, timeout=120)
        data = parse_json(raw) or {}
    except Exception as exc:  # noqa: BLE001
        data = {"error": str(exc)}
    data["model"], data["seconds"] = model, round(time.time() - t, 1)
    return data


def write_proof(sub: dict, claim: str, sources: str) -> tuple[str, str]:
    task = (f"FULL CLAIM: {claim}\nSUB-CLAIM: {sub['assertion']}\nDATASET: {sub.get('dataset','')}\n"
            f"COMPUTE: {sub.get('compute','')}\nNUMBERS ARE IN THESE PASSAGES (verbatim):\n" +
            "\n".join(f"- {q['file']}: {q['text']}" for q in sub.get("quotes") or []))
    raw, _ = chat(PROOF_PROMPT.replace("{sources}", sources), task, think=True,
                  max_tokens=9000, temperature=0.1, timeout=200)
    block = re.search(r"```(?:python)?\s*(.*?)```", raw, re.S)
    proves = re.search(r"PROVES:\s*(.+)", raw)
    return (block.group(1).strip() if block else ""), (proves.group(1).strip() if proves else "")


def run_in_sandbox(script: str, docs: dict[str, bytes] | None = None) -> tuple[str, str]:
    from contree_sdk import ContreeSync
    image = ContreeSync().images.use("python:3.12-slim")
    cmd = ("timeout 90 pip install -q --disable-pip-version-check --root-user-action=ignore pandas requests "
           "> /tmp/pip.log 2>&1 || echo '[probe] pip failed'; exec python proof.py")
    try:
        r = image.run("sh", args=["-c", cmd], cwd="/work", files={"/work/proof.py": script.encode(), **(docs or {})},
                      env={"PYTHONIOENCODING": "utf-8"}, timeout=240, disposable=True).wait()
        out = (r.stdout or "")[-5000:] + ("\n" + r.stderr[-1500:] if r.stderr else "")
    except Exception as exc:  # noqa: BLE001
        return "INCONCLUSIVE", f"sandbox error: {exc}"
    m = re.findall(r"VERDICT:\s*(SUPPORTED|REFUTED|INCONCLUSIVE)", r.stdout or "")
    return (m[-1] if m else "INCONCLUSIVE"), out


REPAIR_PROMPT = """A proof script ended INCONCLUSIVE. Decide why from its own output.
If the data simply is not there, answer exactly: NO_FIX
If the script itself is at fault (a number parsed wrong - e.g. "1,048" read as 48 -, a regex that
missed text it printed, an exception in its own code), return the whole corrected script in one
```python block. Same rules: read /work/sources/*.txt, never re-download them, print the exact
line each number came from, and end with VERDICT: SUPPORTED | REFUTED | INCONCLUSIVE."""


def repair(script: str, output: str) -> str:
    raw, _ = chat(REPAIR_PROMPT, f"SCRIPT:\n```python\n{script}\n```\n\nOUTPUT:\n{output[-4000:]}",
                  think=True, max_tokens=9000, temperature=0, timeout=200)
    if "NO_FIX" in (raw or "")[:200]:
        return ""
    block = re.search(r"```(?:python)?\s*(.*?)```", raw or "", re.S)
    return block.group(1).strip() if block else ""


NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> list[float]:
    out = []
    for n in NUMBER.findall(text):
        try:
            out.append(float(n.replace(",", "")))
        except ValueError:
            pass
    return out


def unused_numbers(quotes: list[dict], output: str) -> list[str]:
    """A verdict must be computed from the passages the chair quoted. A model reading a flattened
    table easily grabs the next row; checking the model's reasoning cannot catch that, checking
    the numbers can."""
    # lines that merely echo the source passage prove nothing about what was computed
    echoes = [_flat(q.get("text", "")) for q in quotes if q.get("text")]
    own = [ln for ln in output.splitlines() if not any(e and e in _flat(ln) for e in echoes)]
    seen = _numbers("\n".join(own))
    missing = []
    for q in quotes:
        for n in _numbers(q.get("text", "")):
            if not any(abs(n - s) <= 1e-6 + 0.001 * abs(n) for s in seen):
                missing.append(f"{n:g}")
    return missing


def audit(assertion: str, verdict: str, output: str) -> str:
    raw, _ = chat(AUDIT_PROMPT, f"SUB-CLAIM: {assertion}\nVERDICT: {verdict}\nPRINTED:\n{output[-3500:]}",
                  think=False, max_tokens=200, temperature=0, timeout=60)
    line = (raw or "").strip().splitlines()[0] if (raw or "").strip() else ""
    return line.split(":", 1)[1].strip() if line.upper().startswith("CONTRADICTS") else ""


def gather(queries: list[str], limit: int = 8) -> dict[str, bytes]:
    """Full text of the documents behind the claim, uploaded next to the proof."""
    seen, docs = set(), {}
    for q in queries:
        try:
            raw = get_search()._client.search(query=q, max_results=4, search_depth="advanced",
                                               include_raw_content=True)
        except Exception as exc:  # noqa: BLE001
            print("  gather failed:", exc)
            continue
        for r in raw.get("results", []):
            url, text = r.get("url", ""), r.get("raw_content") or r.get("content") or ""
            if url in seen or len(text) < 300 or len(docs) >= limit:
                continue
            seen.add(url)
            docs[f"/work/sources/{len(docs):02d}.txt"] = (url + "\n" + text[:60000]).encode("utf-8")
    return docs


PRIMARY_PROMPT = """Articles about a news claim link to other pages. Pick the links most likely to
be the ORIGINAL source of the claim's figures: the report, dataset, memo or official document
the numbers were computed from (not other news stories, not social media, not fact-check home
pages). JSON only: {"primary":[str]} with at most 5 URLs copied exactly from the list, best first."""

RESCOPE_PROMPT = """You chair a fact-checking panel. Below are the sub-claims your panel wrote before
reading the sources, and the source documents now on disk, including the ORIGINAL document
behind the figures when one was found. Rewrite the sub-claims (at most 5) so each one can be
settled by recomputing numbers these documents actually contain: the claimed figure computed
from the original data the way the claim did, the same figure from corrected or complete data,
and how far off the baseline was. Keep the claim's own wording of what is asserted.
For every sub-claim copy, character for character, the short passages (under 300 characters
each) that hold the numbers it needs, with the FILE they are in. If the documents hold nothing
for a part of the claim, keep that part as its own sub-claim with no quotes, so it is reported
as unsettled instead of silently disappearing. JSON only:
{"subclaims":[{"assertion":str,"compute":str,"checkers":[str],"quotes":[{"file":str,"text":str}]}]}"""

LINK = re.compile(r"https?://[^\s)\]\"'<>]+")


def follow_primary(claim: str, docs: dict[str, bytes], limit: int = 3) -> dict[str, bytes]:
    """Fact-checks link to the document the figures came from; fetch that document itself."""
    have = {v.split(b"\n", 1)[0].decode() for v in docs.values()}
    links = []
    for v in docs.values():
        home = urlparse(v.split(b"\n", 1)[0].decode()).netloc.removeprefix("www.")
        mine = 0
        for u in LINK.findall(v.decode("utf-8", "replace")):
            u = u.rstrip(".,;")
            host = urlparse(u).netloc.removeprefix("www.")
            # links back into the same site are navigation, not sources
            if host == home or u in have or u in links or re.search(r"\.(png|jpe?g|gif|svg|webp)(\?|$)", u, re.I):
                continue
            links.append(u)
            mine += 1
            if mine >= 40:
                break
    if not links:
        return {}
    raw, _ = chat(PRIMARY_PROMPT, f"CLAIM: {claim}\nLINKS:\n" + "\n".join(links[:500]), think=False,
                  max_tokens=500, temperature=0, timeout=90)
    picked = [u for u in ((parse_json(raw) or {}).get("primary") or []) if u in links][:5]
    print("    primary sources picked:", picked)
    if not picked:
        return {}
    try:
        got = get_search()._client.extract(urls=picked, extract_depth="advanced")
    except Exception as exc:  # noqa: BLE001
        print("  extract failed:", exc)
        return {}
    print("    could not read:", [f.get("url") for f in got.get("failed_results", [])])
    out = {}
    for r in got.get("results", []):
        text = r.get("raw_content") or ""
        if len(text) >= 300:
            if len(out) >= limit:
                break
            out[f"/work/sources/p{len(out)}.txt"] = (r["url"] + "\n" + text[:60000]).encode("utf-8")
    return out


def _flat(text: str) -> str:
    """Compare letters, digits, % and decimal points only: PDFs and models disagree on quotes,
    dashes, '>' markers and spacing, never on the numbers."""
    return re.sub(r"[^0-9a-z%.]+", " ", text.lower()).strip()


def rescope(subs: list[dict], docs: dict[str, bytes]) -> list[dict]:
    """Sub-claims written before reading the sources ask for data nobody has on disk. Each new
    sub-claim must quote the document text holding its numbers; a quote that is not really in
    that file is thrown away, so nothing gets computed from numbers the chair imagined."""
    parts = []
    for name, body in docs.items():
        size = 12000 if "/p" in name else 2500
        parts.append(f"=== FILE {name}\n{body.decode('utf-8', 'replace')[:size]}")
    raw, _ = chat(RESCOPE_PROMPT, f"SUB-CLAIMS:\n{json.dumps(subs, ensure_ascii=False)}\n\nDOCUMENTS:\n" +
                  "\n\n".join(parts)[:70000], think=True, max_tokens=7000, temperature=0, timeout=200)
    new = [s for s in (parse_json(raw) or {}).get("subclaims", []) if isinstance(s, dict) and s.get("assertion")][:5]
    if not new:
        return [{**s, "quotes": []} for s in subs]
    text = {k: _flat(v.decode("utf-8", "replace")) for k, v in docs.items()}
    for s in new:
        kept, lost = [], []
        for q in s.get("quotes") or []:
            if not isinstance(q, dict):
                continue
            # the chair joins passages with "..."; every piece must be in the file
            pieces = [_flat(p) for p in re.split(r"\.\.\.|…", q.get("text", "")) if len(_flat(p)) >= 12]
            if pieces and all(p in text.get(q.get("file", ""), "") for p in pieces):
                kept.append(q)
            else:
                lost.append(q)
        s["quotes"], s["rejected_quotes"] = kept, lost
    return new


def doc_index(docs: dict[str, bytes]) -> str:
    return "\n".join(f"{k}: {v.split(b'\n', 1)[0].decode()}" for k, v in docs.items())


def prove(sub: dict, claim: str, docs: dict[str, bytes] | None = None) -> dict:
    t = time.time()
    if docs is not None and not sub.get("quotes"):
        return {**sub, "verdict": "NO SOURCE DATA", "proves": "", "script": "", "sources": [], "seconds": 0,
                "output": "None of the documents found contains numbers for this part, so nothing was computed." +
                          "".join(f"\nquote not found in {q.get('file')}: {q.get('text')}" for q in sub.get("rejected_quotes") or [])}
    found = search(f"{sub.get('dataset','')} {sub['assertion']} official statistics data", 6, official=True)
    sources = fmt(found) or "(search found nothing; use well-known official URLs)"
    if docs:
        sources += "\n\nDOCUMENTS ON DISK:\n" + doc_index(docs)
    script, proves = write_proof(sub, claim, sources)
    verdict, output = run_in_sandbox(script, docs) if script else ("INCONCLUSIVE", "no script written")
    if script and verdict == "INCONCLUSIVE":
        fixed = repair(script, output)
        if fixed:
            script = fixed
            verdict, output = run_in_sandbox(script, docs)
            output = "[probe] second attempt after fixing the script's own bug\n" + output
    missing = unused_numbers(sub.get("quotes") or [], output) if verdict != "INCONCLUSIVE" else []
    if missing:
        verdict = "INCONCLUSIVE"
        output += (f"\n[probe] marked inconclusive: the quoted source numbers {missing} never appear in the run,"
                   " so it computed from something else (often the wrong table row).")
    why = audit(sub["assertion"], verdict, output) if verdict != "INCONCLUSIVE" else ""
    if why:
        verdict = "INCONCLUSIVE"
        output += f"\n[probe] marked inconclusive: the run contradicts its own verdict. {why}"
    return {**sub, "verdict": verdict, "proves": proves, "script": script, "output": output,
            "sources": [r.get("url") for r in found], "seconds": round(time.time() - t, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("claim")
    ap.add_argument("--out", default="scratch/news/report.md")
    args = ap.parse_args()
    t0 = time.time()

    print("[1] where the claim comes from")
    context = search(args.claim, 6) + search(f"fact check {args.claim}", 4)
    ctx = fmt(context)

    print(f"[2] {len(REVIEWERS)} jurors split the claim")
    with ThreadPoolExecutor(len(REVIEWERS)) as pool:
        jurors = list(pool.map(lambda m: juror(m, args.claim, ctx), REVIEWERS))
    for j in jurors:
        print(f"    {j['model']}: {len(j.get('parts') or [])} parts, {j.get('first_impression')} ({j['seconds']}s)")

    print("[3] Nemotron merges")
    raw, _ = chat(MERGE_PROMPT, json.dumps([{k: j.get(k) for k in ("model", "parts")} for j in jurors],
                                           ensure_ascii=False), think=True, max_tokens=6000, temperature=0, timeout=200)
    merged = parse_json(raw) or {}
    subs = [s for s in merged.get("subclaims", []) if isinstance(s, dict) and s.get("assertion")][:4]
    for s in subs:
        print("    -", s["assertion"][:110])

    queries = [args.claim, f"fact check {args.claim}"] + [q for q in merged.get("origin_queries", []) if isinstance(q, str)][:3]
    print("[4] gathering the documents behind the numbers:", queries[2:])
    docs = gather(queries)
    print("    following links to the original document")
    docs.update(follow_primary(args.claim, docs))
    print(doc_index(docs))
    subs = rescope(subs, docs)
    print("    sub-claims after reading the sources:")
    for s in subs:
        print("    -", s["assertion"][:110])
    print(f"[5] proving {len(subs)} sub-claims by computation in Nebius Sandboxes")
    with ThreadPoolExecutor(5) as pool:
        proved = list(pool.map(lambda s: prove(s, args.claim, docs), subs))
    for p in proved:
        print(f"    {p['verdict']:13s} {p['assertion'][:90]} ({p['seconds']}s)")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    (out.with_suffix(".json")).write_text(json.dumps({"claim": args.claim, "context": context, "jurors": jurors,
                                                      "merged": merged, "proved": proved, "docs": doc_index(docs)}, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    lines = [f"# News verdict: {args.claim}", f"{len(subs)} sub-claims, {round(time.time()-t0)}s", "",
             "## Jurors' first impressions"]
    lines += [f"- {j['model']}: {j.get('first_impression')} - {j.get('why','')}" for j in jurors]
    if merged.get("undefined"):
        lines += ["", "## What the claim leaves undefined"] + [f"- {u}" for u in merged["undefined"]]
    for p in proved:
        lines += ["", f"## [{p['verdict']}] {p['assertion']}", f"- dataset: {p.get('dataset','')}",
                  f"- raised by: {', '.join(p.get('checkers') or [])}", f"- planned test (written before the run): {p['proves']}",
                  *[f"- source passage: {q['file']}: {q['text']}" for q in p.get("quotes") or []],
                  "```", p["output"][-2500:], "```"]
    out.write_text("\n".join(lines), encoding="utf-8")
    print("report:", out)


if __name__ == "__main__":
    main()
