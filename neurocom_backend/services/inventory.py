from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sklearn.linear_model import LinearRegression

def generate_mock_orders(days_back=90) -> pd.DataFrame:
    """
    Simulates fetching 3 months of orders from Daraz and Shopify.
    Generates a pattern with weekend spikes to simulate seasonality.
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)
    
    dates = pd.date_range(start=start_date, end=end_date, freq='D')
    orders = []

    for date in dates:
        # Simulate base demand
        base_sales = np.random.randint(5, 15)
        
        # Simulate Seasonality: Sales spike on Friday (4) and Saturday (5)
        if date.weekday() in [4, 5]: 
            base_sales += np.random.randint(10, 20)
            
        # Simulate random "Flash Sale" (outliers)
        if np.random.random() > 0.95:
            base_sales += 50 

        # Create 1-3 orders per day summing up to base_sales
        orders.append({"order_date": date, "platform": "daraz", "qty": int(base_sales * 0.6)})
        orders.append({"order_date": date, "platform": "shopify", "qty": int(base_sales * 0.4)})

    return pd.DataFrame(orders)

def analyze_inventory_logic(data: pd.DataFrame, current_stock: int, lead_time: int, safety_stock_days: int, forecast_days: int = 30):
    # 1. Preprocessing
    data['order_date'] = pd.to_datetime(data['order_date'])
    daily_sales = data.groupby('order_date')['qty'].sum().reset_index()
    
    # 2. Feature Engineering for ML
    # We use 'Day Integer' as a feature to find the trend (Slope)
    daily_sales['day_index'] = (daily_sales['order_date'] - daily_sales['order_date'].min()).dt.days
    
    # Prepare X (Features) and y (Target)
    X = daily_sales[['day_index']]
    y = daily_sales['qty']

    # 3. Train a Simple Trend Model (Linear Regression)
    # Note: In production, use Prophet or ARIMA here for seasonality
    model = LinearRegression()
    model.fit(X, y)
    
    # Calculate Average Daily Sales (Burn Rate) using last 14 days for immediate realism
    recent_burn_rate = daily_sales.tail(14)['qty'].mean()

    # 4. Predict Next N Days
    last_day_index = daily_sales['day_index'].max()
    future_days = np.array([[last_day_index + i] for i in range(1, forecast_days + 1)])
    predictions = model.predict(future_days)
    
    # Ensure predictions aren't negative
    predictions = [max(0, round(p)) for p in predictions]

    # 5. Stockout Simulation
    forecast_data = []
    running_stock = current_stock
    stockout_date = None
    days_until_stockout = None

    start_date = daily_sales['order_date'].max()

    for i, predicted_qty in enumerate(predictions):
        future_date = start_date + timedelta(days=i+1)
        running_stock -= predicted_qty
        
        forecast_entry = {
            "date": future_date.strftime("%Y-%m-%d"),
            "predicted_sales": predicted_qty,
            "projected_stock": max(0, running_stock)
        }
        forecast_data.append(forecast_entry)

        # check for stockout
        if running_stock <= 0 and stockout_date is None:
            stockout_date = future_date.strftime("%Y-%m-%d")
            days_until_stockout = i + 1

    # 6. Recommendations
    # Reorder Point = (Average Daily Sales * Lead Time) + Safety Stock
    # Safety Stock = (Max Daily Sales * Max Lead Time) - (Avg Daily Sales * Avg Lead Time) -> simplified here:
    safety_stock_qty = recent_burn_rate * safety_stock_days
    reorder_point = (recent_burn_rate * lead_time) + safety_stock_qty
    
    should_reorder = current_stock < reorder_point
    
    rec_qty = 0
    if should_reorder:
        # Suggest buying enough for 30 days + lead time coverage
        target_stock = (recent_burn_rate * 30) + reorder_point
        rec_qty = int(target_stock - current_stock)

    message = "Inventory looks healthy."
    if stockout_date:
        message = f"CRITICAL: Stockout predicted on {stockout_date}. "
    if should_reorder:
        message += f"Recommendation: Place order immediately."

    return {
        "stockout_predicted": stockout_date is not None,
        "stockout_date": stockout_date,
        "days_until_stockout": days_until_stockout,
        "recommended_reorder_qty": rec_qty,
        "burn_rate_daily": round(recent_burn_rate, 2),
        "forecast_data": forecast_data,
        "message": message
    }

