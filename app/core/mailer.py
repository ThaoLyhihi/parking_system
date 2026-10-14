"""Gửi báo cáo ca qua email (SMTP). Cấu hình ở mục `email:` trong config.yaml;
mật khẩu SMTP lấy từ biến môi trường SMTP_PASSWORD (ưu tiên) để không phải ghi vào file."""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage


logger = logging.getLogger("mailer")


def email_enabled(cfg: dict) -> bool:
    """cfg = app.settings.get_section(db, "email")."""
    return bool(cfg.get("enabled") and cfg.get("smtp_host") and cfg.get("recipients"))


def send_shift_report(cfg: dict, subject: str, body: str, pdf: bytes, filename: str) -> bool:
    """Trả về True nếu gửi thành công. Không ném exception: lỗi mail không được
    làm hỏng việc kết ca, chỉ ghi log để quản lý/bảo vệ tải PDF thủ công."""
    if not email_enabled(cfg):
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.get("from") or cfg.get("username")
    msg["To"] = ", ".join(cfg["recipients"])
    msg.set_content(body)
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=filename)
    host, port = cfg["smtp_host"], int(cfg.get("smtp_port", 587))
    try:
        if cfg.get("security", "starttls") == "ssl":
            smtp = smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=20)
        else:
            smtp = smtplib.SMTP(host, port, timeout=20)
        with smtp:
            if cfg.get("security", "starttls") == "starttls":
                smtp.starttls(context=ssl.create_default_context())
            user = cfg.get("username")
            if user:
                smtp.login(user, os.environ.get("SMTP_PASSWORD") or cfg.get("password", ""))
            smtp.send_message(msg)
        logger.info("Đã gửi báo cáo ca tới %s", msg["To"])
        return True
    except Exception:
        logger.exception("Gửi email báo cáo ca thất bại")
        return False
