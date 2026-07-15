from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse

from .aggregator import Aggregator
from .config import Config
from .dashboard_view import INDEX_HTML, build_dashboard_payload
from .lark_client import LarkClient


app = FastAPI(title="amazon-ops-dashboard", version="0.1.0")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML


@app.get("/api/dashboard")
def dashboard() -> dict:
    cfg = Config()
    cfg.validate()
    return build_dashboard_payload(cfg, LarkClient(cfg.feishu_app_id, cfg.feishu_app_secret))


def build_aggregator() -> Aggregator:
    cfg = Config()
    cfg.validate()
    return Aggregator(cfg, LarkClient(cfg.feishu_app_id, cfg.feishu_app_secret))


def authorize(cfg: Config, authorization: str | None) -> None:
    if not cfg.api_token:
        return
    expected = f"Bearer {cfg.api_token}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="invalid bearer token")


@app.get("/dashboard/health")
def health() -> dict:
    cfg = Config()
    return {
        "ok": bool(cfg.feishu_app_id and cfg.feishu_app_secret),
        "base_token": cfg.dashboard_base_token,
        "search_term_configured": bool(cfg.search_term_summary_url),
    }


@app.post("/dashboard/run")
def run_dashboard(mode: str = Query("dry_run", pattern="^(dry_run|commit)$"), authorization: str | None = Header(default=None)) -> dict:
    cfg = Config()
    authorize(cfg, authorization)
    cfg.validate()
    result = Aggregator(cfg, LarkClient(cfg.feishu_app_id, cfg.feishu_app_secret)).run(mode)
    return result.to_dict()
