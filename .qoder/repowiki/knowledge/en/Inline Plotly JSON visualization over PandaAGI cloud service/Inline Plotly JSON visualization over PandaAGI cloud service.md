---
kind: design
name: Inline Plotly JSON visualization over PandaAGI cloud service
source: session
category: adr
---

# Inline Plotly JSON visualization over PandaAGI cloud service

_Source: coding plans from commit period 0ce6e01 → a79d4e6 — records intent at planning time; the implementation may lag or differ._

**Status:** accepted

## Context
The agent needs to render charts (revenue trends, top products, fee breakdowns) inside the chat stream rather than returning plain text tables. An external chart-generation service was considered.

## Decision drivers
- inline streaming into chat UI
- no new auth/service dependency
- agent-controlled data-to-chart mapping

## Considered options
- **PandaAGI cloud chart generation** _(rejected)_ — pros: Automated chart creation from dataframes; cons: Requires separate PANDA_AGI_KEY, generates files to a workspace directory, no streaming support, blocks until file write completes
- **Native Plotly spec returned from a create_visualization tool** — pros: Zero new runtime dependencies beyond plotly, returns Plotly.js-compatible JSON over the existing WebSocket stream, agent decides exactly what to visualize from already-fetched data

## Decision
Add a create_visualization tool that takes chart type, data points, and labels and returns a Plotly-compatible JSON spec; the frontend renders it via Plotly.js on receiving a visualization event.

## Consequences
Visualization logic stays inside the agent loop — no extra network hop or file I/O. The frontend must implement a Plotly renderer and handle the new visualization event type alongside token/tool events.