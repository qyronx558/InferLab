# ADR-002: Self-hosted single-admin authentication

Date: 2026-10-24. Status: accepted for MVP.

## Context

InferLab has exactly one trusted operator and a private API bound to loopback. The
public site is static and reads only reviewed published snapshots; it never calls
the API. Admin mutations must be authenticated, but there is no sign-up, no
multi-tenant organization, no remote console and no requirement for social login,
SSO or MFA in the MVP. The API must also work offline on the owner's laptop and
must not add a cloud dependency, hosted identity service or paid tier.

The [rulebook](../InferLab_Production_Prompt_Rulebook.pdf) reserves benchmark
execution for the owner and requires that anonymous users cannot reach the GPU.
[ADR-001](ADR-001-zero-cost.md) already keeps private execution local and public
reading static.

## Decision

Self-host authentication inside the local FastAPI app:

- One admin, provisioned only as an Argon2id password hash in
  `INFERLAB_ADMIN_PASSWORD_HASH`. No plaintext password, default credential or user
  table exists.
- Login verifies the password with the maintained argon2-cffi `PasswordHasher` and
  issues a 256-bit opaque token. Only an HMAC-SHA256 digest of the token, keyed by
  the provisioned password hash, is stored in `admin_sessions`.
- The token travels in a host-only `__Host-inferlab_session` cookie with `Secure`,
  `HttpOnly` and `SameSite=Strict`, a 12-hour server-side expiry and a matching
  `Max-Age`. A successful login revokes all earlier sessions; logout deletes the
  current one.
- Every admin request resolves identity from the database and checks expiry
  server-side. Mutations additionally require the exact configured HTTPS Origin
  and the session CSRF token, under the single admission lock used by all writes.
- Login is locked for 15 minutes after five failures. Mutations and login attempts
  are rate limited. Auth outcomes and mutation successes are recorded as redacted
  audit events.
- Public endpoints remain unauthenticated and can only read already published,
  validated snapshots. No private route accepts an identity asserted by the client.
- The API requires local HTTPS for login and mutation, accepts only
  `localhost`/`127.0.0.1` hosts and allows credentialed CORS only from the exact
  configured console origin.

The session lookup key changes whenever the configured password hash changes. As a
result, rotating the admin credential invalidates every existing session without a
migration, manual `admin_sessions` deletion or separate revocation list.

## Managed free tiers considered

Official pricing pages checked 2026-10-24; recheck before relying on any quota.

| Provider | Published free tier | Why it was not chosen for the MVP |
| --- | --- | --- |
| [Auth0](https://auth0.com/pricing) | Free B2C/B2B, up to 25,000 MAU; MFA is not included | Hosted dependency and callback/network flow; overkill for one local admin; free tier lacks MFA |
| [Clerk](https://clerk.com/pricing) | Hobby, 50,000 MRU per app, 3 dashboard seats, fixed 7-day sessions | Requires a hosted app and internet for login; session lifetime and features are vendor-controlled |
| [Supabase Auth](https://supabase.com/pricing) | Free, 50,000 MAU; idle projects pause | Adds a hosted database/auth platform and pause behavior; local-first operation is the requirement |
| [Cloudflare Access](https://www.cloudflare.com/plans/) | Free Zero Trust tier, up to 50 users | Protects a remotely reachable app through Cloudflare; the MVP API is not internet exposed and stays offline |

These products are reasonable when InferLab gains multiple users, remote
administration or SSO/MFA requirements. They are not a better fit for a single
offline loopback operator, and none removes the need to protect the local host.

## Alternatives considered

| Option | Outcome |
| --- | --- |
| Managed identity provider (Auth0, Clerk, Supabase, Cloudflare Access) | Deferred: adds a network and vendor dependency to a local-only console; free-tier limits do not cover offline use |
| Stateless JWT sessions | Rejected: revocation, rotation and server-side expiry are harder to guarantee without a session store; no scalability need |
| HTTP Basic auth on every request | Rejected: no CSRF-safe session flow, logout or server-side revocation, and credentials would be replayed continuously |
| Long-lived API key | Rejected: harder to rotate safely in a browser, no expiry/CSRF binding, and not tied to an interactive login |
| No authentication | Rejected: violates the requirement that anonymous users cannot mutate experiments or reach execution |
| Custom password hashing or hand-rolled crypto | Rejected: password verification stays with Argon2id; tokens use `secrets` and `hmac.compare_digest` |

## Consequences and residual risks

The MVP has no MFA, account recovery, user management or remote console. A stolen
password plus access to the local HTTPS console is sufficient to log in; host
compromise also defeats the application controls. TLS certificate creation and
trust remain operator prerequisites. Session rows remain in the database until
expiry or the next login, but a credential rotation makes old rows unusable.
Audit denial events are best effort when storage is unavailable, and the owner must
manage backups and the password hash as secrets.

Reconsider this decision when remote administration, more than one admin or user,
MFA/SSO/compliance requirements, or a hosted console appears. Any replacement must
preserve server-side identity checks on every mutation, exact-origin and CSRF
protection, rate limits, redacted audits, offline operation and zero recurring cost.

## Implementation map

- `apps/api/src/inferlab_api/security.py`: `session_key`, `require_admin`,
  `require_mutation`, `login`, `logout`, lockout and audit helpers.
- `apps/api/src/inferlab_api/dependencies.py`: `Settings.password_hash` and
  `Settings.origin` provisioning.
- `apps/api/src/inferlab_api/main.py`: TLS/trusted-host enforcement, CORS allowlist,
  security headers and error handling.
- `tests/test_api.py`: credential rotation, unconfigured fail-closed behavior,
  CORS/security headers, cookies, CSRF, lockout and access-boundary tests.
- [API guide](API.md): operator setup and session behavior.
