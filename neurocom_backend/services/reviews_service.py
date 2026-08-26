"""
Scalable review analysis pipeline.

Design principles vs. the naive "dump 50 reviews into one prompt" approach:

1. Deterministic math for anything math can compute (sentiment_score, rating
   trend) — don't ask an LLM to guess a number you already have.
2. Deduplicate near-identical reviews before spending tokens on them.
3. Cluster embeddings to find topics at ANY scale (10 or 100,000 reviews) —
   this replaces "reviews[:50]" with a representative structural summary.
4. Map-reduce: summarize each cluster (map), then synthesize across clusters
   (reduce). No single LLM call ever sees more than ~30-40 reviews.
5. Structured output (Pydantic schema via function-calling) instead of
   string-stripping ```json fences — eliminates parse failures.
6. Return provenance (review IDs / counts) behind each topic and each
   action-plan item so the output is auditable, not just plausible-sounding.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional

import numpy as np
from pydantic import BaseModel, Field
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from neurocom_backend.models.daraz_model import ScrapedProductReviewsResponse


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Review:
    id: str
    text: str
    rating: int  # 1-5
    date: str


def _parse_scraped_date(value: Optional[str]) -> str:
    """review_date comes back from the scraper as e.g. '10 Mar 2026' —
    normalize to ISO (YYYY-MM-DD) so rating_trend's fromisoformat can bucket
    it. Falls back to empty string (skipped by rating_trend) on any format
    Daraz didn't actually document/guarantee."""
    if not value:
        return ""
    try:
        return datetime.strptime(value, "%d %b %Y").date().isoformat()
    except ValueError:
        return ""


def reviews_from_scraped(scraped: ScrapedProductReviewsResponse) -> List[Review]:
    """Adapts daraz_service.scrape_product_reviews's output into this
    pipeline's Review shape. Reviews with no text are dropped — a star-only
    rating with no content carries no signal for topic clustering."""
    reviews: List[Review] = []
    for r in scraped.reviews:
        if not r.content:
            continue
        reviews.append(Review(
            id=str(r.review_id),
            text=r.content,
            rating=r.rating,
            date=_parse_scraped_date(r.review_date),
        ))
    return reviews


# ---------------------------------------------------------------------------
# Structured output schemas (used with .with_structured_output)
# ---------------------------------------------------------------------------

class ClusterSummary(BaseModel):
    topic_label: str = Field(description="Short label, e.g. 'Sizing: Runs Small'")
    sentiment: str = Field(description="positive | negative | mixed")
    key_points: List[str] = Field(description="2-4 bullet points synthesizing this cluster")
    representative_quote_ids: List[str] = Field(description="review ids that best illustrate this cluster")


class ActionItem(BaseModel):
    issue: str
    severity: str = Field(description="low | medium | high | critical")
    affected_review_count: int
    recommendation: str


class FinalAnalysis(BaseModel):
    summary: str = Field(description="2-3 sentence executive summary")
    topics: List[str]
    action_plan: List[ActionItem]


# ---------------------------------------------------------------------------
# Step 1: Deterministic quantitative signal (no LLM — this is the more
# accurate source for sentiment_score, not the model's guess)
# ---------------------------------------------------------------------------

def compute_sentiment_score(reviews: List[Review]) -> int:
    """Weighted average of star ratings, normalized to 0-100."""
    if not reviews:
        return 0
    avg_rating = sum(r.rating for r in reviews) / len(reviews)
    return round((avg_rating - 1) / 4 * 100)


def rating_trend(reviews: List[Review]) -> dict:
    """Bucket average rating by month to catch emerging issues that a flat
    'first 50 reviews' sample would miss entirely. Reviews with a date that
    can't be parsed are skipped rather than failing the whole request,
    since the upstream date format isn't contractually guaranteed."""
    buckets: dict = defaultdict(list)
    for r in reviews:
        try:
            d = datetime.fromisoformat(r.date)
        except (ValueError, TypeError):
            continue
        bucket_key = f"{d.year}-{d.month:02d}"
        buckets[bucket_key].append(r.rating)
    return {k: round(sum(v) / len(v), 2) for k, v in sorted(buckets.items())}


# ---------------------------------------------------------------------------
# Step 2: Deduplicate near-identical reviews (spam / templated reviews skew
# topic frequency and severity)
# ---------------------------------------------------------------------------

def dedupe_reviews(reviews: List[Review], embeddings_model, sim_threshold: float = 0.97) -> List[Review]:
    if len(reviews) < 2:
        return reviews
    vecs = np.array(embeddings_model.embed_documents([r.text for r in reviews]))
    norm = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
    sim_matrix = norm @ norm.T

    keep, seen = [], set()
    for i in range(len(reviews)):
        if i in seen:
            continue
        keep.append(reviews[i])
        dupes = np.where(sim_matrix[i] > sim_threshold)[0]
        seen.update(dupes.tolist())
    return keep


# ---------------------------------------------------------------------------
# Step 3: Cluster reviews by embedding similarity — this is what actually
# lets you handle 1000s of reviews. Instead of hoping 50 reviews are
# representative, you mathematically group ALL reviews into topics, then
# only send a small representative sample per cluster to the LLM.
# ---------------------------------------------------------------------------

