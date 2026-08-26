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
    print("Tables created successfully!")

def get_session():
    with Session(engine) as session:
        yield session
