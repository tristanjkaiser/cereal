"""Flask configuration."""
import os


class Config:
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/cereal")
    POOL_SIZE = int(os.getenv("POOL_SIZE", "5"))
    SECRET_KEY = os.getenv("SECRET_KEY", "cereal-dev-key")
