from fastapi.middleware.cors import CORSMiddleware
import requests
from fastapi import FastAPI, Request, Header, UploadFile, File, Body, APIRouter, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from typing import Optional, Any
import os
from dotenv import load_dotenv
from neurocom_backend.models.inventory_analysis_model import InventoryRequest, InventoryResponse
from neurocom_backend.services.inventory import generate_mock_orders, analyze_inventory_logic
from fastapi import HTTPException
from datetime import datetime

_:bool = load_dotenv()

router  = APIRouter(prefix="/forecast",tags=["Forecast"])

@router.get('/')
async def root():
    return {"message": "Forecast Router"}

@router.post("/predict-stockout", response_model=InventoryResponse)
def predict_stockout(request: InventoryRequest):
    """
    Analyzes historical data (Mocked) and predicts future inventory levels.
    """
    try:
        # 1. Fetch Data (Replace this with your real API calls to Daraz/Shopify)
        print(f"Fetching data for SKU: {request.sku}...")
        df_orders = generate_mock_orders()
        print("Data fetched successfully: ", df_orders)

        # 2. Run Analysis
        result = analyze_inventory_logic(
            df_orders, 
            request.current_stock, 
            request.lead_time_days,
            request.safety_stock_days,
            request.forecast_days
        )

        # 3. Construct Response
        return {
            "sku": request.sku,
            "analysis_date": datetime.now().strftime("%Y-%m-%d"),
            **result
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
