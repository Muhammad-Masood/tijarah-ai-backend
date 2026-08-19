import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import random

router = APIRouter(prefix="/business-insights", tags=["Insights"])

# --- 1. Data Models (The Output Contract) ---

class ProfitMetric(BaseModel):
    sku: str
    revenue: float
    total_costs: float # Commission, shipping, fees
    net_profit: float
    margin_percent: float
    status: str # "Profitable", "Loss Making", "Low Margin"

class OperationalMetric(BaseModel):
    total_orders: int
    return_rate: float
    cancellation_rate: float
    top_return_reasons: List[Dict[str, int]]

class DeadStockItem(BaseModel):
    sku: str
    product_name: str
    days_since_last_sale: int
    current_stock: int
    estimated_frozen_cash: float

class SLAAlert(BaseModel):
    order_id: str
    hours_since_order: float
    status: str # "Safe", "Warning", "Breach"
    items: List[str]

class InsightsResponse(BaseModel):
    profitability: List[ProfitMetric]
    operations: OperationalMetric
    dead_stock: List[DeadStockItem]
    sla_risks: List[SLAAlert]

# --- 2. Mock Data Generator (Simulating Daraz APIs) ---
# Replace this with your actual `daraz_client.get_transaction_details()` and `get_orders()`
def get_mock_daraz_data():
    # Mocking Transaction Data (Finance API)
    transactions = []
    skus = [f"SKU-{i}" for i in range(100, 120)]
    
    for _ in range(500):
        sku = random.choice(skus)
        price = random.randint(500, 3000)
        # Daraz usually charges ~15-20% in total fees + shipping
        commission = -(price * 0.12)
        shipping = -150
        payment_fee = -(price * 0.02)
        
        # Simulate a loss-making product (SKU-105)
        if sku == "SKU-105":
            shipping = -800 # High shipping cost error
        
        transactions.append({"sku": sku, "amount": price, "type": "Item Price", "date": "2024-01-01"})
        transactions.append({"sku": sku, "amount": commission, "type": "Commission", "date": "2024-01-01"})
        transactions.append({"sku": sku, "amount": shipping, "type": "Shipping Fee", "date": "2024-01-01"})
        transactions.append({"sku": sku, "amount": payment_fee, "type": "Payment Fee", "date": "2024-01-01"})

    # Mocking Order Data (Order API)
    orders = []
    now = datetime.now()
    for _ in range(100):
        status = random.choice(['delivered', 'delivered', 'delivered', 'returned', 'canceled', 'pending'])
        created_at = now - timedelta(hours=random.randint(1, 48))
        
        orders.append({
            "order_id": f"ORD-{random.randint(1000,9999)}",
            "items": ["SKU-101"],
            "status": status,
            "created_at": created_at,
            "return_reason": "Quality Issue" if status == 'returned' else None
        })

    # Mocking Product List (Product API)
    products = [{"sku": s, "name": f"Product {s}", "stock": random.randint(0, 50), "price": 1000} for s in skus]
    # Add a dead stock item
    products.append({"sku": "SKU-DEAD-999", "name": "Old Winter Jacket", "stock": 50, "price": 2000})

    return pd.DataFrame(transactions), pd.DataFrame(orders), products

# --- 3. The Logic Engines ---

def analyze_profit(df_trans: pd.DataFrame) -> List[ProfitMetric]:
    # Group by SKU and calculate sum
    metrics = []
    grouped = df_trans.groupby('sku')['amount'].sum().reset_index()
    
    # To get revenue only (positive amounts)
    revenue_df = df_trans[df_trans['amount'] > 0].groupby('sku')['amount'].sum().to_dict()
    
    for _, row in grouped.iterrows():
        sku = row['sku']
        net = row['amount']
        revenue = revenue_df.get(sku, 0)
        costs = revenue - net # Costs are the difference
        
        margin = (net / revenue * 100) if revenue > 0 else 0
        
        status = "Profitable"
        if net < 0: status = "Loss Making"
        elif margin < 10: status = "Low Margin"
        
        metrics.append(ProfitMetric(
            sku=sku,
            revenue=round(revenue, 2),
            total_costs=round(costs, 2),
            net_profit=round(net, 2),
            margin_percent=round(margin, 2),
            status=status
        ))
        
    return sorted(metrics, key=lambda x: x.net_profit)

def analyze_ops(df_orders: pd.DataFrame) -> OperationalMetric:
    total = len(df_orders)
    returned = len(df_orders[df_orders['status'] == 'returned'])
    canceled = len(df_orders[df_orders['status'] == 'canceled'])
    
    reasons = df_orders[df_orders['status'] == 'returned']['return_reason'].value_counts().to_dict()
    formatted_reasons = [{"reason": k, "count": v} for k, v in reasons.items()]
    
    return OperationalMetric(
        total_orders=total,
        return_rate=round((returned/total)*100, 2) if total else 0,
        cancellation_rate=round((canceled/total)*100, 2) if total else 0,
        top_return_reasons=formatted_reasons
    )

def analyze_dead_stock(products: list, df_orders: pd.DataFrame) -> List[DeadStockItem]:
    # Find items not sold in last 90 days (Mocking logic here)
    # In real logic: Filter df_orders for date > 90 days ago, get unique SKUs
    # Then compare with products list
    
    # For mock, we know SKU-DEAD-999 is dead
    dead_items = []
    sold_skus = set(["SKU-100", "SKU-101"]) # Mock sold list
    
    for p in products:
        if "DEAD" in p['sku']: # Simple mock logic
            dead_items.append(DeadStockItem(
                sku=p['sku'],
                product_name=p['name'],
                days_since_last_sale=95,
                current_stock=p['stock'],
                estimated_frozen_cash=p['stock'] * p['price']
            ))
    return dead_items

def analyze_sla(df_orders: pd.DataFrame) -> List[SLAAlert]:
    # Pending orders that are getting old
    pending = df_orders[df_orders['status'] == 'pending'].copy()
    alerts = []
    
    now = datetime.now()
    
    for _, row in pending.iterrows():
        diff = now - row['created_at']
        hours = diff.total_seconds() / 3600
        
        status = "Safe"
        if hours > 24: status = "Breach"
        elif hours > 20: status = "Warning"
        
        if status != "Safe":
            alerts.append(SLAAlert(
                order_id=row['order_id'],
                hours_since_order=round(hours, 1),
                status=status,
                items=row['items']
            ))
            
    return sorted(alerts, key=lambda x: x.hours_since_order, reverse=True)
