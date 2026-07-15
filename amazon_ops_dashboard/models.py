from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ActionItem:
    key: str
    dashboard_date_ms: int
    source: str
    owner: str
    severity: str
    status: str
    site: str = ""
    asin: str = ""
    product: str = ""
    keyword: str = ""
    metric: str = ""
    current_value: str = ""
    suggested_action: str = ""
    source_url: str = ""
    source_record_id: str = ""
    review_date_ms: int | None = None
    updated_at_ms: int = 0

    def fields(self) -> dict[str, Any]:
        data = {
            "事项键": self.key,
            "看板日期": self.dashboard_date_ms,
            "来源": self.source,
            "负责人": self.owner,
            "严重级别": self.severity,
            "状态": self.status,
            "站点": self.site,
            "ASIN": self.asin,
            "产品": self.product,
            "关键词": self.keyword,
            "指标": self.metric,
            "当前值": self.current_value,
            "建议动作": self.suggested_action,
            "源记录ID": self.source_record_id,
            "更新时间": self.updated_at_ms,
        }
        if self.source_url:
            data["源记录链接"] = {"link": self.source_url, "text": "打开源记录"}
        if self.review_date_ms:
            data["复查日期"] = self.review_date_ms
        return data


@dataclass
class HealthRow:
    key: str
    dashboard_date_ms: int
    source: str
    freshness: str
    latest_at_ms: int | None
    age_days: int | None
    record_count: int
    error: str = ""
    suggested_action: str = ""
    updated_at_ms: int = 0

    def fields(self) -> dict[str, Any]:
        data = {
            "健康键": self.key,
            "看板日期": self.dashboard_date_ms,
            "来源": self.source,
            "新鲜度": self.freshness,
            "记录数": self.record_count,
            "错误信息": self.error,
            "建议动作": self.suggested_action,
            "更新时间": self.updated_at_ms,
        }
        if self.latest_at_ms:
            data["最近数据时间"] = self.latest_at_ms
        if self.age_days is not None:
            data["距今天数"] = self.age_days
        return data


@dataclass
class SummaryRow:
    key: str
    dashboard_date_ms: int
    owner: str
    p0: int
    p1: int
    risk_score: int
    total_actions: int
    metrics: dict[str, int]
    updated_at_ms: int

    def fields(self) -> dict[str, Any]:
        data = {
            "汇总键": self.key,
            "看板日期": self.dashboard_date_ms,
            "负责人": self.owner,
            "P0数": self.p0,
            "P1数": self.p1,
            "风险分": self.risk_score,
            "待办总数": self.total_actions,
            "更新时间": self.updated_at_ms,
        }
        data.update(self.metrics)
        return data


@dataclass
class RunResult:
    mode: str
    summary_rows: list[SummaryRow]
    action_items: list[ActionItem]
    health_rows: list[HealthRow]
    write_result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "counts": {
                "summary_rows": len(self.summary_rows),
                "action_items": len(self.action_items),
                "health_rows": len(self.health_rows),
            },
            "summary_rows": [asdict(x) for x in self.summary_rows],
            "action_items": [asdict(x) for x in self.action_items],
            "health_rows": [asdict(x) for x in self.health_rows],
            "write_result": self.write_result,
        }
