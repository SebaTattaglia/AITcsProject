---
doc_id: troubleshooting-database
title: Troubleshooting Database Connection Issues
doc_type: troubleshooting
tags: [database, postgresql, sqlalchemy, connection-pool, timeout]
---

# Troubleshooting Database Connection Issues

## Connection pool exhausted

**Symptom:** `sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached, connection timed out, timeout 30`. Requests hang for 30 seconds and then fail with 500.

**Common causes:**
- Sessions not closed on error paths (most common). Every session must be used as a context manager or closed in `finally`.
- Long transactions holding a connection while calling an external HTTP service.
- Pool size too small for the number of worker processes.

**Resolution:**
1. Check the `db_pool_checked_out` metric to confirm the pool is saturated.
2. Search the code for sessions created outside the `get_db_session` helper and fix them (see the `db_session` snippet).
3. Never call external services inside a transaction; commit first, then call.
4. Size the pool: `pool_size * workers * replicas` must stay below the database `max_connections` minus 20% headroom.

## Statement timeout / slow queries

**Symptom:** `canceling statement due to statement timeout` or p95 latency spikes on read endpoints.

**Resolution:**
1. Run `EXPLAIN (ANALYZE, BUFFERS)` on the query from the slow-query log.
2. Look for sequential scans on large tables and add the missing index (create it with `CREATE INDEX CONCURRENTLY` in production).
3. Replace N+1 queries in ORM loops with `selectinload` / `joinedload`.
4. The default `statement_timeout` is 5s for APIs and 60s for batch jobs; do not raise it to hide a slow query.

## Deadlocks

**Symptom:** `deadlock detected` errors under concurrent updates.

**Resolution:** always lock rows in a consistent order (e.g. by primary key ascending), keep transactions short, and retry the transaction up to 3 times with backoff (see the `retry_with_backoff` snippet). Deadlock retries must be idempotent.

## SSL / authentication failures after rotation

**Symptom:** `password authentication failed` right after the 90-day credential rotation.

**Resolution:** the service did not reload its secrets. Restart the deployment (`kubectl rollout restart deployment/<service>`) and verify it reads the password from Vault, not from a baked-in config.
