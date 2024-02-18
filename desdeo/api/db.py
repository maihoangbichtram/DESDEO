"""Database configuration file for the API."""
# The config should be in a separate file, but for simplicity, we will keep it here for now.

import warnings

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy_utils import create_database, database_exists, drop_database


# TODO: Extract this to a config file.
DB_USER = "bhupindersaini"
DB_PASSWORD = ""  # NOQA: S105
DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "DESDEO3"


SQLALCHEMY_DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(SQLALCHEMY_DATABASE_URL)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Get a database session as a dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

