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
repository cannot point pip at a URL of its own choosing. A folder that declares nothing gets
the packages its imports name, from a fixed list (`PIL` → Pillow). Code that calls ffmpeg or
loads fonts gets ffmpeg and a Korean-capable stand-in font from Debian's own mirror
(`polyjury/tools.py`), and the repository's small data files and remaining sources are
uploaded too, so a proof runs the real scripts on their real inputs. After each run Nemotron
reads the output once more: a script whose printed evidence contradicts its own verdict is
marked unverified.
While you wait for Sandboxes beta access, `--allow-local-exec` runs proofs in a subprocess
instead. Use it only on code you already trust.

A proof only counts as *ran it* if the script really imports or executes the repository's
code. The chair labels its own proofs, and a label is not evidence: a script that greps the
source and prints REPRODUCED is reported as a reading (`polyjury/proofcheck.py`).

## Robot descriptions: proved by simulation

A URDF or MJCF file is code too: a wrong joint limit ships a robot that drives itself into its
own frame. When a repository holds one, jurors review it like any other file, and the sandbox
also gets MuJoCo, trimesh and manifold3d, the meshes the description references, and a tested
helper (`polyjury/robot_helper.py`) for home-pose contacts, single-joint sweeps, collision
onset, URDF-vs-MJCF limit comparison and exact-mesh overlap (MuJoCo collides convex hulls, so
every hull contact is re-checked on the real triangles).

