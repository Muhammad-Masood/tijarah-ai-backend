# Getting Started

<cite>
**Referenced Files in This Document**
- [README.md](file://README.md)
- [Makefile](file://Makefile)
- [pyproject.toml](file://pyproject.toml)
- [main.py](file://neurocom_backend/main.py)
- [settings.py](file://neurocom_backend/utils/settings.py)
- [connection.py](file://neurocom_backend/database/connection.py)
- [redis_cache.py](file://neurocom_backend/utils/redis_cache.py)
- [security.py](file://neurocom_backend/utils/security.py)
</cite>

## Table of Contents
1. Introduction
2. Prerequisites
3. Installation
4. Environment Configuration
5. Running the Server
6. Initial Verification
7. Basic Usage Examples
8. Troubleshooting Guide
9. Conclusion

## Introduction
This guide helps you set up and run the Tijarah AI Backend quickly. You will install dependencies with Poetry, configure environment variables for PostgreSQL and Redis, start the server, and verify that it is running. The backend uses FastAPI and exposes a health endpoint to confirm successful startup.

## Prerequisites
Ensure your system has the following installed before proceeding:
- Python 3.11 or newer
- Poetry (Python package manager)
- A running PostgreSQL server
- A running Redis server

These requirements are enforced by the project configuration and runtime modules that read database and cache settings from environment variables.

**Section sources**
- [pyproject.toml:8-10](file://pyproject.toml#L8-L10)
- [connection.py:9-13](file://neurocom_backend/database/connection.py#L9-L13)
- [settings.py:17-21](file://neurocom_backend/utils/settings.py#L17-L21)

## Installation
Follow these steps to prepare your environment:

1. Install Python 3.11+ if not already installed.
2. Install Poetry using the official installer for your platform.
3. Clone or open the repository in your terminal.
4. Create and activate a virtual environment managed by Poetry:
   - Run: poetry shell
5. Install project dependencies:
   - Run: poetry install

The dependency list and Python version constraint are defined in the project configuration file.

**Section sources**
- [pyproject.toml:1-10](file://pyproject.toml#L1-L10)

## Environment Configuration
Create a .env file in the repository root with the required variables. At minimum, provide:
- DB_CONNECTION_STRING: PostgreSQL connection string
- SECRET_KEY: Secret used for JWT and encryption utilities
- Optional but recommended: REDIS_HOST, REDIS_PORT, REDIS_USERNAME, REDIS_PASSWORD, REDIS_SSL

Example keys to include:
- DB_CONNECTION_STRING
- SECRET_KEY
- JWT_ALGORITHM (optional; defaults to HS256)
- ACCESS_TOKEN_EXPIRE_MINUTES (optional; defaults to 60)
- REDIS_HOST (optional; defaults to localhost)
- REDIS_PORT (optional; defaults to 6379)
- REDIS_USERNAME (optional)
- REDIS_PASSWORD (optional)
- REDIS_SSL (optional; boolean-like values supported)
- SUPABASE_URL, SUPABASE_SECRET_KEY, SUPABASE_PRODUCT_BUCKET (optional, for storage features)

Notes:
- Database migrations run automatically at application startup.
- Redis settings are consumed by the caching layer when enabled.
- Security utilities require SECRET_KEY to generate and decode tokens and to encrypt/decrypt values.

**Section sources**
- [settings.py:11-28](file://neurocom_backend/utils/settings.py#L11-L28)
- [connection.py:9-13](file://neurocom_backend/database/connection.py#L9-L13)
- [security.py:13-28](file://neurocom_backend/utils/security.py#L13-L28)

## Running the Server
You can start the server in development mode using either of the following methods:

- Using Make:
  - Run: make run
- Using Poetry directly:
  - Run: poetry run uvicorn neurocom_backend.main:app --host 0.0.0.0 --port 8000 --reload

The application mounts routers and sets up CORS based on configured allowed origins. On startup, it performs database migrations to ensure tables exist.

**Section sources**
- [Makefile:1-2](file://Makefile#L1-L2)
- [README.md:3-5](file://README.md#L3-L5)
- [main.py:16-37](file://neurocom_backend/main.py#L16-L37)

## Initial Verification
After starting the server, verify it is running:

- Open a browser or use curl to call:
  - http://localhost:8000/health
- Expected response:
  - {"message": "MCP SSE Server is running"}

If you see this response, the server is up and responding.

**Section sources**
- [main.py:43-45](file://neurocom_backend/main.py#L43-L45)

## Basic Usage Examples
Once the server is running, you can interact with endpoints as follows:

- Health check:
  - GET http://localhost:8000/health
- Root endpoint:
  - GET http://localhost:8000/

For authenticated routes, obtain a token via the authentication router and include it in requests as specified by each endpoint’s documentation. Authentication utilities rely on SECRET_KEY and JWT settings.

Note: Some features may require additional services (e.g., external marketplace integrations). Ensure those services are configured in your .env if you plan to use them.

**Section sources**
- [main.py:39-45](file://neurocom_backend/main.py#L39-L45)
- [security.py:22-28](file://neurocom_backend/utils/security.py#L22-L28)

## Troubleshooting Guide
Common setup issues and how to resolve them:

- Missing or invalid DB_CONNECTION_STRING
  - Symptom: Application fails to connect to the database or migration errors occur.
  - Action: Verify your PostgreSQL connection string and network access.
  - Reference: [connection.py:9-13](file://neurocom_backend/database/connection.py#L9-L13)

- Missing SECRET_KEY
  - Symptom: Token creation or encryption/decryption raises an error.
  - Action: Add SECRET_KEY to your .env file.
  - Reference: [security.py:31-35](file://neurocom_backend/utils/security.py#L31-L35)

- Redis connectivity problems
  - Symptom: Cache operations fail or time out.
  - Action: Confirm Redis host, port, credentials, and SSL settings match your environment.
  - Reference: [settings.py:17-21](file://neurocom_backend/utils/settings.py#L17-L21), [redis_cache.py:56-71](file://neurocom_backend/utils/redis_cache.py#L56-L71)

- CORS errors from frontend
  - Symptom: Browser blocks requests due to origin restrictions.
  - Action: Update ALLOWED_ORIGINS in .env or settings to include your frontend URL(s).
  - Reference: [settings.py:11](file://neurocom_backend/utils/settings.py#L11), [main.py:30-36](file://neurocom_backend/main.py#L30-L36)

- Port conflicts
  - Symptom: Server fails to bind to port 8000.
  - Action: Change the port in the uvicorn command or stop the conflicting process.
  - Reference: [Makefile:1-2](file://Makefile#L1-L2), [README.md:3-5](file://README.md#L3-L5)

- Migrations failing
  - Symptom: Tables not created or constraints errors during startup.
  - Action: Check database permissions and schema compatibility; review logs for SQL errors.
  - Reference: [connection.py:15-23](file://neurocom_backend/database/connection.py#L15-L23)

## Conclusion
You now have everything needed to install, configure, and run the Tijarah AI Backend. Use the health endpoint to verify your setup, then proceed to integrate with the API. For advanced features, ensure all required environment variables are set and external services are reachable.