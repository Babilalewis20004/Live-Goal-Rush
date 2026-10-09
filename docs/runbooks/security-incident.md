# Security incident

**Triggers.** `LoginFailureSpike`; a leaked secret (including in git history); suspicious admin activity in the audit log; a report of someone's account being used by another person; unexpected Premium grants; a vulnerability report.

**First rule: stop the bleeding before investigating.** Rotating a credential is cheap; an attacker with a valid one is not.

## 1. Contain

| What | Do this |
|---|---|
| Leaked **football API key / S3 key / SMTP password / Stripe key / webhook secret** | rotate at the provider now; update `.env.production`; `$C up -d api worker scheduler`. (The repository has a committed provider key in history — `docs/security/findings.md` S-1.) |
| Leaked **`JWT_SECRET`** | set a new one and redeploy: every access token becomes invalid within one request. Refresh tokens are stored hashed and unaffected, so users silently re-authenticate; if you suspect refresh tokens too, revoke them all: `update refresh_tokens set revoked_at = now() where revoked_at is null;` (everyone signs in again) |
| One compromised **user** | `POST /api/v1/moderation/users/{id}/suspend` (admin; revokes their sessions, blocks sign-in and every authenticated request at once). Reset requires them to prove ownership of the mailbox |
| A compromised **staff/admin** account | suspend is refused for admins — demote first with the operator CLI: `python -m app.cli set-role name@example.com user`, then suspend; rotate `JWT_SECRET` if their token may have leaked |
| Credential stuffing | tighten at the proxy first (`deploy/nginx/nginx.conf` `limit_req_zone auth`, block the offending CIDR with `deny`), then lower `RATE_LIMIT_LOGIN_PER_MINUTE` |
| Webhook abuse | the endpoint authenticates by HMAC, not IP; if forged calls are arriving the secret is known to someone: rotate `BILLING_WEBHOOK_SECRET` at both ends |
| Active exploitation of the API | take the API out of rotation at nginx (return 503) rather than debugging a live attack |

## 2. Investigate

* **Audit log** — `GET /api/v1/admin/audit-log?action=user.role_change` (and `entitlement.grant`, `user.suspend`, `comment.delete`, `article.delete`, `account.delete`): who, what, when, why. Role changes and entitlement grants by `cli` come from someone with shell access.
* **Logs** — `request_id` ties an HTTP request to the Celery tasks it started. Search for the user id (`"user_id":123`) and for `login_failures_total` spikes by time. Logs contain no tokens or emails, so correlate by user id and time and look the person up in the database.
* **Sessions** — `select id, user_id, ip_address, user_agent, created_at, revoked_at from refresh_tokens where user_id = 123 order by created_at desc;`
* **Refresh-token reuse** is logged as a warning ("Refresh token reuse detected") and revokes the family automatically.
* **Premium abuse** — compare `entitlements`/`subscriptions` with `payment_events`; every legitimate grant has either a verified webhook or a `entitlement.grant` audit entry.

## 3. Recover and tell people

* Restore from backup only if data integrity is in doubt ([backup-restoration.md](backup-restoration.md)); remember a restore resurrects accounts erased since the backup (replay `account.delete` entries — `docs/security/data-inventory.md`).
* If personal data may have been exposed, the legal clock for notifying regulators/users usually starts at *awareness*; involve whoever owns privacy compliance immediately.
* Write the timeline down while it is fresh; add the fix to `docs/security/findings.md` and a regression test (the authorization matrix and `test_auth_hardening.py` are the places to extend).

## 4. Reporting a vulnerability (publish a `security.txt` / contact address before launch — checklist item)
