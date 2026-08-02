# TeamMind

A small, runnable proof that [Maximem Synap](https://synap.maximem.ai) solves a
real B2B memory problem, using its actual SDK against a real Synap instance --
not a simulation.

## The problem

CloudSync is a B2B SaaS product. Acme Corp is one of its customers, with
several employees who all contact support separately. Without a memory layer:

- Every new Acme employee has to re-explain company setup (SSO provider,
  admin contact, etc.) that a coworker already explained last week.
- If you fix that by sharing everything in one bucket, one employee's
  personal request ("give me terse answers") leaks onto replies to their
  coworkers too.

TeamMind proves Synap solves both at once via its scope hierarchy: a
`customer`-scoped fetch returns facts shared across every employee at a
company, while a `user`-scoped fetch returns that one employee's private
preferences -- never the other way around.

## Files

| File | Responsibility |
|---|---|
| `config.py` | Loads/validates config (from `config.json` or env vars) once; fails fast with a clear message. |
| `llm.py` | Generates replies -- real OpenAI call if `OPENAI_API_KEY` is set, otherwise a template. Memory demo works either way. |
| `memory_bot.py` | The only file that imports the Synap SDK. Wraps ingestion, scoped retrieval, and retry logic. |
| `run_demo.py` | The scripted end-to-end proof. Run this first. |
| `chat.py` | Interactive CLI -- have your own conversation as any employee at any company. |

## Setup

```bash
# 1. Create a Client -> Instance -> API key at synap.maximem.ai
#    Instance Settings -> User Relationship -> set to B2B

# 2. Install
pip install -r requirements.txt

# 3. Configure -- either edit config.json, or export env vars:
export SYNAP_API_KEY=synap_your_key_here
# OPENAI_API_KEY is optional -- omit it to use template replies

# 4. Run the scripted proof
python run_demo.py

# 5. Or explore interactively
python chat.py --user maria_chen --customer acme_corp
python chat.py --user jordan_lee --customer acme_corp
```

## What the demo proves

1. Maria Chen (Acme's IT admin) tells the bot Acme uses Okta for SSO, and
   separately asks for terse replies -- in one message. Synap must split this
   into a shared company fact and a private personal preference.
2. Jordan Lee (a different Acme employee, never talked to the bot before)
   asks how to set up SSO. Their reply should already reflect the Okta fact
   Maria gave, with zero re-explaining.
3. Jordan's retrieved context is printed before the bot answers: Maria's
   "terse replies" preference must be absent from it, proving isolation, not
   just sharing.

## Known gaps (read before relying on this beyond a demo)

- **Ingestion is asynchronous.** `memories.create()` returns immediately; the
  extracted facts aren't queryable until the pipeline finishes. `run_demo.py`
  calls `wait_for_completion()` after Maria's turn so Jordan's fetch is
  guaranteed to see it -- a real production app would not block a
  user-facing request on this, and needs a plan for "the fact isn't ready
  yet" (e.g. a fallback for the first reply after a new fact is stated).
- **Two round-trips, merged client-side.** `company_context()` and
  `personal_context()` are two separate SDK calls; the caller merges them.
  That's deliberate here, to make the isolation visible, but it costs a
  network round-trip.
- **Retry is a thin extra layer.** The SDK's own transport already retries
  `SynapTransientError` internally with backoff+jitter; `memory_bot.py` adds
  one more retry at the call site and fails fast on `SynapPermanentError`.
  Production code should still budget for a circuit breaker if Synap becomes
  unavailable, since the agent's context quality now depends on a
  third-party service being up.
- **Privacy and data residence.** This sends real conversation content to a
  third-party memory service. Check Synap's data retention, region options,
  and whether any embeddings step forwards data to a further third party,
  before using this beyond a local experiment.
