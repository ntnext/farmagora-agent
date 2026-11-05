# Farmagorà · Flyer-to-Everything agent

Every month Farmagorà prints a flyer PDF with its offers. This agent turns that PDF into everything the month needs:

- **12 social posts and 6 stories**, with captions and hashtags
- **12 slides for the in-store screens**
- **a publishing calendar**

A person approves twice: first the data, then the content. **Nothing is published automatically**: the final files are ready to upload by hand.

## How it works, simply

The approver only uses a **Google Drive folder**, in the browser. No program to install, no terminal.

```
Volantini Farmagorà/
└── Volantino gennaio/
    ├── volantino.pdf                  ← 1. you drop the flyer here
    ├── DA APPROVARE - dati.txt        ← 2. what to check, then rename to "APPROVATO - dati.txt"
    ├── Revisione.xlsx                 ← correct data / ask for changes (opens in Google Sheets)
    ├── DA APPROVARE - contenuti.txt   ← 3. rename to "APPROVATO - contenuti.txt"
    └── Risultati agente/              ← everything the agent makes
        ├── 1 - Dati letti dal volantino/   Controlla i dati.pdf
        ├── 2 - Contenuti da approvare/     Post/, Storie/, Schermi/, Didascalie.md, Calendario.csv, Controlla i contenuti.pdf
        └── 3 - Pronto da pubblicare/       final images + captions + calendar + zip
```

| Step | Who | What happens |
| --- | --- | --- |
| 1. Drop | Approver | Puts the flyer PDF in `Volantini Farmagorà` (in its own folder, or loose: the agent makes the folder). |
| 2. Read | Agent, ~1–2 min | The AI reads every product, price, discount and date. **Code then checks it all**: discount maths, every price is really printed in the PDF, medicines found by the symbol on the card. Writes `Controlla i dati.pdf`, `Revisione.xlsx` and `DA APPROVARE - dati.txt` with the points to check. |
| 3. Check the data | Approver, ~10 min | Compares the report with the flyer. If something is wrong, fixes the **yellow cells** in `Revisione.xlsx` → tab `Prodotti`. Within a minute the agent applies the fix and checks everything again (a wrong fix is blocked like a wrong reading). When it's right: rename to **`APPROVATO - dati.txt`**. With blocking problems the approval is refused and the file comes back with the reasons. |
| 4. Create | Agent, ~2–3 min | Plans the month (teaser on day one, products, last call), the AI writes the texts, code fills in prices and dates and adds the mandatory warnings, compliance rules check every text, then the images are drawn. |
| 5. Check the content | Approver, ~15 min | Looks at the images. To change one, writes what they want (e.g. `più breve`) in the yellow **"Modifica richiesta"** column of tab `Contenuti`; the agent rewrites only that item and redraws its image. When it's right: rename to **`APPROVATO - contenuti.txt`**. |
| 6. Ready | Agent | Copies everything, with a zip, into `3 - Pronto da pubblicare/`. Upload to social networks and screens stays manual. |

If something goes wrong (e.g. the AI service is busy or out of free quota), the agent writes `ERRORE.txt` in the folder, sends a Mac notification and retries by itself. Replacing the PDF starts over and cancels the old approvals; dropping the **same** PDF again reuses the earlier reading (no new AI call).

### Where it runs

- **Demo (now):** `flyer watch` runs on one Mac and talks to **Google Drive online** through the Drive API: no Drive desktop app anywhere. The approver uses only Drive in the browser. Each check (every 30 s) the agent brings down what the approver changed (new PDF, renamed approval file, edited sheet), works on a private copy on the Mac, and sends the results back up. It works while the Mac is on and `flyer watch` runs; if it stops, it catches up when restarted.
- **Production (if the client approves):** the same agent on a small server (e.g. Google Cloud Run, about €0–10/month), plus email notifications. See PLAN.md §14.

### What the AI does and what the code guarantees

