---
kind: design
name: Single LangGraph agent with marketplace-scoped tools over sub-agents
source: session
category: adr
---

# Single LangGraph agent with marketplace-scoped tools over sub-agents

_Source: coding plans from commit period 0ce6e01 → a79d4e6 — records intent at planning time; the implementation may lag or differ._

**Status:** accepted

## Context
The new Ask Tijarah conversational agent must answer merchant queries that span multiple domains (catalog, orders, financials) and potentially multiple marketplaces (Daraz, Shopify). A supervisor/sub-agent pattern was considered but would add coordination latency and cost.

## Decision drivers
- query complexity across domains
- latency/cost of inter-agent calls
- LLM tool-selection capability at scale

## Considered options
- **Single agent with ~16 marketplace-aware tools** — pros: No coordination overhead; LLM already selects among 16 tools well; simpler state management via MemorySaver per connection
- **Sub-agents per domain or marketplace** _(rejected)_ — pros: Cleaner separation of concerns; easier to scale beyond a certain tool count; cons: Adds supervisor routing latency and cost; most merchant queries naturally span multiple domains making isolation counterproductive

## Decision
Build one LangGraph agent per WebSocket connection that holds all ~16 tools as closures over a TijarahContext; each tool accepts an optional marketplace parameter so the same agent can query Daraz, Shopify, or both in a single turn.

## Consequences
Tool count is capped around 16-30 before re-evaluating a sub-agent split. State lives in MemorySaver per connection, which is fine for single-worker deployments but will need swapping to Redis/Postgres checkpointer when scaling horizontally.