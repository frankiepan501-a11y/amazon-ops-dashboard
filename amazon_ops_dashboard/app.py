from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse

from .aggregator import Aggregator
from .config import Config
from .lark_client import LarkClient


app = FastAPI(title="amazon-ops-dashboard", version="0.1.0")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>亚马逊运营日看板入口</title>
  <style>
    :root {
      --bg: #f4f6f8;
      --panel: #ffffff;
      --text: #172033;
      --muted: #5f6b7a;
      --line: #dfe5ec;
      --primary: #0b6b57;
      --primary-bg: #e8f5f0;
      --warn-bg: #fff7df;
      --warn-line: #efd18d;
    }
    body {
      margin: 0;
      font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    main {
      max-width: 880px;
      margin: 64px auto;
      padding: 0 24px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 32px;
      box-shadow: 0 10px 30px rgba(23, 32, 51, 0.06);
    }
    .eyebrow {
      color: var(--primary);
      font-size: 14px;
      font-weight: 700;
      margin-bottom: 10px;
    }
    h1 {
      font-size: 32px;
      line-height: 1.25;
      margin: 0 0 14px;
    }
    p {
      line-height: 1.8;
      color: var(--muted);
      margin: 0;
    }
    .lead {
      font-size: 17px;
      color: #364152;
      max-width: 720px;
    }
    .notice {
      margin-top: 22px;
      padding: 14px 16px;
      border: 1px solid var(--warn-line);
      border-radius: 8px;
      background: var(--warn-bg);
      color: #5a4614;
      font-weight: 700;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 24px;
    }
    a {
      color: var(--primary);
      font-weight: 700;
      text-decoration: none;
    }
    .button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid var(--primary);
      border-radius: 7px;
      padding: 12px 18px;
      background: var(--primary-bg);
      color: var(--primary);
      min-height: 24px;
    }
    .button.primary {
      background: var(--primary);
      color: #fff;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: 26px;
    }
    .item {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      background: #fbfcfd;
    }
    .item strong {
      display: block;
      margin-bottom: 8px;
    }
    .item span {
      color: var(--muted);
      line-height: 1.7;
      font-size: 14px;
    }
    .help {
      margin-top: 24px;
      padding-top: 20px;
      border-top: 1px solid var(--line);
      color: var(--muted);
      font-size: 14px;
      line-height: 1.8;
    }
    .tech {
      margin-top: 12px;
      color: #7a8594;
      font-size: 13px;
    }
    @media (max-width: 720px) {
      main { margin: 24px auto; padding: 0 14px; }
      .panel { padding: 22px; }
      h1 { font-size: 26px; }
      .grid { grid-template-columns: 1fr; }
      .button { width: 100%; }
    }
  </style>
</head>
<body>
  <main>
    <section class="panel">
      <div class="eyebrow">亚马逊运营日看板</div>
      <h1>同事请从这里进入飞书看板</h1>
      <p class="lead">这个网页只是入口页，真正处理任务的地方在飞书看板里。普通同事只需要点击下面第一个按钮，不需要理解技术接口，也不需要在这里手动刷新数据。</p>

      <div class="notice">如果你是运营同事：点“打开飞书看板”就可以开始看待办。</div>

      <div class="actions">
        <a class="button primary" href="https://u1wpma3xuhr.feishu.cn/base/Ol0ubJol8a6OlKsAhc9cEKngnBe">打开飞书看板</a>
        <a class="button" href="/dashboard/health">查看系统是否正常</a>
      </div>

      <div class="grid">
        <div class="item">
          <strong>这个看板看什么</strong>
          <span>排名风险、Listing 待办、广告搜索词、库存异常、差评处理、数据源是否过期。</span>
        </div>
        <div class="item">
          <strong>同事怎么用</strong>
          <span>按优先级看待办，确认负责人、下一步动作和是否已经处理，不要在这个网页里操作。</span>
        </div>
        <div class="item">
          <strong>多久更新一次</strong>
          <span>系统每天北京时间 09:40 和 13:30 自动更新。数据没变时，先看“系统是否正常”。</span>
        </div>
      </div>

      <div class="help">
        打不开飞书看板，一般是飞书权限问题；把这个页面链接发给负责人处理。看板数据长时间不更新，再点“查看系统是否正常”，把返回内容发给技术或 AI 助手。
        <div class="tech">技术入口：<a href="/docs">接口文档</a>。普通运营同事不用点这里。</div>
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