def cluster_reviews(reviews: List[Review], embeddings_model, k_range=(4, 12)) -> dict:
    # KMeans needs at least k+1 samples per candidate k (and >=2 clusters
    # for silhouette_score to be defined), which a 7-day review window can
    # easily fall short of — fall back to a single cluster rather than
    # crashing on small review counts.
    max_k = min(k_range[1], len(reviews) - 1)
    if max_k < 2:
        return {0: list(reviews)}
    min_k = min(k_range[0], max_k)

    vecs = np.array(embeddings_model.embed_documents([r.text for r in reviews]))

    best_k, best_score, best_labels = min_k, -1, None
    for k in range(min_k, max_k + 1):
        km = KMeans(n_clusters=k, n_init=10, random_state=42).fit(vecs)
        score = silhouette_score(vecs, km.labels_)
        if score > best_score:
            best_k, best_score, best_labels = k, score, km.labels_

    clusters = defaultdict(list)
    for review, label in zip(reviews, best_labels):
        clusters[int(label)].append(review)
    return clusters


# ---------------------------------------------------------------------------
# Step 4: Map — summarize each cluster independently (small, bounded prompts)
# ---------------------------------------------------------------------------

def summarize_cluster(cluster_reviews_: List[Review], llm) -> ClusterSummary:
    # Cap sample size per cluster so cost/latency stay bounded regardless of
    # total review count — a cluster of 400 reviews doesn't need all 400
    # tokens-wise, a representative sample of ~25 conveys the same signal.
    sample = cluster_reviews_[:25]
    blob = "\n".join(f"[{r.id}] ({r.rating}★) {r.text}" for r in sample)

    structured_llm = llm.with_structured_output(ClusterSummary)
    return structured_llm.invoke(
        "These reviews were grouped together because they discuss a similar "
        "theme. Identify that theme, summarize it, and cite representative "
        f"review ids.\n\n{blob}"
    )


# ---------------------------------------------------------------------------
# Step 5: Reduce — synthesize all cluster summaries into the final report
# ---------------------------------------------------------------------------

def synthesize_final_analysis(
    product_name: str,
    cluster_summaries: dict,  # label -> ClusterSummary
    cluster_sizes: dict,      # label -> int
    llm,
) -> FinalAnalysis:
    context_lines = []
    for label, cs in cluster_summaries.items():
        size = cluster_sizes.get(label, 0)
        context_lines.append(
            f"Cluster (n={size}, sentiment={cs.sentiment}): {cs.topic_label}\n"
            + "\n".join(f"  - {p}" for p in cs.key_points)
        )
    context = "\n\n".join(context_lines)

    structured_llm = llm.with_structured_output(FinalAnalysis)
    return structured_llm.invoke(
        f"You are an expert e-commerce brand manager reviewing pre-clustered "
        f"customer feedback for product '{product_name}'. Each cluster below "
        f"already represents a distinct theme with its size (n = number of "
        f"reviews). Use cluster size as a proxy for severity/frequency when "
        f"building the action plan — larger clusters with negative sentiment "
        f"are higher priority.\n\n{context}"
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def analyze_reviews_with_llm_stream(product_name: str, product_id: str, reviews: List[Review]):
    """Same pipeline as analyze_reviews_with_llm, yielding (event, data) pairs
    as each stage finishes instead of returning one dict at the end — lets a
    streaming caller (SSE) render partial results (score, then each topic
    cluster) instead of waiting for the full map-reduce pass. The final
    `complete` event carries the same shape analyze_reviews_with_llm returns."""
    if not reviews:
        return

    embeddings_model = OpenAIEmbeddings()
    llm = ChatOpenAI(temperature=0, model="gpt-5.6-luna")

    sentiment_score = compute_sentiment_score(reviews)
    trend = rating_trend(reviews)
    print("rating_trend: ", trend)
    yield "score", {"sentiment_score": sentiment_score, "rating_trend": trend}

    clean_reviews = dedupe_reviews(reviews, embeddings_model)
    yield "progress", {"stage": "deduped", "review_count": len(clean_reviews)}

    clusters = cluster_reviews(clean_reviews, embeddings_model)
    cluster_sizes = {label: len(revs) for label, revs in clusters.items()}
    yield "progress", {"stage": "clustered", "cluster_count": len(clusters)}

    # 4. Map: one bounded LLM call per cluster. Keyed by the same cluster
    #    label as cluster_sizes so the two stay matched up — KMeans labels
    #    aren't guaranteed contiguous/ordered, so a positional index here
    #    would silently pair each summary with the wrong size. Each summary
    #    is yielded as it completes rather than gathered up front, so topics
    #    appear on the UI one at a time instead of all at once at the end.
    cluster_summaries = {}
    for label, revs in clusters.items():
        cs = summarize_cluster(revs, llm)
        cluster_summaries[label] = cs
        yield "cluster", {
            "label": str(label),
            "size": cluster_sizes[label],
            "topic_label": cs.topic_label,
            "sentiment": cs.sentiment,
            "key_points": cs.key_points,
        }

    # 5. Reduce: one final synthesis call over compact cluster summaries,
    #    never over raw review text.
    final = synthesize_final_analysis(product_name, cluster_summaries, cluster_sizes, llm)

    yield "complete", {
        "sentiment_score": sentiment_score,   # from real ratings, not LLM guess
        "rating_trend": trend,                # catches emerging issues over time
        "summary": final.summary,
        "topics": final.topics,
        "action_plan": [item.model_dump() for item in final.action_plan],
        "cluster_debug": {                    # provenance for auditing
            str(label): {"size": cluster_sizes[label], "label": cs.topic_label}
            for label, cs in cluster_summaries.items()
        },
    }


def analyze_reviews_with_llm(product_name: str, product_id: str, reviews: List[Review]) -> Optional[dict]:
    """Non-streaming entry point — drains analyze_reviews_with_llm_stream and
    returns only its final result, for callers that just want the finished
    report (this is the single orchestration path; the two never drift)."""
    result = None
    for event, data in analyze_reviews_with_llm_stream(product_name, product_id, reviews):
        if event == "complete":
            result = data
    return result