Jurors read text, and a collision is geometry — on
[SO-ARM100](https://github.com/TheRobotStudio/SO-ARM100/tree/main/Simulation/SO101) no juror
found one. So Polyjury adds its own **simulation check**: every joint is swept alone from the
home pose, inside its own limits. Its script is a fixed template rebuilt on the server, so a
client can never send code to run. On SO101 (`so101_new_calib.urdf`, measured 2026-09-27)
`elbow_flex` alone drives `gripper_link` into `shoulder_link` from 1.51 rad (hull) / about
1.49 rad (exact meshes), well inside its 1.69 rad limit: 12,393 mm³ of overlap at the limit.
A whole-arm grid always finds collisions on a 6-DOF arm, which proves nothing; only home-pose
and single-joint collisions are reported.

## Fix it, then prove the fix

Finding a defect is half the job. For every claim reproduced by running the code, Polyjury
writes a patch and runs the same proof again, on a copy of the repository with the patch applied:

1. **Control run.** The proof that reproduced the defect is run again on the untouched code. If it
   does not reproduce a second time, a fix could not be told apart from luck, and none is offered.
2. **Patch.** Code: Nemotron rewrites the one file the claim names. Robots: no model is involved —
   the joint limit is set to the measured first-contact angle minus 0.02 rad.
3. **Re-prove.** The same proof runs on the patched copy and must now print `NOT_REPRODUCED`; a
   code patch that fails gets the output back for one more try. Robots repeat until the sweep is
   clear, up to three rounds, and report the travel the joint gives up.
4. **Review.** Nemotron reads the diff and rejects a patch that deletes the feature, special-cases
   the proof's inputs or swallows the error.

`/api/prove` signs every proof it writes and runs; `/api/fix` only re-runs scripts carrying that
signature, so the browser cannot hand the sandbox code of its own.

Measured 2026-09-28 on the live site: SO101 `so101_new_calib.urdf`, `elbow_flex` upper limit
1.69 → 1.4901 rad, every joint clear on the re-run, 11.5° of travel given up (fix step 39 s).
fastapi-cli: a malformed `pyproject.toml` crashed the CLI; the patch catches
`tomllib.TOMLDecodeError` and the proof no longer reproduces (48 s). An encoding claim was
patched twice, the proof stayed inconclusive, and it is reported as **not fixed**.

We also tried proving each claim three times with a majority vote. On fastapi-cli it did not
make verdicts more repeatable (the same 8 claims proved twice: 4/8 identical either way) and one
claim took 361 s, past the 300 s a serverless call gets, so it is off by default
(`POLYJURY_PROOFS`, `polyjury/consensus.py`). The control run is what keeps a fix honest.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env          # NEBIUS_API_KEY, NEBIUS_PROJECT_ID

# command line
python scripts/polyjury_run.py https://github.com/owner/repo

# web app
uvicorn app.server:app --reload
```

## Use it from your AI (Claude Code, Codex)

`clients/polyjury_mcp.py` is a single-file MCP server, standard library only. It drives the
public site step by step, so your assistant gets the same verdict the web page shows. Point it
at a repository or at one folder (`https://github.com/owner/repo/tree/main/some/folder`).

```bash
# Claude Code
claude mcp add polyjury -- python /path/to/clients/polyjury_mcp.py

# Codex: ~/.codex/config.toml
[mcp_servers.polyjury]
command = "python"
args = ["/path/to/clients/polyjury_mcp.py"]
tool_timeout_sec = 600

# or without an assistant
python clients/polyjury_mcp.py --once https://github.com/owner/repo/tree/main/some/folder
```

Then ask: *"Run polyjury_verify on my repo and fix only what it confirmed."* It runs on the
demo's credits, so it reads public GitHub code only. Set `POLYJURY_URL` to use your own
deployment.

## How it is put together

| Module | Job |
| --- | --- |
| `polyjury/collect.py` | pull a public repo, pick the files worth reviewing |
| `polyjury/panel.py` | jurors review in parallel; prose answers are normalised to JSON |
| `polyjury/chair.py` | Nemotron merges claims, writes each proof, repairs it if it will not parse |
| `polyjury/runner.py` | Sandboxes, or a local subprocess when you ask for it |
| `polyjury/fix_code.py`, `fix_robot.py` | the fix loop: control run, patch, re-prove, review |
| `polyjury/proofcheck.py` | checks that a "ran it" proof really ran the repository's code |
| `polyjury/github_folder.py` | fetches one folder of a repository instead of the whole zipball |
| `clients/polyjury_mcp.py` | MCP server for Claude Code, Codex and other assistants |
| `polyjury/sources.py` | Tavily finds the standard or documentation that names the defect |
| `polyjury/known.py` | is the defect already an issue or pull request upstream? GitHub + Tavily, judged by Nemotron |
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

## Already known upstream?

A reproduced defect is worth an issue only if nobody has filed one. For every claim that
reproduced, Nemotron writes the two queries a maintainer would type into that repository's
tracker — the joint, the function, the option, the error text, not "bug" — and both the
repository's own issues and pull requests (GitHub search, open and closed, following renames)
and the wider web (**Tavily**: advisories, changelogs, other trackers) are searched. Nemotron
then decides whether any hit is the *same* defect, and the claim is marked **known** (an open
issue or PR), **fixed** (closed or merged), **elsewhere** (described on a web page, not in this
tracker) or **new**. A page can never make a claim "known": that word is reserved for the
repository's own tracker.

This stage exists because of a mistake. On 2026-09-28 Polyjury reproduced an actuator range
in Menagerie's SO-101 that disagreed with its joint; a title-keyword search found nothing, and
the draft report called the actuator a typo. A pull request opened the day before had already
found it — and showed the joint range was the side that had drifted. Run today, the check
returns that pull request for that claim, and issue #325 for the elbow self-collision.

## Models

Jurors: `deepseek-ai/DeepSeek-V4-Pro`, `Qwen/Qwen3-235B-A22B-Instruct-2507`, `openai/gpt-oss-120b`.
Nebius can retire a model without notice (Qwen3.5-397B vanished for an afternoon on 2026-09-27
and the site ran on two jurors until someone noticed), so when a juror answers 404 a stand-in
from `panel.BACKUP` takes its seat — called with thinking off, because with it on those models
spend the whole answer budget thinking — and the verdict says who stood in for whom.
Presiding: `nvidia/nemotron-3-super-120b-a12b` with thinking enabled — merging contradictory
reviews and writing a falsifiable test is judgement, not retrieval.

## What's next

A robot description is the first kind of hardware Polyjury can prove things about. The next
question is whether the same loop works one step earlier: an AI writes the CAD (CadQuery) and
the URDF for a wearable from a brief, and Polyjury checks the geometry against the brief. A
first experiment on AR-glasses frames showed that the build-and-load loop works and that
collision checks alone are not enough — a frame with no lens openings passes them — so the
next step is brief-derived geometric assertions plus a vision model comparing renders to the
brief.

## Licence

Apache-2.0. See [LICENSE](LICENSE).
