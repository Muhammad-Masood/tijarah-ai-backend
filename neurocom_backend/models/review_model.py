from pydantic import BaseModel
from typing import List, Optional

class Review(BaseModel):
    review_id: str
    text: str
    rating: int
    date: str

class AnalysisRequest(BaseModel):
    product_name: str
    reviews: List[Review]

class ActionItem(BaseModel):
    issue: str
    severity: str  # High, Medium, Low
    recommendation: str

class ReviewAnalysisResponse(BaseModel):
    sentiment_score: int
    summary: str
    topics: List[str]
    action_plan: List[ActionItem]

class ChatRequest(BaseModel):
    query: str
    reviews: List[Review] # In real app, you'd load from DB, not pass in payload