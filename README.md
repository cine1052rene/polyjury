# Polyjury

**One AI wrote your code. Don't let one AI judge it.**

Polyjury sends your repository to several open models on [Nebius Token Factory](https://tokenfactory.nebius.com).
Each one reviews it alone. NVIDIA Nemotron then presides: it merges what the jurors said, throws
out what cannot be checked, and — for every surviving claim — writes a Python script that tries to
make the defect actually happen. The script is executed. **Only what is reproduced reaches you.**

A review that says "this might be vulnerable" costs you an afternoon. A review that says
"here is the request, here is the response, here is the file it wrote" costs you a fix.

## Why a jury

Measured on this project's own code, three models produced 17 findings between them and only
**2 of the merged claims were raised by more than one model**. A single reviewer misses most of it.
They also disagree in the other direction: claims that sound serious fall apart the moment you run them.

| Verdict | Meaning |
| --- | --- |
| `CONFIRMED · RAN IT` | a script made it happen, and the output is shown |
| `LIKELY · READ IT` | supported by the source, but not by execution |
| `FALSE ALARM` | the check ran correctly and the defect did not happen |
| `NEEDS A HUMAN` | the check itself failed — that proves nothing either way |

That last row matters. A proof script that crashes is not a disproof, and Polyjury never
pretends otherwise.

## Where the proofs run

Model-written code that tries to break things is exactly what you must not run on your own
machine — so it runs in **Nebius Token Factory Sandboxes**, one disposable microVM per proof.
Before each proof the VM installs what the repository declares in `pyproject.toml` (including
its test dependency group) or `requirements.txt` — plain requirement strings only, so a
repository cannot point pip at a URL of its own choosing.
While you wait for Sandboxes beta access, `--allow-local-exec` runs proofs in a subprocess
instead. Use it only on code you already trust.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env          # NEBIUS_API_KEY, NEBIUS_PROJECT_ID

# command line
python scripts/polyjury_run.py https://github.com/owner/repo

# web app
uvicorn app.server:app --reload
```

## How it is put together

| Module | Job |
| --- | --- |
| `polyjury/collect.py` | pull a public repo, pick the files worth reviewing |
| `polyjury/panel.py` | jurors review in parallel; prose answers are normalised to JSON |
| `polyjury/chair.py` | Nemotron merges claims, writes each proof, repairs it if it will not parse |
| `polyjury/runner.py` | Sandboxes, or a local subprocess when you ask for it |
| `polyjury/sources.py` | Tavily finds the standard or documentation that names the defect |
| `polyjury/report.py` | the verdicts, plus a prompt you can paste back to the AI that wrote the code |
| `polyjury/llm.py` | one place that talks to Token Factory |
| `app/server.py` | one short HTTP call per step, so the browser can show the work |

## Sources

A reproduced defect proves that something happens. It does not explain why it is a
known bad idea. For every claim, Nemotron rewrites the defect in the vocabulary of
the standards and **Tavily** searches CWE, OWASP, MDN, PortSwigger, the RFCs and the
official docs for the literature that already names it. The Sources drawer in the web
app shows what it found, next to the run that proved it.

Tavily's `include_domains` turned out to be unreliable — the same query returned MDN,
PortSwigger and OWASP on one call and a dictionary definition of "rate" on the next —
so both a filtered and an open search run in parallel and the authoritative hits are
picked from the combined pool.

## Models

Jurors: `deepseek-ai/DeepSeek-V4-Pro`, `Qwen/Qwen3.5-397B-A17B`, `openai/gpt-oss-120b`.
Presiding: `nvidia/nemotron-3-super-120b-a12b` with thinking enabled — merging contradictory
reviews and writing a falsifiable test is judgement, not retrieval.

## Licence

Apache-2.0. See [LICENSE](LICENSE).
