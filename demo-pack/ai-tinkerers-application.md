# AI Tinkerers — Demo Proposal (copy/paste)

Filled for Pranav Gupta, thinkaicorp. Format = **Main Stage Demo** (already selected).

---

## Talk Title (Required)

**Six Claude Agents and a Trust Boundary: A Clinical Co-Pilot Built in a Weekend**

Alt options if the first feels too long:
- *The Pharmacist Caught What the Cardiologist Missed: A Multi-Agent Co-Pilot*
- *Fan-out, Converge, Re-hydrate: Building a Multi-Agent Clinical Co-Pilot*

---

## What did you build? (Required)

A multi-agent clinical co-pilot that runs six specialist Claude agents in parallel on top of a PHI-safe pipeline — every LLM call sees only de-identified text, and re-identification happens server-side after the model returns.

Live, I'll load a synthetic 68F new-AFib case where the cardiology plan proposes amiodarone for a patient already on warfarin. The Triage, Differential, Pharmacy, Guidelines, Bias-Check, and Communication agents stream into six panels via `asyncio.gather`. The Pharmacy agent flags the warfarin–amiodarone CYP2C9/3A4 interaction; Bias-Check independently flags anchoring on rhythm control; the orchestrator detects the cross-agent convergence and elevates it as a high-severity flag. I'll then toggle the *Safety Gate* off so the audience sees raw PHI hit the LLM and get echoed back — then flip it on and show the audit log assertion (zero raw PHI, only counts + SHA-256 hashes). I'll show the FastAPI/WebSocket code that fans out the agents, the trust-boundary diagram, the structured-field redactor, the live audit log tail, and the keystone pytest (`test_pharmacy_catches_warfarin_amiodarone`). Repo, logs, and 35/35 passing tests are all open.

---

## What will another builder learn? (Required)

Three hard-won things, none of them domain-specific:

1. **Cross-agent convergence is a better signal than any single agent's confidence.** I spent the first iteration tuning a single "supervisor" agent and it kept under- or over-flagging. The unlock was cheaper: run N specialists in parallel, then have the orchestrator look for the same concern surfacing from ≥2 independent agents. The Pharmacy/Bias-Check overlap on the warfarin case is the entire demo, and it falls out of dumb set intersection — no extra prompting, no judge model.

2. **Put the trust boundary inside the process, not at the API.** I almost shipped a version where redaction was a separate microservice. Keeping the `replacement_map` in-process memory (never logged, never serialized, never sent to the LLM) made the audit story dramatically simpler and the re-hydration step a 5-line function instead of a service contract. The lesson generalizes to any LLM app handling sensitive strings.

3. **Always ship a deterministic offline twin.** `asyncio.gather` with a 20s per-agent timeout means one slow agent doesn't kill the run — but the venue Wi-Fi will. I built an offline simulator that produces the exact same UI states from canned outputs so the stage demo can't fail. Cost: ~2 hours. Anxiety saved: a lot.

---

## Technologies Used (Required)

- **Azure OpenAI (GPT-4o deployment)** — the six specialist agents and the orchestrator. Streaming responses over WebSocket. Chose Azure over Anthropic direct only because of the BAA story I want to be able to point at on stage; the prompt layer is provider-agnostic.
- **Claude Code (Sonnet + Opus)** — the entire codebase was built with Claude Code. Sonnet for the per-agent prompts and FastAPI wiring; Opus for the orchestrator convergence logic and the redaction trust-boundary design. I'll show the `CLAUDE.md` and a couple of prompts that mattered.
- **Python + `asyncio.gather`** — parallel agent fan-out with per-agent timeouts so one slow stream doesn't block the others.
- **FastAPI + WebSockets** — six concurrent token streams to six UI panels, plus a live audit-log tail.
- **Vanilla JS + a single `index.html`** — no React, no build step. The whole UI is one static file; everything interesting is on the server.
- **Regex/heuristic PHI detector + deterministic placeholder redactor** — built in-house. Not Presidio; the demo's point is that the *pattern* matters more than the library.
- **Append-only JSONL audit log** — counts and SHA-256 hashes only, never raw text, never the replacement map. There's a pytest that asserts no known PHI string ever appears in the log.
- **pytest (35 tests)** — including the keystone `test_pharmacy_catches_warfarin_amiodarone` that I'll run live.

