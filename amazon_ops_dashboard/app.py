from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse

from .aggregator import Aggregator
from .config import Config
from .lark_client import LarkClient


app = FastAPI(title="amazon-ops-dashboard", version="0.1.0")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Amazon Ops Dashboard</title>
  <style>
    body { margin: 0; font-family: Arial, sans-serif; background: #f7f8fa; color: #1f2937; }
    main { max-width: 760px; margin: 72px auto; padding: 0 24px; }
    h1 { font-size: 30px; margin: 0 0 12px; }
    p { line-height: 1.6; color: #4b5563; }
    .panel { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 24px; }
    .links { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 22px; }
    a { color: #0f766e; font-weight: 700; text-decoration: none; }
    .button { border: 1px solid #0f766e; border-radius: 6px; padding: 10px 14px; background: #ecfdf5; }
    code { background: #eef2f7; border-radius: 4px; padding: 2px 6px; }
  </style>
</head>
<body>
  <main>
    <section class="panel">
      <h1>Amazon Ops Dashboard Service</h1>
      <p>This domain is the refresh API for the Feishu Base dashboard. The operator-facing dashboard lives in Feishu; n8n calls this service on schedule to refresh summary, action, and source-health rows.</p>
      <p>Browser access to <code>/</code> is read-only. Production refresh still requires the protected <code>POST /dashboard/run?mode=commit</code> endpoint.</p>
      <div class="links">
        <a class="button" href="https://u1wpma3xuhr.feishu.cn/base/Ol0ubJol8a6OlKsAhc9cEKngnBe">Open Feishu Dashboard</a>
        <a class="button" href="/dashboard/health">Check API Health</a>
        <a class="button" href="/docs">Open API Docs</a>
      </div>
    </section>
  </main>
</body>
</html>"""


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
