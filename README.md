# Claude Code for Healthcare: Multi-Agent Clinical Co-Pilot

A live-demo Python project showing how Claude Code can build a credible,
multi-agent clinical workbench in a weekend - one that augments clinicians
with six specialist agents reasoning in parallel, an orchestrator that
synthesizes their work, and a PHI-safe foundation that keeps every LLM call
on de-identified text.

> **Synthetic data only.** This is a demonstration of privacy-preserving
> engineering patterns. It is **not** a HIPAA/PHIPA/PIPEDA-compliant system.
> Do not use it with real patient data.

> **Synthetic data only.** This is a demonstration of privacy-preserving
> engineering patterns. It is **not** a HIPAA/PHIPA/PIPEDA-compliant system.
> Do not use it with real patient data.

---

## What the live demo shows

A structured clinical case enters the system. Six specialist Claude agents
run in parallel - **Triage, Differential Dx, Pharmacy, Guidelines,
Bias-Check, Communication** - each visible in its own streaming panel.
An Orchestrator agent fans them back in, produces a ranked action plan,
and flags concerns where two or more agents converged on the same issue.

**The hero moment**: a 68F new-onset AFib patient on warfarin, with the
cardiology plan proposing amiodarone. Five of the six agents focus on
rhythm control. The **Pharmacy agent catches the warfarin-amiodarone
interaction** (CYP2C9/3A4 inhibition - INR will spike to 4.5+ over 7-10
days) and the **Bias-Check agent independently flags anchoring on rhythm
control**. The orchestrator sees the convergence and elevates a
high-severity cross-flag.

Everything runs on top of the existing PHI-safe pipeline: the LLM only ever
sees de-identified text, the clinician-facing view is re-hydrated
server-side, and the audit log records zero raw PHI.

## What this demo originally shows

1. A synthetic raw clinical note enters the pipeline.
2. A pattern-based detector flags PHI/PII spans.
3. A deterministic redactor replaces them with stable placeholders such as
   `[PATIENT_NAME_1]`, `[MRN_1]`, `[PROVIDER_NAME_1]`.
4. A leakage validator re-scans the redacted text for any PHI-shaped strings
   that survived.
