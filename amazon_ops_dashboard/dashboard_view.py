import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import Config
from .lark_client import LarkClient, normalize_cell


BJ = timezone(timedelta(hours=8))

SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
DONE_STATUSES = {"已完成", "已处理", "已归档", "已关闭", "关闭"}
NO_ACTION_STATUSES = {"无需处理", "无需操作", "无需跟进", "正常"}
BAD_HEALTH = {"错误", "过期", "临期", "未接入"}

MODULES = [
    {
        "key": "listing",
        "title": "Listing 体检",
        "subtitle": "先修上架质量，再谈广告和排名",
        "sources": ["A31", "万词作战台"],
        "owner_hint": "运营负责人",
    },
    {
        "key": "rank",
        "title": "排名风险",
        "subtitle": "自然排名、广告在榜、快照过期",
        "sources": ["Rank"],
        "owner_hint": "站点负责人",
    },
    {
        "key": "ads",
        "title": "广告搜索词",
        "subtitle": "放量词、否词、人工判断词",
        "sources": ["搜索词v2"],
        "owner_hint": "广告负责人",
    },
    {
        "key": "traffic",
        "title": "曝光机会",
        "subtitle": "展示份额机会词和 CSV 新鲜度",
        "sources": ["展示份额"],
        "owner_hint": "广告/运营",
    },
    {
        "key": "reviews",
        "title": "差评处理",
        "subtitle": "新增差评、7天复检、14天未解决",
        "sources": ["差评审计"],
        "owner_hint": "客服/运营",
    },
    {
        "key": "inventory",
        "title": "库存处置",
        "subtitle": "超龄、冗余、清货动作，待接入",
        "sources": ["库存处置", "库存预警"],
        "owner_hint": "备货/运营",
    },
]


def build_dashboard_payload(cfg: Config, lark: LarkClient) -> dict[str, Any]:
    actions = [
        normalize_action_record(rec)
        for rec in lark.list_records(cfg.dashboard_base_token, cfg.action_table_id, 10000)
    ]
    health = [
        normalize_health_record(rec)
        for rec in lark.list_records(cfg.dashboard_base_token, cfg.health_table_id, 1000)
    ]
    summary = [
        normalize_summary_record(rec)
        for rec in lark.list_records(cfg.dashboard_base_token, cfg.summary_table_id, 1000)
    ]
    actions = [x for x in actions if x["key"]]
    health = [x for x in health if x["source"]]
    summary = [x for x in summary if x["owner"]]

    human_actions = [x for x in actions if needs_human(x)]
    active_or_monitor = [x for x in actions if not is_done(x)]
    p0 = sum(1 for x in human_actions if x["severity"] == "P0")
    p1 = sum(1 for x in human_actions if x["severity"] == "P1")
    abnormal_sources = [x for x in health if x["freshness"] in BAD_HEALTH]
    owners = build_owner_rows(actions, human_actions)
    modules = build_modules(actions, human_actions, health)

    return {
        "generated_at_ms": now_ms(),
        "feishu_base_url": f"https://u1wpma3xuhr.feishu.cn/base/{cfg.dashboard_base_token}",
        "kpis": {
            "human_open": len(human_actions),
            "p0": p0,
            "p1": p1,
            "monitored_total": len(active_or_monitor),
            "all_action_rows": len(actions),
            "abnormal_sources": len(abnormal_sources),
            "source_count": len(health),
            "owner_count": len(owners),
        },
        "modules": modules,
        "priority_actions": sort_actions(human_actions)[:40],
        "monitor_actions": sort_actions([x for x in active_or_monitor if not needs_human(x)])[:60],
        "health": sorted(health, key=lambda x: (0 if x["freshness"] in BAD_HEALTH else 1, x["source"])),
        "owners": owners,
        "summary": summary,
    }


def now_ms() -> int:
    return int(time.time() * 1000)


