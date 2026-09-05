"""Service layer for merchant product expense management.

Handles CRUD operations for product expenses (costs like product cost,
fuel, packaging, etc.) that are deducted from net revenue when
calculating actual net profit.
"""
from typing import List, Optional
from uuid import UUID

from sqlmodel import Session, select

from neurocom_backend.database.models.expense import (
    ProductExpense,
    ProductExpenseCreate,
    ProductExpenseUpdate,
)


def create_expense(
    db: Session,
    merchant_id: UUID,
    payload: ProductExpenseCreate,
) -> ProductExpense:
    """Create a new product expense for a merchant."""
    expense = ProductExpense(
        merchant_id=merchant_id,
        sku_id=payload.sku_id.strip(),
        platform=payload.platform.strip().lower(),
        category=payload.category.strip(),
        amount=payload.amount,
        description=payload.description,
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


def get_merchant_expenses(
    db: Session,
    merchant_id: UUID,
    platform: Optional[str] = None,
    sku_id: Optional[str] = None,
) -> List[ProductExpense]:
    """Fetch all expenses for a merchant, optionally filtered by platform or SKU."""
    query = select(ProductExpense).where(ProductExpense.merchant_id == merchant_id)
    if platform:
        query = query.where(ProductExpense.platform == platform.strip().lower())
    if sku_id:
        query = query.where(ProductExpense.sku_id == sku_id.strip())
    query = query.order_by(ProductExpense.created_at.desc())
    return list(db.exec(query).all())


def get_expense_by_id(
    db: Session,
    expense_id: UUID,
    merchant_id: UUID,
) -> Optional[ProductExpense]:
    """Fetch a single expense by ID, scoped to the merchant."""
    return db.exec(
        select(ProductExpense).where(
            ProductExpense.id == expense_id,
            ProductExpense.merchant_id == merchant_id,
        )
    ).first()


def update_expense(
    db: Session,
    expense: ProductExpense,
    payload: ProductExpenseUpdate,
) -> ProductExpense:
    """Update an existing product expense."""
    from neurocom_backend.database.models.marketplace import utc_now

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None and isinstance(value, str):
            value = value.strip()
            if field == "platform":
                value = value.lower()
        setattr(expense, field, value)
    expense.updated_at = utc_now()
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


def delete_expense(
    db: Session,
    expense: ProductExpense,
) -> None:
    """Delete a product expense."""
    db.delete(expense)
    db.commit()
