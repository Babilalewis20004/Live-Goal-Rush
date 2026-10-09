# Runbooks

One page per thing that breaks. Each follows the same shape — **Symptoms → Impact → Diagnose → Fix → Verify → Afterwards** —
and every command assumes you are in the deployment directory with:

```bash
C="docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production"
```

| Situation | Runbook | Alert that points here |
|---|---|---|
| The site or API is down / erroring | [api-outage.md](api-outage.md) | `ApiErrorBudgetBurn`, `DatabaseConnectionPoolExhausted`, `ApiDown` |
| PostgreSQL is down or unreachable | [database-outage.md](database-outage.md) | `DatabaseUnreachable` |
| Redis is down or full | [redis-outage.md](redis-outage.md) | `RedisUnreachableFromApi`, `RedisDown` |
| Scores are not updating | [provider-outage.md](provider-outage.md) | `FootballLiveDataStale`, `FootballProviderFailing` |
| Jobs are piling up or failing | [celery-backlog.md](celery-backlog.md) | `CeleryBacklog`, `CeleryWorkerSilent`, `FailedJobsNeedAttention` |
| Live updates stopped / sockets dropping | [websocket-outage.md](websocket-outage.md) | `WebSocketClientsBeingEvicted` |
| Payments or entitlements look wrong | [payment-webhook-failure.md](payment-webhook-failure.md) | `PaymentWebhookProcessingFailing`, `WebhookSignatureRejections` |
| Suspected breach / abuse | [security-incident.md](security-incident.md) | `LoginFailureSpike` |
| Restore the database from backup | [backup-restoration.md](backup-restoration.md) | `BackupStale` |
| Undo a release | [rollback.md](rollback.md) | smoke test failure after deploy |

**First five minutes, always:** `curl -s https://<site>/health/ready`, `curl -s https://<site>/version`,
`$C ps`, `$C logs --tail 100 api`, and the admin view `GET /api/v1/admin/system` (dependencies, queue depth, failed
jobs, live-data freshness, DB pool). Every API log line carries a `request_id`; the same id is in nginx's access log and
in the logs of any Celery task that request started — search for it across all three.
