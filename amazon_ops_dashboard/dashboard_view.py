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
        "subtitle": "A31 告警、上架质量和基础异常",
        "sources": ["A31"],
        "owner_hint": "运营负责人",
    },
    {
        "key": "wanci",
        "title": "万词计划",
        "subtitle": "埋词、收录、首页、广告承接、Rank 追踪",
        "sources": ["万词作战台"],
        "owner_hint": "项目运营",
        "href": "/wanci",
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


def build_wanci_payload(cfg: Config, lark: LarkClient) -> dict[str, Any]:
    registry_records = [
        normalize_wanci_registry(rec, cfg)
        for rec in lark.list_records(cfg.wanci_registry.app_token, cfg.wanci_registry.table_id, cfg.max_records_per_source)
    ]
    registry_records = [x for x in registry_records if x["group_key"]]
    snapshot_records = [
        normalize_wanci_record(rec, cfg)
        for rec in lark.list_records(cfg.wanci_weekly.app_token, cfg.wanci_weekly.table_id, cfg.max_records_per_source)
    ]
    snapshot_records = [x for x in snapshot_records if x["group_key"]]
    action_records = [
        normalize_action_record(rec)
        for rec in lark.list_records(cfg.dashboard_base_token, cfg.action_table_id, 10000)
    ]
    wanci_actions = [x for x in action_records if x["source"] == "万词作战台"]
    actions_by_record: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for action in wanci_actions:
        if action["source_record_id"]:
            actions_by_record[action["source_record_id"]].append(action)

    snapshots_by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in snapshot_records:
        snapshots_by_group[item["group_key"]].append(item)

    plans = []
    registry_by_group = {item["group_key"]: item for item in registry_records}
    plan_groups = sorted(set(registry_by_group) | set(snapshots_by_group))
    for group_key in plan_groups:
        current = registry_by_group.get(group_key)
        history = sorted(snapshots_by_group.get(group_key, []), key=lambda x: x["snapshot_ms"], reverse=True)
        latest_snapshot = history[0] if history else None
        latest = merge_wanci_current(current, latest_snapshot, cfg)
        latest["snapshot_record_ids"] = [x["snapshot_record_id"] for x in history if x["snapshot_record_id"]]
        related = []
        for rid in latest["snapshot_record_ids"]:
            related.extend(actions_by_record.get(rid, []))
        if not related:
            related = [
                action for action in wanci_actions
                if action["asin"] == latest["asin"]
                and action["site"] == latest["site"]
                and action["owner"] == latest["owner"]
            ]
        related = dedupe_actions(related)
        open_actions = [x for x in related if needs_human(x)]
        completed_actions = [x for x in related if is_done(x) or x["status"] in NO_ACTION_STATUSES]
        flags = wanci_issue_flags(latest)
        issue_count = max(len(flags), len(related))
        if not flags and not open_actions:
            progress = 100
            stage = "观察中"
        elif open_actions:
            done = len(completed_actions)
            total = max(issue_count, done + len(open_actions), 1)
            progress = max(15, min(95, int(done / total * 100)))
            stage = "待处理"
        else:
            progress = 85
            stage = "待确认"
        plans.append({
            **latest,
            "stage": stage,
            "progress": progress,
            "issues": flags,
            "open_actions": sort_actions(open_actions),
            "completed_actions": completed_actions,
            "todo_open": len(open_actions),
            "todo_done": len(completed_actions),
            "todo_total": len(related),
            "history": history[:8],
        })

    plans = sorted(plans, key=lambda x: (
        0 if x["stage"] == "待处理" else 1 if x["stage"] == "待确认" else 2,
        -(x["todo_open"] * 100 + len(x["issues"]) * 10),
        x["owner"],
        x["site"],
        x["asin"],
    ))
    owner_rows = build_wanci_owner_rows(plans)
    return {
        "generated_at_ms": now_ms(),
        "feishu_base_url": f"https://u1wpma3xuhr.feishu.cn/base/{cfg.dashboard_base_token}",
        "source_url": f"https://u1wpma3xuhr.feishu.cn/base/{cfg.wanci_registry.app_token}?table={cfg.wanci_registry.table_id}",
        "snapshot_source_url": f"https://u1wpma3xuhr.feishu.cn/base/{cfg.wanci_weekly.app_token}?table={cfg.wanci_weekly.table_id}",
        "summary": {
            "plans": len(plans),
            "active_plans": sum(1 for x in plans if x["registry_status"] == "在跑"),
            "prep_plans": sum(1 for x in plans if x["registry_status"] == "筹备"),
            "todo_open": sum(x["todo_open"] for x in plans),
            "todo_done": sum(x["todo_done"] for x in plans),
            "listing_abnormal": sum(1 for x in plans if x["daily_update"] == "会每天更新" and x["listing_status"] not in ("", "正常")),
            "budget_exhausted": sum(1 for x in plans if x["daily_update"] == "会每天更新" and x["budget_exhausted"] > 0),
            "no_rank_tracking": sum(1 for x in plans if x["rank_tracking"] == "否"),
            "stale_snapshots": sum(1 for x in plans if x["snapshot_ms"] and x["age_days"] > 10 and x["daily_update"] == "会每天更新"),
            "missing_snapshots": sum(1 for x in plans if not x["snapshot_ms"] and x["daily_update"] == "会每天更新"),
        },
        "owners": owner_rows,
        "plans": plans,
    }


def normalize_wanci_record(rec: dict[str, Any], cfg: Config) -> dict[str, Any]:
    f = rec.get("fields") or {}
    record_id = rec.get("record_id", "")
    snapshot_ms = parse_time_value(f.get("快照时间"))
    site = text_value(f.get("站点")) or text_value(f.get("区域"))
    asin = text_value(f.get("ASIN"))
    product = text_value(f.get("产品"))
    owner = text_value(f.get("负责运营")) or "未分配"
    group_key = wanci_group_key(site, asin, product, owner) or record_id
    include_delta = int_value(f.get("收录Δ"))
    page_delta = int_value(f.get("首页Δ"))
    budget = int_value(f.get("预算耗尽"))
    listing_status = text_value(f.get("listing状态")) or "正常"
    return {
        "record_id": record_id,
        "group_key": group_key,
        "snapshot_record_id": record_id,
        "snapshot_ms": snapshot_ms,
        "snapshot": date_text(snapshot_ms),
        "age_days": age_days_from_ms(snapshot_ms),
        "owner": owner,
        "site": site,
        "asin": asin,
        "product": product,
        "failure": text_value(f.get("失职")),
        "budget_exhausted": budget,
        "rank_tracking": text_value(f.get("有rank追踪")),
        "listing_status": listing_status,
        "include_delta": include_delta,
        "page_delta": page_delta,
        "source_url": f"https://u1wpma3xuhr.feishu.cn/base/{cfg.wanci_weekly.app_token}?table={cfg.wanci_weekly.table_id}&record={record_id}",
    }


def normalize_wanci_registry(rec: dict[str, Any], cfg: Config) -> dict[str, Any]:
    f = rec.get("fields") or {}
    record_id = rec.get("record_id", "")
    site = text_value(f.get("站点"))
    asin = text_value(f.get("ASIN"))
    product = text_value(f.get("产品"))
    owner = text_value(f.get("负责运营")) or "未分配"
    rank_table_id = text_value(f.get("rank子表id"))
    registry_status = text_value(f.get("状态"))
    daily_update = text_value(f.get("是否每天更新"))
    rank_updated_ms = parse_time_value(f.get("最近排名更新时间"))
    return {
        "registry_record_id": record_id,
        "group_key": wanci_group_key(site, asin, product, owner) or record_id,
        "owner": owner,
        "site": site,
        "asin": asin,
        "product": product,
        "registry_status": registry_status,
        "daily_update": daily_update,
        "rank_table_id": rank_table_id,
        "rank_updated_ms": rank_updated_ms,
        "rank_updated_at": date_text(rank_updated_ms),
        "registry_url": f"https://u1wpma3xuhr.feishu.cn/base/{cfg.wanci_registry.app_token}?table={cfg.wanci_registry.table_id}&record={record_id}",
    }


def merge_wanci_current(current: dict[str, Any] | None, snapshot: dict[str, Any] | None, cfg: Config) -> dict[str, Any]:
    if current:
        rank_tracking = "是" if current["rank_table_id"] else "暂不追踪" if current["registry_status"] == "筹备" or current["daily_update"] == "暂时不会" else "否"
        base = {
            "record_id": current["registry_record_id"],
            "group_key": current["group_key"],
            "owner": current["owner"],
            "site": current["site"],
            "asin": current["asin"],
            "product": current["product"],
            "registry_status": current["registry_status"],
            "daily_update": current["daily_update"],
            "rank_tracking": rank_tracking,
            "rank_table_id": current["rank_table_id"],
            "rank_updated_ms": current["rank_updated_ms"],
            "rank_updated_at": current["rank_updated_at"],
            "registry_url": current["registry_url"],
            "source_url": current["registry_url"],
        }
    else:
        base = {
            "record_id": snapshot["record_id"] if snapshot else "",
            "group_key": snapshot["group_key"] if snapshot else "",
            "owner": snapshot["owner"] if snapshot else "未分配",
            "site": snapshot["site"] if snapshot else "",
            "asin": snapshot["asin"] if snapshot else "",
            "product": snapshot["product"] if snapshot else "",
            "registry_status": "未登记",
            "daily_update": "",
            "rank_tracking": snapshot["rank_tracking"] if snapshot else "",
            "rank_table_id": "",
            "rank_updated_ms": 0,
            "rank_updated_at": "",
            "registry_url": "",
            "source_url": snapshot["source_url"] if snapshot else "",
        }
    if snapshot:
        base.update({
            "snapshot_record_id": snapshot["snapshot_record_id"],
            "snapshot_record_ids": [snapshot["snapshot_record_id"]],
            "snapshot_ms": snapshot["snapshot_ms"],
            "snapshot": snapshot["snapshot"],
            "age_days": snapshot["age_days"],
            "failure": snapshot["failure"],
            "budget_exhausted": snapshot["budget_exhausted"],
            "listing_status": snapshot["listing_status"],
            "include_delta": snapshot["include_delta"],
            "page_delta": snapshot["page_delta"],
            "snapshot_url": snapshot["source_url"],
        })
    else:
        base.update({
            "snapshot_record_id": "",
            "snapshot_record_ids": [],
            "snapshot_ms": 0,
            "snapshot": "",
            "age_days": 999,
            "failure": "",
            "budget_exhausted": 0,
            "listing_status": "",
            "include_delta": 0,
            "page_delta": 0,
            "snapshot_url": f"https://u1wpma3xuhr.feishu.cn/base/{cfg.wanci_weekly.app_token}?table={cfg.wanci_weekly.table_id}",
        })
    return base


def wanci_group_key(site: str, asin: str, product: str, owner: str) -> str:
    return "|".join([site, asin]).strip("|") or "|".join([site, asin, product, owner]).strip("|")


def wanci_issue_flags(item: dict[str, Any]) -> list[str]:
    flags = []
    if item["daily_update"] and item["daily_update"] != "会每天更新":
        return flags
    if truthy_text(item["failure"]):
        flags.append("存在失职项")
    if item["budget_exhausted"] > 0:
        flags.append(f"预算耗尽 {item['budget_exhausted']} 个")
    if item["rank_tracking"] == "否":
        flags.append("未建 Rank 追踪")
    if item["listing_status"] not in ("", "正常"):
        flags.append(f"Listing 状态：{item['listing_status']}")
    if item["include_delta"] < 0:
        flags.append(f"收录下降 {item['include_delta']}")
    if item["page_delta"] < 0:
        flags.append(f"首页下降 {item['page_delta']}")
    if not item["snapshot_ms"] and item["daily_update"] == "会每天更新":
        flags.append("暂无周复审快照")
    elif item["age_days"] > 10 and item["daily_update"] == "会每天更新":
        flags.append(f"快照 {item['age_days']} 天未更新")
    return flags


def dedupe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    seen = set()
    for action in actions:
        key = action["key"] or action["record_id"]
        if key in seen:
            continue
        seen.add(key)
        out.append(action)
    return out


def build_wanci_owner_rows(plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "owner": "",
        "plans": 0,
        "todo_open": 0,
        "todo_done": 0,
        "listing_abnormal": 0,
        "avg_progress": 0,
    })
    for plan in plans:
        row = rows[plan["owner"]]
        row["owner"] = plan["owner"]
        row["plans"] += 1
        row["todo_open"] += plan["todo_open"]
        row["todo_done"] += plan["todo_done"]
        row["listing_abnormal"] += 1 if plan["listing_status"] not in ("", "正常") else 0
        row["avg_progress"] += plan["progress"]
    out = []
    for row in rows.values():
        if row["plans"]:
            row["avg_progress"] = int(row["avg_progress"] / row["plans"])
        out.append(row)
    return sorted(out, key=lambda x: (-(x["todo_open"] * 100 + x["listing_abnormal"] * 10), x["owner"]))


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
            "href": module.get("href", ""),
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


