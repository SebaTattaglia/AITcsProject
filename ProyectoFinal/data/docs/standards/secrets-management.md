---
doc_id: secrets-management
title: Secrets Management Policy
doc_type: standard
tags: [security, secrets, vault, credentials]
---

# Secrets Management Policy

## Rules

- Secrets (API keys, passwords, tokens, certificates) are never committed to Git, not even in private repositories or in test fixtures.
- Applications read secrets from environment variables injected at runtime from HashiCorp Vault. Local development uses a `.env` file listed in `.gitignore`; commit only a `.env.example` with empty values.
- Each service has its own credentials with least privilege. Shared "team" accounts are not allowed.
- Database passwords and API keys rotate every 90 days; rotation is automated by the platform team.

## If a secret is leaked

1. Revoke or rotate the secret immediately — deleting the commit is not enough, it stays in history and forks.
2. Open a security incident in the tracker with severity High.
3. Purge it from history with `git filter-repo` and force-push only after the security team approves.
4. Review access logs for the period the secret was exposed.

## Logging

Never log secrets, full tokens, or `Authorization` headers. Mask them so only the first 4 characters remain (`sk-a…`). The shared logging library does this automatically for fields named `password`, `token`, `secret` and `api_key`.
