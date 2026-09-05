"""API endpoints for merchant product expense management.

Allows merchants to define per-SKU expenses (product cost, fuel, packaging,
etc.) that are later deducted from net revenue when calculating actual
net profit in the financial analytics.
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from neurocom_backend.database.connection import get_session
from neurocom_backend.database.models.merchant import Merchant
from neurocom_backend.database.models.expense import (
    ProductExpenseCreate,
    ProductExpenseRead,
    ProductExpenseUpdate,
)
from neurocom_backend.dependencies import get_current_user
from neurocom_backend.services.expense_service import (
    create_expense,
    delete_expense,
    get_expense_by_id,
    get_merchant_expenses,
    update_expense,
)

router = APIRouter(prefix="/expenses", tags=["Product Expenses"])


@router.post("/", response_model=ProductExpenseRead, status_code=status.HTTP_201_CREATED)
def add_expense(
    payload: ProductExpenseCreate,
    merchant: Merchant = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> ProductExpenseRead:
    """Create a new product expense (e.g. product cost, fuel, packaging)."""
    return create_expense(db, merchant.id, payload)


@router.get("/", response_model=List[ProductExpenseRead])
def list_expenses(
    platform: Optional[str] = None,
    sku_id: Optional[str] = None,
    merchant: Merchant = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> List[ProductExpenseRead]:
    """List all product expenses for the authenticated merchant."""
    return get_merchant_expenses(db, merchant.id, platform=platform, sku_id=sku_id)


@router.get("/{expense_id}", response_model=ProductExpenseRead)
def get_expense(
    expense_id: UUID,
    merchant: Merchant = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> ProductExpenseRead:
    """Get a specific product expense by ID."""
    expense = get_expense_by_id(db, expense_id, merchant.id)
    if not expense:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Expense not found",
        )
    return expense


@router.put("/{expense_id}", response_model=ProductExpenseRead)
def update_expense_endpoint(
    expense_id: UUID,
    payload: ProductExpenseUpdate,
    merchant: Merchant = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> ProductExpenseRead:
    """Update an existing product expense."""
    expense = get_expense_by_id(db, expense_id, merchant.id)
    if not expense:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Expense not found",
        )
    return update_expense(db, expense, payload)


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense_endpoint(
    expense_id: UUID,
    merchant: Merchant = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> None:
    """Delete a product expense."""
    expense = get_expense_by_id(db, expense_id, merchant.id)
    if not expense:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Expense not found",
        )
    delete_expense(db, expense)