The AI **reads** the flyer and **writes** the texts. Everything that must be exactly right is done or checked by code:

- Prices, old prices, discounts and dates in every output come from the approved data. The AI writes placeholders (`{price:<id>}`, `{valid_to}`); any number it writes itself is blocked.
- Discount check with Farmagorà's rule: printed % = computed % rounded down. Products sharing a price card must share the price.
- Medicines are found by the symbol printed on the card, not by the AI. A medicine missing its flag, or a known medicine brand marked as something else, is blocked.
- Medicines, My Agorà-only prices and loyalty small print get the mandatory text automatically and are listed for manual review.
- Forbidden health claims (`cura`, `guarisce`, `previene`… in `config/compliance.yaml`) are blocked.
- No step passes an approval without an approval record in the run's `manifest.json`, which also logs every correction, AI call, token count and cost.

## Set up the Drive folder (demo)

1. `pip install -e ".[all,dev]"` and `playwright install chromium` (see Quick start below).
2. Put the keys in `.env`: `GEMINI_API_KEY` (reads the flyer) and `GROQ_API_KEY` (writes the texts). Free tiers are enough for a demo.
3. In Drive (browser), create `Volantini Farmagorà` in **Il mio Drive** (name set in `drive.api_folder`).
4. Give the agent access to Drive, once (Google account that owns the folder):
   1. console.cloud.google.com → new project (e.g. `farmagora-flyer-agent`) → enable **Google Drive API**.
   2. Menu → **Google Auth platform** → **Branding** → app name, support email → Audience **Internal** → contact email → agree → Create.
   3. **Google Auth platform** → **Clients** → **Create Client** → type **Desktop app** → Create → **Download JSON**.
   4. Save it as `credentials.json` in the project folder (secret: gitignored, like `.env`).
5. Run `flyer watch` (`drive.mode: api` in `config/app.yaml`). The first time a browser window asks you to sign in and allow access; the token is saved in `.secrets/` (gitignored) and refreshed by itself. Leave it running (`--once` for a single pass).

The agent acts as your account (OAuth), so every file it creates belongs to you. A Google "service account" is not used: it has no storage of its own and cannot create files in a My Drive folder (only in a Shared Drive).

Older alternative: `drive.mode: sync` (or `flyer watch --local`) works on a folder synced to the Mac by Google Drive for desktop (`drive.watch_dir`). It is less reliable: the desktop app can stop syncing after the Mac sleeps.

### Free-tier limits (demo)

- **Gemini** (reading): about 20 requests per day per model; one flyer = one request. The quota resets around 09:00 Italian time. When it runs out, the agent waits an hour and tries again. `gemini-3.8-flash` scored 100% on the hand-checked flyer; `gemini-3.5-flash-lite` (current setting) has its own quota and read the January flyer with no blocking issues, but has not been scored.
- **Groq** (texts): 8,000 tokens per minute, so posts are written 6 at a time (`batch_size` in `config/app.yaml`), and "too many tokens this minute" is retried after a pause. Groq cannot read the flyer itself on the free tier (images are too big).
- On paid tiers both limits go away, at about **€0.10 per flyer**.

Tip for the demo: do a full run the day before, so a busy or exhausted free tier cannot spoil the recording (DEMO.md).

