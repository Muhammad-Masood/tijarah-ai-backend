import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
# from langchain_classic.chains import retrieval_qa
# from langchain.chains import RetrievalQA
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
# from langchain_core.prompts import PromptTemplate
import json
from dotenv import load_dotenv
from neurocom_backend.models.review_model import Review, ReviewAnalysisResponse, ChatRequest, ActionItem, AnalysisRequest
from neurocom_backend.services.reviews_service import analyze_reviews_with_llm, reviews_from_scraped
from neurocom_backend.services.daraz_service import scrape_product_reviews

_:bool = load_dotenv()

router  = APIRouter(prefix="/reviews",tags=["Reviews Analysis"])

@router.get('/')
async def root():
    return {"message": "Reviews Analysis Router"}

@router.post("/analyze-reviews", response_model=ReviewAnalysisResponse)
async def analyze_product_reviews(request: AnalysisRequest):
    scraped = scrape_product_reviews(request.product_url)
    if not scraped.reviews:
        raise HTTPException(status_code=400, detail="No reviews found for this product")

    reviews = reviews_from_scraped(scraped)
    if not reviews:
        raise HTTPException(status_code=400, detail="No usable review content found for this product")

    # Run Analysis
    data = analyze_reviews_with_llm(request.product_name, scraped.item_id, reviews)

    if not data:
        raise HTTPException(status_code=500, detail="AI Analysis failed")

    return data

@router.post("/chat-with-reviews")
async def chat_with_reviews(request: ChatRequest):
    """
    This endpoint demonstrates RAG. 
    The user asks "Why is shipping bad?" and we retrieve relevant docs.
    """
    # 1. Re-create vector store (In prod, load existing store)
    documents = [Document(page_content=r.text) for r in request.reviews]
    embeddings = OpenAIEmbeddings()
    vectorstore = Chroma.from_documents(documents, embeddings)
    
    # 2. Setup Retrieval Chain
    retriever = vectorstore.as_retriever(search_kwargs={"k": 5}) # Get top 5 relevant reviews
    llm = ChatOpenAI(temperature=0)
    prompt = ChatPromptTemplate.from_template(
        """You are analyzing product reviews.
        Use the following reviews to answer the question.

        Reviews:
        {context}

        Question:
        {question}
        """
    )

    chain = (
        {
            "context": retriever,
            "question": lambda x: x
        }
        | prompt
        | llm
        | StrOutputParser()
    )
    answer = chain.invoke(request.query)
    return {"answer": answer}