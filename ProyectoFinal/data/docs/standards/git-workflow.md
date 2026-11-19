---
doc_id: git-workflow
title: Git Workflow and Code Review
doc_type: standard
tags: [git, pull-request, code-review, branching]
---

# Git Workflow and Code Review

## Branching model

We use trunk-based development. `main` is always deployable.

- Feature branches: `feature/<ticket>-short-description` (e.g. `feature/DEV-1042-pool-metrics`).
- Fix branches: `fix/<ticket>-short-description`.
- Branches live at most 3 days; split bigger work behind feature flags.
- Never push directly to `main`; it is protected and requires a pull request.

## Commit messages

Follow Conventional Commits: `type(scope): summary` in imperative mood, max 72 characters.
Allowed types: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `build`, `ci`, `chore`.

```text
fix(orders): release DB connection when payment call times out

The session was not closed on PaymentGatewayUnavailableError,
which exhausted the pool under load. Refs DEV-1042.
```

## Pull requests

- Keep PRs under 400 changed lines. Larger PRs must be split or justified in the description.
- The description includes: what changed, why, how it was tested, and the ticket id.
- At least one approval from a code owner; two for changes in `payments/` or `auth/`.
- CI must be green (lint, type check, tests, security scan) before merging.
- Use squash merge so `main` keeps one commit per PR.

## Code review checklist

1. Does the change follow the coding standards and API guidelines?
2. Are errors handled and logged once, with a correlation id?
3. Are there tests for the new behaviour and the failure paths?
4. Are secrets, credentials or personal data absent from code, logs and fixtures?
5. Is the change backwards compatible, or is the migration documented?
