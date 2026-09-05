---
kind: design
name: WebSocket endpoint without OAuth2PasswordBearer authentication
source: session
category: adr
---

# WebSocket endpoint without OAuth2PasswordBearer authentication

_Source: coding plans from commit period 0ce6e01 → a79d4e6 — records intent at planning time; the implementation may lag or differ._

**Status:** accepted

## Context
The /ask_tijarah endpoint must accept merchant credentials so the agent can call Daraz/Shopify APIs. Standard FastAPI OAuth2PasswordBearer does not work over WebSockets.

## Decision drivers
- WebSocket transport constraints
- backward compatibility with existing token resolution helpers
- flexibility to pass tokens inline vs. resolve from DB

## Considered options
- **Reuse existing auth-protected router pattern** _(rejected)_ — pros: Consistent with other routers; cons: OAuth2PasswordBearer is incompatible with WebSocket connections
- **Accept optional x-daraz-access-token and x-shopify-access-token headers and fall back to DB lookup** — pros: Works over WS; supports both explicit per-request scoping and auto-resolution from MarketplaceConnection; reuses existing _resolve_daraz_access_token and get_shopify_credentials helpers

## Decision
Register routers/tijarah_chat_router.py directly in main.py without require_auth; read marketplace tokens from WebSocket headers when present, otherwise decrypt stored tokens from MarketplaceConnection for the current merchant.

## Consequences
The endpoint is intentionally unauthenticated at the router level — security relies on the upstream proxy/load balancer protecting the /ask_tijarah path. Token scoping is enforced per connection via TijarahContext.