def normalize_action_record(rec: dict[str, Any]) -> dict[str, Any]:
    f = rec.get("fields") or {}
    source_link = link_value(f.get("源记录链接"))
    updated_ms = int_value(f.get("更新时间"))
    return {
        "record_id": rec.get("record_id", ""),
        "key": text_value(f.get("事项键")),
        "date": text_value(f.get("看板日期")),
        "source": text_value(f.get("来源")) or "未分类",
        "owner": text_value(f.get("负责人")) or "未分配",
        "severity": text_value(f.get("严重级别")) or "P2",
        "status": text_value(f.get("状态")) or "待处理",
        "site": text_value(f.get("站点")),
        "asin": text_value(f.get("ASIN")),
        "product": text_value(f.get("产品")),
        "keyword": text_value(f.get("关键词")),
        "metric": text_value(f.get("指标")),
        "current_value": text_value(f.get("当前值")),
        "suggested_action": text_value(f.get("建议动作")),
        "source_url": source_link,
        "source_record_id": text_value(f.get("源记录ID")),
        "updated_at_ms": updated_ms,
        "updated_at": date_text(updated_ms),
    }


def normalize_health_record(rec: dict[str, Any]) -> dict[str, Any]:
    f = rec.get("fields") or {}
    latest_ms = int_value(f.get("最近数据时间"))
    updated_ms = int_value(f.get("更新时间"))
    return {
        "record_id": rec.get("record_id", ""),
        "key": text_value(f.get("健康键")),
        "source": text_value(f.get("来源")) or "未分类",
        "freshness": text_value(f.get("新鲜度")) or "未知",
        "latest_at_ms": latest_ms,
        "latest_at": date_text(latest_ms),
        "age_days": int_value(f.get("距今天数")),
        "record_count": int_value(f.get("记录数")),
        "error": text_value(f.get("错误信息")),
        "suggested_action": text_value(f.get("建议动作")),
        "updated_at_ms": updated_ms,
        "updated_at": date_text(updated_ms),
    }


def normalize_summary_record(rec: dict[str, Any]) -> dict[str, Any]:
    f = rec.get("fields") or {}
    return {
        "record_id": rec.get("record_id", ""),
        "owner": text_value(f.get("负责人")) or "未分配",
        "p0": int_value(f.get("P0数")),
        "p1": int_value(f.get("P1数")),
        "risk_score": int_value(f.get("风险分")),
        "total_actions": int_value(f.get("待办总数")),
        "updated_at_ms": int_value(f.get("更新时间")),
    }


def build_owner_rows(actions: list[dict[str, Any]], human_actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_owner: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "owner": "",
        "human_open": 0,
        "p0": 0,
        "p1": 0,
        "monitor_total": 0,
        "sources": defaultdict(int),
    })
    human_keys = {x["key"] for x in human_actions}
    for action in actions:
        owner = action["owner"] or "未分配"
        row = by_owner[owner]
        row["owner"] = owner
        if not is_done(action):
            row["monitor_total"] += 1
            row["sources"][action["source"]] += 1
        if action["key"] in human_keys:
            row["human_open"] += 1
            if action["severity"] == "P0":
                row["p0"] += 1
            if action["severity"] == "P1":
                row["p1"] += 1
    rows = []
    for row in by_owner.values():
        top_sources = sorted(row["sources"].items(), key=lambda x: x[1], reverse=True)[:3]
        rows.append({
            "owner": row["owner"],
            "human_open": row["human_open"],
            "p0": row["p0"],
            "p1": row["p1"],
            "monitor_total": row["monitor_total"],
            "top_sources": [{"source": k, "count": v} for k, v in top_sources],
        })
    return sorted(rows, key=lambda x: (-(x["p0"] * 100 + x["p1"] * 10 + x["human_open"]), x["owner"]))


def build_modules(actions: list[dict[str, Any]], human_actions: list[dict[str, Any]], health: list[dict[str, Any]]) -> list[dict[str, Any]]:
    human_keys = {x["key"] for x in human_actions}
    health_by_source = {x["source"]: x for x in health}
    rows = []
    for module in MODULES:
        sources = set(module["sources"])
        module_actions = [x for x in actions if x["source"] in sources and not is_done(x)]
        module_human = [x for x in module_actions if x["key"] in human_keys]
        module_health = [health_by_source[x] for x in module["sources"] if x in health_by_source]
        worst = worst_health(module_health)
        rows.append({
            "key": module["key"],
            "title": module["title"],
            "subtitle": module["subtitle"],
            "sources": module["sources"],
            "owner_hint": module["owner_hint"],
            "health": worst,
            "health_text": health_label(worst),
            "human_open": len(module_human),
            "p0": sum(1 for x in module_human if x["severity"] == "P0"),
            "p1": sum(1 for x in module_human if x["severity"] == "P1"),
            "monitor_total": len(module_actions),
            "top_actions": sort_actions(module_human)[:5],
            "health_rows": module_health,
        })
    return rows


