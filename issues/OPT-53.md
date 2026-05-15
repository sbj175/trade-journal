---
id: OPT-53
title: Implement OAuth2 Authorization Code flow for user onboarding
status: Done
priority: High
assignee: Steve Johnson
created: 2026-02-13
started: 2026-02-24
completed: 2026-02-25
labels: [SaaS Migration]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-53/implement-oauth2-authorization-code-flow-for-user-onboarding
---

# OPT-53: Implement OAuth2 Authorization Code flow for user onboarding

## Research Findings

Tastytrade supports the standard OAuth2 Authorization Code flow (redirect-based), which enables a smooth "Connect to Tastytrade" onboarding experience for SaaS users. This replaces the current manual copy/paste of provider_secret + refresh_token.

### How the Flow Works

1. User clicks "Connect to Tastytrade" in the app
2. Redirected to `https://my.tastytrade.com/auth.html` with `client_id`, `redirect_uri`, `scope=read`, `state`
3. User logs in on Tastytrade's site and clicks "Allow"
4. Redirected back to the app with an authorization code
5. Backend exchanges the code for tokens via `POST https://api.tastyworks.com/oauth/token` with `grant_type=authorization_code`
6. Refresh token stored securely, passed to `Session(provider_secret, refresh_token)`

### Key Technical Details

**Endpoints:**

* Authorization: `https://my.tastytrade.com/auth.html`
* Token exchange: `https://api.tastyworks.com/oauth/token`
* Sandbox auth: `https://cert-my.staging-tasty.works/auth.html`
* Sandbox token: `https://api.cert.tastyworks.com/oauth/token`

**OAuth2 Scopes (only two):**

* `read` — Account info, positions, balances, transactions, market data
* `trade` — Place and manage orders
* For this app, only `read` scope is needed

**Grant Types Supported:**

| Grant Type | Supported | Notes |
| -- | -- | -- |
| Authorization Code | Yes | Full redirect-based flow |
| Refresh Token | Yes | Used for ongoing access after initial auth |
| PKCE | No | Returns 405 Method Not Allowed |

**Token Lifecycle:**

* Access tokens expire after 15 minutes (auto-refreshed by Python SDK)
* Refresh tokens do not expire

### Python SDK Gap

The `tastytrade` Python SDK (v12) does **not** implement the authorization code flow. It only supports `Session(provider_secret, refresh_token)`. The auth code flow needs to be built in FastAPI:

1. `GET /auth/tastytrade` — Builds authorization URL and redirects user
2. `GET /auth/tastytrade/callback` — Receives authorization code, exchanges for tokens
3. Store refresh token securely, create `Session` with it

The [tasty-go SDK](<https://github.com/laustindasauce/tasty-go>) has a complete reference implementation of the auth code flow (`GetAuthorizationURL()`, `StartRedirectServer()`, `WaitForCode()`, `ExchangeCodeForTokens()`).

### API Terms of Service

* Each user must have their own unique token — sharing tokens across users is prohibited
* Multi-user SaaS pattern is permitted (QuantConnect does this)
* Building a commercial multi-user app likely requires becoming a Tastytrade partner
* Contact: `api.support@tastytrade.com`

### Proof of Concept

QuantConnect uses this exact flow with multiple end-users. Their docs describe: "Click Authenticate → On the tastytrade website, log in → Click Allow to grant access."

### References

* [Tastytrade Developer Portal](<https://developer.tastytrade.com/>)
* [Tastytrade OAuth2 Docs](<https://developer.tastytrade.com/oauth/>)
* [tastytrade Python SDK - session.py](<https://github.com/tastyware/tastytrade/blob/master/tastytrade/session.py>)
* [tasty-go SDK (auth code flow reference)](<https://github.com/laustindasauce/tasty-go>)
* [tastytrade-api-js (official JS SDK)](<https://github.com/tastytrade/tastytrade-api-js>)
* [Tastytrade API Terms of Service (PDF)](<https://assets.tastyworks.com/production/documents/open_api_terms_and_conditions.pdf>)
* [Tastytrade Postman Collection](<https://www.postman.com/tastytradeapi/tastytrade-api/documentation/p5jnvzh/tastytrade-api>)

### Action Items

- [X] Contact `api.support@tastytrade.com` about partner program for commercial multi-user app
- [ ] Register an OAuth application on [my.tastytrade.com](<http://my.tastytrade.com>) with production callback URL (can be done in Phase 2)
- [ ] Build auth code flow endpoints in FastAPI (Phase 1 of SaaS conversion)
- [ ] Test with sandbox endpoints before production

## Comments

### 2026-02-24 — Steve Johnson

## Implementation Complete

Branch: `opt-53-oauth-authorization-code-flow`

### What was built

**New file: `src/routers/tastytrade_oauth.py`** — Three endpoints:
- `POST /api/auth/tastytrade/authorize` (JWT required) — Builds Tastytrade authorization URL with Fernet-encrypted state parameter
- `GET /auth/tastytrade/callback` (public) — Receives redirect from Tastytrade, exchanges auth code for refresh token, stores encrypted in DB, redirects to `/positions`
- `POST /api/auth/tastytrade/disconnect` (JWT required) — Removes credentials and disconnects

**Modified files:**
- `app.py` — Registered new router
- `src/utils/auth_manager.py` — `_load_user_credentials()` now falls back to `TASTYTRADE_CLIENT_SECRET` env var when `encrypted_provider_secret` is NULL (for auth-code-flow users)
- `static/js/auth.js` — Added `requireTastytrade()` function that redirects to Settings onboarding if credentials aren't configured
- `static/js/positions-app.js`, `ledger-app.js`, `reports-app.js`, `risk-app.js` — Added `await Auth.requireTastytrade()` after `requireAuth()` in init
- `static/js/settings-app.js` — Added onboarding/authEnabled state, `connectTastytrade()` and `disconnectTastytrade()` methods, URL param parsing for tab/onboarding/error
- `static/settings.html` — Conditional UI: auth-enabled shows OAuth connect button with onboarding welcome panel; auth-disabled shows existing manual credential form
- `CLAUDE.md` — Documented the full flow, env vars, architecture, developer rules

### New env vars needed
```
TASTYTRADE_CLIENT_ID=<tastytrade-client-id>
TASTYTRADE_CLIENT_SECRET=<same as TASTYTRADE_PROVIDER_SECRET>
TASTYTRADE_REDIRECT_URI=http://localhost:8000/auth/tastytrade/callback
```

### Before testing
The registered redirect URI on Tastytrade must be updated from `http://localhost:8000` to `http://localhost:8000/auth/tastytrade/callback`.
