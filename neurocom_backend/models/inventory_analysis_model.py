from pydantic import BaseModel, Field
from typing import List, Optional

class InventoryRequest(BaseModel):
    sku: str
    current_stock: int = Field(..., gt=0, description="Current physical inventory count")
    lead_time_days: int = Field(7, description="Days it takes for supplier to deliver new stock")
    safety_stock_days: int = Field(3, description="Buffer stock in days to maintain")
    forecast_days: int = Field(30, description="Number of days to forecast into the future")

class DailyForecast(BaseModel):
    date: str
    predicted_sales: float
    projected_stock: float

class InventoryResponse(BaseModel):
    sku: str
    analysis_date: str
    stockout_predicted: bool
    stockout_date: Optional[str] = None
    days_until_stockout: Optional[int] = None
    recommended_reorder_qty: int
    burn_rate_daily: float
    forecast_data: List[DailyForecast]
    message: str