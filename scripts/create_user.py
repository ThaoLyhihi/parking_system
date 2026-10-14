"""Tạo tài khoản: python scripts/create_user.py <username> <full_name> <admin|guard>
Mật khẩu nhập tương tác (không đưa vào đối số dòng lệnh để khỏi lọt vào shell history)."""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth import create_user  # noqa: E402
from app.db.base import get_session, init_db  # noqa: E402


def main() -> None:
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    username, full_name, role = sys.argv[1:]
    password = getpass.getpass("Mật khẩu (>= 8 ký tự): ")
    if password != getpass.getpass("Nhập lại: "):
        sys.exit("Mật khẩu không khớp")
    init_db()
    db = get_session()
    create_user(db, username, password, full_name, role)
    print(f"Đã tạo {role} '{username}'")


if __name__ == "__main__":
    main()
