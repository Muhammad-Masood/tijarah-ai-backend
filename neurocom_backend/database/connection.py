from sqlalchemy import text
from sqlmodel import create_engine, SQLModel, Session
from dotenv import load_dotenv
import os
from .models import *

_:bool = load_dotenv()

engine = create_engine(
    os.getenv("DB_CONNECTION_STRING"),
    pool_recycle=300,
    echo=os.getenv("SQL_ECHO", "false").strip().lower() in ("1", "true", "yes"),
)

def perform_migration():
    SQLModel.metadata.create_all(engine)
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE marketplace_connection ADD COLUMN IF NOT EXISTS store_identifier VARCHAR(255) NOT NULL DEFAULT 'default'"))
            connection.execute(text("ALTER TABLE marketplace_connection DROP CONSTRAINT IF EXISTS uq_merchant_marketplace"))
            connection.execute(text("ALTER TABLE marketplace_connection DROP CONSTRAINT IF EXISTS uq_merchant_marketplace_store"))
            connection.execute(text("ALTER TABLE marketplace_connection ADD CONSTRAINT uq_merchant_marketplace_store UNIQUE (merchant_id, marketplace_id, store_identifier)"))
    print("Tables created successfully!")

def get_session():
    with Session(engine) as session:
        yield session
