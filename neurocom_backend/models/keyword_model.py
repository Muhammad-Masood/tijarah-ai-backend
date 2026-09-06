"""Pydantic models for the Daraz SEO Keyword Analysis tool.

The keyword analysis pipeline takes a merchant's product, builds a catalog
of competing products from Daraz's public search, filters by adaptive
semantic relevance (percentile-based), mines candidate keywords via
hybrid NLP + LLM, clusters them by embedding similarity to discover
buyer intents, builds a product-keyword bipartite graph with community
detection, and scores keyword clusters by relevance vs. competition.
"""

from pydantic import BaseModel, Field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class KeywordAnalysisRequest(BaseModel):
    item_id: int = Field(description="Daraz item_id of the merchant's own product")
    max_iterations: int = Field(default=4, ge=1, le=8, description="Number of iterative expansion rounds")
    max_catalog_size: int = Field(default=500, ge=50, le=2000, description="Cap on total catalog products before filtering")
    stream: bool = Field(default=False, description="If true, stream progress events via SSE")


# ---------------------------------------------------------------------------
# Intermediate / nested shapes
# ---------------------------------------------------------------------------

class SeedKeyword(BaseModel):
    keyword: str
    source: str = Field(description="Origin of the keyword: 'llm', 'nlp', or 'attribute'")


class CatalogProduct(BaseModel):
    item_id: str
    name: str
    price: str
    rating_score: Optional[str] = None
    review_count: Optional[str] = None
    image: str
    seller_name: Optional[str] = None
    item_url: Optional[str] = None
    keyword_sources: List[str] = Field(default=[], description="Keywords that surfaced this product")


class ScoredKeyword(BaseModel):
    keyword: str
    keyword_variants: List[str] = Field(default=[], description="Semantically equivalent keywords in the same cluster (e.g. 'face slimming', 'jawline shaper', 'double chin reducer')")
    relevance_score: float = Field(description="Avg embedding similarity of matching catalog products (0-1)")
    competition_count: int = Field(description="Total Daraz listings for this keyword (from filteredQuatity)")
    winning_score: float = Field(description="(relevance * cluster_bonus) / log2(competition + 2) — higher is better")
    matching_products: int = Field(description="How many catalog products match any keyword in this cluster")
    cluster_size: int = Field(default=1, description="How many semantically equivalent keywords are in this cluster — more = stronger buyer intent signal")
    example_products: List[str] = Field(default=[], description="Top 3 product names that match this keyword cluster")


class RepeatProduct(BaseModel):
    """Products that appear across 3+ keyword searches — strong competitors
    or keyword-stuffed listings worth monitoring separately."""
    item_id: str
    name: str
    appearance_count: int
    keywords_matched: List[str]


# ---------------------------------------------------------------------------
# Final response
# ---------------------------------------------------------------------------

class KeywordAnalysisResponse(BaseModel):
    user_product: dict = Field(description="The merchant's product info (title, description, price, etc.)")
    seed_keywords: List[SeedKeyword]
    total_catalog_size: int = Field(description="Total products scraped across all keyword searches")
    total_relevant_products: int = Field(description="Products that passed embedding similarity filter")
    winning_keywords: List[ScoredKeyword] = Field(description="Keywords sorted by winning_score descending")
    repeat_products: List[RepeatProduct] = Field(description="Products appearing in 3+ keyword result sets")
    iterations_run: int
