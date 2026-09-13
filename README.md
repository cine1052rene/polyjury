# Factdunit

**A daily detective game where fictional cases are cracked by today's real-world facts — and AI prosecutors, defenders and judges make every clue fair.**

> Status: early prototype for the Nebius × NVIDIA Global AI Hackathon (2026). Probes and design notes only; the playable app is under construction.

## Why

Misinformation spreads faster than fact-checks, and the skill that stops it — *checking the source, the date and the original context* — is rarely practiced. Research on "inoculation" games shows people get better at spotting manipulation by playing. Factdunit turns that skill into a daily habit: you can only solve the case by verifying real, current facts on the open web.

## Modes

| Mode | What you do |
|---|---|
| 🕵️ **City Case** | A fictional theft in a real city, today. One suspect's alibi collides with a real public fact (a line closure, a road shutdown, a venue closure). Search the live web to find it. |
| 🔍 **Rumor Squad** | Everyone investigates the same real circulating claim. You are scored on your *process* (Stop · Investigate the source · Find better coverage · Trace the original), not just the verdict. |
| 🌍 **Rumor Passport** | Follow one rumor as it crosses languages and countries, and see how it mutated. |

**Ground rules:** fictional people only · no real crimes, CCTV, faces or location tracking · short quotes with attribution and a link to the original source.

## How it works

```
Tavily (search / extract, date-filtered)          ← today's public facts & claims
        │
        ▼
Fact selector (Nemotron, thinking on)             ← keep only definitive, in-window facts; verify the quote exists in the page
        │
        ▼
Case writer                                        ← fictional suspects, exactly one alibi contradicted
        │
        ▼
Fair-play court                                    ← defender looks for any reasonable reading; judge (Nemotron) decides
        │                                            unfair puzzles are rejected and regenerated
        ▼
Player investigation → process scoring (SIFT rubric)
```

All model calls run on **Nebius Token Factory** (OpenAI-compatible API) using **NVIDIA Nemotron 3** models; web retrieval uses **Tavily**.

## Early measurements (Sep 2026, small samples)

- Fair-play judge (Nemotron 3 Super, thinking on) with a "reasonable reading" rule: 6/6 on a hand-labelled set of 3 fair and 3 flawed puzzles.
- Process scoring separates a thorough investigation (7–8/8) from a sloppy one (0/8).
- Quotes selected from Korean and English news verified against the extracted page text.

## Setup

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows (use bin/activate on macOS/Linux)
pip install -r requirements.txt
cp .env.example .env   # add NEBIUS_API_KEY and TAVILY_API_KEY
python scripts/list_models.py
```

## Repository layout

```
config.py              environment & model roles
core/nebius_client.py  Token Factory wrapper (OpenAI SDK)
core/tavily_client.py  Tavily wrapper
scripts/               probes: case_probe*.py, seoul_probe*.py, defense_probe.py
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).
