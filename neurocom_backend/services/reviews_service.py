import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
import json
from neurocom_backend.models.review_model import Review, ReviewAnalysisResponse, ChatRequest, ActionItem

def analyze_reviews_with_llm(product_name: str, reviews: List[Review]):
    documents = [
        Document(page_content=r.text, metadata={"rating": r.rating, "date": r.date})
        for r in reviews
    ]
    embeddings = OpenAIEmbeddings()
    vectorstore = Chroma.from_documents(documents, embeddings)
    
    # We feed the LLM a sample of reviews or a summary from RAG to get the big picture
    llm = ChatOpenAI(temperature=0, model="gpt-4o")

    # Construct the prompt
    # We aggregate all text for the analysis (if under token limit) 
    # OR use Map-Reduce if you have thousands of reviews.
    # For this example, we assume < 50 reviews fit in context, or we take top 20 relevant ones.
    
    review_text_blob = "\n".join([f"- {r.text} ({r.rating} stars)" for r in reviews[:50]])

    system_prompt = f"""
    You are an expert E-commerce Brand Manager. 
    Analyze the following reviews for the product: "{product_name}".
    
    Output strictly in valid JSON format with these keys:
    1. "sentiment_score": (0 to 100 integer)
    2. "summary": (A 2-sentence executive summary)
    3. "topics": (List of strings, e.g. "Sizing: Runs Small", "Quality: Durable")
    4. "action_plan": (List of objects with "issue", "severity", "recommendation")
    
    Reviews:
    {review_text_blob}
    """

    response = llm.invoke(system_prompt)
    
    # Parse JSON output from LLM
    try:
        content = response.content.replace("```json", "").replace("```", "")
        analysis_data = json.loads(content)
        
        return analysis_data, vectorstore
    except Exception as e:
        print(f"Error parsing LLM response: {e}")
        return None, None