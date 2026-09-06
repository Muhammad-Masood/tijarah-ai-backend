# Tijarah AI Backend

The backend powering **Tijarah AI** — an AI-driven intelligence hub for e-commerce sellers. It connects to **Daraz** and **Shopify**, and provides dashboards, analytics, AI chat, product listing tools, review intelligence, and WhatsApp customer support through a single, secure REST + WebSocket API.

---

## What It Does

| Capability | Description |
|---|---|
| **Marketplace Integration** | Secure OAuth connection to Daraz and Shopify seller accounts — manage products, orders, inventory, and payouts in one place. |
| **Financial Analytics** | Per-product profit & loss, fee breakdowns, payout tracking, cash-flow trends, and settlement reconciliation — with chart-ready data for the UI. |
| **SEO Keyword Analysis** | AI-powered keyword research for any product: discovers high-intent search phrases, measures competition, and ranks "winning" keywords — streamed live to the UI stage-by-stage. |
| **Reviews Intelligence** | Scrape and analyze product reviews with LLMs to surface sentiment, recurring complaints, and improvement opportunities. |
| **AI Chat Assistant** | Chat with your data — ask about orders, products, or performance in natural language. Includes product-focused and general assistant chat. |
| **Returns & Insights** | Returns dashboards with reasons, refund totals, dispute tracking, and monthly trends. |
| **WhatsApp Customer Support** | An AI agent that confirms orders and summarizes merchant chats over WhatsApp on a schedule. |
| **Product Listing** | Draft, review, and publish product listings to marketplaces with AI assistance. |
| **Expense Tracking** | Record per-product costs so profit calculations reflect your true margins. |

---

## Technology Stack

- **Python 3.11+** with **FastAPI** — modern, high-performance REST/WebSocket API
- **PostgreSQL** (via SQLModel) — primary data store with automatic schema migration on startup
- **Redis** — caching layer for marketplace and analytics data
- **OpenAI / OpenRouter** — LLM reasoning and embeddings for the AI features
- **Poetry** — deterministic dependency management
- **Plotly** — chart data generated server-side for the frontend
- **Supabase Storage** — product image hosting

---

## Getting Started

### Prerequisites

- Python **3.11** or newer
- [Poetry](https://python-poetry.org/docs/#installation)
- A **PostgreSQL** database
- A **Daraz seller account** (for marketplace features)
- OpenAI or OpenRouter API keys (for AI features)

### Installation

```bash
# 1. Clone the repository and enter the folder
cd tijarah-ai-backend

# 2. Install dependencies into an isolated environment
poetry install

# 3. Create your environment file
copy .env.example .env        # Windows
cp .env.example .env          # macOS / Linux

# 4. Open .env and fill in your real credentials
#    (database URL, API keys, secrets — see table below)

# 5. Start the server with auto-reload
make run
```

The API is now available at **http://localhost:8000**.

### Interactive API Documentation

FastAPI ships with built-in docs — no setup required:

- **Swagger UI:** http://localhost:8000/docs — browse and test every endpoint live
- **ReDoc:** http://localhost:8000/redoc — readable reference documentation
- **Health check:** http://localhost:8000/health

---

## Configuration

All settings are read from the `.env` file:

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | API key for LLM + embeddings |
| `DARAZ_APP_KEY` / `DARAZ_APP_SECRET` | Daraz open-API credentials |
| `DARAZ_API_URL` / `DARAZ_AUTH_URL` | Daraz REST endpoints |
| `DB_CONNECTION_STRING` | PostgreSQL connection URL |
| `SECRET_KEY` | Encryption key for stored tokens |
| `JWT_ALGORITHM` / `ACCESS_TOKEN_EXPIRE_MINUTES` | Authentication token settings |
| `SHOPIFY_API_KEY` / `SHOPIFY_API_SECRET` / `SHOPIFY_API_VERSION` / `SHOPIFY_SCOPES` | Shopify app credentials |
| `SUPABASE_URL` / `SUPABASE_SECRET_KEY` / `SUPABASE_PRODUCT_BUCKET` | Image storage |
| `APP_CALLBACK_URL` | OAuth callback URL |

> Never commit your `.env` file — it is excluded via `.gitignore`.

---

## API Overview

| Area | Base Path | Highlights |
|---|---|---|
| Authentication | `/auth` | Signup, login, JWT tokens |
| Daraz integration | `/daraz` | Products, orders, financial dashboards, keyword analysis, review scraping, returns insights |
| Shopify integration | `/shopify` | Products, orders, inventory sync |
| Marketplace connections | `/marketplace` | Connect / manage seller accounts |
| Reviews analysis | `/reviews` | LLM-powered review analysis with streaming |
| Forecasting | `/forecast` | Sales & inventory forecasting |
| Product listing | `/product-listing` | AI-assisted listing creation & publishing |
| Expenses | `/expenses` | Per-product cost tracking |
| Storage | `/storage` | Product image uploads |
| Tijarah chat | `/tijarah` | WebSocket AI assistant with live token streaming |
| WhatsApp support | `/whatsapp/support` | Order confirmations & merchant chat summaries |

All endpoints (except auth and chat) require a bearer token obtained from `/auth`.

---

## Project Structure

```
neurocom_backend/
├── main.py              # FastAPI app, routers, startup (DB migration, scheduler)
├── dependencies.py      # Authentication & role-based access
├── routers/             # HTTP endpoints per feature
├── services/            # Business logic (analytics, AI agents, integrations)
├── models/              # Request/response schemas (Pydantic)
├── schemas/             # Auth schemas
├── database/            # DB connection, ORM models, seeding
├── mcp_server/          # Embedded MCP (Model Context Protocol) server
├── agents/              # AI agent orchestration
└── utils/               # Settings, security, caching, SSE helpers
```

---

## Real-Time & Streaming

- **WebSocket** — the `/tijarah` chat assistant streams AI responses token-by-token.
- **Server-Sent Events (SSE)** — long-running analyses (keyword research, review analysis, returns insights) stream progress and partial results so the UI updates instantly at every stage instead of waiting for the final answer.

---

## Security

- Passwords hashed with **bcrypt**; sessions via signed **JWT** tokens.
- Marketplace access tokens are **encrypted at rest** and scoped per merchant.
- Role-based access control (`require_roles`) guards administrative operations.
- CORS restricted to configured frontend origins.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `Address already in use` on port 8000 | Stop the other process or run `poetry run uvicorn neurocom_backend.main:app --port 8001 --reload` |
| Database errors on startup | Verify `DB_CONNECTION_STRING` in `.env` and that PostgreSQL is running |
| Daraz/Shopify calls return 401 | Reconnect the marketplace from the UI to refresh the OAuth token |
| AI endpoints fail | Check `OPENAI_API_KEY` (or OpenRouter key) in `.env` |

---

## Support

For deployment help, feature requests, or issues, contact the development team.