## Quick start for developers (no API key needed)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[all,dev]"
playwright install chromium
flyer --provider offline run tests/fixtures/flyers/2026-10_ottobre-novembre_tieni-alte-le-difese.pdf --yes
```

Open `runs/<id>/review.html`. Images are in `runs/<id>/out/` and zipped in `runs/<id>/export/`. With `--provider offline` the flyer is "read" from the hand-checked golden file of the Oct–Nov 2026 fixture and the texts come from Italian templates: the full flow without any API key. A new flyer **needs a real provider** for reading.

## Choose the AI provider

Provider, model and temperature are set per task (`extract`, `copy_social`, `copy_screens`) in `config/app.yaml`:

```yaml
extract:     { provider: gemini, model: gemini-3.8-flash, temperature: 0 }
copy_social: { provider: groq,   model: openai/gpt-oss-120b, temperature: 0.7, batch_size: 6 }
```

or override everything for one command: `flyer --provider openai --model <id> run volantino.pdf`.
Providers: `anthropic`, `openai`, `gemini`, `groq`, `openai_compatible` (Mistral, Ollama, vLLM… set `base_url`), `offline`. Models that accept only a few images per request (`max_images`) read the flyer in page batches merged automatically. Busy servers (5xx) and per-minute rate limits are retried after 10, 30 and 60 s; daily quotas are not. Costs come from `config/pricing.yaml`.

## Terminal commands (same steps, for developers)

```bash
flyer ingest volantino.pdf        # creates runs/<id>/, renders pages, text layer, medicine symbols, photos
flyer extract                     # AI reads the flyer -> flyer_data.json + validation + review.html
flyer validate                    # re-run the data checks after editing runs/<id>/flyer_data.json
flyer approve-data                # Gate 1 (refused if blocking issues)
flyer generate                    # code plans the month, AI writes texts with placeholders only
flyer check                       # compliance rules
flyer regen --item post-03 --note "più breve"   # rewrite one post, story or screen (e.g. screen-07)
flyer render                      # PNGs + calendar.csv
flyer approve-pack                # Gate 2
flyer export                      # zip for manual upload
flyer status                      # state, history, provider/model/tokens/cost per call
flyer score                       # reading accuracy vs the hand-checked golden file (no AI call)
flyer eval --providers gemini:gemini-3.8-flash,anthropic:claude-sonnet-5-5   # compare providers
flyer watch                       # the Drive folder agent described above
```

Commands act on the latest run; pass a run id prefix to target another one.

## Project layout

See PLAN.md §4. Pure logic in `src/flyer_agent/core` (validation, planning, compliance, folder workflow `folder_flow.py`, review spreadsheet `review_sheet.py`, Drive mirror planning `mirror.py`), AI providers in `src/flyer_agent/adapters/llm`, PDF/Excel/rendering in `src/flyer_agent/adapters`, the stages and the Drive watcher in `src/flyer_agent/stages` (`pipeline.py`, `watch.py`, `drive_sync.py`; Google Drive connector in `adapters/gdrive.py`), templates in `templates/` (HTML + CSS, editable by a designer), prompts in `prompts/`.

## Tests

`pytest` (78 tests, no real AI or Google calls): unit (validation, placeholders, planning, state machine, folder decisions, spreadsheet edits), contract (AI adapters, retries), integration (full offline pipeline with rendering, medicine symbols, photos, and the whole Drive folder flow: drop → sheet correction → approvals → change request → export, both on a local folder and on a fake online Drive). Also `ruff check` and `mypy src/flyer_agent/core`.

## Status and known limits

- **Done:** reading checked at 100% (name, prices, badges, 51/51 medicines) on the hand-checked Oct–Nov 2026 flyer; Drive folder workflow tested end to end on a real Drive with the January 2026 flyer (sheet corrections, both approvals, export).
- **Not yet tried on a real Drive:** a change request from the `Contenuti` tab (covered by the automated test).
- The May 2026 and Jul–Aug 2025 answer keys (`*.golden.draft.json`) wait for a hand-check.
- Demo runs on one Mac: if the Mac sleeps or `flyer watch` stops, nothing happens until it restarts (then it catches up). No email yet, only Mac notifications (seen by whoever runs the agent).
- Drive API mode: live-tested on 5 Nov 2026 with the February 2026 flyer, browser only (approval → content → approval → export), and existing folders adopted without redoing work. A change request from the `Contenuti` tab is covered by the automated tests but not yet tried live.
- If the approver and the agent save `Revisione.xlsx` at the same moment, the later save wins; the agent only rewrites it between steps.
- Fonts: Montserrat + Caveat (open fonts) stand in for the brand fonts until we receive them.
