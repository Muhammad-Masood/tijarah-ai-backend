from pydantic import BaseModel
from typing import List, Optional, Dict

class Review(BaseModel):
    review_id: str
    text: str
    rating: int
    date: str

class AnalysisRequest(BaseModel):
    product_url: str
    product_name: str

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

class ChatRequest(BaseModel):
    query: str
    reviews: List[Review] # In real app, you'd load from DB, not pass in payload