def worst_health(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "待接入"
    order = {"错误": 0, "过期": 1, "未接入": 2, "临期": 3, "未知": 4, "正常": 5}
    return sorted((x["freshness"] for x in rows), key=lambda x: order.get(x, 4))[0]


def health_label(value: str) -> str:
    return {
        "正常": "正常",
        "临期": "快过期",
        "过期": "数据过期",
        "错误": "需要配置/修复",
        "未接入": "未接入",
        "待接入": "待接入",
    }.get(value, value or "未知")


def sort_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(actions, key=lambda x: (
        SEVERITY_ORDER.get(x["severity"], 9),
        x["owner"],
        x["source"],
        x["site"],
        x["asin"],
        x["metric"],
    ))


def needs_human(action: dict[str, Any]) -> bool:
    return not is_done(action) and action["status"] not in NO_ACTION_STATUSES


def is_done(action: dict[str, Any]) -> bool:
    return action["status"] in DONE_STATUSES


def text_value(value: Any) -> str:
    return normalize_cell(value).strip()


def int_value(value: Any) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = normalize_cell(value).replace(",", "").strip()
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def link_value(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("link") or value.get("url") or "")
    if isinstance(value, list):
        for item in value:
            link = link_value(item)
            if link:
                return link
    return ""


def date_text(ms: int) -> str:
    if not ms:
        return ""
    if ms < 10000000000:
        ms *= 1000
    return datetime.fromtimestamp(ms / 1000, tz=BJ).strftime("%Y-%m-%d %H:%M")


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>亚马逊运营驾驶舱</title>
  <style>
    :root {
      --paper: #f4f1ea;
      --surface: #fffdf7;
      --surface-2: #eee7d8;
      --ink: #171914;
      --muted: #6a6d60;
      --line: #d8d0c2;
      --green: #166b52;
      --red: #b13d35;
      --amber: #b06f16;
      --blue: #285d91;
      --violet: #6f568c;
      --shadow: 0 18px 42px rgba(37, 32, 24, .08);
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      min-width: 1180px;
      color: var(--ink);
      font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
      letter-spacing: 0;
      background:
        linear-gradient(90deg, rgba(23,25,20,.035) 1px, transparent 1px),
        linear-gradient(180deg, rgba(23,25,20,.03) 1px, transparent 1px),
        var(--paper);
      background-size: 28px 28px;
    }
    .app { display: grid; grid-template-columns: 216px minmax(0, 1fr); min-height: 100vh; }
    .sidebar {
      position: sticky;
      top: 0;
      height: 100vh;
      padding: 18px 14px;
      background: #1c211b;
      color: #f8f3e8;
      display: flex;
      flex-direction: column;
      border-right: 1px solid #0c0f0b;
    }
    .brand { display: flex; gap: 10px; align-items: center; margin-bottom: 28px; }
    .mark {
      width: 38px;
      height: 38px;
      display: grid;
      place-items: center;
      border: 1px solid rgba(248,243,232,.28);
      color: #40e0b9;
      font-weight: 900;
      font-size: 13px;
    }
    .brand strong { display: block; font-size: 14px; }
    .brand span { display: block; color: rgba(248,243,232,.62); font-size: 11px; margin-top: 3px; }
    nav { display: grid; gap: 6px; }
    nav a {
      color: rgba(248,243,232,.84);
      text-decoration: none;
      min-height: 35px;
      display: flex;
      align-items: center;
      padding: 0 10px;
      border-radius: 5px;
      font-size: 13px;
    }
    nav a:hover, nav a.active { background: #2a3028; color: #fff; }
    .source-card {
      margin-top: auto;
      padding: 13px;
      border: 1px solid rgba(248,243,232,.14);
      border-radius: 8px;
      background: #11150f;
      line-height: 1.65;
      font-size: 12px;
      color: rgba(248,243,232,.78);
    }
    .source-card strong { display: block; color: #fff; margin: 4px 0; }
    main { padding: 28px 32px 54px; min-width: 0; }
    .topbar { display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; margin-bottom: 18px; }
    .eyebrow { color: var(--green); font-weight: 900; font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }
    h1 { margin: 3px 0 8px; font-size: 42px; line-height: 1.05; font-weight: 950; }
    .subtitle { max-width: 920px; color: var(--muted); font-size: 13px; line-height: 1.75; }
    .actions { display: flex; gap: 9px; align-items: center; justify-content: flex-end; flex-wrap: wrap; color: var(--muted); font-size: 12px; }
    .button, button {
      height: 34px;
      border: 1px solid var(--ink);
      border-radius: 5px;
      padding: 0 12px;
      background: var(--ink);
      color: #fffdf7;
      font-weight: 800;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-family: inherit;
      font-size: 13px;
    }
    .button.secondary, button.secondary { background: var(--surface); color: var(--ink); border-color: var(--line); }
    .section { margin-top: 22px; scroll-margin-top: 22px; }
    .section-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-end; margin-bottom: 10px; }
    h2 { margin: 0; font-size: 22px; }
    .hint { color: var(--muted); font-size: 12px; line-height: 1.6; }
    .kpis { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; }
    .card, .panel, .notice {
      background: rgba(255,253,247,.9);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .kpi { min-height: 104px; padding: 14px; position: relative; overflow: hidden; }
    .kpi::after {
      content: "";
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      height: 3px;
      background: linear-gradient(90deg, var(--green), var(--amber), var(--violet));
    }
    .label { color: var(--muted); font-size: 12px; font-weight: 800; }
    .value { margin-top: 10px; font-size: 30px; line-height: 1; font-weight: 950; font-variant-numeric: tabular-nums; }
    .delta { margin-top: 8px; color: var(--muted); font-size: 11px; line-height: 1.5; }
    .danger .value { color: var(--red); }
    .warn .value { color: var(--amber); }
    .ok .value { color: var(--green); }
    .notice {
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: center;
      padding: 12px 14px;
      margin-top: 12px;
      border-color: #e2c885;
      background: #fff7df;
      font-size: 13px;
    }
    .grid-2 { display: grid; grid-template-columns: 1.25fr .75fr; gap: 12px; align-items: start; }
    .grid-3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
    .grid-6 { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; }
    .panel { padding: 14px; overflow: hidden; }
    .panel-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin-bottom: 11px; padding-bottom: 9px; border-bottom: 1px solid #ece4d6; }
    .panel h3 { margin: 0; font-size: 16px; }
    .module {
      min-height: 176px;
      padding: 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      border-left: 4px solid var(--green);
    }
    .module.bad { border-left-color: var(--red); }
    .module.warn { border-left-color: var(--amber); }
    .module.todo { border-left-color: var(--violet); }
    .module-title { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }
    .module-title strong { font-size: 17px; }
    .tag {
      display: inline-flex;
      align-items: center;
      min-height: 23px;
      padding: 0 8px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: #f6efe2;
      color: #40463e;
      white-space: nowrap;
      font-size: 12px;
      font-weight: 800;
    }
    .tag.p0, .tag.bad { color: var(--red); border-color: rgba(177,61,53,.34); background: rgba(177,61,53,.08); }
    .tag.p1, .tag.warn { color: var(--amber); border-color: rgba(176,111,22,.35); background: rgba(176,111,22,.09); }
    .tag.ok { color: var(--green); border-color: rgba(22,107,82,.35); background: rgba(22,107,82,.08); }
    .tag.todo { color: var(--violet); border-color: rgba(111,86,140,.35); background: rgba(111,86,140,.08); }
    .module-meta { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: auto; }
    .mini { padding: 8px; background: #fffaf0; border: 1px solid #eadfcd; border-radius: 7px; }
    .mini span { display: block; color: var(--muted); font-size: 11px; margin-bottom: 5px; }
    .mini strong { font-size: 20px; font-variant-numeric: tabular-nums; }
    .queue { display: grid; gap: 9px; }
    .queue-item { padding: 12px; border: 1px solid #e7dccb; border-radius: 8px; background: #fffaf0; }
    .queue-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
    .queue-head strong { font-size: 14px; overflow-wrap: anywhere; }
    .queue-body { margin-top: 7px; color: var(--muted); font-size: 12px; line-height: 1.65; overflow-wrap: anywhere; }
    .queue-foot { margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
    .queue-foot a { color: var(--green); font-weight: 800; text-decoration: none; }
    .bar-row {
      display: grid;
      grid-template-columns: 96px minmax(0, 1fr) 78px;
      gap: 10px;
      align-items: center;
      padding: 7px 0;
      border-bottom: 1px solid #eee5d8;
      font-size: 12px;
    }
    .bar-row:last-child { border-bottom: 0; }
    .track { height: 10px; background: #e7dfd1; border-radius: 999px; overflow: hidden; }
    .fill { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--green), var(--blue)); min-width: 2px; }
    .health-row {
      display: grid;
      grid-template-columns: 120px 80px 80px minmax(0, 1fr);
      gap: 10px;
      align-items: start;
      padding: 10px 0;
      border-bottom: 1px solid #eee5d8;
      font-size: 12px;
    }
    .health-row:last-child { border-bottom: 0; }
    .filters { display: grid; grid-template-columns: 1.2fr 1fr 1fr 1fr; gap: 9px; margin-bottom: 10px; }
    select, input {
      width: 100%;
      height: 34px;
      border: 1px solid var(--line);
      border-radius: 5px;
      padding: 0 10px;
      background: rgba(255,253,247,.92);
      color: var(--ink);
      font-family: inherit;
    }
    .table-wrap { overflow: auto; max-height: 560px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); }
    table { width: 100%; min-width: 1220px; border-collapse: collapse; font-size: 12px; }
    th, td { padding: 9px 10px; border-bottom: 1px solid #ece4d6; text-align: left; vertical-align: top; }
    th { position: sticky; top: 0; background: #eee7d8; z-index: 1; color: #3b4039; }
    td { line-height: 1.5; overflow-wrap: anywhere; }
    .empty { color: var(--muted); padding: 20px; border: 1px dashed var(--line); border-radius: 8px; background: rgba(255,253,247,.62); }
    .loading { padding: 18px; color: var(--muted); }
    .error { color: var(--red); background: rgba(177,61,53,.08); border: 1px solid rgba(177,61,53,.25); border-radius: 8px; padding: 16px; }
    @media (max-width: 1360px) {
      .kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .grid-6, .grid-3 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .grid-2 { grid-template-columns: 1fr; }
    }
    @media (max-width: 980px) {
      body { min-width: 0; }
      .app { grid-template-columns: 1fr; }
      .sidebar { position: relative; height: auto; }
      main { padding: 18px 14px 42px; }
      .kpis, .grid-6, .grid-3 { grid-template-columns: 1fr; }
      h1 { font-size: 30px; }
      .topbar, .section-head { flex-direction: column; align-items: stretch; }
      .filters { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside class="sidebar">
      <div class="brand">
        <div class="mark">AMZ</div>
        <div>
          <strong>Amazon Ops</strong>
          <span>运营中控台</span>
        </div>
      </div>
      <nav>
        <a href="#overview" class="active">总览</a>
        <a href="#modules">业务模块</a>
        <a href="#priority">今日待办</a>
        <a href="#health">数据健康</a>
        <a href="#owners">负责人</a>
        <a href="#details">明细池</a>
      </nav>
      <div class="source-card">
        <div>数据源</div>
        <strong>Feishu Bitable</strong>
        <div>页面只读；处理动作仍回源表或飞书看板。</div>
        <div id="sideStatus">正在读取数据...</div>
      </div>
    </aside>

    <main>
      <header class="topbar" id="overview">
        <div>
          <div class="eyebrow">Amazon Operations Command</div>
          <h1>亚马逊运营驾驶舱</h1>
          <div class="subtitle">把 A31、Rank、搜索词、展示份额、万词作战台、差评审计等源表重新整理成“谁要处理、先处理什么、哪个数据源卡住”的运营看板。</div>
        </div>
        <div class="actions">
          <span id="refreshText">未刷新</span>
          <button class="secondary" onclick="loadDashboard()">刷新页面数据</button>
          <a class="button secondary" id="feishuLink" href="https://u1wpma3xuhr.feishu.cn/base/Ol0ubJol8a6OlKsAhc9cEKngnBe">打开飞书原表</a>
        </div>
      </header>

      <section id="kpis" class="kpis">
        <div class="loading">正在加载看板数据...</div>
      </section>
      <div id="notice"></div>

      <section class="section" id="modules">
        <div class="section-head">
          <div>
            <h2>业务模块看板</h2>
            <div class="hint">按亚马逊运营链路重排，不再让同事在 2000 多行表格里找重点。</div>
          </div>
          <div class="hint">P0/P1 看今天要处理；监控项看系统盯住了多少对象。</div>
        </div>
        <div id="moduleGrid" class="grid-6"></div>
      </section>

      <section class="section grid-2" id="priority">
        <div class="panel">
          <div class="panel-head">
            <h3>今日优先处理</h3>
            <span>只展示需要人工动作的事项</span>
          </div>
          <div id="priorityList" class="queue"></div>
        </div>
        <div class="panel">
          <div class="panel-head">
            <h3>模块判断</h3>
            <span>先修数据源，再处理业务项</span>
          </div>
          <div id="moduleJudgement" class="queue"></div>
        </div>
      </section>

      <section class="section grid-2" id="health">
        <div class="panel">
          <div class="panel-head">
            <h3>数据源健康</h3>
            <span>过期/错误会让看板误判</span>
          </div>
          <div id="healthRows"></div>
        </div>
        <div class="panel" id="owners">
          <div class="panel-head">
            <h3>负责人负载</h3>
            <span>按待处理和监控项排序</span>
          </div>
          <div id="ownerRows"></div>
        </div>
      </section>

      <section class="section" id="details">
        <div class="section-head">
          <div>
            <h2>明细池</h2>
            <div class="hint">用于追溯，不是主要工作入口。普通同事先看上面的“今日优先处理”。</div>
          </div>
        </div>
        <div class="panel">
          <div class="filters">
            <input id="searchInput" placeholder="搜索负责人 / ASIN / 产品 / 关键词" />
            <select id="sourceFilter"></select>
            <select id="severityFilter">
              <option value="">全部等级</option>
              <option value="P0">P0</option>
              <option value="P1">P1</option>
              <option value="P2">P2</option>
              <option value="P3">P3</option>
            </select>
            <select id="humanFilter">
              <option value="">全部状态</option>
              <option value="human">只看待人工处理</option>
              <option value="monitor">只看监控项/无需处理</option>
            </select>
          </div>
          <div id="detailTable" class="table-wrap"></div>
        </div>
      </section>
    </main>
  </div>

  <script>
    const state = { data: null, allRows: [] };
    const nf = new Intl.NumberFormat("zh-CN");
    const $ = (id) => document.getElementById(id);

    function esc(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function tag(value, extra = "") {
      const cls = value === "P0" ? "p0" : value === "P1" ? "p1" : extra;
      return `<span class="tag ${cls}">${esc(value || "无")}</span>`;
    }

    function healthClass(value) {
      if (["错误", "过期", "需要配置/修复"].includes(value)) return "bad";
      if (["临期", "快过期"].includes(value)) return "warn";
      if (["未接入", "待接入"].includes(value)) return "todo";
      return "ok";
    }

    function statusKind(row) {
      if (["已完成", "已处理", "已归档", "已关闭", "关闭"].includes(row.status)) return "done";
      if (["无需处理", "无需操作", "无需跟进", "正常"].includes(row.status)) return "monitor";
      return "human";
    }

    async function loadDashboard() {
      $("refreshText").textContent = "刷新中...";
      try {
        const res = await fetch("/api/dashboard", { cache: "no-store" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`);
        state.data = data;
        state.allRows = [...(data.priority_actions || []), ...(data.monitor_actions || [])];
        $("feishuLink").href = data.feishu_base_url;
        $("sideStatus").textContent = `${nf.format(data.kpis.source_count)} 个源，${nf.format(data.kpis.all_action_rows)} 条记录`;
        $("refreshText").textContent = `已刷新 ${new Date(data.generated_at_ms).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`;
        render();
      } catch (err) {
        $("kpis").innerHTML = `<div class="error">看板加载失败：${esc(err.message)}</div>`;
        $("refreshText").textContent = "刷新失败";
      }
    }

    function render() {
      renderKpis();
      renderNotice();
      renderModules();
      renderPriority();
      renderJudgement();
      renderHealth();
      renderOwners();
      renderFilters();
      renderDetails();
      bindFilters();
    }

    function renderKpis() {
      const k = state.data.kpis;
      const cards = [
        ["待人工处理", k.human_open, "需要负责人今天处理的事项", k.human_open ? "danger" : "ok"],
        ["P0 / P1", `${k.p0} / ${k.p1}`, "P0 会阻断；P1 当日必看", k.p0 ? "danger" : k.p1 ? "warn" : "ok"],
        ["数据源异常", k.abnormal_sources, "错误、过期、未接入、临期", k.abnormal_sources ? "warn" : "ok"],
        ["监控项总数", k.monitored_total, "系统仍在盯的对象，不等于都要处理", ""],
        ["负责人", k.owner_count, "当前看板涉及的处理人", ""],
        ["数据源", k.source_count, "A31 / Rank / 万词 / 搜索词等", ""],
      ];
      $("kpis").innerHTML = cards.map(([label, value, hint, cls]) => `
        <article class="card kpi ${cls}">
          <div class="label">${esc(label)}</div>
          <div class="value">${esc(value)}</div>
          <div class="delta">${esc(hint)}</div>
        </article>
      `).join("");
    }

    function renderNotice() {
      const k = state.data.kpis;
      const text = k.abnormal_sources
        ? `当前有 ${k.abnormal_sources} 个数据源异常。先修数据源，否则运营看板会漏项或误报。`
        : k.human_open
          ? `当前有 ${k.human_open} 个待人工处理事项。先看 P0/P1，再看负责人负载。`
          : "当前没有待人工处理事项；看板主要用于监控数据源和异常是否重新出现。";
      $("notice").innerHTML = `<div class="notice"><strong>看板判断：</strong><span>${esc(text)}</span><a class="button secondary" href="#health">查看数据源</a></div>`;
    }

    function renderModules() {
      $("moduleGrid").innerHTML = state.data.modules.map((m) => {
        const cls = healthClass(m.health);
        return `
          <article class="card module ${cls}">
            <div class="module-title">
              <div>
                <strong>${esc(m.title)}</strong>
                <div class="hint">${esc(m.subtitle)}</div>
              </div>
              ${tag(m.health_text, cls)}
            </div>
            <div class="hint">来源：${esc(m.sources.join(" / "))}</div>
            <div class="module-meta">
              <div class="mini"><span>待人工</span><strong>${nf.format(m.human_open)}</strong></div>
              <div class="mini"><span>P0/P1</span><strong>${nf.format(m.p0)}/${nf.format(m.p1)}</strong></div>
              <div class="mini"><span>监控项</span><strong>${nf.format(m.monitor_total)}</strong></div>
            </div>
          </article>
        `;
      }).join("");
    }

    function actionTitle(a) {
      const parts = [a.source, a.site, a.product || a.asin, a.keyword, a.metric].filter(Boolean);
      return parts.join(" · ") || a.key;
    }

    function renderActionList(rows, emptyText) {
      if (!rows.length) return `<div class="empty">${esc(emptyText)}</div>`;
      return rows.map((a) => `
        <div class="queue-item">
          <div class="queue-head">
            <strong>${esc(actionTitle(a))}</strong>
            <span>${tag(a.severity)} ${tag(a.status, statusKind(a) === "monitor" ? "ok" : "")}</span>
          </div>
          <div class="queue-body">
            负责人：${esc(a.owner || "未分配")}　当前值：${esc(a.current_value || "无")}<br />
            建议动作：${esc(a.suggested_action || "回源表确认")}
          </div>
          <div class="queue-foot">
            ${a.source_url ? `<a href="${esc(a.source_url)}" target="_blank" rel="noreferrer">打开源记录</a>` : ""}
            ${a.asin ? `<span class="tag">${esc(a.asin)}</span>` : ""}
            ${a.keyword ? `<span class="tag">${esc(a.keyword)}</span>` : ""}
          </div>
        </div>
      `).join("");
    }

    function renderPriority() {
      $("priorityList").innerHTML = renderActionList(state.data.priority_actions.slice(0, 12), "当前没有需要人工处理的事项。");
    }

    function renderJudgement() {
      const rows = state.data.modules
        .filter((m) => m.human_open || !["正常"].includes(m.health))
        .map((m) => ({
          severity: m.p0 ? "P0" : m.p1 ? "P1" : m.health === "正常" ? "P2" : "P1",
          status: m.health_text,
          source: m.title,
          owner: m.owner_hint,
          current_value: `${m.human_open} 个待人工，${m.monitor_total} 个监控项`,
          suggested_action: m.human_open ? "先处理该模块 P0/P1，再回源表关闭状态。" : "先处理数据源配置或更新，再判断业务待办。",
          metric: m.subtitle,
          source_url: "",
        }));
      $("moduleJudgement").innerHTML = renderActionList(rows, "所有模块当前都没有明显阻断。");
    }

    function renderHealth() {
      $("healthRows").innerHTML = state.data.health.map((h) => `
        <div class="health-row">
          <strong>${esc(h.source)}</strong>
          ${tag(h.freshness, healthClass(h.freshness))}
          <span>${h.age_days ? `${nf.format(h.age_days)} 天` : "无"}</span>
          <span>${esc(h.error || h.suggested_action || "正常")}<br /><span class="hint">最近数据：${esc(h.latest_at || "无")}；记录数：${nf.format(h.record_count || 0)}</span></span>
        </div>
      `).join("");
    }

    function renderOwners() {
      const max = Math.max(1, ...state.data.owners.map((x) => x.monitor_total));
      $("ownerRows").innerHTML = state.data.owners.slice(0, 12).map((o) => `
        <div class="bar-row">
          <strong>${esc(o.owner)}</strong>
          <div class="track"><span class="fill" style="width:${Math.max(3, o.monitor_total / max * 100)}%"></span></div>
          <span>${nf.format(o.human_open)} 待 / ${nf.format(o.monitor_total)} 盯</span>
        </div>
      `).join("");
    }

    function renderFilters() {
      const sources = [...new Set(state.allRows.map((x) => x.source).filter(Boolean))].sort();
      $("sourceFilter").innerHTML = `<option value="">全部来源</option>` + sources.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
    }

    function bindFilters() {
      ["searchInput", "sourceFilter", "severityFilter", "humanFilter"].forEach((id) => {
        const el = $(id);
        if (el && !el.dataset.bound) {
          el.addEventListener("input", renderDetails);
          el.addEventListener("change", renderDetails);
          el.dataset.bound = "1";
        }
      });
    }

    function renderDetails() {
      const q = $("searchInput")?.value?.trim().toLowerCase() || "";
      const source = $("sourceFilter")?.value || "";
      const severity = $("severityFilter")?.value || "";
      const kind = $("humanFilter")?.value || "";
      const rows = state.allRows.filter((a) => {
        const hay = [a.owner, a.source, a.site, a.asin, a.product, a.keyword, a.metric, a.current_value, a.suggested_action].join(" ").toLowerCase();
        if (q && !hay.includes(q)) return false;
        if (source && a.source !== source) return false;
        if (severity && a.severity !== severity) return false;
        if (kind && statusKind(a) !== kind) return false;
        return true;
      }).slice(0, 200);
      if (!rows.length) {
        $("detailTable").innerHTML = `<div class="empty">没有匹配的明细。</div>`;
        return;
      }
      $("detailTable").innerHTML = `
        <table>
          <thead>
            <tr>
              <th>等级</th><th>状态</th><th>来源</th><th>负责人</th><th>站点</th><th>ASIN / 产品</th><th>关键词</th><th>指标</th><th>当前值</th><th>建议动作</th><th>源记录</th>
            </tr>
          </thead>
          <tbody>
            ${rows.map((a) => `
              <tr>
                <td>${tag(a.severity)}</td>
                <td>${tag(a.status, statusKind(a) === "monitor" ? "ok" : "")}</td>
                <td>${esc(a.source)}</td>
                <td>${esc(a.owner)}</td>
                <td>${esc(a.site)}</td>
                <td>${esc([a.asin, a.product].filter(Boolean).join(" / "))}</td>
                <td>${esc(a.keyword)}</td>
                <td>${esc(a.metric)}</td>
                <td>${esc(a.current_value)}</td>
                <td>${esc(a.suggested_action)}</td>
                <td>${a.source_url ? `<a href="${esc(a.source_url)}" target="_blank" rel="noreferrer">打开</a>` : ""}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      `;
    }

    document.querySelectorAll("nav a").forEach((link) => {
      link.addEventListener("click", () => {
        document.querySelectorAll("nav a").forEach((x) => x.classList.remove("active"));
        link.classList.add("active");
      });
    });

    loadDashboard();
  </script>
</body>
</html>"""
