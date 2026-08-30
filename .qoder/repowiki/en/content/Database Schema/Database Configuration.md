# Database Configuration

<cite>
**Referenced Files in This Document**
- [connection.py](file://neurocom_backend/database/connection.py)
- [seed.py](file://neurocom_backend/database/seed.py)
- [main.py](file://neurocom_backend/main.py)
- [settings.py](file://neurocom_backend/utils/settings.py)
- [__init__.py](file://neurocom_backend/database/models/__init__.py)
- [marketplace.py](file://neurocom_backend/database/models/marketplace.py)
- [user.py](file://neurocom_backend/database/models/user.py)
- [product.py](file://neurocom_backend/database/models/product.py)
- [order.py](file://neurocom_backend/database/models/order.py)
- [merchant.py](file://neurocom_backend/database/models/merchant.py)
- [pyproject.toml](file://pyproject.toml)
- [Makefile](file://Makefile)
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
This document explains how the Tijarah AI Backend configures and initializes its database using SQLModel and SQLAlchemy. It covers connection setup, environment variables, connection string formatting, schema creation, migration behavior, seeding strategy, and operational guidance for development, staging, and production. It also outlines backup and recovery procedures, performance tuning parameters, monitoring considerations, and scaling/high availability notes based on the current codebase.

## Project Structure
The database layer is implemented under neurocom_backend/database with:
- Connection and session management
- Model definitions (SQLModel tables)
- A seed module (currently disabled)
- Migration logic executed at application startup

```mermaid
graph TB
subgraph "Database Layer"
C["connection.py"]
S["seed.py"]
M["models/*"]
end
subgraph "App Entry"
A["main.py"]
end
subgraph "Config"
U["utils/settings.py"]
P["pyproject.toml"]
K["Makefile"]
end
A --> C
C --> M
A --> U
P --> C
K --> A
```

**Diagram sources**
- [connection.py:1-28](file://neurocom_backend/database/connection.py#L1-L28)
- [main.py:1-90](file://neurocom_backend/main.py#L1-L90)
- [settings.py:1-29](file://neurocom_backend/utils/settings.py#L1-L29)
- [pyproject.toml:1-40](file://pyproject.toml#L1-L40)
- [Makefile:1-2](file://Makefile#L1-L2)

**Section sources**
- [connection.py:1-28](file://neurocom_backend/database/connection.py#L1-L28)
- [main.py:1-90](file://neurocom_backend/main.py#L1-L90)
- [settings.py:1-29](file://neurocom_backend/utils/settings.py#L1-L29)
- [pyproject.toml:1-40](file://pyproject.toml#L1-L40)
- [Makefile:1-2](file://Makefile#L1-L2)

## Core Components
- Engine and session: The engine is created from a connection string read from environment variables, with pooling configured via pool_recycle and optional SQL echo control.
- Migration: On app startup, tables are created and PostgreSQL-specific DDL adjustments are applied to ensure correct constraints and columns.
- Models: SQLModel classes define tables and relationships across users, merchants, marketplaces, orders, and products.
- Seeding: A seed script exists but is currently commented out; it demonstrates how to populate initial data.

**Section sources**
- [connection.py:9-27](file://neurocom_backend/database/connection.py#L9-L27)
- [main.py:16-29](file://neurocom_backend/main.py#L16-L29)
- [__init__.py:1-13](file://neurocom_backend/database/models/__init__.py#L1-L13)
- [seed.py:1-92](file://neurocom_backend/database/seed.py#L1-L92)

## Architecture Overview
At runtime, FastAPI loads environment variables and runs migrations before serving requests. The database engine uses a connection pool and exposes sessions via a generator used by services/routers.

```mermaid
sequenceDiagram
participant Proc as "Process"
participant App as "FastAPI main.py"
participant DBConn as "database/connection.py"
participant Models as "database/models/*"
participant DB as "PostgreSQL"
Proc->>App : Start server
App->>DBConn : perform_migration()
DBConn->>Models : Import all models
DBConn->>DB : create_all(metadata)
DBConn->>DB : Apply PostgreSQL DDL adjustments
DBConn-->>App : Migrations complete
App-->>Proc : Server ready
```

**Diagram sources**
- [main.py:16-29](file://neurocom_backend/main.py#L16-L29)
- [connection.py:9-23](file://neurocom_backend/database/connection.py#L9-L23)
- [__init__.py:1-13](file://neurocom_backend/database/models/__init__.py#L1-L13)

## Detailed Component Analysis

### Database Connection and Pooling
- Connection string: Read from DB_CONNECTION_STRING environment variable.
- Pool recycling: pool_recycle=300 seconds to refresh connections proactively.
- SQL echo: Enabled when SQL_ECHO is set to true/1/yes (case-insensitive).
- Session factory: get_session yields a new Session per request scope.

```mermaid
flowchart TD
Start(["Engine init"]) --> LoadEnv["Load .env"]
LoadEnv --> BuildURL["Read DB_CONNECTION_STRING"]
BuildURL --> CreateEngine["create_engine(..., pool_recycle=300, echo=...)"]
CreateEngine --> GetSession["get_session() yields Session(engine)"]
GetSession --> End(["Ready for queries"])
```

**Diagram sources**
- [connection.py:7-13](file://neurocom_backend/database/connection.py#L7-L13)
- [connection.py:25-27](file://neurocom_backend/database/connection.py#L25-L27)

**Section sources**
- [connection.py:7-13](file://neurocom_backend/database/connection.py#L7-L13)
- [connection.py:25-27](file://neurocom_backend/database/connection.py#L25-L27)

### Environment Variables and Settings
- DB_CONNECTION_STRING: Required for database connectivity.
- SQL_ECHO: Optional boolean-like flag to enable SQL logging.
- Other settings (e.g., Redis, JWT, Supabase) are loaded early to avoid import-order issues.

Environment variable usage patterns:
- DB_CONNECTION_STRING: Used directly by the engine.
- SQL_ECHO: Converted to boolean via string checks.
- General settings: Loaded once at module import time.

**Section sources**
- [connection.py:9-12](file://neurocom_backend/database/connection.py#L9-L12)
- [settings.py:1-29](file://neurocom_backend/utils/settings.py#L1-L29)

### Schema Creation and Migration Strategy
- Tables are created automatically using SQLModel metadata on startup.
- PostgreSQL-specific DDL ensures store_identifier column and unique constraint exist and are correctly defined.
- No external migration tool is used; changes must be reflected in model definitions or inline DDL.

```mermaid
flowchart TD
Boot["App boot"] --> CreateAll["SQLModel.metadata.create_all(engine)"]
CreateAll --> CheckDialect{"Dialect == 'postgresql'?"}
CheckDialect --> |Yes| AlterDDL["Run ALTER TABLE statements<br/>add column / drop constraints / add unique"]
CheckDialect --> |No| Done["Migration complete"]
AlterDDL --> Done
```

**Diagram sources**
- [connection.py:15-23](file://neurocom_backend/database/connection.py#L15-L23)

**Section sources**
- [connection.py:15-23](file://neurocom_backend/database/connection.py#L15-L23)

### Data Models and Relationships
Key entities:
- UserBase/Customer/Merchant: Users with roles; Merchant extends user with business details.
- Marketplace/MarketplaceConnection: Marketplaces and their encrypted connections per merchant/store.
- Product/Order/ProductOrder: E-commerce order flow with product associations.

```mermaid
erDiagram
USER_BASE {
uuid id PK
string full_name
string email UK
string password
enum role
}
CUSTOMER {
uuid id PK
string address
string phone_number
}
MERCHANT {
uuid id PK
string business_name
string phone_number
}
MARKETPLACE {
uuid id PK
string name UK
string slug UK
string url
string logo_url
}
MARKETPLACE_CONNECTION {
uuid id PK
uuid merchant_id FK
uuid marketplace_id FK
string store_identifier
text encrypted_access_token
datetime connected_at
}
PRODUCT {
uuid id PK
string title
float price
string description
string image
string category
}
ORDER {
uuid id PK
float total_amount
enum status
datetime created_at
datetime updated_at
uuid customer_id FK
}
PRODUCT_ORDER {
uuid id PK
uuid product_id FK
int quantity
float sub_total
uuid order_id FK
}
USER_BASE ||--o{ CUSTOMER : "extends"
USER_BASE ||--o{ MERCHANT : "extends"
MERCHANT ||--o{ MARKETPLACE_CONNECTION : "has"
MARKETPLACE ||--o{ MARKETPLACE_CONNECTION : "has"
CUSTOMER ||--o{ ORDER : "places"
ORDER ||--o{ PRODUCT_ORDER : "contains"
PRODUCT ||--o{ PRODUCT_ORDER : "referenced_by"
```

**Diagram sources**
- [user.py:10-42](file://neurocom_backend/database/models/user.py#L10-L42)
- [merchant.py:11-30](file://neurocom_backend/database/models/merchant.py#L11-L30)
- [marketplace.py:17-41](file://neurocom_backend/database/models/marketplace.py#L17-L41)
- [product.py:13-21](file://neurocom_backend/database/models/product.py#L13-L21)
- [order.py:21-39](file://neurocom_backend/database/models/order.py#L21-L39)

**Section sources**
- [user.py:10-42](file://neurocom_backend/database/models/user.py#L10-L42)
- [merchant.py:11-30](file://neurocom_backend/database/models/merchant.py#L11-L30)
- [marketplace.py:17-41](file://neurocom_backend/database/models/marketplace.py#L17-L41)
- [product.py:13-21](file://neurocom_backend/database/models/product.py#L13-L21)
- [order.py:21-39](file://neurocom_backend/database/models/order.py#L21-L39)

### Seeding Process and Initial Data Population
- A seed script exists but is fully commented out; it shows how to populate mock customers, products, and orders.
- To use it, uncomment and execute within a session context using the existing engine/session utilities.

Recommendation:
- Implement a dedicated CLI command or management script that imports seed functions and runs them against the configured engine.

**Section sources**
- [seed.py:1-92](file://neurocom_backend/database/seed.py#L1-L92)

### Application Startup and Migration Invocation
- The FastAPI lifespan calls perform_migration during startup, ensuring schema readiness before handling requests.

**Section sources**
- [main.py:16-29](file://neurocom_backend/main.py#L16-L29)

## Dependency Analysis
- Runtime dependencies include SQLModel, SQLAlchemy, psycopg2-binary for PostgreSQL, and dotenv for environment loading.
- The app entrypoint wires routers and middleware; database initialization is decoupled into the database module.

```mermaid
graph LR
PyProj["pyproject.toml"] --> SQLM["sqlmodel"]
PyProj --> SA["sqlalchemy"]
PyProj --> PG["psycopg2-binary"]
Main["main.py"] --> Conn["database/connection.py"]
Conn --> Models["database/models/*"]
```

**Diagram sources**
- [pyproject.toml:8-15](file://pyproject.toml#L8-L15)
- [main.py:1-90](file://neurocom_backend/main.py#L1-L90)
- [connection.py:1-28](file://neurocom_backend/database/connection.py#L1-L28)

**Section sources**
- [pyproject.toml:8-15](file://pyproject.toml#L8-L15)
- [main.py:1-90](file://neurocom_backend/main.py#L1-L90)
- [connection.py:1-28](file://neurocom_backend/database/connection.py#L1-L28)

## Performance Considerations
- Connection pooling: pool_recycle=300 helps prevent stale connections. Consider adjusting based on your database’s max_connections and idle timeout policies.
- SQL echo: Enable only in development to diagnose queries; disable in production to reduce overhead.
- Indexes: Primary keys and selected fields are indexed in models; review query patterns to add additional indexes if needed.
- Query efficiency: Use explicit selects and limit result sets where appropriate in services.

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
Common issues and resolutions:
- Missing DB_CONNECTION_STRING: Ensure the environment variable is set before starting the app.
- SQL_ECHO not working: Verify the value is one of true/1/yes (case-insensitive).
- Migration errors on PostgreSQL: Confirm dialect detection and permissions for DDL operations.
- Seed script not running: Uncomment the desired functions and call them explicitly in a session context.

Operational tips:
- Validate connectivity by checking logs when SQL_ECHO is enabled.
- If constraints fail, inspect the DDL block in perform_migration and adjust as your schema evolves.

**Section sources**
- [connection.py:9-23](file://neurocom_backend/database/connection.py#L9-L23)
- [seed.py:1-92](file://neurocom_backend/database/seed.py#L1-L92)

## Conclusion
The backend uses a simple, effective approach: SQLModel-driven schema creation with inline PostgreSQL DDL adjustments and environment-based configuration. For robustness, consider adopting a formal migration tool, enabling structured logging, and adding health checks for database connectivity. Seeding should be integrated as a controlled CLI operation.

[No sources needed since this section summarizes without analyzing specific files]

## Appendices

### Environment Variables Reference
- DB_CONNECTION_STRING: Full database URL (e.g., postgresql+psycopg2://user:pass@host:port/dbname).
- SQL_ECHO: Boolean-like string to enable SQL logging (true/1/yes).
- Additional app settings are loaded from utils/settings.py (e.g., Redis, JWT, Supabase).

**Section sources**
- [connection.py:9-12](file://neurocom_backend/database/connection.py#L9-L12)
- [settings.py:1-29](file://neurocom_backend/utils/settings.py#L1-L29)

### Example Configurations by Environment
- Development:
  - Set DB_CONNECTION_STRING to a local PostgreSQL instance.
  - Optionally set SQL_ECHO=true for verbose query logs.
- Staging:
  - Point DB_CONNECTION_STRING to a staging database.
  - Keep SQL_ECHO disabled unless debugging.
- Production:
  - Use a managed PostgreSQL service with proper IAM/network security.
  - Disable SQL_ECHO.
  - Tune pool_recycle and other pool settings according to provider recommendations.

[No sources needed since this section provides general guidance]

### Backup and Recovery Procedures
- Use your database provider’s native tools (e.g., pg_dump/pg_restore for PostgreSQL) to schedule regular backups.
- Test restore procedures periodically to ensure recoverability.
- Store backups securely with encryption and access controls.

[No sources needed since this section provides general guidance]

### Monitoring Setup
- Enable slow query logs at the database level to identify performance bottlenecks.
- Monitor connection pool metrics (active/idle connections, wait times) provided by your hosting platform.
- Add application-level health endpoints that verify database connectivity and report status.

[No sources needed since this section provides general guidance]

### Scaling and High Availability
- Scale horizontally by running multiple application instances behind a load balancer; they share the same database.
- Use managed database features like read replicas for read-heavy workloads.
- Configure connection limits and timeouts appropriately for multi-instance deployments.
- Plan failover strategies with automated backups and point-in-time recovery.

[No sources needed since this section provides general guidance]