"""Database session handling with SQLAlchemy that never leaks connections.

Approved snippet. Every request or job gets a session from get_db_session(); it is
always closed, and rolled back on error, so the connection pool cannot be exhausted.
"""
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

engine = create_engine(
    "postgresql+psycopg://orders@db.internal/orders",  # password comes from the environment
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_pre_ping=True,  # drops dead connections after failovers or rotations
    pool_recycle=1800,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def get_db_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()  # returns the connection to the pool on every path


# FastAPI dependency version
def db_dependency() -> Iterator[Session]:
    with get_db_session() as session:
        yield session
