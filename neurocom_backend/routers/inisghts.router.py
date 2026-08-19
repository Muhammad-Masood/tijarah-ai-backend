from fastapi.middleware.cors import CORSMiddleware
import requests
from fastapi import FastAPI, Request, Header, UploadFile, File, Body, APIRouter, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from typing import Optional, Any
import os
from dotenv import load_dotenv
from neurocom_backend.models.inventory_analysis_model import InventoryRequest, InventoryResponse
from neurocom_backend.services.insights import analyze_sla, analyze_dead_stock, analyze_ops, analyze_profit, get_mock_daraz_data, InsightsResponse, SLAAlert, DeadStockItem, OperationalMetric, ProfitMetric
from fastapi import HTTPException
from datetime import datetime

_:bool = load_dotenv()

router  = APIRouter(prefix="/insights",tags=["Business Insights"])

@router.get("/dashboard", response_model=InsightsResponse)
async def get_business_insights():
    df_trans, df_orders, products = get_mock_daraz_data()
    
    profit_data = analyze_profit(df_trans)
    ops_data = analyze_ops(df_orders)
    dead_stock_data = analyze_dead_stock(products, df_orders)
    sla_data = analyze_sla(df_orders)
    
    return InsightsResponse(
        profitability=profit_data,
        operations=ops_data,
        dead_stock=dead_stock_data,
        sla_risks=sla_data
    )