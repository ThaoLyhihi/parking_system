from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import config
from app.db.models import Base

# Biến môi trường DATABASE_URL (đặt trong docker-compose.yml) được ưu tiên hơn
# config.yaml — để chạy qua Docker Compose dùng PostgreSQL gói chung mà không
# phải sửa file config, còn chạy local (dev/test) vẫn dùng SQLite trong
# config.example.yaml mà không cần đặt biến môi trường nào.
_DATABASE_URL = os.environ.get("DATABASE_URL") or config.get("database.url", "sqlite:///parking.db")

_engine = create_engine(_DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def init_db() -> None:
    """Tạo toàn bộ bảng nếu chưa có. Dùng cho dev/demo (SQLite); khi triển khai
    với PostgreSQL/MySQL thật nên dùng công cụ migration (Alembic) thay vì gọi
    trực tiếp hàm này."""
    Base.metadata.create_all(_engine)


def get_session() -> Session:
    return SessionLocal()