def parse_time_value(value: Any) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, (int, float)):
        n = int(value)
        return n * 1000 if n and n < 10000000000 else n
    text = normalize_cell(value).strip()
    if not text:
        return 0
    if text.isdigit():
        n = int(text)
        return n * 1000 if n and n < 10000000000 else n
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return int(datetime.strptime(text, fmt).replace(tzinfo=BJ).timestamp() * 1000)
        except ValueError:
            pass
    return 0


def age_days_from_ms(ms: int) -> int:
    if not ms:
        return 999
    return max(0, int((now_ms() - ms) / 86400000))


def truthy_text(value: Any) -> bool:
    text = normalize_cell(value).strip().lower()
    return text not in ("", "0", "false", "否", "无", "正常", "no", "none", "null")


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
    .module-link {
      color: var(--green);
      font-size: 12px;
      font-weight: 900;
      text-decoration: none;
      width: fit-content;
    }
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
        <a href="/" class="active">总览</a>
        <a href="/wanci">万词计划</a>
        <a href="#priority">今日待办</a>
        <a href="#health">数据健康</a>
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
            ${m.href ? `<a class="module-link" href="${esc(m.href)}">进入${esc(m.title)}工作台</a>` : ""}
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


WANCI_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>万词计划工作台</title>
  <style>
    :root {
      --paper: #f4f1ea;
      --surface: #fffdf7;
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
      width: 38px; height: 38px; display: grid; place-items: center;
      border: 1px solid rgba(248,243,232,.28); color: #40e0b9; font-weight: 900; font-size: 13px;
    }
    .brand strong { display: block; font-size: 14px; }
    .brand span { display: block; color: rgba(248,243,232,.62); font-size: 11px; margin-top: 3px; }
    nav { display: grid; gap: 6px; }
    nav a {
      color: rgba(248,243,232,.84); text-decoration: none; min-height: 35px;
      display: flex; align-items: center; padding: 0 10px; border-radius: 5px; font-size: 13px;
    }
    nav a:hover, nav a.active { background: #2a3028; color: #fff; }
    .source-card {
      margin-top: auto; padding: 13px; border: 1px solid rgba(248,243,232,.14);
      border-radius: 8px; background: #11150f; line-height: 1.65; font-size: 12px; color: rgba(248,243,232,.78);
    }
    .source-card strong { display: block; color: #fff; margin: 4px 0; }
    main { padding: 28px 32px 54px; min-width: 0; }
    .topbar { display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; margin-bottom: 18px; }
    .eyebrow { color: var(--green); font-weight: 900; font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }
    h1 { margin: 3px 0 8px; font-size: 42px; line-height: 1.05; font-weight: 950; }
    .subtitle { max-width: 940px; color: var(--muted); font-size: 13px; line-height: 1.75; }
    .actions { display: flex; gap: 9px; align-items: center; justify-content: flex-end; flex-wrap: wrap; color: var(--muted); font-size: 12px; }
    .button, button {
      height: 34px; border: 1px solid var(--ink); border-radius: 5px; padding: 0 12px;
      background: var(--ink); color: #fffdf7; font-weight: 800; cursor: pointer; text-decoration: none;
      display: inline-flex; align-items: center; justify-content: center; font-family: inherit; font-size: 13px;
    }
    .button.secondary, button.secondary { background: var(--surface); color: var(--ink); border-color: var(--line); }
    .kpis { display: grid; grid-template-columns: repeat(8, minmax(0, 1fr)); gap: 10px; margin-bottom: 14px; }
    .card, .panel {
      background: rgba(255,253,247,.9); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow);
    }
    .kpi { min-height: 96px; padding: 13px; position: relative; overflow: hidden; }
    .kpi::after {
      content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 3px;
      background: linear-gradient(90deg, var(--green), var(--amber), var(--violet));
    }
    .label { color: var(--muted); font-size: 12px; font-weight: 800; }
    .value { margin-top: 10px; font-size: 28px; line-height: 1; font-weight: 950; font-variant-numeric: tabular-nums; }
    .delta { margin-top: 8px; color: var(--muted); font-size: 11px; line-height: 1.5; }
    .danger .value { color: var(--red); }
    .warn .value { color: var(--amber); }
    .ok .value { color: var(--green); }
    .layout { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(420px, .85fr); gap: 12px; align-items: start; }
    .panel { padding: 14px; overflow: hidden; }
    .panel-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin-bottom: 11px; padding-bottom: 9px; border-bottom: 1px solid #ece4d6; }
    .panel h2, .panel h3 { margin: 0; font-size: 17px; }
    .hint { color: var(--muted); font-size: 12px; line-height: 1.6; }
    .filters { display: grid; grid-template-columns: 1.4fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; }
    select, input {
      width: 100%; height: 34px; border: 1px solid var(--line); border-radius: 5px;
      padding: 0 10px; background: rgba(255,253,247,.92); color: var(--ink); font-family: inherit;
    }
    .task-list { display: grid; gap: 9px; max-height: 720px; overflow: auto; padding-right: 4px; }
    .task {
      text-align: left; height: auto; color: var(--ink); background: #fffaf0; border: 1px solid #e7dccb;
      border-left: 4px solid var(--green); border-radius: 8px; padding: 12px; display: block; cursor: pointer;
    }
    .task:hover, .task.active { border-left-color: var(--amber); background: #fff6e6; }
    .task.bad { border-left-color: var(--red); }
    .task.warn { border-left-color: var(--amber); }
    .task-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 8px; }
    .task-title { font-weight: 900; font-size: 14px; overflow-wrap: anywhere; }
    .task-meta { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
    .tag {
      display: inline-flex; align-items: center; min-height: 23px; padding: 0 8px; border-radius: 999px;
      border: 1px solid var(--line); background: #f6efe2; color: #40463e; white-space: nowrap; font-size: 12px; font-weight: 800;
    }
    .tag.bad { color: var(--red); border-color: rgba(177,61,53,.34); background: rgba(177,61,53,.08); }
    .tag.warn { color: var(--amber); border-color: rgba(176,111,22,.35); background: rgba(176,111,22,.09); }
    .tag.ok { color: var(--green); border-color: rgba(22,107,82,.35); background: rgba(22,107,82,.08); }
    .progress { margin-top: 9px; height: 9px; border-radius: 999px; background: #e7dfd1; overflow: hidden; }
    .progress span { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--green), var(--blue)); min-width: 2px; }
    .detail-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-bottom: 12px; }
    .mini { padding: 9px; background: #fffaf0; border: 1px solid #eadfcd; border-radius: 7px; }
    .mini span { display: block; color: var(--muted); font-size: 11px; margin-bottom: 5px; }
    .mini strong { font-size: 20px; font-variant-numeric: tabular-nums; }
    .timeline, .todo-list, .owner-list { display: grid; gap: 8px; }
    .row {
      display: grid; grid-template-columns: 112px minmax(0, 1fr) 110px; gap: 10px;
      align-items: start; padding: 9px 0; border-bottom: 1px solid #eee5d8; font-size: 12px;
    }
    .row:last-child { border-bottom: 0; }
    .todo {
      padding: 10px; border: 1px solid #e7dccb; border-radius: 7px; background: #fffaf0; font-size: 12px; line-height: 1.65;
    }
    .todo strong { display: block; font-size: 13px; margin-bottom: 4px; }
    .todo a, .source-link { color: var(--green); font-weight: 900; text-decoration: none; }
    .owner-row { display: grid; grid-template-columns: 90px minmax(0, 1fr) 120px; gap: 10px; align-items: center; padding: 7px 0; border-bottom: 1px solid #eee5d8; font-size: 12px; }
    .track { height: 9px; background: #e7dfd1; border-radius: 999px; overflow: hidden; }
    .fill { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--green), var(--blue)); min-width: 2px; }
    .empty, .loading { color: var(--muted); padding: 20px; border: 1px dashed var(--line); border-radius: 8px; background: rgba(255,253,247,.62); }
    .error { color: var(--red); background: rgba(177,61,53,.08); border: 1px solid rgba(177,61,53,.25); border-radius: 8px; padding: 16px; }
    @media (max-width: 1360px) {
      .kpis { grid-template-columns: repeat(4, minmax(0, 1fr)); }
      .layout { grid-template-columns: 1fr; }
    }
    @media (max-width: 980px) {
      body { min-width: 0; }
      .app { grid-template-columns: 1fr; }
      .sidebar { position: relative; height: auto; }
      main { padding: 18px 14px 42px; }
      .kpis, .detail-grid { grid-template-columns: 1fr; }
      .filters { grid-template-columns: 1fr; }
      h1 { font-size: 30px; }
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
          <span>万词计划工作台</span>
        </div>
      </div>
      <nav>
        <a href="/">总览</a>
        <a href="/wanci" class="active">万词计划</a>
        <a href="#tasks">任务台</a>
        <a href="#detail">Listing变化</a>
        <a href="#owners">负责人进度</a>
      </nav>
      <div class="source-card">
        <div>数据源</div>
        <strong>万词总台 + 周快照</strong>
        <div>总台决定当前项目与 Rank 配置；周快照展示 Listing 变化。</div>
        <div id="sideStatus">正在读取数据...</div>
      </div>
    </aside>
    <main>
      <header class="topbar">
        <div>
          <div class="eyebrow">Wanci Plan Operations</div>
          <h1>万词计划工作台</h1>
          <div class="subtitle">把万词计划从首页拆出来，按 ASIN/站点/产品展示跟进进度、Listing 变化、Rank 追踪、预算耗尽和待办完成情况。当前项目以总台注册表为准，周快照只作为复审历史。</div>
        </div>
        <div class="actions">
          <span id="refreshText">未刷新</span>
          <button class="secondary" onclick="loadWanci()">刷新页面数据</button>
          <a class="button secondary" id="sourceLink" href="#">打开万词总台</a>
        </div>
      </header>
      <section id="kpis" class="kpis"><div class="loading">正在加载万词计划...</div></section>
      <section class="layout" id="tasks">
        <div class="panel">
          <div class="panel-head">
            <h2>万词任务台</h2>
            <span class="hint">点击任一任务，右侧展示 Listing 变化和待办进度。</span>
          </div>
          <div class="filters">
            <input id="searchInput" placeholder="搜索负责人 / ASIN / 产品 / 站点" />
            <select id="ownerFilter"></select>
            <select id="stageFilter">
              <option value="">全部阶段</option>
              <option value="待处理">待处理</option>
              <option value="待确认">待确认</option>
              <option value="观察中">观察中</option>
            </select>
            <select id="issueFilter">
              <option value="">全部问题</option>
              <option value="listing">Listing异常</option>
              <option value="rank">未建Rank追踪</option>
              <option value="budget">预算耗尽</option>
              <option value="stale">快照过期</option>
            </select>
          </div>
          <div id="taskList" class="task-list"></div>
        </div>
        <div class="panel" id="detail">
          <div class="panel-head">
            <h2>Listing 变化与待办</h2>
            <span class="hint">默认展示最需要处理的一条。</span>
          </div>
          <div id="detailPane" class="empty">请选择左侧任务。</div>
        </div>
      </section>
      <section class="panel" id="owners" style="margin-top:12px;">
        <div class="panel-head">
          <h2>负责人进度</h2>
          <span class="hint">按未完成待办和 Listing 异常排序。</span>
        </div>
        <div id="ownerRows" class="owner-list"></div>
      </section>
    </main>
  </div>

  <script>
    const state = { data: null, selected: null };
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

    function tag(value, cls = "") {
      return `<span class="tag ${cls}">${esc(value || "无")}</span>`;
    }

    function issueClass(plan) {
      if (plan.stage === "待处理") return "bad";
      if (plan.stage === "待确认") return "warn";
      return "";
    }

    async function loadWanci() {
      $("refreshText").textContent = "刷新中...";
      try {
        const res = await fetch("/api/wanci", { cache: "no-store" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`);
        state.data = data;
        state.selected = data.plans[0]?.group_key || null;
        $("sourceLink").href = data.source_url;
        $("sideStatus").textContent = `${nf.format(data.summary.plans)} 个计划，${nf.format(data.summary.todo_open)} 个待办`;
        $("refreshText").textContent = `已刷新 ${new Date(data.generated_at_ms).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`;
        render();
      } catch (err) {
        $("kpis").innerHTML = `<div class="error">万词计划加载失败：${esc(err.message)}</div>`;
        $("refreshText").textContent = "刷新失败";
      }
    }

    function render() {
      renderKpis();
      renderFilters();
      renderTasks();
      renderDetail();
      renderOwners();
      bindFilters();
    }

    function renderKpis() {
      const s = state.data.summary;
      const cards = [
        ["计划数", s.plans, `在跑 ${s.active_plans} / 筹备 ${s.prep_plans}`, ""],
        ["未完成待办", s.todo_open, "需要运营继续处理", s.todo_open ? "danger" : "ok"],
        ["已完成/关闭", s.todo_done, "来自待办状态", "ok"],
        ["Listing异常", s.listing_abnormal, "listing状态非正常", s.listing_abnormal ? "warn" : "ok"],
        ["预算耗尽", s.budget_exhausted, "需要广告预算判断", s.budget_exhausted ? "warn" : ""],
        ["未建Rank追踪", s.no_rank_tracking, "按总台 rank子表id 判断", s.no_rank_tracking ? "warn" : "ok"],
        ["快照过期", s.stale_snapshots, "已有快照但超过 10 天", s.stale_snapshots ? "warn" : "ok"],
        ["无周快照", s.missing_snapshots, "总台在跑但未进入复审表", s.missing_snapshots ? "danger" : "ok"],
      ];
      $("kpis").innerHTML = cards.map(([label, value, hint, cls]) => `
        <article class="card kpi ${cls}">
          <div class="label">${esc(label)}</div>
          <div class="value">${esc(value)}</div>
          <div class="delta">${esc(hint)}</div>
        </article>
      `).join("");
    }

    function renderFilters() {
      const owners = [...new Set(state.data.plans.map((x) => x.owner).filter(Boolean))].sort();
      const current = $("ownerFilter").value || "";
      $("ownerFilter").innerHTML = `<option value="">全部负责人</option>` + owners.map((x) => `<option value="${esc(x)}">${esc(x)}</option>`).join("");
      $("ownerFilter").value = current;
    }

    function filteredPlans() {
      const q = $("searchInput")?.value?.trim().toLowerCase() || "";
      const owner = $("ownerFilter")?.value || "";
      const stage = $("stageFilter")?.value || "";
      const issue = $("issueFilter")?.value || "";
      return state.data.plans.filter((p) => {
        const hay = [p.owner, p.site, p.asin, p.product, p.stage, p.issues.join(" ")].join(" ").toLowerCase();
        if (q && !hay.includes(q)) return false;
        if (owner && p.owner !== owner) return false;
        if (stage && p.stage !== stage) return false;
        if (issue === "listing" && ["", "正常"].includes(p.listing_status)) return false;
        if (issue === "rank" && p.rank_tracking !== "否") return false;
        if (issue === "budget" && !p.budget_exhausted) return false;
        if (issue === "stale" && p.age_days <= 10) return false;
        return true;
      });
    }

    function renderTasks() {
      const rows = filteredPlans();
      if (!rows.length) {
        $("taskList").innerHTML = `<div class="empty">没有匹配的万词计划。</div>`;
        return;
      }
      if (!rows.some((x) => x.group_key === state.selected)) state.selected = rows[0].group_key;
      $("taskList").innerHTML = rows.map((p) => `
        <button type="button" class="task ${issueClass(p)} ${p.group_key === state.selected ? "active" : ""}" data-key="${esc(p.group_key)}">
          <div class="task-head">
            <div>
              <div class="task-title">${esc(p.product || p.asin || "未命名计划")}</div>
              <div class="hint">${esc(p.site || "无站点")} · ${esc(p.asin || "无ASIN")} · ${esc(p.owner)}</div>
            </div>
            ${tag(p.stage, p.stage === "待处理" ? "bad" : p.stage === "待确认" ? "warn" : "ok")}
          </div>
          <div class="progress"><span style="width:${Math.max(3, p.progress)}%"></span></div>
          <div class="task-meta">
            ${tag(p.registry_status || "未登记", p.registry_status === "在跑" ? "ok" : "warn")}
            ${tag(`进度 ${p.progress}%`)}
            ${tag(`待办 ${p.todo_done}/${p.todo_total}`)}
            ${tag(`Listing ${p.listing_status || "正常"}`, p.listing_status && p.listing_status !== "正常" ? "warn" : "ok")}
            ${p.rank_tracking === "否" ? tag("未建Rank", "warn") : ""}
          </div>
        </button>
      `).join("");
      document.querySelectorAll(".task").forEach((node) => {
        node.addEventListener("click", () => {
          state.selected = node.dataset.key;
          renderTasks();
          renderDetail();
        });
      });
    }

    function selectedPlan() {
      return state.data.plans.find((x) => x.group_key === state.selected) || state.data.plans[0];
    }

    function renderDetail() {
      const p = selectedPlan();
      if (!p) {
        $("detailPane").innerHTML = `<div class="empty">暂无万词计划。</div>`;
        return;
      }
      $("detailPane").innerHTML = `
        <div class="detail-grid">
          <div class="mini"><span>阶段</span><strong>${esc(p.stage)}</strong></div>
          <div class="mini"><span>跟进进度</span><strong>${esc(p.progress)}%</strong></div>
          <div class="mini"><span>待办完成</span><strong>${esc(p.todo_done)}/${esc(p.todo_total)}</strong></div>
          <div class="mini"><span>收录变化</span><strong>${esc(p.include_delta)}</strong></div>
          <div class="mini"><span>首页变化</span><strong>${esc(p.page_delta)}</strong></div>
          <div class="mini"><span>快照距今</span><strong>${esc(p.age_days)}天</strong></div>
        </div>
        <div class="todo-list">
          <div class="todo">
            <strong>${esc(p.product || p.asin)}</strong>
            站点：${esc(p.site || "无")}　ASIN：${esc(p.asin || "无")}　负责人：${esc(p.owner)}<br />
            总台状态：${esc(p.registry_status || "未登记")}　更新策略：${esc(p.daily_update || "无")}<br />
            Listing状态：${esc(p.listing_status || "正常")}　Rank追踪：${esc(p.rank_tracking || "无")}　Rank最近更新：${esc(p.rank_updated_at || "无")}　预算耗尽：${esc(p.budget_exhausted)}
            <br /><a class="source-link" href="${esc(p.registry_url || p.source_url)}" target="_blank" rel="noreferrer">打开万词总台记录</a>
            ${p.snapshot_url ? ` · <a class="source-link" href="${esc(p.snapshot_url)}" target="_blank" rel="noreferrer">打开周快照记录</a>` : ""}
          </div>
          ${p.issues.length ? `<div class="todo"><strong>当前问题</strong>${p.issues.map((x) => `<div>${esc(x)}</div>`).join("")}</div>` : `<div class="todo"><strong>当前问题</strong>没有明显异常，保持观察。</div>`}
          ${renderTodos(p)}
        </div>
        <h3 style="margin:16px 0 8px;">Listing 快照变化</h3>
        <div class="timeline">
          ${p.history.map((h) => `
            <div class="row">
              <strong>${esc(h.snapshot || "无日期")}</strong>
              <span>Listing：${esc(h.listing_status || "正常")} · 快照Rank：${esc(h.rank_tracking || "无")} · 预算耗尽：${esc(h.budget_exhausted)}</span>
              <span>收录Δ ${esc(h.include_delta)} / 首页Δ ${esc(h.page_delta)}</span>
            </div>
          `).join("")}
        </div>
      `;
    }

    function renderTodos(p) {
      const rows = [...p.open_actions, ...p.completed_actions].slice(0, 12);
      if (!rows.length) return `<div class="todo"><strong>待办记录</strong>当前没有匹配到聚合待办，按源表快照判断进度。</div>`;
      return `<div class="todo"><strong>待办记录</strong>${rows.map((a) => `
        <div style="margin-top:8px;">
          ${tag(a.severity, a.severity === "P0" ? "bad" : a.severity === "P1" ? "warn" : "")}
          ${tag(a.status, ["无需处理","已处理","已完成"].includes(a.status) ? "ok" : "")}
          ${esc(a.metric)}：${esc(a.current_value || "无")}
          ${a.source_url ? ` · <a href="${esc(a.source_url)}" target="_blank" rel="noreferrer">源记录</a>` : ""}
        </div>
      `).join("")}</div>`;
    }

    function renderOwners() {
      const max = Math.max(1, ...state.data.owners.map((x) => x.plans));
      $("ownerRows").innerHTML = state.data.owners.map((o) => `
        <div class="owner-row">
          <strong>${esc(o.owner)}</strong>
          <div class="track"><span class="fill" style="width:${Math.max(3, o.plans / max * 100)}%"></span></div>
          <span>${nf.format(o.plans)} 计划 · ${nf.format(o.todo_open)} 待办 · ${nf.format(o.avg_progress)}%</span>
        </div>
      `).join("");
    }

    function bindFilters() {
      ["searchInput", "ownerFilter", "stageFilter", "issueFilter"].forEach((id) => {
        const el = $(id);
        if (el && !el.dataset.bound) {
          el.addEventListener("input", () => { renderTasks(); renderDetail(); });
          el.addEventListener("change", () => { renderTasks(); renderDetail(); });
          el.dataset.bound = "1";
        }
      });
    }

    loadWanci();
  </script>
</body>
</html>"""
