# Performance Insights

<cite>
**Referenced Files in This Document**
- [main.py](file://neurocom_backend/main.py)
- [inisghts.router.py](file://neurocom_backend/routers/inisghts.router.py)
- [insights.service.py](file://neurocom_backend/services/insights.service.py)
- [inventory_analysis_model.py](file://neurocom_backend/models/inventory_analysis_model.py)
- [daraz_service.py](file://neurocom_backend/services/daraz_service.py)
- [reviews_service.py](file://neurocom_backend/services/reviews_service.py)
- [review_model.py](file://neurocom_backend/models/review_model.py)
</cite>

## Table of Contents
1. Introduction
2. Project Structure
3. Core Components
4. Architecture Overview
5. Detailed Component Analysis
6. Dependency Analysis
7. Performance Considerations
8. Troubleshooting Guide
9. Conclusion
10. Appendices

## Introduction
This document explains the performance insights engine that aggregates business metrics, computes KPIs, and generates actionable insights for merchants. It covers profitability analysis, operational metrics, dead stock detection, SLA risk alerts, returns insights with trend analysis, and review sentiment scoring. It also describes how these components integrate into dashboards and reporting flows, including example outputs and configuration points for thresholds and custom metrics.

## Project Structure
The insights functionality is exposed via a FastAPI router and implemented through service functions that operate on dataframes or API responses. The application mounts routers and provides endpoints consumed by dashboards and reporting tools.

```mermaid
graph TB
A["FastAPI App<br/>main.py"] --> B["Insights Router<br/>inisghts.router.py"]
B --> C["Insights Service<br/>insights.service.py"]
C --> D["Mock Data Generator<br/>insights.service.py"]
C --> E["Returns & Reviews Insights<br/>daraz_service.py / reviews_service.py"]
A --> F["Other Routers<br/>forecast_router.py etc."]
```

**Diagram sources**
- [main.py:29-89](file://neurocom_backend/main.py#L29-L89)
- [inisghts.router.py:15-31](file://neurocom_backend/routers/inisghts.router.py#L15-L31)
- [insights.service.py:1-183](file://neurocom_backend/services/insights.service.py#L1-L183)

**Section sources**
- [main.py:29-89](file://neurocom_backend/main.py#L29-L89)
- [inisghts.router.py:15-31](file://neurocom_backend/routers/inisghts.router.py#L15-L31)

## Core Components
- Profitability analysis: Computes per-SKU revenue, costs, net profit, margin percentage, and status classification.
- Operational metrics: Aggregates total orders, return rate, cancellation rate, and top return reasons.
- Dead stock detection: Identifies items not sold within a threshold window and estimates frozen cash.
- SLA risk alerts: Flags pending orders approaching or breaching delivery SLAs based on elapsed time.
- Returns insights: Streams computation over returns and orders to produce reason breakdowns, monthly trends, dispute/refund rates, and recommendations.
- Review sentiment: Calculates a normalized sentiment score from ratings and builds monthly rating trends.

**Section sources**
- [insights.service.py:12-43](file://neurocom_backend/services/insights.service.py#L12-L43)
- [insights.service.py:93-183](file://neurocom_backend/services/insights.service.py#L93-L183)
- [daraz_service.py:1340-1467](file://neurocom_backend/services/daraz_service.py#L1340-L1467)
- [reviews_service.py:105-126](file://neurocom_backend/services/reviews_service.py#L105-L126)

## Architecture Overview
The dashboard endpoint orchestrates multiple analyses and returns a unified response. Each analysis function encapsulates its own logic and data contracts.

```mermaid
sequenceDiagram
participant Client as "Dashboard Client"
participant Router as "Insights Router"
participant Service as "Insights Service"
participant Mock as "Mock Data Generator"
participant Daraz as "Daraz Returns Service"
participant Reviews as "Reviews Service"
Client->>Router : GET /insights/dashboard
Router->>Service : get_mock_daraz_data()
Service-->>Router : transactions, orders, products
Router->>Service : analyze_profit(transactions)
Router->>Service : analyze_ops(orders)
Router->>Service : analyze_dead_stock(products, orders)
Router->>Service : analyze_sla(orders)
Note over Service,Daraz : Optional : use real APIs instead of mock
Service-->>Router : InsightsResponse
Router-->>Client : JSON payload
```

**Diagram sources**
- [inisghts.router.py:17-31](file://neurocom_backend/routers/inisghts.router.py#L17-L31)
- [insights.service.py:47-89](file://neurocom_backend/services/insights.service.py#L47-L89)
- [insights.service.py:93-183](file://neurocom_backend/services/insights.service.py#L93-L183)

## Detailed Component Analysis

### Profitability Engine
- Aggregates transaction amounts by SKU to derive net profit.
- Derives revenue as the sum of positive amounts per SKU.
- Computes margin percentage and classifies status: profitable, loss making, or low margin.
- Outputs a sorted list of SKUs by net profit for prioritization.

```mermaid
flowchart TD
Start(["Start"]) --> Group["Group transactions by SKU"]
Group --> Revenue["Sum positive amounts per SKU (revenue)"]
Group --> Net["Sum all amounts per SKU (net)"]
Revenue --> Margin["Compute margin = net / revenue * 100"]
Net --> Status{"net < 0?"}
Status --> |Yes| Loss["Status = Loss Making"]
Status --> |No| LowMargin{"margin < 10%?"}
LowMargin --> |Yes| Low["Status = Low Margin"]
LowMargin --> |No| Profit["Status = Profitable"]
Margin --> Output["Emit ProfitMetric"]
Loss --> Output
Low --> Output
Profit --> Output
Output --> End(["End"])
```

**Diagram sources**
- [insights.service.py:93-122](file://neurocom_backend/services/insights.service.py#L93-L122)

**Section sources**
- [insights.service.py:93-122](file://neurocom_backend/services/insights.service.py#L93-L122)

### Operational Metrics Engine
- Counts total orders, returned orders, and canceled orders.
- Computes return and cancellation rates as percentages.
- Aggregates top return reasons by frequency.

```mermaid
flowchart TD
S(["Start"]) --> T["Total orders = len(orders)"]
T --> R["Returned = count(status == 'returned')"]
T --> C["Canceled = count(status == 'canceled')"]
R --> Rates["return_rate = returned / total * 100"]
C --> CancelRate["cancellation_rate = canceled / total * 100"]
R --> Reasons["Top return reasons by count"]
Rates --> Emit["Emit OperationalMetric"]
CancelRate --> Emit
Reasons --> Emit
Emit --> E(["End"])
```

**Diagram sources**
- [insights.service.py:124-137](file://neurocom_backend/services/insights.service.py#L124-L137)

**Section sources**
- [insights.service.py:124-137](file://neurocom_backend/services/insights.service.py#L124-L137)

### Dead Stock Detection
- Identifies items not sold within a defined window (mocked here).
- Estimates frozen cash as current stock multiplied by product price.
- Emits a list of dead stock items with key identifiers.

```mermaid
flowchart TD
S(["Start"]) --> Filter["Filter products not sold in last N days"]
Filter --> Calc["For each item: compute estimated_frozen_cash = stock * price"]
Calc --> Emit["Emit DeadStockItem records"]
Emit --> E(["End"])
```

**Diagram sources**
- [insights.service.py:139-157](file://neurocom_backend/services/insights.service.py#L139-L157)

**Section sources**
- [insights.service.py:139-157](file://neurocom_backend/services/insights.service.py#L139-L157)

### SLA Risk Alerts
- Scans pending orders and calculates hours since creation.
- Applies thresholds: warning above a set hour count, breach beyond another.
- Emits alerts sorted by urgency.

```mermaid
flowchart TD
S(["Start"]) --> Pending["Select pending orders"]
Pending --> ForEach{"For each order"}
ForEach --> Hours["hours = now - created_at"]
Hours --> Check{"hours > 24?"}
Check --> |Yes| Breach["status = Breach"]
Check --> |No| Warn{"hours > 20?"}
Warn --> |Yes| Warning["status = Warning"]
Warn --> |No| Safe["status = Safe"]
Breach --> Emit["Emit SLAAlert if not Safe"]
Warning --> Emit
Safe --> Next["Next order"]
Emit --> Next
Next --> Done(["End"])
```

**Diagram sources**
- [insights.service.py:159-182](file://neurocom_backend/services/insights.service.py#L159-L182)

**Section sources**
- [insights.service.py:159-182](file://neurocom_backend/services/insights.service.py#L159-L182)

### Returns Insights and Recommendations
- Streams fetching of reverse orders and orders with items.
- Filters by product scope (SKU or product ID).
- Computes overall return rate, dispute rate, refund request rate, reason breakdown, and monthly trends.
- Generates recommendations based on thresholds (e.g., high return rate, top reason, disputes).

```mermaid
sequenceDiagram
participant Caller as "Caller"
participant Stream as "get_returns_insights_stream"
participant API as "Marketplace APIs"
Caller->>Stream : start streaming
Stream->>API : fetch reverse orders
API-->>Stream : reverse_orders
Stream->>API : fetch orders with items
API-->>Stream : orders_with_items
Stream->>Stream : filter by product scope
Stream->>Stream : compute rates, reasons, monthly trend
Stream-->>Caller : yield progress events
Stream-->>Caller : yield complete result
```

**Diagram sources**
- [daraz_service.py:1340-1467](file://neurocom_backend/services/daraz_service.py#L1340-L1467)

**Section sources**
- [daraz_service.py:1340-1467](file://neurocom_backend/services/daraz_service.py#L1340-L1467)

### Review Sentiment and Trends
- Computes a normalized sentiment score from star ratings.
- Builds monthly rating trends to detect emerging issues.
- Produces an action plan and topics derived from clustering and LLM-based summarization.

```mermaid
flowchart TD
S(["Start"]) --> Score["sentiment_score = normalize(avg_rating)"]
Score --> Trend["rating_trend = monthly average ratings"]
Trend --> Plan["action_plan + topics from analysis"]
Plan --> Emit["Emit ReviewAnalysisResponse"]
Emit --> E(["End"])
```

**Diagram sources**
- [reviews_service.py:105-126](file://neurocom_backend/services/reviews_service.py#L105-L126)
- [reviews_service.py:282-303](file://neurocom_backend/services/reviews_service.py#L282-L303)
- [review_model.py:19-25](file://neurocom_backend/models/review_model.py#L19-L25)

**Section sources**
- [reviews_service.py:105-126](file://neurocom_backend/services/reviews_service.py#L105-L126)
- [reviews_service.py:282-303](file://neurocom_backend/services/reviews_service.py#L282-L303)
- [review_model.py:19-25](file://neurocom_backend/models/review_model.py#L19-L25)

### Inventory Forecasting Integration
- Uses recent burn rate and lead/safety stock parameters to forecast daily sales and projected stock levels.
- Predicts stockout date and recommends reorder quantities.

```mermaid
flowchart TD
S(["Start"]) --> Burn["Compute recent_burn_rate"]
Burn --> Safety["safety_stock_qty = recent_burn_rate * safety_stock_days"]
Safety --> Reorder["reorder_point = (recent_burn_rate * lead_time) + safety_stock_qty"]
Reorder --> Sim["Simulate daily stock depletion using predicted sales"]
Sim --> Out["Emit forecast_data, stockout info, recommended_reorder_qty"]
Out --> E(["End"])
```

**Diagram sources**
- [inventory_analysis_model.py:4-25](file://neurocom_backend/models/inventory_analysis_model.py#L4-L25)
- [inventory_analysis_model.py:63-101](file://neurocom_backend/services/inventory.py#L63-L101)

**Section sources**
- [inventory_analysis_model.py:4-25](file://neurocom_backend/models/inventory_analysis_model.py#L4-L25)
- [inventory_analysis_model.py:63-101](file://neurocom_backend/services/inventory.py#L63-L101)

## Dependency Analysis
- Router depends on service functions to compute insights and assemble responses.
- Service functions depend on dataframes or marketplace API responses; currently uses mock data but can be swapped for live integrations.
- Returns insights depend on marketplace order and reverse order APIs.
- Review insights depend on review data and optional LLM-based summarization.

```mermaid
graph LR
Router["Insights Router"] --> Service["Insights Service"]
Service --> MockData["Mock Data Generator"]
Service --> Returns["Returns Insights (Daraz)"]
Service --> Reviews["Review Insights"]
Router --> MainApp["FastAPI App"]
```

**Diagram sources**
- [inisghts.router.py:15-31](file://neurocom_backend/routers/inisghts.router.py#L15-L31)
- [insights.service.py:47-89](file://neurocom_backend/services/insights.service.py#L47-L89)
- [daraz_service.py:1340-1467](file://neurocom_backend/services/daraz_service.py#L1340-L1467)
- [reviews_service.py:105-126](file://neurocom_backend/services/reviews_service.py#L105-L126)

**Section sources**
- [inisghts.router.py:15-31](file://neurocom_backend/routers/inisghts.router.py#L15-L31)
- [insights.service.py:47-89](file://neurocom_backend/services/insights.service.py#L47-L89)

## Performance Considerations
- Use vectorized operations (pandas groupby, filtering) to minimize loops over large datasets.
- Cache repeated computations (e.g., aggregated metrics) when serving dashboards frequently.
- Stream long-running computations (as done in returns insights) to provide progressive updates.
- Avoid unnecessary object allocations inside hot loops; precompute constants like thresholds.
- Consider pagination or time-windowing for large order histories to reduce memory footprint.

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
- Missing or malformed dates: Ensure timestamps are parsed consistently; handle exceptions gracefully to avoid failing entire requests.
- Zero denominators: Guard against division by zero when computing rates (e.g., total orders equals zero).
- Threshold tuning: Adjust SLA warning/breach thresholds and margin thresholds based on category norms.
- Data consistency: Validate that SKU/product IDs map correctly across orders and returns; mismatches can skew metrics.
- Streaming completion: Confirm that streaming consumers handle both progress and complete events properly.

**Section sources**
- [insights.service.py:124-137](file://neurocom_backend/services/insights.service.py#L124-L137)
- [insights.service.py:159-182](file://neurocom_backend/services/insights.service.py#L159-L182)
- [daraz_service.py:1340-1467](file://neurocom_backend/services/daraz_service.py#L1340-L1467)

## Conclusion
The performance insights engine provides a modular, extensible foundation for merchant analytics. It computes core KPIs (profitability, operations, dead stock, SLA risks), enriches them with returns insights and review sentiment, and exposes results via a clean API for dashboards. Thresholds and logic can be tuned to match business needs, and the design supports swapping mock data for live marketplace integrations.

[No sources needed since this section summarizes without analyzing specific files]

## Appendices

### API Endpoints and Contracts
- Dashboard endpoint:
  - Method: GET
  - Path: /insights/dashboard
  - Response model: InsightsResponse containing profitability, operations, dead_stock, sla_risks

- Business insights router prefix:
  - Prefix: /business-insights (router defined in service file)

**Section sources**
- [inisghts.router.py:15-31](file://neurocom_backend/routers/inisghts.router.py#L15-L31)
- [insights.service.py:8-43](file://neurocom_backend/services/insights.service.py#L8-L43)

### Example Outputs
- Profitability: Per-SKU revenue, costs, net profit, margin percent, status.
- Operations: Total orders, return rate, cancellation rate, top return reasons.
- Dead stock: SKU, product name, days since last sale, current stock, estimated frozen cash.
- SLA risks: Order ID, hours since order, status (Safe/Warning/Breach), items.
- Returns insights: Overall return rate, dispute rate, refund request rate, reason breakdown, monthly trend, recommendations.
- Review insights: Sentiment score, rating trend, summary, topics, action plan.

**Section sources**
- [insights.service.py:12-43](file://neurocom_backend/services/insights.service.py#L12-L43)
- [daraz_service.py:1436-1450](file://neurocom_backend/services/daraz_service.py#L1436-L1450)
- [reviews_service.py:282-303](file://neurocom_backend/services/reviews_service.py#L282-L303)

### Custom Metric Configuration
- SLA thresholds: Warning and breach hours can be adjusted in the SLA alert logic.
- Profit margins: Low-margin threshold can be tuned in profitability classification.
- Dead stock window: Days-since-last-sale threshold can be parameterized.
- Return thresholds: Recommendation triggers (e.g., overall return rate >= 10%) can be configured.

**Section sources**
- [insights.service.py:109-112](file://neurocom_backend/services/insights.service.py#L109-L112)
- [insights.service.py:170-172](file://neurocom_backend/services/insights.service.py#L170-L172)
- [daraz_service.py:1418-1434](file://neurocom_backend/services/daraz_service.py#L1418-L1434)

### Integration with Reporting Dashboards
- Mount routers in the main app to expose endpoints.
- Consume /insights/dashboard for consolidated metrics.
- Use streaming endpoints for long-running analyses to update UI progressively.
- Map response models to frontend charts and tables.

**Section sources**
- [main.py:29-89](file://neurocom_backend/main.py#L29-L89)
- [inisghts.router.py:17-31](file://neurocom_backend/routers/inisghts.router.py#L17-L31)