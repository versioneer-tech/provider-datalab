# ADR-004: Token Lifetime for Delegated Access

> Written: 08.11.2026.

## Status

Proposed. No change selected.

## Context

Exchanged access tokens inherit the realm's access-token lifespan (typically
short, e.g. 5 minutes). They have no refresh token in the current
setup. A longer duration could be useful for delegated tasks.

Device and standard flows should keep the realm default. A possible separate
default for exchanged tokens is 30 days, configurable through EnvironmentConfig.
Keycloak uses one access-token lifespan per client, so changing the shared
client's setting also changes login tokens.

## Options

### Use a separate exchange client

Give an exchange client its own access-token lifespan. Keep the login client
on the realm default. Exchange callers would need the new client ID and
credentials. The existing scope and role restrictions must still apply.

### Keep one client with a custom extension

A Keycloak extension could apply a separate lifetime only to token exchange.
This keeps the current client and credentials but adds code to maintain and
check when Keycloak changes. It could also accept a requested shorter duration,
bounded by the configured exchange limit.

### Allow refresh tokens from exchange

Set `allowRefreshTokenInStandardTokenExchange` to `SAME_SESSION` and request a
refresh token during exchange. Access tokens would stay short-lived; the caller
would need to refresh them while the user session remains valid.

Keycloak does not allow this for source tokens from offline sessions. The
device-login helper uses an offline session, so this option does not cover
that path. The delegated-token helper would also need refresh support and
client credentials.

## Limits

Session limits can shorten the issued lifetime. From Keycloak 26.8.2, exchanged
tokens also cannot outlive their source token unless the requester client
enables **Allow exchange token expiration after subject token expiration**.
See [Keycloak token exchange](https://www.keycloak.org/securing-apps/token-exchange#_standard-token-exchange-details).

The virtual API validates JWTs locally, so an issued token can remain usable
until expiry after logout or client-secret rotation. Removing its profile or
RBAC binding can stop access sooner for all callers that use it.
