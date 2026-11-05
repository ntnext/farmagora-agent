# CLAUDE.md — Farmagorà Flyer-to-Everything Agent

Read `PLAN.md` first (especially §1a Flyer anatomy and §1b Brand, learned from the real flyers in `tests/fixtures/`). It is the source of truth for scope, architecture, data contracts and milestones.

## Current state

v0.1 runs end to end offline (see README.md). Next: M1 with a real provider for `extract`.

## How to work

- Build one milestone at a time (M0 → M6). Before starting a milestone, write a short task list. At the end, run checks and summarise what was done and what is left.
- Do not start the next milestone until `ruff check`, `mypy src/flyer_agent/core` and `pytest` pass.
- Ask before adding a new dependency that is not listed in PLAN.md §3.
- Ask before changing a data contract in `core/models.py`; update the JSON schema snapshots in the same change.

## Architecture rules

- `core/` is pure: no network, filesystem, SDK or Playwright imports. Only Pydantic, stdlib and `core` modules.
- Business logic talks to the outside only through `ports/` (`typing.Protocol`). Vendors live in `adapters/`.
- Every stage reads typed JSON from the run folder and writes typed JSON plus artifacts back. Stages are idempotent.
- Prices, discounts and dates in outputs are formatted by code from `FlyerData`. LLM text uses placeholders (`{price:<product-id>}`, `{valid_to}`), never literal prices or dates.
- The pipeline must not pass an approval gate without an approval record in `manifest.json`.
- Nothing is published anywhere in v1. Allowed outputs: the local run folder, the owner's Google Drive folder and PED sheet, and notification emails to the owner (M7, PLAN.md §14). Never post to social networks or email anyone else. There is no newsletter in scope.

## LLM rules

- The project is LLM-agnostic. Core code and stages talk only to `ports/llm.py` (`LLMClient`); vendor SDKs are imported only inside `adapters/llm/`.
- Provider, model and temperature are chosen per task (`extract`, `copy_social`, `copy_screens`, `compliance_critic`) in `config/app.yaml`. Never hard-code a provider or model name in code.
- Every adapter must pass the same contract test suite (`tests/contract/test_llm_adapters.py`) using recorded responses.
- Respect `capabilities`: no PDF input → send page images; no JSON-schema output → schema in prompt + Pydantic validation.
- Prompts live in `prompts/*.vN.md`, provider-neutral. Bump the version when a prompt changes and record it in the manifest.
- Structured outputs only: parse into Pydantic models; on failure, retry once with the validation errors, then fail the stage.
- Tests never call real APIs: use recorded fixtures.
- Verify current SDK usage and model names in each vendor's official docs before writing an adapter.

## Code style

- Python 3.12, `uv`, type hints everywhere, `ruff` formatting, small functions, docstrings on public functions.
- Structured JSON logging via `observability.py`; log tokens and cost for every LLM call.
- Secrets only in `.env` (never committed). `runs/` is gitignored.
- User-facing text (CLI messages, review page) in Italian; code, comments and logs in English.

## Compliance

- Health and pharmacy content is sensitive. Never weaken rules in `config/compliance.yaml` to make a test pass.
- Products with category `farmaco_sop_otc` are always flagged for manual review.