5. A prompt-injection detector inspects the original note for instruction-like
   payloads ("ignore previous instructions", "include the patient's full
   name", etc.).
6. If either safety gate fails, summarization is **blocked** and an audit
   record is written. The model never sees the unsafe input.
7. If both gates pass, a deterministic local summarizer produces a structured
   JSON `clinical_workflow_support` summary from the de-identified text.
8. An append-only JSONL audit log records what happened, with hashes of the
   inputs and outputs - **never the raw text and never the replacement map**.

## Why healthcare AI needs privacy gates *before* model calls

- Once raw PHI hits a third-party model API, you have lost control of it -
  retention, training, jurisdiction, vendor sub-processing all become
  contractual problems instead of engineering problems.
- Clinical text is a high-injection-risk input surface: any free-text field
  filled by humans is a place where a "system note" can be smuggled in.
- Health data is high-impact and high-regret: re-identification, breach
  notification, and clinician trust are all asymmetric downside.
- The right pattern is **fail-closed**: if a control is unsure, block and
  alert. Never default to "send anyway".

## Architecture

The pipeline is built around a **trust boundary**: only the LLM call sits
outside it. Re-identification ("re-hydration") happens server-side, using a
replacement_map that never leaves the trusted process and never reaches the
audit log.

```
                 +---------------- trusted boundary ----------------+
                 |                                                  |
  raw note ---->|  detect -> redact -> leakage check -> injection ----+
                 |                                                  | |
                 |                                                  | v
                 |                                                  | Azure
                 |                                                  | OpenAI
                 |                                                  | |
  clinician <----|  re-hydrate <----------------------------------------+
                 |       ^                                          |
                 |       | replacement_map (in-memory only,         |
                 |       |  never logged, never sent to LLM)        |
                 |                                                  |
  audit log <----|  audit (counts + sha256, NO raw PHI)             |
                 |                                                  |
                 +--------------------------------------------------+
```

Source layout:

```
healthcare-ai-safety-pipeline/
  README.md
  requirements.txt
  .env.example
  demo.py                  # CLI demo (offline)
  run_web.sh               # launches the web demo on :8765
  data/
    raw/                   # synthetic input notes (committed)
    processed/             # de-identified text + summaries + audit log (generated)
  src/
    config.py
    pipeline.py            # run_pipeline (sync) + run_pipeline_streaming (async)
    deid/
      detector.py          # regex/heuristic PHI detector
      redactor.py          # deterministic placeholder redactor
      rehydrator.py        # server-side re-identification of LLM summaries
    validation/
      phi_leakage_checker.py
      prompt_injection_checker.py
    summarization/
      safe_summarizer.py   # local deterministic summarizer (no LLM call)
      llm_summarizer.py    # Azure OpenAI streaming client
    audit/
      audit_logger.py      # JSONL audit log writer
    reporting/
      console_reporter.py
  web/
    main.py                # FastAPI: REST + WebSocket
    static/
      index.html           # EMR-styled single page
      styles.css
      app.js
  tests/
    test_deid_detector.py
    test_redactor.py
    test_rehydrator.py
    test_phi_leakage_checker.py
    test_prompt_injection_checker.py
    test_pipeline.py
    test_audit_logger.py
```

## Setup

Requires Python 3.10+.

```bash
cd healthcare-ai-safety-pipeline
python -m venv .venv
source .venv/bin/activate          # on macOS/Linux
pip install -r requirements.txt
```

## Architecture (co-pilot)

```
                                    ┌─ Triage Agent ──────────┐
                                    ├─ Differential Dx Agent ─┤
  case JSON ──► [PHI-safe pipeline]─►├─ Pharmacy Agent ────────┼─► Orchestrator ──► UI
                (structured +       ├─ Guidelines Agent ──────┤  + Re-hydration
                 free-text)         ├─ Bias-Check Agent ──────┤    (server-side)
                                    └─ Communication Agent ───┘
                       │                       │                     │
                       ▼                       ▼                     ▼
                  PHI audit             6 parallel LLM         Clinician view
                                        token streams          (real names back)
```

- All six specialists run concurrently via `asyncio.gather` with 20s
  per-agent timeouts. One failing agent does not kill the others.
- Two redaction passes: a structured-field redactor walks the case dict
  (demographics, "Dr. X Y" substrings everywhere), then the existing
  free-text detector catches residual PHI in narrative fields.
- Re-hydration uses the combined replacement_map server-side. The clinician
  view contains real (synthetic) names; the LLM view contains placeholders;
  the audit log contains neither - just counts + SHA-256 hashes.

---

## Run the live web demo (recommended for stage)

The web app is the version built for the AI Tinkerers / healthtech demo. It
shows the pipeline as an animated flow inside a clinical-SaaS-style UI, with
a real (streaming) Azure OpenAI summarization step and a server-side
re-hydration stage.

```bash
cp .env.example .env          # fill in your Azure OpenAI values
./run_web.sh                  # http://localhost:8765
```

If you skip `.env`, the pipeline still runs end-to-end — it falls back to the
local deterministic summarizer and the UI surfaces a `fallback_local` badge.

### What you get in the UI

- **Patient encounter rail (left).** EMR-style worklist of the four synthetic
  notes plus a "+ Paste new note" button so the audience can drop in their
  own.
- **Tabbed canvas (centre).**
  - *Source Note* — raw note with PHI spans highlighted.
  - *Pipeline* — animated 7-stage flow with a visible **trust boundary** —
    everything except the LLM card sits inside the trusted zone.
  - *De-identified* — side-by-side raw vs redacted text, placeholders pilled.
  - *Summary* — pill toggle between **"What the LLM produced"**
    (`[PATIENT_NAME_1]`, `[MRN_1]`) and **"What the clinician sees"**
    (re-hydrated server-side, real synthetic name back).
  - *Audit Log* — live JSONL feed plus a "Verify no raw PHI" assertion that
    re-runs the same check the pytest suite does, against the live log.
- **Right rail.** **Safety Gate** toggle (with a confirmation modal when
  flipped OFF), engine selector (Azure / local), Run button, last-run card,
  and a live event-log console.

### The "danger toggle"

Flipping the **Safety Gate** to OFF shows the audience what happens when the
gates are bypassed: the raw note (PHI included) is sent straight to the LLM,
which faithfully echoes the patient name, MRN, etc. back. The audit event is
explicitly tagged `unsafe_demo_completed` and the model output is post-scanned
for PHI so the UI can quantify the leak. **Synthetic data only.**

### 5-minute live demo script (co-pilot)

| t | Action |
|---|--------|
| 0:00 | Open `http://localhost:8765`. EMR chrome + synthetic banner. One-beat: *"every LLM call in this app runs on de-identified text."* |
| 0:20 | Click **"Whitfield · 68F · new AFib + complex polypharmacy"**. Case tab - narrate: warfarin in current meds, cardiology proposes amiodarone, CKD3, prior TIA. |
| 1:00 | Click **Run Co-Pilot**. Switch to **Co-Pilot Workspace**. Six panels light yellow, then green one by one. *"Six specialist Claude agents reasoning in parallel."* |
| 2:00 | Agents complete. **Pharmacy panel shows an amber flag**. Expand it. Read the warfarin-amiodarone interaction explanation. *"The pharmacist caught what the cardiologist almost missed."* |
| 2:30 | Switch to **Plan** tab. Cross-flags panel shows multiple agents converging on the warfarin-amiodarone concern AND on guideline discordance (rate vs rhythm). Toggle to "What the LLM produced" - placeholders are visible. Toggle back to clinician view - "Eleanor Whitfield" is back. |
| 3:30 | "+ Paste a case" - take an audience case (or click another preset) and run. |
| 4:15 | **Safety & Audit** tab. Verify no raw PHI assertion - green check. *"Zero raw PHI across the audit, full agent trace."* |
| 4:45 | Close: *"Six Claude agents. One orchestrator. PHI safety as foundation. Built end-to-end with Claude Code."* |

The four preset cases each demonstrate a different reasoning pattern:
- **Whitfield (AFib)** - polypharmacy + drug-drug interaction catch
- **Singh (chest pain)** - premature closure on ACS when PE is more likely
- **Chen (headache)** - missed SAH/meningitis red flags
- **Patel (falls)** - iatrogenic cognitive decline from anticholinergic load

---

## Run the CLI demo (offline fallback / classroom)

```bash
python demo.py
```

You will see a per-note report for the four synthetic notes:

| File | Expected outcome |
| ---- | ---------------- |
| `note_safe.txt` | Completed - already PHI-light, summarized as-is. |
| `note_with_phi.txt` | Completed - PHI detected, redacted, validated, summarized. |
| `note_with_prompt_injection.txt` | **Blocked** - injection patterns detected. |
| `note_complex.txt` | Completed - many fake names/dates redacted, summarized. |

Generated artefacts land in `data/processed/`:

- `note_*.deidentified.txt` - the redacted clinical text
- `note_*.summary.json` - the structured safe summary
- `audit_log.jsonl` - append-only audit log (PHI-free)

## Run the tests

```bash
pytest -v
```

The tests prove:

- the detector finds every expected PHI category in the synthetic notes,
- the redactor produces deterministic placeholders that are stable across
  repeat surface forms,
- the leakage checker catches phones, emails, MRNs, residual `Patient: Name`
  lines, and more,
- the prompt-injection checker catches `ignore previous instructions`,
  `include the patient's full name`, `output the MRN`, and friends,
- the pipeline blocks the prompt-injection note,
- the audit log never contains any of the raw PHI strings present in the
  source notes.

## Demo flow for AI Tinkerers

A clean five-minute live walkthrough:

1. **Show `data/raw/` in the file tree** and open `note_with_phi.txt` and
   `note_with_prompt_injection.txt` so the audience sees the threat surface.
2. `python demo.py` - the console output tells the whole story:
   - safe note: clean run,
   - PHI note: detection counts, then a successful summary built from
     `[PATIENT_NAME_1]`-style placeholders,
   - injection note: `[BLOCKED]` with the matched patterns named,
   - complex note: many providers/dates handled consistently.
3. `cat data/processed/audit_log.jsonl` - point out that the entries contain
   only counts and SHA-256 hashes, no clinical text.
4. `pytest -v` - the audit-log test in particular is satisfying: it asserts
   that none of the known raw PHI strings ever appear in the log file.
5. End on the lesson: **In healthcare AI, the model is not the first step.
   The privacy and safety gate is.**

## Safety principles applied here

- **Synthetic data only.** Every name, MRN, phone, address, and health card
  number in this repo is fake.
- **Fail-closed.** Any failed validation blocks summarization.
- **Never send raw PHI to the summarizer.** The summarizer signature only
  accepts the de-identified text.
- **Don't log raw clinical text.** The audit log records counts and SHA-256
  hashes, not text. The redactor's `replacement_map` is also never written
  out, because the keys are the original PHI strings.
- **Mask leakage findings.** Even when reporting that a phone number was
  found, the audit-friendly representation is masked (`9********2`).
- **Structured JSON output.** Summaries are typed and labelled with a clear
  clinician-review disclaimer.
- **Human review.** The summary `disclaimer` field is non-optional.

## What is intentionally simplified

- The PHI detector is regex/heuristic. It will miss anything outside its
  pattern set (e.g. nicknames, free-text addresses without a street suffix,
  international ID formats, unlabelled names embedded in prose).
- The prompt-injection checker is a deterministic phrase list. Real attackers
  use obfuscation, encoding, multilingual variants, and indirect injection.
- The "summarizer" is a small set of keyword rules so the demo runs offline
  and deterministically. There is no LLM call.
- Audit logging is a single local JSONL file. Not encrypted, not append-only
  at the filesystem level, not shipped anywhere.
- There is no authentication, RBAC, key management, or network boundary.

## What production would require

- **Healthcare-specific NLP de-identification** (e.g. Microsoft Presidio with
  custom recognizers, MITRE Scrubber, Philter, or a clinical NER model
  trained on de-identification corpora) plus expert review.
- **Privacy impact assessment** appropriate to the deployment jurisdiction
  (HIPAA in the US, PHIPA / PIPEDA in Canada, GDPR in the EU).
- **Data residency review.** Where does the model run? Where do logs sit?
  Cross-border data transfer review.
- **Encryption at rest and in transit** for every store and every hop.
- **IAM and least privilege.** No human or service account should hold both
  raw-input access and model-output access by default.
- **Private networking.** Model endpoints inside a VPC/VNet with no public
  egress; signed inter-service calls.
- **Audit retention policy** with WORM storage, tamper-evidence, and
  documented deletion timelines.
- **Human-in-the-loop review** of every summary before it influences a
  clinical decision; explicit clinician sign-off captured in the audit trail.
- **Clinical safety validation** including red-team evaluation, drift
  monitoring, and an incident response runbook.
- **Monitoring and incident response** for prompt-injection telemetry,
  validation-failure rates, and unusual PHI-detection volumes.
- **Vendor agreements.** BAA (US HIPAA), DPA (GDPR), or equivalent for every
  third-party processor including the model vendor.
- **Organizational compliance review** for PHIPA/HIPAA/PIPEDA/GDPR depending
  on where patients and providers are located.

---

**Key lesson: In healthcare AI, the model is not the first step. The privacy
and safety gate is.**
