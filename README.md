# Meal Mentor

A concierge agent that plans your week of meals, tracks your pantry, computes
nutrition, and stages grocery orders — with a real coordinator/specialist
multi-agent architecture, persistent memory, guardrails, and end-to-end
observability on Google Cloud.

Built on the [Google Agent Development Kit (ADK)](https://google.github.io/adk-docs/)
and scaffolded from `google-agents-cli`.

---

## The problem

Cooking at home takes planning. You need to think about what everyone in the
house will eat, what you already have, what's about to expire, what fits your
diet, and what to buy. Most people just wing it — and end up wasting food or
ordering takeout.

## The solution

A multi-agent concierge with five specialists behind a triage coordinator:

```
                    Coordinator (Gemini Pro)
                          │  transfer_to_agent
     ┌────────────┬───────┼─────────┬─────────────┐
     ▼            ▼       ▼         ▼             ▼
  Planner    PantryKeeper Nutritionist Shopper    Coach
   (Pro)      (Flash)     (Flash)     (Flash)   (Flash-Lite)
```

The user says "plan my week" or "I bought 500g of pasta" or "order groceries",
and the coordinator picks the right specialist. Every specialist owns a small,
sharply-scoped tool surface with typed inputs and structured outputs, so the
model never has to guess a schema.

---

## Architecture at a glance

| Layer | File | What it does |
| --- | --- | --- |
| Coordinator | `app/agent.py` | Routes each turn; runs self-eval + spawns async memory consolidation |
| Specialists | `app/sub_agents/*.py` | Five focused agents with distinct model tiers |
| Tools | `app/tools/*.py` | 11 tools grouped by concern; every one is `@traced_tool` and returns typed JSON |
| Schemas | `app/models.py` | Pydantic models used as the JSON schema for every tool arg and result |
| Memory | `app/memory/firestore_store.py`, `app/memory/consolidation.py` | Firestore persistence + sliding-window compaction + async consolidation |
| Guardrails | `app/guardrails/policy.py`, `app/guardrails/self_eval.py` | Prompt-injection filter, unsafe-advice blocker, LLM-as-judge self-eval |
| Observability | `app/observability/logging_config.py`, `tracing.py`, `pii.py` | Structured JSON logs, intent-vs-outcome, OTel spans, DLP-based PII redaction |
| Secrets | `app/secrets.py` | Secret Manager wrapper — no hardcoded API keys anywhere |
| Infra (IaC) | `deployment/terraform/**` | Terraform for Firestore, Cloud Run, Secret Manager, WIF, service accounts, log sinks |
| CI/CD | `.github/workflows/*.yaml` | Lint → unit → integration → eval → build → deploy staging → prod |
| Eval | `tests/eval/**` | Golden dataset of 10 scenarios + LLM-as-judge grader |

---

## Rubric mapping

The [AgentOps rubric](https://fde-project-evaluator-510868799189.us-central1.run.app/)
scores 5 categories. Direct pointers into the code:

### 1. Tool & Interface Design
- **Comprehensive tool docstrings** — every tool has a purpose block, `Args:`,
  and `Returns:` (see e.g. [`app/tools/pantry.py`](app/tools/pantry.py)).
- **Descriptive naming** — `add_pantry_item`, `place_grocery_order`,
  `confirm_grocery_order`, `compute_recipe_nutrition` (never `update_data`).
- **Explicit JSON schemas** — every tool argument and return value is a Pydantic
  model in [`app/models.py`](app/models.py), so the LLM sees a strict schema.
- **Guided error handling** — no tool ever raises. Errors return a
  [`ToolError`](app/models.py) with `code`, `message`, and `recovery_hint`.

### 2. Context & Memory
- **Robust system instructions** — each specialist has a "constitution" with
  persona, rules, and safety constraints (see
  [`app/sub_agents/planner.py`](app/sub_agents/planner.py)).
- **History compaction** — token-bounded sliding window + running summary in
  [`app/memory/consolidation.py::compact_history`](app/memory/consolidation.py),
  wired as a `before_model_callback` on every agent.
- **Persistent session state** — Firestore-backed store in
  [`app/memory/firestore_store.py`](app/memory/firestore_store.py) plus
  Agent Platform Sessions (see [`app/app_utils/services.py`](app/app_utils/services.py))
  for cross-session conversation history.
- **Async memory operations** — `spawn_consolidation` (in `consolidation.py`)
  fires learning extraction on `asyncio.create_task` so the UI never waits.

### 3. Orchestration & Logic
- **Multi-agent patterns** — Coordinator + 5 specialists via ADK's
  `sub_agents` + `transfer_to_agent`.
- **Strategic model routing** — Coordinator/Planner on `gemini-2.5-pro`,
  Pantry/Nutritionist/Shopper on `gemini-2.5-flash`, Coach on
  `gemini-2.5-flash-lite`. Model IDs live in [`app/config.py`](app/config.py).
- **Guardrails & policy plugins** — `PolicyGuardPlugin` (prompt injection +
  unsafe advice) is registered as an ADK `Plugin` in `App(plugins=[...])`.
  A `self_evaluate_response` after-agent callback runs Flash-Lite as an
  LLM-as-judge on every reply.
- **Human-in-the-loop hooks** — `place_grocery_order` returns
  `awaiting_confirmation` with a one-time token; the actual charge only fires
  after the user echoes that token to `confirm_grocery_order`. See
  [`app/tools/shopping.py`](app/tools/shopping.py) and the
  `test_hitl_order_requires_confirmation_token` test.

### 4. Observability & Tracing
- **Structured JSON logging** — [`observability/logging_config.py`](app/observability/logging_config.py)
  routes to Cloud Logging with a `_JsonFormatter` fallback for local dev.
- **Intent vs outcome capture** — the `@traced_tool` decorator emits a
  `tool.intent` log *before* every call and a correlated `tool.outcome` log
  *after* it, linked by `call_id`.
- **Distributed tracing** — every tool call becomes an OTel span
  (`tool.<name>`) via [`observability/tracing.py`](app/observability/tracing.py);
  ADK's own spans and the Cloud Trace exporter are wired in
  [`app_utils/telemetry.py`](app/app_utils/telemetry.py).
- **PII redaction** — [`observability/pii.py`](app/observability/pii.py) runs
  a Cloud DLP redaction pass (or a regex fallback) on every logged and
  persisted payload before it leaves the process.

### 5. Infrastructure & CI/CD
- **Automated evaluation suite** — 10-scenario golden dataset in
  [`tests/eval/datasets/basic-dataset.json`](tests/eval/datasets/basic-dataset.json)
  graded by an LLM-as-judge in [`tests/eval/metrics.py`](tests/eval/metrics.py);
  runs in CI via `agents-cli eval`.
- **Infrastructure as Code** — Terraform in
  [`deployment/terraform/single-project`](deployment/terraform/single-project)
  and [`deployment/terraform/cicd`](deployment/terraform/cicd) provisions
  Firestore, Cloud Run, Secret Manager, Artifact Registry, service accounts,
  Workload Identity Federation, and log sinks.
- **Secure secret management** — [`app/secrets.py`](app/secrets.py) is the
  only path to external API keys; secrets are provisioned by
  [`deployment/terraform/*/secretmanager.tf`](deployment/terraform/single-project/secretmanager.tf).
  Grep the tree for hardcoded keys — there aren't any.

---

## Requirements

- **uv** — Python package manager: <https://docs.astral.sh/uv/>
- **agents-cli** — `uv tool install google-agents-cli`
- **gcloud SDK** — <https://cloud.google.com/sdk/docs/install>
- **Terraform** — <https://developer.hashicorp.com/terraform/downloads>

---

## Quick start

```bash
# One-time
uv tool install google-agents-cli
agents-cli install

# Local playground (no GCP needed — uses in-memory Firestore fallback)
USE_IN_MEMORY_STORE=1 agents-cli playground

# Unit tests
USE_IN_MEMORY_STORE=1 uv run pytest tests/unit

# Full lint + test + integration
uv run ruff check app tests
uv run pytest tests

# Run eval against the golden dataset
agents-cli eval generate --dataset tests/eval/datasets/basic-dataset.json
agents-cli eval grade    --config  tests/eval/eval_config.yaml
```

---

## Deployment

```bash
# One project, one command
gcloud config set project <your-project-id>
agents-cli infra single-project
agents-cli deploy
```

For full staging + prod CI/CD with Workload Identity Federation:

```bash
agents-cli infra cicd
# Then push to main — GitHub Actions handles the rest.
```

---

## Data model

All persistent state lives in Firestore under keys prefixed with the user id:

| Collection | Doc id | Contents |
| --- | --- | --- |
| `pantry_items` | `{user_id}:{item_key}` | one ingredient with quantity + unit + expiry |
| `meal_plans` | `{user_id}:{week_start}` | a `MealPlan` for the week starting on that Monday |
| `user_preferences` | `{user_id}:profile` | dietary restrictions, dislikes, household size |
| `user_learnings` | `{user_id}:{key}` | facts extracted asynchronously from conversation |
| `pending_orders` | `{user_id}:{token}` | HITL-staged grocery orders awaiting confirmation |

The store falls back to an in-memory dict when `USE_IN_MEMORY_STORE=1`, so
tests and the local playground don't need GCP creds.