---

## Project URL — Website or Github (Optional)

*(Pranav: paste your GitHub repo URL here once it's pushed. If it's still local-only, leave blank and rely on the Video Demo URL.)*

Suggested: `https://github.com/<your-handle>/healthcare-ai-safety-pipeline`

---

## Project URL 2 (Optional)

Leave blank, or paste a link to a short write-up if you publish one on your thinkaicorp blog.

---

## Video Demo URL (Optional)

*(Paste the Loom URL once recorded. The local server is already running on `http://127.0.0.1:8765` — see "Loom recording script" below.)*

---

## Checkbox — REQUIRED

☑ **I agree to show the technical work behind what I built — live demo, architecture, evals, logs/traces, workflow, or repo. No pitches, no slides.**

---

# Loom recording script (≤4 minutes)

Open `http://127.0.0.1:8765` in a clean browser window. Screen + webcam.

| t | Action | What to say |
|---|---|---|
| 0:00 | EMR-styled UI loads. Point at the "synthetic data only" banner. | "Multi-agent clinical co-pilot. Every LLM call in this app runs on de-identified text. I'll show you why that matters and how the agents reason together." |
| 0:20 | Click **Whitfield · 68F · new AFib + complex polypharmacy**. Show the Case tab. | "68-year-old, new atrial fibrillation, already on warfarin, cardiology proposes amiodarone. Six Claude specialists are about to look at this in parallel." |
| 0:50 | Click **Run Co-Pilot**. Switch to **Co-Pilot Workspace**. Six panels stream. | "Triage, Differential, Pharmacy, Guidelines, Bias-Check, Communication. `asyncio.gather`, 20-second per-agent timeout, six concurrent token streams over WebSockets." |
| 1:40 | Pharmacy panel shows amber flag. Expand it. | "Pharmacy caught the warfarin–amiodarone interaction. CYP2C9 and 3A4 inhibition, INR projected to spike to 4.5+ over 7-10 days. The cardiologist's plan didn't account for it." |
| 2:00 | Switch to **Plan** tab. Cross-flags panel. | "The orchestrator sees Pharmacy and Bias-Check converging on the same case from different angles. That convergence is the high-severity signal — not any single agent's confidence." |
| 2:20 | Toggle "What the LLM produced" → "What the clinician sees". | "LLM only ever saw `[PATIENT_NAME_1]`. Re-hydration happens server-side from a `replacement_map` that never leaves the process and never hits the audit log." |
| 2:45 | Flip **Safety Gate OFF**. Confirm modal. Re-run. | "Watch what happens with the gates off." (PHI appears in the LLM output.) "Audit event tagged `unsafe_demo_completed`, post-scan quantifies the leak. This is why fail-closed matters." |
| 3:15 | Flip Safety Gate ON. Open **Safety & Audit** tab. Click "Verify no raw PHI". | "Audit log is JSONL — counts and SHA-256 only. Pytest asserts no known PHI string ever appears in there. Green check." |
| 3:35 | Drop to terminal. `.venv/bin/pytest tests/test_agents.py -v -k warfarin`. | "And here's the keystone test — the one that asserts the Pharmacy agent catches this specific interaction. 35 of 35 passing." |
| 3:55 | Back to UI. Close on the trust-boundary diagram if you've got slides open in the README; otherwise close on the audit log. | "Six Claude agents, one orchestrator, PHI safety as the foundation. Built end-to-end with Claude Code in a weekend. See you at the meetup." |

**Recording tips:**
- Hide the browser bookmarks bar.
- Pre-load the homepage so the first frame isn't a spinner.
- Have the terminal already at the repo root with the venv active.
- Open the README in a second tab pre-scrolled to the architecture diagram for the closing shot, *only if* you want a static visual; otherwise stay in the running app.

---

# Server is already running

```
http://127.0.0.1:8765
```

Started via `./run_web.sh` from the repo root. To stop: `lsof -ti:8765 | xargs kill`.
