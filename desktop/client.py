"""Client HTTP gọi server nhúng (127.0.0.1) — giao diện chỉ nói chuyện với server qua API, không đụng DB trực tiếp."""
from __future__ import annotations

import requests


class ApiError(Exception):
    pass


def _detail(resp: requests.Response) -> str:
    try:
        d = resp.json().get("detail")
        if isinstance(d, list):  # lỗi validate của FastAPI
            return "; ".join(f"{'.'.join(map(str, e.get('loc', [])[1:]))}: {e.get('msg')}" for e in d)
        return str(d)
    except Exception:
        return f"HTTP {resp.status_code}"


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.token: str | None = None
        self.user: dict = {}
        self._s = requests.Session()

    @property
    def is_admin(self) -> bool:
        return self.user.get("role") == "admin"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def request(self, method: str, path: str, *, raw: bool = False, **kw):
        try:
            resp = self._s.request(method, self.base_url + path, headers=self._headers(), timeout=kw.pop("timeout", 15), **kw)
        except requests.RequestException as e:
            raise ApiError(f"Không kết nối được máy chủ nội bộ: {e}") from e
        if resp.status_code >= 400:
            raise ApiError(_detail(resp))
        if raw:
            return resp
        return resp.json() if resp.content else None

    def get(self, path: str, **params):
        return self.request("GET", path, params={k: v for k, v in params.items() if v is not None})

    def post(self, path: str, body: dict | None = None):
        return self.request("POST", path, json=body or {})

    def put(self, path: str, body: dict):
        return self.request("PUT", path, json=body)

    def patch(self, path: str, body: dict):
        return self.request("PATCH", path, json=body)

    def delete(self, path: str):
        return self.request("DELETE", path)

    def login(self, username: str, password: str) -> None:
        data = self.post("/auth/login", {"username": username, "password": password})
        self.token = data["token"]
        self.user = {**self.get("/me"), "shift_id": data.get("shift_id")}

    def logout(self) -> None:
        try:
            self.post("/auth/logout")
        except ApiError:
            pass
        self.token, self.user = None, {}
