# Farmagorà · Flyer-to-Everything agent

Every month Farmagorà prints a flyer (a PDF) with its offers. This agent turns that PDF into everything the month needs:

- **12 social posts and 6 stories**, with captions and hashtags
- **12 slides for the in-store screens**
- **a publishing calendar** (which post goes out on which day)

A person approves the work twice: first the data the agent read from the flyer, then the finished content.

**Nothing is published automatically.** The final files are left in a folder, ready to upload to social networks and screens by hand.

---

## Contents

1. [How it works](#1-how-it-works)
2. [For the approver: using it from Google Drive](#2-for-the-approver-using-it-from-google-drive)
3. [Set up the agent on a Mac (step by step)](#3-set-up-the-agent-on-a-mac-step-by-step)
4. [Run it](#4-run-it)
5. [Try it without any key or Google account](#5-try-it-without-any-key-or-google-account)
6. [What the AI does and what the code guarantees](#6-what-the-ai-does-and-what-the-code-guarantees)
7. [Choose the AI provider](#7-choose-the-ai-provider)
8. [Free-tier limits](#8-free-tier-limits)
9. [Terminal commands for developers](#9-terminal-commands-for-developers)
10. [Troubleshooting](#10-troubleshooting)
11. [Project layout and tests](#11-project-layout-and-tests)
12. [Status and known limits](#12-status-and-known-limits)

---

## 1. How it works

There are two sides:

- **The approver** (e.g. the marketing manager) only uses a **Google Drive folder in the browser**. They install nothing and never open a terminal.
- **The agent** is a program running on one Mac. It checks that Drive folder every 30 seconds, does the work, and puts the results back into the same folder.

The approver talks to the agent by **dropping files** and **renaming files** in Drive.

```
Volantini Farmagorà/                     ← the shared folder in "Il mio Drive"
└── Volantino gennaio/                   ← one folder per flyer
    ├── volantino.pdf                    ← 1. the approver drops the flyer here
    ├── DA APPROVARE - dati.txt          ← 2. check the data, then rename it to "APPROVATO - dati.txt"
    ├── Revisione.xlsx                   ← fix data or ask for changes (opens in Google Sheets)
    ├── DA APPROVARE - contenuti.txt     ← 3. check the content, then rename it to "APPROVATO - contenuti.txt"
    └── Risultati agente/                ← everything the agent makes
        ├── 1 - Dati letti dal volantino/   Controlla i dati.pdf
        ├── 2 - Contenuti da approvare/     Post/, Storie/, Schermi/, Didascalie.md, Calendario.csv, Controlla i contenuti.pdf
        └── 3 - Pronto da pubblicare/       final images + captions + calendar + a .zip of everything
```

| Step | Who | What happens |
| --- | --- | --- |
| 1. Drop | Approver | Puts the flyer PDF into `Volantini Farmagorà`. It can go in its own folder, or loose in the main folder (the agent then makes a folder for it). |
| 2. Read | Agent, ~1–2 min | The AI reads every product, price, discount and date. **Then code checks all of it**: the discount maths, that every price really appears in the PDF, and which products are medicines (found by the symbol printed on the card). It writes `Controlla i dati.pdf`, `Revisione.xlsx` and `DA APPROVARE - dati.txt`, which lists the points to check. |
| 3. Check the data | Approver, ~10 min | Compares the report with the flyer. If something is wrong, fixes the **yellow cells** in `Revisione.xlsx`, tab `Prodotti`. Within a minute the agent applies the fix and checks everything again (a wrong fix is blocked just like a wrong reading). When everything is right, renames the file to **`APPROVATO - dati.txt`**. If there are still blocking problems, the agent refuses the approval and the file comes back with the reasons. |
| 4. Create | Agent, ~2–3 min | Plans the month (a teaser on day one, then the products, then a last call). The AI writes the texts; code fills in prices and dates and adds the mandatory warnings; compliance rules check every text; then the images are drawn. |
| 5. Check the content | Approver, ~15 min | Looks at the images. To change one, writes the request (e.g. `più breve`) in the yellow **"Modifica richiesta"** column of the `Contenuti` tab. The agent rewrites only that item and redraws its image. When everything is right, renames the file to **`APPROVATO - contenuti.txt`**. |
| 6. Ready | Agent | Copies everything, with a .zip, into `3 - Pronto da pubblicare/`. Uploading to social networks and screens stays manual. |

Good to know:

- If something goes wrong (for example the AI service is busy or out of free quota), the agent writes **`ERRORE.txt`** in the flyer folder, shows a Mac notification, and tries again by itself.
- **Replacing the PDF** with a different one starts over and cancels the old approvals.
- Dropping the **same** PDF again reuses the earlier reading, with no new AI call.

---

## 2. For the approver: using it from Google Drive

You only need a browser and access to the `Volantini Farmagorà` folder.

1. Open Google Drive and go to **Il mio Drive → Volantini Farmagorà**.
2. Drag the new flyer PDF into the folder.
3. Wait 2–3 minutes. A folder with the flyer's name appears, with `DA APPROVARE - dati.txt` inside.
4. Open `Risultati agente/1 - Dati letti dal volantino/Controlla i dati.pdf` and compare it with the flyer.
5. Something wrong? Open `Revisione.xlsx` (it opens in Google Sheets), go to the **`Prodotti`** tab and fix the **yellow** cell. Wait about a minute: the report is updated.
6. All correct? Right-click `DA APPROVARE - dati.txt` → **Rinomina** → type `APPROVATO - dati.txt`.
7. Wait 2–3 minutes. The posts, stories and screen slides appear in `Risultati agente/2 - Contenuti da approvare/`.
8. Want a change? In `Revisione.xlsx`, **`Contenuti`** tab, write what you want in the yellow **"Modifica richiesta"** column on that item's row (e.g. `più breve`, `tono più allegro`). The column next to it changes to say the request was applied.
9. All good? Rename `DA APPROVARE - contenuti.txt` to `APPROVATO - contenuti.txt`.
10. The final files are in `Risultati agente/3 - Pronto da pubblicare/`. Download them and upload them by hand.

If you see `ERRORE.txt`, open it: it says what went wrong in plain Italian. Usually you just wait; the agent tries again by itself.

---

## 3. Set up the agent on a Mac (step by step)

You do this **once**, on the Mac that will run the agent. It takes about 30 minutes.

### 3.1 What you need

| Thing | Why | How to check |
| --- | --- | --- |
| A Mac (macOS) | Runs the agent | — |
| **Python 3.12** | The agent is written in Python | In Terminal: `python3 --version` should print `Python 3.12.x` |
| **git** | To download the project | `git --version` |
| A **Google account** | Owns the Drive folder | — |
| A **Gemini API key** (free) | The AI that reads the flyer | Get one at <https://aistudio.google.com/apikey> |
| A **Groq API key** (free) | The AI that writes the texts | Get one at <https://console.groq.com/keys> |

To open **Terminal**: press `Cmd + Space`, type `Terminal`, press Enter. Every command below is typed there, followed by Enter.

If Python 3.12 is missing, the easiest way is [Homebrew](https://brew.sh): install it, then run `brew install python@3.12 git`.

### 3.2 Download the project

```bash
cd ~/Documents
git clone https://github.com/ntnext/farmagora-agent.git
cd farmagora-agent
```

From now on, **every command is run from inside this folder** (`cd ~/Documents/farmagora-agent` if you open a new Terminal window).

### 3.3 Install it

```bash
python3.12 -m venv .venv            # creates a private Python environment in the ".venv" folder
source .venv/bin/activate           # turns it on: your prompt now starts with (.venv)
pip install -e ".[all,dev]"         # installs the agent and everything it needs (a few minutes)
playwright install chromium         # downloads the browser used to draw the images
```

Check that it worked:

```bash
flyer --help
```

You should see a list of commands. If you get `command not found: flyer`, you forgot `source .venv/bin/activate`. You need to run that line **every time you open a new Terminal window**.

### 3.4 Put the API keys in `.env`

Create a file named `.env` in the project folder:

```bash
touch .env && open -e .env        # creates the file and opens it in TextEdit
```

Paste these two lines, replacing the placeholders with your real keys, then save:

```
GEMINI_API_KEY=your-gemini-key-here
GROQ_API_KEY=your-groq-key-here
```

No spaces around `=`, no quotes. `.env` is secret: it is in `.gitignore`, so git never uploads it. **Never share it, and never paste keys anywhere else.**

### 3.5 Create the folder in Google Drive

1. Open <https://drive.google.com> with the Google account that will own the folder.
2. In **Il mio Drive** (My Drive, the top level, not inside another folder) create a folder named exactly **`Volantini Farmagorà`** (with the accent on the `à`).
3. Share it with the approver: right-click → **Condividi** → their email → **Editor**.

The folder name is set in `config/app.yaml` (`drive.api_folder`). If you use a different name, change it there too.

### 3.6 Let the agent use Google Drive (once)

The agent needs permission to read and write files in your Drive. Google calls this an "OAuth client". Do it with the **same Google account** that owns the folder.

1. Go to <https://console.cloud.google.com>.
2. At the top, click the project selector → **New project** → name it e.g. `farmagora-flyer-agent` → **Create**. Make sure the new project is selected.
3. Search bar → **Google Drive API** → **Enable**.
4. Menu (☰) → **Google Auth platform** → **Branding** → **Get started**:
   - App name: `Farmagora flyer agent`; support email: yours → Next.
   - Audience: **Internal** (if you can't pick it, as with a personal Gmail account, pick **External** and add yourself under **Audience → Test users**) → Next.
   - Contact email: yours → Next → agree → **Create**.
5. **Google Auth platform** → **Clients** → **Create client**:
   - Application type: **Desktop app**; name: anything → **Create**.
   - Click **Download JSON**.
6. Move the downloaded file into the project folder and rename it to exactly **`credentials.json`**:

   ```bash
   mv ~/Downloads/client_secret_*.json ~/Documents/farmagora-agent/credentials.json
   ```

`credentials.json` is secret too and is in `.gitignore`.

The agent acts **as your account**, so every file it creates belongs to you. A Google "service account" is not used: it has no storage of its own and cannot create files in a My Drive folder.

---

## 4. Run it

```bash
cd ~/Documents/farmagora-agent
source .venv/bin/activate
flyer watch
```

- **The first time**, a browser window opens: pick your Google account and click **Allow**. If Google says the app isn't verified, click **Advanced → Go to …**: it's your own app. A token is saved in `.secrets/google-token.json` (secret, gitignored) and renewed by itself, so this only happens once.
- You then see: `Controllo la cartella Drive 'Volantini Farmagorà' online ogni 30 s. Ctrl+C per fermare.`
- **Leave the Terminal window open.** The agent only works while it runs. To stop it, press `Ctrl + C`. When you start it again, it catches up on anything that happened while it was off.
- Keep the Mac awake: **System Settings → Displays / Battery → prevent automatic sleeping** while it runs, or start it with `caffeinate -i flyer watch`.

Useful variants:

| Command | What it does |
| --- | --- |
| `flyer watch` | Checks the Drive folder every 30 s, forever |
| `flyer watch --once` | Checks once and exits (handy to test) |
| `flyer watch --local` | Old mode: works on a folder synced to the Mac by the Google Drive desktop app (`drive.watch_dir` in `config/app.yaml`). Less reliable: the desktop app can stop syncing after the Mac sleeps. |

How it talks to Drive: on each check the agent downloads what the approver changed (new PDF, renamed approval file, edited sheet), works on a private copy on the Mac (in `runs/drive-cache/`), and uploads the results. It never overwrites a file the approver changed in the meantime.

---

## 5. Try it without any key or Google account

To see the whole flow on your Mac with no API key, use the `offline` provider on the sample flyer included in the project:

```bash
source .venv/bin/activate
flyer --provider offline run tests/fixtures/flyers/2026-10_ottobre-novembre_tieni-alte-le-difese.pdf --yes
```

Then open the results:

```bash
open runs/                      # each run is a folder named runs/<id>/
```

- `runs/<id>/review.html`: the review page (double-click to open it in the browser)
- `runs/<id>/out/`: the images
- `runs/<id>/export/`: the final .zip

In `offline` mode the flyer is not really read by an AI: the data comes from a hand-checked answer file for that sample flyer, and the texts come from Italian templates. It works **only for the sample flyers in `tests/fixtures/flyers/`**. A new flyer needs a real AI provider.

---

## 6. What the AI does and what the code guarantees

The AI **reads** the flyer and **writes** the texts. Everything that must be exactly right is done or checked by code:

- **Prices, old prices, discounts and dates** in every output come from the approved data. The AI only writes placeholders such as `{price:<product-id>}` and `{valid_to}`, and code fills them in. Any number the AI writes on its own is blocked.
- **Discount check** with Farmagorà's rule: the printed % equals the computed % rounded down. Products sharing a price card must share the price.
- **Medicines** are found by the symbol printed on the card, not by the AI. A medicine missing its flag, or a known medicine brand marked as something else, is blocked.
- Medicines, **My Agorà-only prices** and loyalty small print get the mandatory text automatically and are listed for manual review.
- **Forbidden health claims** (`cura`, `guarisce`, `previene`… listed in `config/compliance.yaml`) are blocked.
- **No step passes an approval** without an approval record in the run's `manifest.json`, which also logs every correction, AI call, token count and cost.

---

## 7. Choose the AI provider

Each task can use a different provider and model. They are set in `config/app.yaml`:

```yaml
extract:     { provider: gemini, model: gemini-3.8-flash, temperature: 0 }      # reads the flyer
copy_social: { provider: groq,   model: openai/gpt-oss-120b, temperature: 0.7, batch_size: 6 }   # writes posts and stories
copy_screens:{ provider: groq,   model: openai/gpt-oss-120b, temperature: 0.7 }  # writes the screen slides
```

To switch, change one line; no code changes are needed. Each provider needs its key in `.env`:

| Provider | Key in `.env` |
| --- | --- |
| `gemini` | `GEMINI_API_KEY` |
| `groq` | `GROQ_API_KEY` |
| `anthropic` | `ANTHROPIC_API_KEY` |
| `openai` | `OPENAI_API_KEY` |
| `openai_compatible` (Mistral, Ollama, vLLM…; set `base_url`) | `OPENAI_COMPATIBLE_API_KEY` |
| `offline` | none |

To override everything for one command: `flyer --provider openai --model <model-id> run volantino.pdf`.

Models that accept only a few images per request (`max_images`) read the flyer a few pages at a time, and the parts are merged automatically. Busy servers (errors 5xx) and per-minute limits are retried after 10, 30 and 60 s; daily quotas are not. Costs are computed from `config/pricing.yaml`.

---

## 8. Free-tier limits

Free tiers are enough for a demo, with these limits:

- **Gemini** (reading): about 20 requests per day per model. One flyer = one request. The quota resets around 09:00 Italian time. When it runs out, the agent writes `ERRORE.txt` and tries again an hour later.
- **Groq** (texts): 8,000 tokens per minute, so posts are written 6 at a time (`batch_size` in `config/app.yaml`). "Too many tokens this minute" errors are retried after a pause. Groq can't read the flyer itself on the free tier (the images are too big).
- On **paid tiers** both limits go away, for about **€0.10 per flyer**.

**Tip before a demo:** do a full run the same day or the day before, so a busy or exhausted free tier can't spoil it (see `DEMO.md`).

---

## 9. Terminal commands for developers

The Drive agent runs these same steps by itself. You can also run them one by one:

```bash
flyer ingest volantino.pdf        # creates runs/<id>/: page images, text layer, medicine symbols, photos
flyer extract                     # the AI reads the flyer -> flyer_data.json + checks + review.html
flyer validate                    # re-run the data checks after editing runs/<id>/flyer_data.json
flyer approve-data                # approval 1 (refused if there are blocking issues)
flyer generate                    # code plans the month; the AI writes texts with placeholders only
flyer check                       # compliance rules
flyer regen --item post-03 --note "più breve"   # rewrite one post, story or screen (e.g. screen-07)
flyer render                      # draws the PNG images + calendar.csv
flyer approve-pack                # approval 2
flyer export                      # .zip for manual upload
flyer status                      # state, history, provider/model/tokens/cost of each AI call
flyer score                       # reading accuracy against the hand-checked answer file (no AI call)
flyer eval --providers gemini:gemini-3.8-flash,anthropic:claude-sonnet-5-5   # compare providers
flyer run volantino.pdf --yes     # all of the above in one go, approving automatically
flyer watch                       # the Drive agent described above
```

Commands act on the latest run. To target another run, pass the start of its id (the folder name in `runs/`).

---

## 10. Troubleshooting

| Problem | Fix |
| --- | --- |
| `command not found: flyer` | Run `source .venv/bin/activate` in the project folder first. |
| `python3.12: command not found` | Install Python 3.12 (`brew install python@3.12`). |
| `manca credentials.json` | The Google OAuth file is missing or has the wrong name. Redo §3.6, step 6. |
| `cartella 'Volantini Farmagorà' non trovata` | The folder must be in the top level of **Il mio Drive**, named exactly like `drive.api_folder` in `config/app.yaml`, and owned by the account you signed in with. |
| Google sign-in shows "Access blocked" or "app not verified" | In Google Cloud, **Google Auth platform → Audience**: add your email as a test user. Then click **Advanced → Go to …** on the warning. |
| Signed in with the wrong Google account | Delete `.secrets/google-token.json` and run `flyer watch` again. |
| `ERRORE.txt` says the quota is exhausted (`429`, `RESOURCE_EXHAUSTED`) | The free daily limit is used up. Wait (the agent retries by itself), or use a paid key. |
| `Drive non raggiungibile, riprovo` | Internet or Google hiccup. Nothing to do: it retries on the next check. |
| Nothing happens after dropping a PDF | Is `flyer watch` running in Terminal? Is the Mac awake? A freshly uploaded PDF is left alone for a short moment so the upload can finish. |
| Images look wrong or don't get drawn | Run `playwright install chromium` again. |
| Start a flyer over from scratch | Delete its folder in Drive and drop the PDF again. |

---

## 11. Project layout and tests

```
config/        app.yaml (providers, Drive), compliance.yaml (forbidden claims), brand.yaml, channels.yaml, pricing.yaml
prompts/       the AI instructions (versioned: *.v1.md, *.v2.md…)
templates/     HTML + CSS for posts, stories and screens (editable by a designer)
assets/        logos and fonts
src/flyer_agent/
  core/        pure logic: data checks, planning, compliance, folder workflow, review sheet, Drive sync planning
  ports/       interfaces to the outside world (AI, Drive…)
  adapters/    the real implementations: AI providers (llm/), PDF, Excel, image rendering, Google Drive (gdrive.py)
  stages/      the steps (pipeline.py), the folder agent (watch.py) and the Drive agent (drive_sync.py)
tests/         unit, contract and integration tests; sample flyers in tests/fixtures/flyers/
runs/          one folder per run (created by the agent, not uploaded to git)
PLAN.md        full design: scope, architecture, data formats, milestones
DEMO.md        how to run the demo
```

Run the checks:

```bash
pytest                         # 88 tests, no real AI or Google calls
ruff check                     # code style
mypy src/flyer_agent/core      # type checks
```

The tests cover: data checks, placeholders, planning, state machine, folder decisions and spreadsheet edits (unit); every AI adapter and its retries (contract); the full offline pipeline with rendering, medicine symbols and photos, and the whole Drive flow (drop → sheet correction → approvals → change request → export) on a local folder and on a fake online Drive (integration).

---

## 12. Status and known limits

- **Done:** reading checked at 100% (names, prices, badges, 51/51 medicines) on the hand-checked Oct–Nov 2026 flyer.
- **Done:** Drive API mode tested live on 5 Nov 2026, browser only: January 2026 and February 2026 flyers, from drop to export (sheet corrections, both approvals). Existing folders are picked up without redoing work.
- **Not yet tried on a real Drive:** a change request from the `Contenuti` tab (covered by the automated tests).
- The May 2026 and Jul–Aug 2025 answer files (`*.golden.draft.json`) still need a hand-check.
- The demo runs on one Mac: if the Mac sleeps or `flyer watch` stops, nothing happens until it restarts (then it catches up). No emails yet, only Mac notifications, seen by whoever runs the agent.
- If the approver and the agent save `Revisione.xlsx` at the same moment, the later save wins. The agent only rewrites it between steps.
- Fonts: Montserrat and Caveat (open fonts) stand in for the brand fonts until we receive them.
- **Production (if the client approves):** the same agent on a small server (e.g. Google Cloud Run, about €0–10/month) plus email notifications. See PLAN.md §14.
