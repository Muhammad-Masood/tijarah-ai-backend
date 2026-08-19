"""Bootstrap an admin account directly in the DB.

Usage:
    poetry run python -m neurocom_backend.scripts.create_admin \
        --email admin@example.com --password "strong-password" --full-name "Admin User"

There is no public API endpoint for creating admins by design; this script
is the only supported way to create one.
"""
import argparse

from sqlmodel import Session, select

from neurocom_backend.database.connection import engine
from neurocom_backend.database.models.merchant import Merchant
from neurocom_backend.database.models.user import UserRole
from neurocom_backend.utils.security import hash_password


def create_admin(email: str, password: str, full_name: str, business_name: str) -> None:
    with Session(engine) as db:
        existing = db.exec(select(Merchant).where(Merchant.email == email)).first()
        if existing:
            if existing.role == UserRole.admin:
                print(f"Admin already exists for {email}")
                return
            existing.role = UserRole.admin
            db.add(existing)
            db.commit()
            print(f"Promoted existing account {email} to admin")
            return

        admin = Merchant(
            full_name=full_name,
            business_name=business_name,
            email=email,
            password=hash_password(password),
            role=UserRole.admin,
        )
        db.add(admin)
        db.commit()
        print(f"Created admin account for {email}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create or promote an admin account")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--full-name", required=True, dest="full_name")
    parser.add_argument("--business-name", default="Admin")
    args = parser.parse_args()
    create_admin(
        email=args.email,
        password=args.password,
        full_name=args.full_name,
        business_name=args.business_name,
    )
