from pydantic import BaseModel
from typing import List, Optional, Dict

class AnalysisRequest(BaseModel):
    product_url: str
    product_name: str
    stream: bool = False

class ActionItem(BaseModel):
    issue: str
    severity: str  # low | medium | high | critical
    affected_review_count: int
    recommendation: str

class ClusterDebugEntry(BaseModel):
    size: int
    label: str

class ReviewAnalysisResponse(BaseModel):
    sentiment_score: int
    rating_trend: Dict[str, float]
    summary: str
    topics: List[str]
    action_plan: List[ActionItem]
    cluster_debug: Dict[str, ClusterDebugEntry]