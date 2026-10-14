"""Xác thực + phân quyền: admin (quản lý) và guard (bảo vệ).

- Mật khẩu: scrypt + salt ngẫu nhiên (chuẩn thư viện, không cần thêm package).
- Phiên: token ngẫu nhiên gửi qua header "Authorization: Bearer <token>"; DB chỉ
  lưu SHA-256 của token nên lộ DB cũng không dùng lại được token.
- Windows hardware agent (không phải người) dùng header "X-Agent-Key" khớp với
  hardware_agent.api_key trong config (hoặc biến môi trường AGENT_API_KEY).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
import secrets

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import config
from app.db.base import get_session
from app.db.models import AuthToken, User, WorkShift

ROLE_ADMIN = "admin"
ROLE_GUARD = "guard"
TOKEN_TTL = dt.timedelta(hours=config.get("auth.token_ttl_hours", 12))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
    except ValueError:
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_token(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(AuthToken(token_hash=_hash_token(token), user_id=user.id,
                     expires_at=dt.datetime.utcnow() + TOKEN_TTL))
    db.commit()
    return token


def revoke_token(db: Session, token: str) -> None:
    db.query(AuthToken).filter(AuthToken.token_hash == _hash_token(token)).delete()
    db.commit()


def open_work_shift(db: Session, user: User) -> WorkShift:
    """Bảo vệ đăng nhập -> dùng lại ca đang mở (nếu có) hoặc mở ca mới."""
    ws = db.query(WorkShift).filter(WorkShift.user_id == user.id, WorkShift.status == "open").first()
    if ws is None:
        ws = WorkShift(user_id=user.id)
        db.add(ws)
        db.commit()
    return ws


def create_user(db: Session, username: str, password: str, full_name: str, role: str) -> User:
    if role not in (ROLE_ADMIN, ROLE_GUARD):
        raise ValueError(f"role không hợp lệ: {role}")
    if len(password) < 8:
        raise ValueError("Mật khẩu phải có ít nhất 8 ký tự")
    user = User(username=username, password_hash=hash_password(password), full_name=full_name, role=role)
    db.add(user)
    db.commit()
    return user


def bootstrap_admin() -> None:
    """Chưa có tài khoản nào -> tạo admin đầu tiên từ biến môi trường
    PARKING_ADMIN_USER / PARKING_ADMIN_PASSWORD (hoặc dùng scripts/create_user.py)."""
    password = os.environ.get("PARKING_ADMIN_PASSWORD")
    db = get_session()
    try:
        if db.query(User).count() == 0 and password:
            create_user(db, os.environ.get("PARKING_ADMIN_USER", "admin"), password, "Quản lý", ROLE_ADMIN)
    finally:
        db.close()


# ---- FastAPI dependencies -------------------------------------------------

def get_db():
    db = get_session()
    try:
        yield db
    finally:
        db.close()


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def user_from_token(db: Session, token: str | None) -> User | None:
    """Dùng chung cho header Bearer (HTTP) và query param (WebSocket — browser
    không gửi được header tuỳ ý khi mở kết nối WebSocket)."""
    if not token:
        return None
    row = db.query(AuthToken).filter(AuthToken.token_hash == _hash_token(token)).first()
    if row is None or row.expires_at < dt.datetime.utcnow():
        return None
    user = db.get(User, row.user_id)
    return user if (user and user.is_active) else None


def current_user(authorization: str | None = Header(default=None),
                 db: Session = Depends(get_db)) -> User:
    user = user_from_token(db, _bearer(authorization))
    if user is None:
        raise HTTPException(401, "Chưa đăng nhập hoặc phiên không hợp lệ/đã hết hạn")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != ROLE_ADMIN:
        raise HTTPException(403, "Chỉ quản lý (admin) mới được dùng chức năng này")
    return user


def agent_key_ok(key: str | None) -> bool:
    expected = os.environ.get("AGENT_API_KEY") or config.get("hardware_agent.api_key")
    return bool(expected) and bool(key) and hmac.compare_digest(key, str(expected))


def user_or_agent(authorization: str | None = Header(default=None),
                  x_agent_key: str | None = Header(default=None),
                  db: Session = Depends(get_db)) -> User | None:
    """Trả về User nếu là người đăng nhập, None nếu là hardware agent hợp lệ."""
    if x_agent_key is not None:
        if agent_key_ok(x_agent_key):
            return None
        raise HTTPException(401, "Sai agent key")
    return current_user(authorization, db)


def require_agent(x_agent_key: str | None = Header(default=None)) -> None:
    if not agent_key_ok(x_agent_key):
        raise HTTPException(401, "Thiếu hoặc sai agent key")
