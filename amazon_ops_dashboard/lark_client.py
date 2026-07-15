import json
import time
import urllib.parse
import urllib.request
from urllib.error import URLError
from typing import Any


class LarkClient:
    def __init__(self, app_id: str, app_secret: str) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self._tenant_token = ""
        self._tenant_token_exp = 0.0
        self._opener = urllib.request.build_opener()

    def _open(self, request: urllib.request.Request, timeout: int = 60) -> Any:
        return self._opener.open(request, timeout=timeout)

    def token(self) -> str:
        if self._tenant_token and time.time() < self._tenant_token_exp:
            return self._tenant_token
        body = json.dumps({"app_id": self.app_id, "app_secret": self.app_secret}).encode("utf-8")
        req = urllib.request.Request(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        payload = self._send_json(req, timeout=20)
        if payload.get("code", 0) != 0:
            raise RuntimeError(f"tenant token failed: {payload}")
        self._tenant_token = payload["tenant_access_token"]
        self._tenant_token_exp = time.time() + 6600
        return self._tenant_token

    def request(self, method: str, path: str, params: dict[str, Any] | None = None, body: dict[str, Any] | None = None) -> dict[str, Any]:
        qs = ""
        if params:
            qs = "?" + urllib.parse.urlencode(params, doseq=True)
        data = None
        headers = {
            "Authorization": f"Bearer {self.token()}",
            "Content-Type": "application/json; charset=utf-8",
        }
        if body is not None:
            data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(
            f"https://open.feishu.cn/open-apis{path}{qs}",
            data=data,
            headers=headers,
            method=method,
        )
        payload = self._send_json(req)
        if payload.get("code", 0) in (99991663, 99991664):
            self._tenant_token = ""
            headers["Authorization"] = f"Bearer {self.token()}"
            req = urllib.request.Request(
                f"https://open.feishu.cn/open-apis{path}{qs}",
                data=data,
                headers=headers,
                method=method,
            )
            payload = self._send_json(req)
        if payload.get("code", 0) != 0:
            raise RuntimeError(f"Lark API error {payload.get('code')}: {payload.get('msg') or payload.get('message')}")
        return payload.get("data") or {}

    def _send_json(self, req: urllib.request.Request, timeout: int = 60) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return json.loads(self._open(req, timeout=timeout).read().decode("utf-8"))
            except (TimeoutError, URLError, PermissionError) as exc:
                last_error = exc
                time.sleep(0.6 + attempt * 1.2)
        raise last_error or RuntimeError("request failed")

    def list_records(self, app_token: str, table_id: str, limit: int = 5000) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page_token = ""
        while True:
            params: dict[str, Any] = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token
            data = self.request("GET", f"/bitable/v1/apps/{app_token}/tables/{table_id}/records", params=params)
            records.extend(data.get("items") or [])
            time.sleep(0.15)
            if len(records) >= limit:
                return records[:limit]
            if not data.get("has_more"):
                return records
            page_token = data.get("page_token", "")

    def batch_create_records(self, app_token: str, table_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {"created": 0}
        total = 0
        for i in range(0, len(rows), 500):
            chunk = rows[i:i + 500]
            self.request(
                "POST",
                f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create",
                body={"records": [{"fields": r} for r in chunk]},
            )
            total += len(chunk)
        return {"created": total}

    def batch_update_records(self, app_token: str, table_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {"updated": 0}
        total = 0
        for i in range(0, len(rows), 500):
            chunk = rows[i:i + 500]
            self.request(
                "POST",
                f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update",
                body={"records": chunk},
            )
            total += len(chunk)
        return {"updated": total}

    def upsert_by_key(self, app_token: str, table_id: str, key_field: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        existing = self.list_records(app_token, table_id, limit=10000)
        by_key: dict[str, str] = {}
        for rec in existing:
            fields = rec.get("fields") or {}
            key = normalize_cell(fields.get(key_field))
            if key:
                by_key[key] = rec.get("record_id", "")

        creates: list[dict[str, Any]] = []
        updates: list[dict[str, Any]] = []
        for fields in rows:
            key = normalize_cell(fields.get(key_field))
            if key in by_key:
                updates.append({"record_id": by_key[key], "fields": fields})
            else:
                creates.append(fields)
        result = {}
        result.update(self.batch_create_records(app_token, table_id, creates))
        result.update(self.batch_update_records(app_token, table_id, updates))
        return result


def normalize_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("name") or item.get("link") or item.get("url") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or value.get("link") or value.get("url") or "")
    return str(value)
