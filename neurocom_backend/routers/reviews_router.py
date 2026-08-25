from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from neurocom_backend.models.review_model import ReviewAnalysisResponse, AnalysisRequest
from neurocom_backend.services.reviews_service import analyze_reviews_with_llm, analyze_reviews_with_llm_stream, reviews_from_scraped
from neurocom_backend.services.daraz_service import scrape_product_reviews
from neurocom_backend.utils.sse import sse_stream

_:bool = load_dotenv()

router  = APIRouter(prefix="/reviews",tags=["Reviews Analysis"])

@router.get('/')
async def root():
    return {"message": "Reviews Analysis Router"}

@router.post("/analyze-reviews", response_model=ReviewAnalysisResponse)
async def analyze_product_reviews(request: AnalysisRequest):
    try:
        scraped = scrape_product_reviews(request.product_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not scraped.reviews:
        raise HTTPException(status_code=400, detail="No reviews found for this product")

    reviews = reviews_from_scraped(scraped)
    if not reviews:
        raise HTTPException(status_code=400, detail="No usable review content found for this product")

    if request.stream:
        return StreamingResponse(
            sse_stream(analyze_reviews_with_llm_stream(request.product_name, scraped.item_id, reviews)),
            media_type="text/event-stream",
        )

    # Run Analysis
    data = analyze_reviews_with_llm(request.product_name, scraped.item_id, reviews)

    if not data:
        raise HTTPException(status_code=500, detail="AI Analysis failed")

    return data