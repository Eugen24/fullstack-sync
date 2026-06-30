---
description: Run a contract review of recent changes — scoped (low) or full both-repos (hard). Report-only by default; hard can auto-sync+commit on a feature branch.
argument-hint: "[--hard]"
allowed-tools: Bash(git rev-parse:*), Bash(git diff:*), Bash(git branch:*)
---

# Fullstack Sync Review

Invoke the `fullstack-sync-review` skill. If `$ARGUMENTS` contains `--hard`, run the
**hard** path (full diff across both repos, all lenses, autopilot guarded off the default
branch). Otherwise run the **low** path (scoped diff, lens-selected, report-only).

Current branch: !`git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown`
