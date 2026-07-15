import json
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import Config, SourceTable
from .lark_client import LarkClient, normalize_cell
from .models import ActionItem, HealthRow, RunResult, SummaryRow


BJ = timezone(timedelta(hours=8))


def now_ms() -> int:
    return int(time.time() * 1000)


def date_start_ms(ts_ms: int | None = None) -> int:
    dt = datetime.fromtimestamp((ts_ms or now_ms()) / 1000, tz=BJ)
    return int(datetime(dt.year, dt.month, dt.day, tzinfo=BJ).timestamp() * 1000)


def age_days(latest_ms: int | None, ref_ms: int | None = None) -> int | None:
    if not latest_ms:
        return None
    return max(0, int(((ref_ms or now_ms()) - latest_ms) / 86400000))


def age_or_unknown(latest_ms: int | None) -> int:
    age = age_days(latest_ms)
    return 999 if age is None else age


def parse_ms(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        n = int(value)
        if n < 10000000000:
            n *= 1000
        return n
    text = normalize_cell(value).strip()
    if not text:
        return None
    if text.isdigit():
        n = int(text)
        if n < 10000000000:
            n *= 1000
        return n
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return int(datetime.strptime(text, fmt).replace(tzinfo=BJ).timestamp() * 1000)
        except ValueError:
            pass
    return None


def num(value: Any, default: float = 0) -> float:
    text = normalize_cell(value).replace(",", "").replace("%", "").strip()
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def truthy_zh(value: Any) -> bool:
    text = normalize_cell(value).strip().lower()
    return text not in ("", "0", "false", "否", "无", "正常", "no", "none", "null")


def owner_name(value: Any) -> str:
    text = normalize_cell(value).strip()
    text = "".join(text.split())
    if not text:
        return "未分配"
    known = ("黄奕纯", "余培霓", "陈翔宇", "林明坚", "潘志聪")
    for name in known:
        if name in text:
            return name if text == name else "/".join([n for n in known if n in text])
    if "翔" in text or "翔宇" in text or "陈翔" in text:
        return "陈翔宇"
    return text


def base_record_url(app_token: str, table_id: str, record_id: str) -> str:
    return f"https://u1wpma3xuhr.feishu.cn/base/{app_token}?table={table_id}&record={record_id}"


class Aggregator:
    def __init__(self, cfg: Config, lark: LarkClient) -> None:
        self.cfg = cfg
        self.lark = lark
        self.today_ms = date_start_ms()
        self.updated_ms = now_ms()

    def run(self, mode: str = "dry_run") -> RunResult:
        if mode not in ("dry_run", "commit"):
            raise ValueError("mode must be dry_run or commit")

        actions: list[ActionItem] = []
        health: list[HealthRow] = []

        for collector in (self.collect_a31, self.collect_rank, self.collect_search_term, self.collect_impression, self.collect_wanci, self.collect_review_audit):
            try:
                src_actions, src_health = collector()
                actions.extend(src_actions)
                health.extend(src_health)
            except Exception as exc:
                source = {
                    "collect_a31": "A31",
                    "collect_rank": "Rank",
                    "collect_search_term": "搜索词v2",
                    "collect_impression": "展示份额",
                    "collect_wanci": "万词作战台",
                    "collect_review_audit": "差评审计",
                }.get(collector.__name__, collector.__name__.replace("collect_", ""))
                health.append(self.health(source, "错误", None, 0, str(exc), "检查源表权限、字段名或服务配置"))

        summary = self.build_summary(actions)
        result = RunResult(mode=mode, summary_rows=summary, action_items=actions, health_rows=health)

        if mode == "commit":
            result.write_result = self.write(result)
        return result

    def health(self, source: str, freshness: str, latest_ms: int | None, count: int, error: str = "", suggested_action: str = "") -> HealthRow:
        return HealthRow(
            key=source,
            dashboard_date_ms=self.today_ms,
            source=source,
            freshness=freshness,
            latest_at_ms=latest_ms,
            age_days=age_days(latest_ms),
            record_count=count,
            error=error[:900],
            suggested_action=suggested_action[:900],
            updated_at_ms=self.updated_ms,
        )

    def collect_a31(self) -> tuple[list[ActionItem], list[HealthRow]]:
        table = self.cfg.a31_alerts
        records = self.lark.list_records(table.app_token, table.table_id, self.cfg.max_records_per_source)
        actions: list[ActionItem] = []
        latest = None
        for rec in records:
            f = rec.get("fields") or {}
            latest = max(latest or 0, parse_ms(f.get("date")) or 0) or latest
            validity = normalize_cell(f.get("alert_validity"))
            status = normalize_cell(f.get("status"))
            if validity not in ("有效告警", "待校验"):
                continue
            if status not in ("待处理", "处理中"):
                continue
            level = normalize_cell(f.get("alert_level"))
            severity = "P0" if level in ("Critical", "红", "P0") else "P1" if level in ("Warning", "橙", "P1") else "P2"
            rid = rec.get("record_id", "")
            metric = normalize_cell(f.get("monitor_point")) or normalize_cell(f.get("alert_type"))
            actions.append(ActionItem(
                key=f"A31:{validity}:{rid}",
                dashboard_date_ms=self.today_ms,
                source="A31",
                owner=owner_name(f.get("owner")),
                severity=severity,
                status="待处理",
                site=normalize_cell(f.get("country")),
                asin=normalize_cell(f.get("asin")),
                metric=f"{validity}/{metric}" if metric else validity,
                current_value=normalize_cell(f.get("delta_value")) or normalize_cell(f.get("alert_reason")),
                suggested_action=normalize_cell(f.get("suggested_action")) or "回到 A31 告警日志确认并处理",
                source_url=base_record_url(table.app_token, table.table_id, rid),
                source_record_id=rid,
                review_date_ms=parse_ms(f.get("复查日期")),
                updated_at_ms=self.updated_ms,
            ))
        freshness = "正常" if (age_days(latest) or 0) <= 2 else "过期"
        return actions, [self.health("A31", freshness, latest, len(actions), suggested_action="" if actions else "无有效待处理告警")]

    def collect_rank(self) -> tuple[list[ActionItem], list[HealthRow]]:
        site_enabled = self._rank_enabled_sites()
        actions: list[ActionItem] = []
        latest_all = None
        checked_tables = 0
        for country, table_id in self.cfg.rank_country_tables.items():
            if site_enabled and site_enabled.get(country) is False:
                continue
            records = self.lark.list_records(self.cfg.rank_base_token, table_id, self.cfg.max_records_per_source)
            checked_tables += 1
            for rec in records:
                f = rec.get("fields") or {}
                status = normalize_cell(f.get("执行状态"))
                if status == "已停用":
                    continue
                snapshot_ms = parse_ms(f.get("本次快照时间"))
                latest_all = max(latest_all or 0, snapshot_ms or 0) or latest_all
                owner = owner_name(f.get("负责人"))
                asin = normalize_cell(f.get("ASIN"))
                keyword = normalize_cell(f.get("关键词"))
                rid = rec.get("record_id", "")
                base = {
                    "dashboard_date_ms": self.today_ms,
                    "source": "Rank",
                    "owner": owner,
                    "site": country,
                    "asin": asin,
                    "keyword": keyword,
                    "source_url": base_record_url(self.cfg.rank_base_token, table_id, rid),
                    "source_record_id": rid,
                    "updated_at_ms": self.updated_ms,
                }
                if status in ("失败", "待查询"):
                    actions.append(ActionItem(key=f"Rank:{country}:{rid}:status", severity="P1" if status == "失败" else "P2", status="待处理", metric="任务状态", current_value=status, suggested_action="检查排名追踪任务失败/待查询原因，必要时补跑", **base))
                if snapshot_ms and (age_days(snapshot_ms) or 0) > 3:
                    actions.append(ActionItem(key=f"Rank:{country}:{rid}:stale", severity="P2", status="待处理", metric="快照过期", current_value=f"{age_days(snapshot_ms)}天未更新", suggested_action="确认该站点排名追踪是否正常跑完", **base))
                natural = normalize_cell(f.get("自然排名"))
                ads = normalize_cell(f.get("广告排名"))
                change = normalize_cell(f.get("自然变化"))
                if natural in ("", "无", "未上榜", "未收录"):
                    actions.append(ActionItem(key=f"Rank:{country}:{rid}:missing", severity="P1", status="待处理", metric="自然排名", current_value=natural or "空", suggested_action="检查 Listing 收录和关键词相关性；必要时补埋词/调整广告承接", **base))
                if natural in ("", "无", "未上榜", "未收录") and ads not in ("", "无", "未上榜"):
                    actions.append(ActionItem(key=f"Rank:{country}:{rid}:ads_only", severity="P1", status="待处理", metric="仅广告在榜", current_value=f"广告={ads}", suggested_action="广告能打出但自然未收录，优先检查 Listing 关键词承接", **base))
                drop = self._rank_drop(change)
                if drop >= 3:
                    actions.append(ActionItem(key=f"Rank:{country}:{rid}:drop", severity="P1" if drop >= 5 else "P2", status="待处理", metric="自然排名下降", current_value=change, suggested_action="对照最近 Listing/广告/竞品变化，确认是否需要补预算或优化 Listing", **base))
        fresh = "正常" if latest_all and age_or_unknown(latest_all) <= 2 else "过期"
        return actions, [self.health("Rank", fresh, latest_all, checked_tables, suggested_action="JP 若在站点配置停用，不纳入过期告警")]

    def _rank_enabled_sites(self) -> dict[str, bool]:
        try:
            records = self.lark.list_records(self.cfg.rank_base_token, self.cfg.rank_site_config_table_id, 500)
        except Exception:
            return {}
        out: dict[str, bool] = {}
        for rec in records:
            f = rec.get("fields") or {}
            country = normalize_cell(f.get("国家代码")) or normalize_cell(f.get("国家")) or normalize_cell(f.get("站点"))
            enabled_val = f.get("是否启用")
            enabled = bool(enabled_val) if isinstance(enabled_val, bool) else normalize_cell(enabled_val) not in ("", "否", "false", "False", "0")
            if country:
                out[country.upper()] = enabled
        return out

    def _rank_drop(self, text: str) -> int:
        if "↓" not in text and "-" not in text:
            return 0
        digits = "".join(ch for ch in text if ch.isdigit())
        return int(digits) if digits else 0

    def collect_search_term(self) -> tuple[list[ActionItem], list[HealthRow]]:
        if not self.cfg.search_term_summary_url:
            return [], [self.health("搜索词v2", "错误", None, 0, "未配置 SEARCH_TERM_SUMMARY_URL", "配置现有搜索词 v2 服务的 dashboard summary endpoint")]
        headers = {"Content-Type": "application/json"}
        if self.cfg.search_term_api_token:
            headers["Authorization"] = f"Bearer {self.cfg.search_term_api_token}"
        req = urllib.request.Request(self.cfg.search_term_summary_url, headers=headers, method="GET")
        data = json.loads(urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=120).read().decode("utf-8"))
        rows = data.get("actions") or data.get("items") or []
        latest = parse_ms(data.get("latest_at") or data.get("updated_at"))
        actions = []
        for idx, row in enumerate(rows):
            action_type = normalize_cell(row.get("type") or row.get("action") or row.get("category"))
            if action_type in ("observe", "monitor"):
                continue
            severity = normalize_cell(row.get("severity")) or ("P1" if action_type in ("negate", "pending_human") else "P2")
            key = normalize_cell(row.get("key")) or f"SearchTerm:{idx}:{normalize_cell(row.get('asin'))}:{normalize_cell(row.get('keyword'))}:{action_type}"
            actions.append(ActionItem(
                key=key,
                dashboard_date_ms=self.today_ms,
                source="搜索词v2",
                owner=owner_name(row.get("owner")),
                severity=severity,
                status="待处理",
                site=normalize_cell(row.get("site") or row.get("country") or row.get("store")),
                asin=normalize_cell(row.get("asin")),
                keyword=normalize_cell(row.get("keyword") or row.get("query")),
                metric=action_type,
                current_value=normalize_cell(row.get("current_value") or row.get("reason")),
                suggested_action=normalize_cell(row.get("suggested_action")) or self._search_action_text(action_type),
                source_url=normalize_cell(row.get("source_url") or row.get("source_link")),
                source_record_id=normalize_cell(row.get("source_record_id")),
                updated_at_ms=self.updated_ms,
            ))
        fresh = "正常" if latest and age_or_unknown(latest) <= 2 else "临期" if latest else "正常"
        return actions, [self.health("搜索词v2", fresh, latest, len(actions), suggested_action="已读取外部搜索词 v2 summary endpoint")]

    def _search_action_text(self, action_type: str) -> str:
        return {
            "boost": "潜力词：单独建活动或加预算观察",
            "scale": "王牌词：创建精准匹配手动广告",
            "negate": "低效词：检查后加入否定关键词",
            "warn": "异常词：人工确认费用/转化异常",
            "pending_human": "需要人工判断后再执行广告动作",
        }.get(action_type, "查看搜索词 v2 详情后处理")

    def collect_impression(self) -> tuple[list[ActionItem], list[HealthRow]]:
        table = self.cfg.impression_tasks
        records = self.lark.list_records(table.app_token, table.table_id, self.cfg.max_records_per_source)
        latest = None
        latest_by_owner: dict[str, tuple[int, dict[str, Any], str]] = {}
        for rec in records:
            f = rec.get("fields") or {}
            status = normalize_cell(f.get("执行状态"))
            if "完成" not in status and status not in ("已完成", "完成"):
                continue
            t = parse_ms(f.get("完成时间")) or parse_ms(f.get("数据日期止")) or 0
            latest = max(latest or 0, t) or latest
            owner = owner_name(f.get("运营负责人") or f.get("触发人"))
            if t and (owner not in latest_by_owner or t > latest_by_owner[owner][0]):
                latest_by_owner[owner] = (t, f, rec.get("record_id", ""))
        actions: list[ActionItem] = []
        for owner, (t, f, rid) in latest_by_owner.items():
            days = age_days(t) or 0
            opp = int(num(f.get("机会词数"), 0))
            report = normalize_cell(f.get("报告文档链接"))
            if days > 30:
                actions.append(ActionItem(
                    key=f"Impression:{owner}:stale",
                    dashboard_date_ms=self.today_ms,
                    source="展示份额",
                    owner=owner,
                    severity="P1",
                    status="待处理",
                    metric="报告新鲜度",
                    current_value=f"{days}天未更新",
                    suggested_action="上传新的展示份额 CSV 并重新跑四象限分析",
                    source_url=base_record_url(table.app_token, table.table_id, rid),
                    source_record_id=rid,
                    updated_at_ms=self.updated_ms,
                ))
            elif opp > 0:
                actions.append(ActionItem(
                    key=f"Impression:{owner}:opportunity",
                    dashboard_date_ms=self.today_ms,
                    source="展示份额",
                    owner=owner,
                    severity="P2",
                    status="待处理",
                    metric="机会词数",
                    current_value=str(opp),
                    suggested_action="打开展示份额报告，优先处理机会象限关键词",
                    source_url=report or base_record_url(table.app_token, table.table_id, rid),
                    source_record_id=rid,
                    updated_at_ms=self.updated_ms,
                ))
        fresh = "正常" if latest and age_or_unknown(latest) <= 30 else "过期"
        return actions, [self.health("展示份额", fresh, latest, len(actions), suggested_action="V1 只展示新鲜度、机会词数和报告链接")]

    def collect_wanci(self) -> tuple[list[ActionItem], list[HealthRow]]:
        table = self.cfg.wanci_weekly
        records = self.lark.list_records(table.app_token, table.table_id, self.cfg.max_records_per_source)
        latest = None
        actions: list[ActionItem] = []
        for rec in records:
            f = rec.get("fields") or {}
            t = parse_ms(f.get("快照时间"))
            latest = max(latest or 0, t or 0) or latest
            if t and (age_days(t) or 99) > 14:
                continue
            owner = owner_name(f.get("负责运营"))
            site = normalize_cell(f.get("站点")) or normalize_cell(f.get("区域"))
            asin = normalize_cell(f.get("ASIN"))
            product = normalize_cell(f.get("产品"))
            rid = rec.get("record_id", "")
            base = {
                "dashboard_date_ms": self.today_ms,
                "source": "万词作战台",
                "owner": owner,
                "site": site,
                "asin": asin,
                "product": product,
                "source_url": base_record_url(table.app_token, table.table_id, rid),
                "source_record_id": rid,
                "updated_at_ms": self.updated_ms,
            }
            if truthy_zh(f.get("失职")):
                actions.append(ActionItem(key=f"Wanci:{rid}:失职", severity="P1", status="待处理", metric="失职", current_value=normalize_cell(f.get("失职")), suggested_action="检查作战台失职原因并补齐运营动作", **base))
            budget = int(num(f.get("预算耗尽"), 0))
            if budget > 0:
                actions.append(ActionItem(key=f"Wanci:{rid}:预算耗尽", severity="P1", status="待处理", metric="预算耗尽", current_value=str(budget), suggested_action="检查预算耗尽广告，确认是否需要加预算或降无效词", **base))
            if normalize_cell(f.get("有rank追踪")) == "否":
                actions.append(ActionItem(key=f"Wanci:{rid}:无rank追踪", severity="P2", status="待处理", metric="有rank追踪", current_value="否", suggested_action="为核心词补建 Rank 追踪", **base))
            listing = normalize_cell(f.get("listing状态"))
            if listing and listing != "正常":
                actions.append(ActionItem(key=f"Wanci:{rid}:listing状态", severity="P1", status="待处理", metric="listing状态", current_value=listing, suggested_action="先处理 Listing 状态异常，再判断关键词/广告动作", **base))
            for field_name in ("收录Δ", "首页Δ"):
                delta = num(f.get(field_name), 0)
                if delta < 0:
                    actions.append(ActionItem(key=f"Wanci:{rid}:{field_name}", severity="P2", status="待处理", metric=field_name, current_value=str(int(delta)), suggested_action="复查埋词/广告拉动是否导致收录或首页下降", **base))
        days = age_days(latest)
        days_u = age_or_unknown(latest)
        fresh = "正常" if latest and days_u <= 7 else "临期" if latest and days_u <= 10 else "过期"
        return actions, [self.health("万词作战台", fresh, latest, len(actions), suggested_action="周快照超过7天会进入健康风险")]

    def collect_review_audit(self) -> tuple[list[ActionItem], list[HealthRow]]:
        if not self.cfg.amz_review_audit_summary_url:
            return [], [self.health("差评审计", "未接入", None, 0, "未配置 AMZ_REVIEW_AUDIT_SUMMARY_URL", "配置客服服务 /cs/amz-review-audit/run 的 dry-run summary endpoint")]
        headers = {"Content-Type": "application/json"}
        if self.cfg.amz_review_audit_api_token:
            headers["Authorization"] = f"Bearer {self.cfg.amz_review_audit_api_token}"
        req = urllib.request.Request(
            self.cfg.amz_review_audit_summary_url,
            data=b"{}",
            headers=headers,
            method="POST",
        )
        data = json.loads(urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=120).read().decode("utf-8"))
        if data.get("ok") is False:
            return [], [self.health("差评审计", "错误", None, 0, normalize_cell(data.get("error")), "检查客服服务差评审计 endpoint")]

        recheck = data.get("recheck") or {}
        metrics = recheck.get("metrics") or {}
        by_owner = metrics.get("负责人待处理数/已处理未改善数") or {}
        actions: list[ActionItem] = []
        for owner, counts in by_owner.items():
            pending = int(num((counts or {}).get("待处理"), 0))
            failed = int(num((counts or {}).get("已处理未改善"), 0))
            if failed:
                actions.append(ActionItem(
                    key=f"ReviewAudit:{owner}:failed",
                    dashboard_date_ms=self.today_ms,
                    source="差评审计",
                    owner=owner_name(owner),
                    severity="P1",
                    status="待处理",
                    metric="7天复检失败",
                    current_value=f"{failed}条",
                    suggested_action="打开差评审计表，检查已标记处理但首页仍有差评的 Listing；必要时公开复盘处理动作是否真实执行",
                    updated_at_ms=self.updated_ms,
                ))
            if pending:
                actions.append(ActionItem(
                    key=f"ReviewAudit:{owner}:pending",
                    dashboard_date_ms=self.today_ms,
                    source="差评审计",
                    owner=owner_name(owner),
                    severity="P2",
                    status="待处理",
                    metric="待处理差评",
                    current_value=f"{pending}条",
                    suggested_action="处理新增 Review / Feedback 卡片，并提交处理方式进入 T+7 复检",
                    updated_at_ms=self.updated_ms,
                ))
        over14 = int(num(metrics.get("14天以上未解决数"), 0))
        if over14:
            actions.append(ActionItem(
                key="ReviewAudit:over14",
                dashboard_date_ms=self.today_ms,
                source="差评审计",
                owner="未分配",
                severity="P0",
                status="待处理",
                metric="14天以上未解决",
                current_value=f"{over14}条",
                suggested_action="超过 14 天仍未改善，需要上级介入；确认是否客观无法移除或执行动作无效",
                updated_at_ms=self.updated_ms,
            ))
        recovered = int(num(metrics.get("首页无差评恢复数"), 0))
        health_text = f"复检失败={metrics.get('7天复检失败数', 0)}; 14天未解决={over14}; 首页恢复={recovered}"
        return actions, [self.health("差评审计", "正常", now_ms(), len(actions), suggested_action=health_text)]

    def build_summary(self, actions: list[ActionItem]) -> list[SummaryRow]:
        by_owner: dict[str, list[ActionItem]] = defaultdict(list)
        for action in actions:
            by_owner[action.owner or "未分配"].append(action)
        rows: list[SummaryRow] = []
        for owner, items in sorted(by_owner.items()):
            metrics = {
                "A31有效告警": sum(1 for x in items if x.source == "A31" and "待校验" not in x.key),
                "A31待校验": sum(1 for x in items if x.source == "A31" and "待校验" in x.key),
                "Rank下滑": sum(1 for x in items if x.source == "Rank" and x.metric == "自然排名下降"),
                "Rank未收录": sum(1 for x in items if x.source == "Rank" and x.metric in ("自然排名", "仅广告在榜")),
                "Rank失败过期": sum(1 for x in items if x.source == "Rank" and x.metric in ("任务状态", "快照过期")),
                "搜索词放量": sum(1 for x in items if x.source == "搜索词v2" and x.metric in ("boost", "scale")),
                "搜索词否词": sum(1 for x in items if x.source == "搜索词v2" and x.metric == "negate"),
                "搜索词待人审": sum(1 for x in items if x.source == "搜索词v2" and x.metric == "pending_human"),
                "展示份额机会词": sum(1 for x in items if x.source == "展示份额" and x.metric == "机会词数"),
                "展示份额距今天数": max([int(num(x.current_value.split("天")[0], 0)) for x in items if x.source == "展示份额" and "天" in x.current_value] or [0]),
                "万词失职": sum(1 for x in items if x.source == "万词作战台" and x.metric == "失职"),
                "万词预算耗尽": sum(1 for x in items if x.source == "万词作战台" and x.metric == "预算耗尽"),
                "万词未追踪": sum(1 for x in items if x.source == "万词作战台" and x.metric == "有rank追踪"),
                "差评7天复检失败": sum(int(num(x.current_value.replace("条", ""), 0)) for x in items if x.source == "差评审计" and x.metric == "7天复检失败"),
                "差评待处理": sum(int(num(x.current_value.replace("条", ""), 0)) for x in items if x.source == "差评审计" and x.metric == "待处理差评"),
                "差评14天未解决": sum(int(num(x.current_value.replace("条", ""), 0)) for x in items if x.source == "差评审计" and x.metric == "14天以上未解决"),
            }
            p0 = sum(1 for x in items if x.severity == "P0")
            p1 = sum(1 for x in items if x.severity == "P1")
            risk = p0 * 100 + p1 * 30 + sum(1 for x in items if x.severity == "P2") * 10 + sum(1 for x in items if x.severity == "P3") * 3
            rows.append(SummaryRow(
                key=f"{datetime.fromtimestamp(self.today_ms / 1000, tz=BJ).strftime('%Y-%m-%d')}|{owner}",
                dashboard_date_ms=self.today_ms,
                owner=owner,
                p0=p0,
                p1=p1,
                risk_score=risk,
                total_actions=len(items),
                metrics=metrics,
                updated_at_ms=self.updated_ms,
            ))
        return rows

    def write(self, result: RunResult) -> dict[str, Any]:
        base = self.cfg.dashboard_base_token
        summary_fields = self.fields_for_table(self.cfg.summary_table_id, [x.fields() for x in result.summary_rows])
        action_fields = self.fields_for_table(self.cfg.action_table_id, [x.fields() for x in result.action_items])
        health_fields = self.fields_for_table(self.cfg.health_table_id, [x.fields() for x in result.health_rows])
        write_result = {
            "summary": self.lark.upsert_by_key(base, self.cfg.summary_table_id, "汇总键", summary_fields),
            "actions": self.lark.upsert_by_key(base, self.cfg.action_table_id, "事项键", action_fields),
            "health": self.lark.upsert_by_key(base, self.cfg.health_table_id, "健康键", health_fields),
        }
        write_result["stale_actions"] = self.close_missing_actions(action_fields)
        return write_result

    def fields_for_table(self, table_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        allowed = self.lark.list_field_names(self.cfg.dashboard_base_token, table_id)
        return [{k: v for k, v in row.items() if k in allowed} for row in rows]

    def close_missing_actions(self, current_fields: list[dict[str, Any]]) -> dict[str, Any]:
        current_keys = {normalize_cell(x.get("事项键")) for x in current_fields}
        records = self.lark.list_records(self.cfg.dashboard_base_token, self.cfg.action_table_id, 10000)
        updates = []
        for rec in records:
            f = rec.get("fields") or {}
            key = normalize_cell(f.get("事项键"))
            status = normalize_cell(f.get("状态"))
            if key in current_keys or status in ("已处理", "无需处理", "已同步原表"):
                continue
            updates.append({
                "record_id": rec.get("record_id"),
                "fields": {
                    "事项键": key,
                    "状态": "无需处理",
                    "看板日期": self.today_ms,
                    "建议动作": "本次聚合未再命中该事项；如原系统仍异常，下次会重新打开。",
                    "更新时间": self.updated_ms,
                },
            })
        return self.lark.batch_update_records(self.cfg.dashboard_base_token, self.cfg.action_table_id, updates)
