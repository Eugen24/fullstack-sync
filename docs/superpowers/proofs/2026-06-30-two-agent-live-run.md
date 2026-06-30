# Proof: two-agent live parallel-sync run

**Date:** 2026-06-30 · **Result:** PASS

Closes (as far as one session allows) the "two live sessions" gap. Real subagents —
not hand-fed JSON — drove the protocol in two separate git repos concurrently.

## Setup

- `backend/` repo (FastAPI-ish): existing `GET /v3/users/{id}`.
- `app/` repo (Flutter-ish): existing `getUser` call, plus `.fullstack-sync/` state dir.
- Two subagents launched in ONE message (concurrent): a BACKEND session (snake_case) and
  an APP session (camelCase). Each told to add `POST /v3/users/{id}/orders` from the same
  *semantic* contract (order total in cents; response id/total/timestamp), implement only
  its own side, then write its slice via `scripts/sync_state.py write-slice`.

## What the agents produced (independently)

```
backend POST fields: ["total_cents", "order_id", "created_at"]
app     POST fields: ["totalCents",  "orderId",  "createdAt"]
```

Opposite casing, same semantics. After `sync_state` normalization both contracts hashed to
the **same** fingerprint `bc198a10f1c581c7…`.

## Controller verification

1. On-disk `backend.fp.json` and `app.fp.json` (written by two different processes) →
   hashes **MATCH** — single-writer-per-slice held under real concurrency, no clobber.
2. `reconcile --side app` → baseline recorded.
3. `status --side app` → **IN_SYNC** (exit 0).
4. Backend renamed `order_id`→`id`, refreshed its slice → `status` → **MOVED** (exit 2).

## What this proves / does not prove

**Proves:** concurrent two-context operation, single-writer-per-slice safety, the
camel/snake fingerprint equality on *agent-generated* contracts, reconcile baseline, and
drift detection — end to end.

**Does NOT prove:** two genuinely separate `claude` processes (subagents share one host
session); extraction against large/messy real codebases (these fixtures are minimal). The
agents *converged* on field names here, but a semantic spec ("the order id") can still be
named differently by each side — that divergence would surface as drift, which is the
intended behavior (field-name skew is the #1 drift source), not a false positive.
