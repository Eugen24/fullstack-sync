---
name: fullstack-run
description: Launch the backend API and the client app together for end-to-end testing, pointing the app at the local backend. Use when the user wants to run both sides, "start the stack", "run backend and app", test against a local API, or reproduce an integration bug. Starts the backend dev server, confirms it's healthy, then runs the app against it.
---

# Fullstack Run

Bring up backend + app locally and point the app at the local API.

## 0. Load config

Read `.fullstack-sync.json`. Need `backend.root`, `backend.stack`, `app.root`,
`app.stack`. If missing → `/fullstack-setup`.

## 1. Start the backend (background)

Detect the run command from the backend stack — do NOT assume:
- FastAPI: `uvicorn asgi:app --reload` / a `Procfile web:` line / `mise`/`make`
  target. Read `Procfile`, `mise.toml`, `Makefile`, `README` for the real cmd.
- Node: `npm run dev` / the `scripts.dev` in package.json.
- Django: `python manage.py runserver`.

Run it with `run_in_background: true`. Capture the bound host:port.

## 2. Health-check the backend

Poll the health/root route until it answers (or OpenAPI at `/docs`,
`/openapi.json`). Surface the real URL. If it won't boot, stop and show the
backend logs — do not start the app against a dead API.

## 3. Point the app at local backend — resolve host PER DEVICE

Find the app's base-URL config (env file, `--dart-define`, a `const baseUrl`,
build flavor). Set it to the local backend — but `localhost` does NOT resolve
the same across targets (the #1 reason this "works" yet the app can't connect):

| Target | Host to use |
|--------|-------------|
| iOS simulator | `localhost` / `127.0.0.1` |
| **Android emulator** | **`10.0.2.2`** (NOT localhost) |
| Physical device (USB, Android) | host LAN IP, or `adb reverse tcp:<port> tcp:<port>` |
| Physical device (iOS/Wi-Fi) | host LAN IP (same network) |
| Flutter **web** | `localhost` works, but backend needs **CORS** for the origin |

Pick the host from the device chosen in step 4. Note the base-URL change so it
can be reverted (fullstack-verify checks no override is left behind).

## 4. Run the app

Use the project's own run path (prefer a project `run`/launch skill if one
exists). For Flutter pick an available device; on Apple-Silicon iOS sims beware
arm64-only plugins (MLKit/scanner) — fall back to a real device or Android if
the sim can't link.

## 5. Report

Print: backend URL + health status, app target/device, and the base-URL change
made. Keep the backend running in the background; tell the user how to stop it.
