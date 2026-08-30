# Environment Setup & Configuration

<cite>
**Referenced Files in This Document**
- [settings.py](file://neurocom_backend/utils/settings.py)
- [connection.py](file://neurocom_backend/database/connection.py)
- [redis_cache.py](file://neurocom_backend/utils/redis_cache.py)
- [security.py](file://neurocom_backend/utils/security.py)
- [storage_service.py](file://neurocom_backend/services/storage_service.py)
- [shopify_service.py](file://neurocom_backend/services/shopify_service.py)
- [daraz_service.py](file://neurocom_backend/services/daraz_service.py)
- [chat_service.py](file://neurocom_backend/services/chat_service.py)
- [client.py](file://neurocom_backend/mcp_server/client.py)
- [main.py](file://neurocom_backend/main.py)
- [Makefile](file://Makefile)
- [README.md](file://README.md)
- [pyproject.toml](file://pyproject.toml)
</cite>

## Table of Contents
1. [Introduction](#introduction)
2. [Project Structure](#project-structure)
3. [Core Components](#core-components)
4. [Architecture Overview](#architecture-overview)
5. [Detailed Component Analysis](#detailed-component-analysis)
6. [Dependency Analysis](#dependency-analysis)
7. [Performance Considerations](#performance-considerations)
8. [Troubleshooting Guide](#troubleshooting-guide)
9. [Conclusion](#conclusion)
10. [Appendices](#appendices)

## Introduction
This document provides comprehensive environment setup and configuration guidance for the Tijarah AI Backend. It covers all required environment variables, database connection settings, Redis configuration, external service integrations (Shopify, Daraz, Supabase Storage, OpenAI-compatible providers), and how configuration is loaded at runtime. It also documents security considerations, secret management strategies, environment-specific overrides, and troubleshooting steps for common configuration issues.

The application uses environment variables via python-dotenv to load configuration from a .env file. There is no centralized Pydantic Settings model; instead, configuration values are read directly using os.getenv with defaults where applicable.

## Project Structure
Configuration is primarily defined and consumed across these areas:
- Centralized environment loading and shared constants: utils/settings.py
- Database engine creation and session handling: database/connection.py
- Redis-backed caching layer: utils/redis_cache.py
- Security utilities (JWT, password hashing, encryption): utils/security.py
- External integrations: services/* (Shopify, Daraz, Supabase Storage, Chat/LM providers)
- Entry points and tooling: main.py, Makefile, README.md, pyproject.toml

```mermaid
graph TB
A["Application Startup<br/>main.py"] --> B["Settings Loader<br/>utils/settings.py"]
A --> C["Database Engine<br/>database/connection.py"]
A --> D["Redis Cache Client<br/>utils/redis_cache.py"]
A --> E["Security Utilities<br/>utils/security.py"]
A --> F["External Services<br/>services/*"]
F --> G["Shopify Service<br/>services/shopify_service.py"]
F --> H["Daraz Service<br/>services/daraz_service.py"]
F --> I["Storage Service<br/>services/storage_service.py"]
F --> J["Chat/LM Clients<br/>services/chat_service.py, mcp_server/client.py"]
```

**Diagram sources**
- [main.py](file://neurocom_backend/main.py)
- [settings.py](file://neurocom_backend/utils/settings.py)
- [connection.py](file://neurocom_backend/database/connection.py)
- [redis_cache.py](file://neurocom_backend/utils/redis_cache.py)
- [security.py](file://neurocom_backend/utils/security.py)
- [shopify_service.py](file://neurocom_backend/services/shopify_service.py)
- [daraz_service.py](file://neurocom_backend/services/daraz_service.py)
- [storage_service.py](file://neurocom_backend/services/storage_service.py)
- [chat_service.py](file://neurocom_backend/services/chat_service.py)
- [client.py](file://neurocom_backend/mcp_server/client.py)

**Section sources**
- [README.md:1-6](file://README.md#L1-L6)
- [Makefile:1-2](file://Makefile#L1-L2)
- [pyproject.toml:1-40](file://pyproject.toml#L1-L40)

## Core Components
This section summarizes the key configuration components and their responsibilities.

- Settings loader and shared constants
  - Loads .env early so other modules can safely import derived constants at import time.
  - Exposes shared configuration such as JWT parameters, Redis settings, Shopify cache TTLs, and Supabase storage settings.

- Database
  - Creates SQLAlchemy engine using DB_CONNECTION_STRING.
  - Enables SQL echo based on SQL_ECHO.
  - Provides migration helper and session generator.

- Redis cache
  - Initializes a single redis client instance with host, port, username, password, SSL, and timeouts.
  - Uses configurable TTLs for marketplace caches.

- Security
  - Reads SECRET_KEY, JWT_ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES.
  - Provides password hashing/verification, JWT encode/decode, and symmetric encryption helpers.

- External services
  - Shopify: requires API key/secret and optional version/scopes; validates presence before OAuth token exchange.
  - Daraz: requires app key/secret; supports caching with background refresh.
  - Supabase Storage: requires URL and secret key; validates presence before upload/download/delete.
  - Chat/LM providers: require provider-specific API keys (e.g., OpenRouter, Groq).

**Section sources**
- [settings.py:1-29](file://neurocom_backend/utils/settings.py#L1-L29)
- [connection.py:1-28](file://neurocom_backend/database/connection.py#L1-L28)
- [redis_cache.py:1-204](file://neurocom_backend/utils/redis_cache.py#L1-L204)
- [security.py:1-44](file://neurocom_backend/utils/security.py#L1-L44)
- [shopify_service.py:1-200](file://neurocom_backend/services/shopify_service.py#L1-L200)
- [daraz_service.py:1-200](file://neurocom_backend/services/daraz_service.py#L1-L200)
- [storage_service.py:1-142](file://neurocom_backend/services/storage_service.py#L1-L142)
- [chat_service.py:1-29](file://neurocom_backend/services/chat_service.py#L1-L29)
- [client.py:1-178](file://neurocom_backend/mcp_server/client.py#L1-L178)

## Architecture Overview
The backend loads configuration at startup through multiple modules that each call dotenv or rely on a central loader. The application then initializes:
- Database engine and session factory
- Redis client (lazy initialization)
- Security utilities (JWT, encryption)
- External service clients (Shopify, Daraz, Supabase, LM providers)

```mermaid
sequenceDiagram
participant App as "App (main.py)"
participant Env as ".env loader"
participant DB as "DB Engine (connection.py)"
participant RC as "Redis Cache (redis_cache.py)"
participant SEC as "Security (security.py)"
participant EXT as "External Services"
App->>Env : Load environment variables
App->>DB : Create engine with DB_CONNECTION_STRING
App->>RC : Initialize Redis client (host/port/ssl/auth)
App->>SEC : Read SECRET_KEY, JWT_ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
App->>EXT : Configure Shopify/Daraz/Supabase/LM clients
Note over App,EXT : All configuration sourced from environment variables
```

**Diagram sources**
- [settings.py:1-29](file://neurocom_backend/utils/settings.py#L1-L29)
- [connection.py:1-28](file://neurocom_backend/database/connection.py#L1-L28)
- [redis_cache.py:1-204](file://neurocom_backend/utils/redis_cache.py#L1-L204)
- [security.py:1-44](file://neurocom_backend/utils/security.py#L1-L44)
- [shopify_service.py:1-200](file://neurocom_backend/services/shopify_service.py#L1-L200)
- [daraz_service.py:1-200](file://neurocom_backend/services/daraz_service.py#L1-L200)
- [storage_service.py:1-142](file://neurocom_backend/services/storage_service.py#L1-L142)
- [chat_service.py:1-29](file://neurocom_backend/services/chat_service.py#L1-L29)
- [client.py:1-178](file://neurocom_backend/mcp_server/client.py#L1-L178)

## Detailed Component Analysis

### Environment Variables Reference
Below is a consolidated list of environment variables used by the application, grouped by purpose.

- Application and security
  - SECRET_KEY: Required for JWT signing and encryption.
  - JWT_ALGORITHM: Algorithm used for JWT (default HS256).
  - ACCESS_TOKEN_EXPIRE_MINUTES: Token lifetime in minutes (default 60).

- Database
  - DB_CONNECTION_STRING: Full database connection string.
  - SQL_ECHO: Enable SQL logging when set to true/1/yes.

- Redis
  - REDIS_HOST: Hostname (default localhost).
  - REDIS_PORT: Port (default 6379).
  - REDIS_USERNAME: Optional username for Redis authentication.
  - REDIS_PASSWORD: Optional password for Redis authentication.
  - REDIS_SSL: Enable SSL for Redis connections (true/1/yes).
  - DARAZ_CACHE_TTL_SECONDS: Default TTL for Daraz cache entries.
  - SHOPIFY_CACHE_TTL_SECONDS: Default TTL for Shopify cache entries.

- Shopify integration
  - SHOPIFY_API_KEY: Shopify app client ID.
  - SHOPIFY_API_SECRET: Shopify app client secret.
  - SHOPIFY_APP_CALLBACK_URL: Redirect URI for OAuth flow.
  - SHOPIFY_API_VERSION: GraphQL API version (default 2025-01).
  - SHOPIFY_SCOPES: Comma-separated OAuth scopes (default includes product/order/inventory/publication permissions).

- Daraz integration
  - DARAZ_APP_KEY: Daraz app key.
  - DARAZ_APP_SECRET: Daraz app secret.
  - APP_CALLBACK_URL: Callback URL used in authorization flows.

- Supabase Storage
  - SUPABASE_URL: Base URL for Supabase project.
  - SUPABASE_SECRET_KEY: Service role or appropriate key for storage operations.
  - SUPABASE_PRODUCT_BUCKET: Bucket name for product images (default product-images).

- AI / LLM providers
  - OPEN_ROUTER_AI_API_KEY: API key for OpenRouter-based chat services.
  - GROQ_API_KEY: API key for Groq-based LLM calls (used in MCP client).
  - GEMINI_API_KEY: Optional key for Google Generative AI (commented usage in MCP client).

Notes:
- Many modules call load_dotenv() to ensure .env is loaded before reading environment variables.
- Some variables have sensible defaults; others are strictly required and will raise errors if missing.

**Section sources**
- [settings.py:11-29](file://neurocom_backend/utils/settings.py#L11-L29)
- [connection.py:9-13](file://neurocom_backend/database/connection.py#L9-L13)
- [redis_cache.py:56-71](file://neurocom_backend/utils/redis_cache.py#L56-L71)
- [security.py:13-28](file://neurocom_backend/utils/security.py#L13-L28)
- [shopify_service.py:21-25](file://neurocom_backend/services/shopify_service.py#L21-L25)
- [daraz_service.py:35](file://neurocom_backend/services/daraz_service.py#L35)
- [storage_service.py:32-35](file://neurocom_backend/services/storage_service.py#L32-L35)
- [chat_service.py:7-10](file://neurocom_backend/services/chat_service.py#L7-L10)
- [client.py:22-32](file://neurocom_backend/mcp_server/client.py#L22-L32)

### Database Connection Settings
- The database engine is created with a connection string from DB_CONNECTION_STRING.
- SQL echo can be toggled via SQL_ECHO.
- Migration helper creates tables and applies PostgreSQL-specific adjustments.
- Session generator yields sessions for request handling.

Best practices:
- Use a secure connection string with least-privilege credentials.
- Ensure network access to the database from the deployment environment.
- Validate connectivity during startup or health checks.

**Section sources**
- [connection.py:1-28](file://neurocom_backend/database/connection.py#L1-L28)

### Redis Configuration and Caching
- Redis client is lazily initialized with host, port, username, password, SSL, and timeouts.
- Cache entries store both transformed value and content hash of raw payload.
- Background stale-while-revalidate refreshes data without blocking requests.
- TTLs are configurable per service (Daraz, Shopify).

Operational notes:
- For managed Redis (e.g., cloud), enable REDIS_SSL and provide credentials.
- Tune socket timeouts if connecting to remote Redis instances.
- Monitor cache hit rates and adjust TTLs based on upstream API stability.

**Section sources**
- [redis_cache.py:56-71](file://neurocom_backend/utils/redis_cache.py#L56-L71)
- [redis_cache.py:110-150](file://neurocom_backend/utils/redis_cache.py#L110-L150)
- [redis_cache.py:152-204](file://neurocom_backend/utils/redis_cache.py#L152-L204)
- [settings.py:17-25](file://neurocom_backend/utils/settings.py#L17-L25)

### Security and Secrets Management
- SECRET_KEY is required for JWT and encryption; missing it raises a runtime error.
- JWT algorithm and token expiry are configurable.
- Password hashing uses bcrypt via passlib.
- Symmetric encryption helpers derive a Fernet key from SECRET_KEY.

Secret management recommendations:
- Store secrets in environment variables injected by your platform (Kubernetes Secrets, Docker secrets, CI/CD vaults).
- Avoid committing .env files to version control; use .gitignore.
- Rotate SECRET_KEY carefully; existing encrypted values will become unreadable after rotation.

**Section sources**
- [security.py:13-44](file://neurocom_backend/utils/security.py#L13-L44)
- [settings.py:13-15](file://neurocom_backend/utils/settings.py#L13-L15)

### External Service Integrations

#### Shopify
- Requires SHOPIFY_API_KEY and SHOPIFY_API_SECRET; missing credentials raise an internal server error during token exchange.
- Supports configurable API version and OAuth scopes.
- Uses GraphQL endpoints for product and order operations.

Operational tips:
- Ensure redirect URI matches Shopify app configuration.
- Validate scopes include necessary permissions.
- Handle userErrors returned by Shopify API appropriately.

**Section sources**
- [shopify_service.py:21-25](file://neurocom_backend/services/shopify_service.py#L21-L25)
- [shopify_service.py:87-121](file://neurocom_backend/services/shopify_service.py#L87-L121)

#### Daraz
- Requires DARAZ_APP_KEY and DARAZ_APP_SECRET to initialize the client.
- Uses caching with background refresh to reduce upstream API calls.
- Removes volatile envelope keys before hashing to avoid false cache misses.

Operational tips:
- Set appropriate cache TTLs based on product update frequency.
- Monitor rate limits and backoff behavior from the marketplace API.

**Section sources**
- [daraz_service.py:35](file://neurocom_backend/services/daraz_service.py#L35)
- [daraz_service.py:48-100](file://neurocom_backend/services/daraz_service.py#L48-L100)

#### Supabase Storage
- Requires SUPABASE_URL and SUPABASE_SECRET_KEY; missing configuration returns a 503.
- Uploads enforce allowed image types and size limits.
- Downloads and deletes use service role key for private buckets.

Operational tips:
- Restrict bucket policies to least privilege.
- Validate paths to prevent traversal attacks.
- Use HTTPS URLs for public objects.

**Section sources**
- [storage_service.py:32-35](file://neurocom_backend/services/storage_service.py#L32-L35)
- [storage_service.py:46-74](file://neurocom_backend/services/storage_service.py#L46-L74)
- [storage_service.py:77-102](file://neurocom_backend/services/storage_service.py#L77-L102)
- [storage_service.py:128-142](file://neurocom_backend/services/storage_service.py#L128-L142)

#### AI / LLM Providers
- Chat service uses OpenRouter-compatible endpoint with OPEN_ROUTER_AI_API_KEY.
- MCP client uses Groq-compatible endpoint with GROQ_API_KEY (and optionally Gemini).
- Ensure base_url and api_key are correctly configured per provider.

Operational tips:
- Pin model names per environment to control costs and performance.
- Implement retries and timeouts for provider calls.

**Section sources**
- [chat_service.py:7-10](file://neurocom_backend/services/chat_service.py#L7-L10)
- [client.py:22-32](file://neurocom_backend/mcp_server/client.py#L22-L32)

### Configuration Loading Flow
```mermaid
flowchart TD
Start(["Process Start"]) --> LoadEnv["Load .env via python-dotenv"]
LoadEnv --> Settings["Read shared settings<br/>JWT, Redis, Shopify, Supabase"]
Settings --> DBInit["Initialize DB engine<br/>DB_CONNECTION_STRING"]
Settings --> RedisInit["Initialize Redis client<br/>host/port/ssl/auth"]
Settings --> SecInit["Initialize security<br/>SECRET_KEY, JWT config"]
Settings --> ExtInit["Configure external services<br/>Shopify, Daraz, Supabase, LMs"]
DBInit --> Ready(["Ready"])
RedisInit --> Ready
SecInit --> Ready
ExtInit --> Ready
```

**Diagram sources**
- [settings.py:1-29](file://neurocom_backend/utils/settings.py#L1-L29)
- [connection.py:1-28](file://neurocom_backend/database/connection.py#L1-L28)
- [redis_cache.py:1-204](file://neurocom_backend/utils/redis_cache.py#L1-L204)
- [security.py:1-44](file://neurocom_backend/utils/security.py#L1-L44)
- [shopify_service.py:1-200](file://neurocom_backend/services/shopify_service.py#L1-L200)
- [daraz_service.py:1-200](file://neurocom_backend/services/daraz_service.py#L1-L200)
- [storage_service.py:1-142](file://neurocom_backend/services/storage_service.py#L1-L142)
- [chat_service.py:1-29](file://neurocom_backend/services/chat_service.py#L1-L29)
- [client.py:1-178](file://neurocom_backend/mcp_server/client.py#L1-L178)

## Dependency Analysis
Key dependencies and their roles:
- python-dotenv: Loads environment variables from .env.
- sqlmodel/sqlalchemy: Database ORM and engine creation.
- redis: Redis client for caching.
- cryptography/passlib/pyjwt: Security utilities for encryption and JWT.
- requests: HTTP client for external APIs.
- openai/google-genai: LLM provider clients.

```mermaid
graph LR
A["Environment Variables"] --> B["python-dotenv"]
B --> C["Settings (shared constants)"]
C --> D["SQLAlchemy/SQLModel"]
C --> E["Redis Client"]
C --> F["Security (JWT, Encryption)"]
C --> G["HTTP Clients (requests)"]
C --> H["LLM Clients (openai, google-genai)"]
```

**Diagram sources**
- [pyproject.toml:8-35](file://pyproject.toml#L8-L35)
- [settings.py:1-29](file://neurocom_backend/utils/settings.py#L1-L29)
- [connection.py:1-28](file://neurocom_backend/database/connection.py#L1-L28)
- [redis_cache.py:1-204](file://neurocom_backend/utils/redis_cache.py#L1-L204)
- [security.py:1-44](file://neurocom_backend/utils/security.py#L1-L44)

**Section sources**
- [pyproject.toml:8-35](file://pyproject.toml#L8-L35)

## Performance Considerations
- Redis caching reduces upstream API calls and CPU-intensive transforms; tune TTLs based on data volatility.
- Background refresh avoids blocking requests while revalidating cache.
- Connection pooling and retries for HTTP clients improve resilience.
- SQL echo should be disabled in production to reduce log noise.

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
Common configuration issues and resolutions:

- Missing or invalid database connection
  - Symptom: Engine creation fails or cannot connect.
  - Action: Verify DB_CONNECTION_STRING format and network access; check SQL_ECHO for debugging.

- Redis connection failures
  - Symptom: Cannot connect to Redis or timeouts.
  - Action: Confirm REDIS_HOST, REDIS_PORT, credentials, and REDIS_SSL; adjust socket timeouts if needed.

- JWT or encryption errors
  - Symptom: Runtime error indicating SECRET_KEY is not configured.
  - Action: Provide SECRET_KEY; ensure consistent JWT_ALGORITHM and ACCESS_TOKEN_EXPIRE_MINUTES.

- Shopify OAuth/token exchange failures
  - Symptom: Internal server error or bad request during token exchange.
  - Action: Ensure SHOPIFY_API_KEY and SHOPIFY_API_SECRET are set; verify redirect URI and scopes.

- Supabase Storage errors
  - Symptom: 503 when storage is not configured; 502 on network errors; 404 for missing objects.
  - Action: Set SUPABASE_URL and SUPABASE_SECRET_KEY; validate bucket name and object paths; check HTTPS requirement for public URLs.

- LLM provider errors
  - Symptom: Authentication or model errors.
  - Action: Provide correct API keys (OPEN_ROUTER_AI_API_KEY, GROQ_API_KEY); verify base_url and model names.

**Section sources**
- [connection.py:9-13](file://neurocom_backend/database/connection.py#L9-L13)
- [redis_cache.py:56-71](file://neurocom_backend/utils/redis_cache.py#L56-L71)
- [security.py:31-35](file://neurocom_backend/utils/security.py#L31-L35)
- [shopify_service.py:87-121](file://neurocom_backend/services/shopify_service.py#L87-L121)
- [storage_service.py:32-35](file://neurocom_backend/services/storage_service.py#L32-L35)
- [storage_service.py:46-74](file://neurocom_backend/services/storage_service.py#L46-L74)
- [chat_service.py:7-10](file://neurocom_backend/services/chat_service.py#L7-L10)
- [client.py:22-32](file://neurocom_backend/mcp_server/client.py#L22-L32)

## Conclusion
The Tijarah AI Backend relies on environment variables for all configuration, loaded via python-dotenv. Centralized settings expose shared constants, while individual modules initialize their respective clients (database, Redis, security, external services). Follow the recommended secret management practices, validate configurations per environment, and use the troubleshooting guide to resolve common issues quickly.

[No sources needed since this section summarizes without analyzing specific files]

## Appendices

### Step-by-Step Setup Instructions

- Development
  - Install dependencies using Poetry.
  - Create a .env file with required variables (see Environment Variables Reference).
  - Run the server using the provided Makefile command or Poetry run uvicorn.

- Staging
  - Inject environment variables via your staging platform (secrets manager, container env).
  - Ensure Redis SSL and credentials are configured for managed Redis.
  - Disable SQL echo and enable appropriate logging levels.

- Production
  - Use strong, rotated secrets (SECRET_KEY, provider API keys).
  - Configure Redis with SSL and proper authentication.
  - Validate database connectivity and perform migrations before serving traffic.
  - Monitor cache hit rates and adjust TTLs; review external API rate limits.

[No sources needed since this section provides general guidance]