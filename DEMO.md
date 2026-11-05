# Demo script (3 minutes)

Goal: show the client that the monthly flyer becomes a ready-to-approve content pack in about 30 minutes of human checking instead of several hours, with zero price errors.

Flyer used: Jul–Aug 2025 "La salute che conviene" (no Nov–Dec 2026 flyer available). Everything runs on Gemini; nothing is published.

## Before recording

- `.env` has a working LLM key; `config/app.yaml` (or `--provider`) points every task to it.
- Do a full run the day before (`flyer run <pdf>`), keep the run folder open: Gemini's free tier can be slow or busy, so record from a finished run and show the live command only for the first step.
- Open in browser tabs: the flyer PDF, `runs/<id>/review.html`, the `out/` folder.

## Script

| Time | Show | Say (key points) |
|---|---|---|
| 0:00–0:20 | The flyer PDF | "This is the monthly flyer: 36 products, prices, discounts, services, My Agorà. Today someone turns it into posts, stories and in-store screens by hand: several hours each month." |
| 0:20–0:45 | Terminal: `flyer run volantino.pdf` | "One command. The agent reads the whole flyer: every product, price, discount and validity date." |
| 0:45–1:25 | `review.html`, data table (Gate 1) | "First check, the most important: the data. Prices are read from the PDF and checked by code: discount maths, shared prices, and every price printed in the PDF must be in the table. Medicines are found by code too, from the symbol on the card, so the mandatory warning can never be forgotten. A person approves here." |
| 1:25–2:15 | `review.html` gallery: teaser, posts, stories, screens | "Then it writes the month: a teaser on day one, products, services before their deadline, a last-call post. The AI writes the text, but prices and dates are filled in by code from the approved data: the AI cannot invent a price. Medicine posts get the mandatory warning automatically. Forbidden health claims are blocked." |
| 2:15–2:40 | `flyer regen --item post-03 --note "più breve"` → updated post | "If a post isn't right, you write a note in plain Italian and it rewrites only that one." |
| 2:40–3:00 | `out/` folder: PNGs, `captions.md`, `calendar.csv` | "Second approval, then everything is exported, ready to upload, with the publishing calendar. About 30 minutes of checking instead of hours. Nothing is published without your OK." |

## Numbers to quote (fill in from the last full run)

- Machine time, PDF → export: about 3 minutes (Jul–Aug 2025 run, Gemini Flash; plus waits when the free tier is busy).
- AI cost per flyer: about €0.10 at paid-tier prices.
- Extraction accuracy on the hand-checked flyer (Oct–Nov 2026): 51/51 products, 100% name + prices + badges, 0 medicine errors (`flyer score`).
- Output: 1 teaser, up to 12 posts, 6 stories, up to 12 screen slides, calendar CSV.

## Next step to pitch

Monthly use without any tool to learn: drop the PDF in a Google Drive folder, check and approve in a Google Sheet, get an email when it's ready (PLAN.md §14, M7).
