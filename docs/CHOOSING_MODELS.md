# Choosing models and providers

Every model the study calls (the perturbation author, the four targets, the judge)
is named in **one file: `configs/model_panel.yaml`**. Changing a model, moving to a
newer version, or adding a provider that is not built in is an edit to that file.
No code changes.

## The workflow

```bash
# 1. edit configs/model_panel.yaml
python scripts/validate_panel.py          # 2. offline, free: catches typos and invalid settings
python scripts/list_models.py             # 3. free: is every ID offered to your key? newer ones?
python scripts/list_models.py --provider anthropic --grep opus   # browse one provider
python scripts/smoke_test_providers.py    # 4. PAID, tiny: one short prompt per configured model
# 5. set frozen: true, commit, lock (RUNBOOK Phase 6)
```

Steps 2 and 3 cost nothing. Step 4 sends one "reply with: ready" prompt to each
configured model and is the only paid step before the study itself. Model listing
generates no tokens and the built-in providers do not bill for it. It still needs
each provider's key, and like any request it is subject to that provider's terms.

## Changing a model

Edit the entry's `model` (and `reasoning_effort` if the new model supports
different levels). Give the target a new `target_id` that names the model, because
the ID appears in every result file:

```yaml
  - target_id: anthropic_opus55
    provider: anthropic
    model: claude-opus-5-5
    reasoning_effort: high
    tools: disabled
```

Set `reasoning_effort` explicitly. `provider_default` leaves it to the provider,
and providers change defaults between versions (for example Claude Opus 5.5
defaults to `medium` where Claude Opus 5 defaulted to `high`). The validator warns
when you leave it implicit.

Valid `reasoning_effort` values by API style (checked offline):

| API style | values |
|---|---|
| `openai_responses` (OpenAI, xAI) | `minimal` `low` `medium` `high` `xhigh` |
| `anthropic_messages` | `low` `medium` `high` `xhigh` `max` |
| `google_generate_content` | `low` `medium` `high` (sent as `thinkingLevel`) |
| `openai_chat_completions` | `minimal` `low` `medium` `high`, if the server accepts `reasoning_effort` |

The validator only knows what each API style accepts. A particular model may
support fewer levels, and the smoke test is where that shows up.

## Adding a provider

Built in: `openai`, `anthropic`, `google`, `xai`. Anything else goes under
`providers:` and is then used by name:

```yaml
providers:
  deepseek:
    api: openai_chat_completions
    base_url: https://api.deepseek.com/v1
    api_key_env: DEEPSEEK_API_KEY
    vendor: deepseek

target_models:
  - target_id: deepseek_v4
    provider: deepseek
    model: deepseek-v4            # whatever list_models.py shows
    reasoning_effort: high
    tools: disabled
```

`openai_chat_completions` is the OpenAI-compatible request shape, which almost
every other vendor, aggregator, gateway and local server speaks. Optional fields:

| field | default | use |
|---|---|---|
| `api_key_env` | required for remote servers | `null` for a keyless local server |
| `effort_param` | `reasoning_effort` | `null` if the server rejects that field |
| `max_tokens_field` | `max_tokens` | e.g. `max_completion_tokens` |
| `extra_headers` | none | constant headers a gateway requires |
| `vendor` | the provider name | the model's developer |

Put the key in the environment variable named by `api_key_env`, or in
`API_KEYS.local.md` (git-ignored) as `DEEPSEEK_API_KEY = ...`. Keys never appear
in a URL, a log line or a result file.

A built-in can be redirected field by field, e.g. to a regional or corporate
gateway that speaks the same API:

```yaml
providers:
  anthropic:
    base_url: https://gateway.example.org/anthropic/v1
```

### Aggregators and the `vendor` field

`vendor` is **who built the model**, not whose API served it. The design requires
four targets from four different developers, and the judge-bias audit compares the
judge's developer with each target's developer. When several models come through
one aggregator, set `vendor` on each model entry:

```yaml
  - target_id: openai_gpt56_sol
    provider: openrouter
    model: openai/gpt-5.6-sol
    vendor: openai
```

### Open-weight judge (sensitivity analysis)

The protocol allows a secondary open-weight judge if it is public, version-pinned
and reproducible before lock. Serve the pinned weights with vLLM or Ollama and
point a provider at it:

```yaml
providers:
  local_vllm:
    api: openai_chat_completions
    base_url: http://localhost:8000/v1
    api_key_env: null
    effort_param: null
    vendor: open_weight

secondary_judges:
  - judge_id: open_weight_blinded
    provider: local_vllm
    model: org/clinical-judge-70b@<exact revision>
    mode: blinded
    reasoning_effort: provider_default
```

## Changing the design itself

```yaml
design:
  target_count: 4
  distinct_target_vendors: true
  primary_judge_count: 1
```

These numbers are enforced by every script. Changing them changes the study's
sample sizes and the analysis plan, so it is a protocol amendment: update
`protocol/PROTOCOL.md` and `protocol/STATISTICAL_ANALYSIS_PLAN.md` in the same
commit, before lock.

## What is recorded for every call

Configured and provider-reported model ID (a mismatch is flagged as
`resolved_model_matches_configured=false`), API style, endpoint, reasoning setting,
token cap, request hash, HTTP status, attempts, finish reason, refusal details,
timing and usage. No provider-side fallback to a different model is ever
requested: if a model declines, that is the configured model's outcome.

## After the lock

The panel file is hashed into `data/study_lock.json`. After lock, the target and
judge runners refuse to start if it has changed. Swapping a model then requires a
logged deviation (`protocol/DEVIATIONS.md`) and a new lock.
