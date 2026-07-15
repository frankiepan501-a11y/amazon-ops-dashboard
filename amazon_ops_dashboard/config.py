import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceTable:
    app_token: str
    table_id: str


@dataclass(frozen=True)
class Config:
    feishu_app_id: str = field(default_factory=lambda: os.getenv("FEISHU_BITABLE_APP_ID") or os.getenv("FEISHU_APP_ID", ""))
    feishu_app_secret: str = field(default_factory=lambda: os.getenv("FEISHU_BITABLE_APP_SECRET") or os.getenv("FEISHU_APP_SECRET", ""))
    api_token: str = field(default_factory=lambda: os.getenv("DASHBOARD_API_TOKEN", ""))

    dashboard_base_token: str = field(default_factory=lambda: os.getenv("DASHBOARD_BASE_TOKEN", "Ol0ubJol8a6OlKsAhc9cEKngnBe"))
    summary_table_id: str = field(default_factory=lambda: os.getenv("DASHBOARD_SUMMARY_TABLE_ID", "tblns68SBBMRmweX"))
    action_table_id: str = field(default_factory=lambda: os.getenv("DASHBOARD_ACTION_TABLE_ID", "tblSLfuQnYxoFYzn"))
    health_table_id: str = field(default_factory=lambda: os.getenv("DASHBOARD_HEALTH_TABLE_ID", "tblqIkbjVZBZGCV2"))

    search_term_summary_url: str = field(default_factory=lambda: os.getenv("SEARCH_TERM_SUMMARY_URL", ""))
    search_term_api_token: str = field(default_factory=lambda: os.getenv("SEARCH_TERM_API_TOKEN", ""))
    amz_review_audit_summary_url: str = field(default_factory=lambda: os.getenv("AMZ_REVIEW_AUDIT_SUMMARY_URL", ""))
    amz_review_audit_api_token: str = field(default_factory=lambda: os.getenv("AMZ_REVIEW_AUDIT_API_TOKEN", ""))

    max_records_per_source: int = field(default_factory=lambda: int(os.getenv("MAX_RECORDS_PER_SOURCE", "5000")))

    a31_alerts: SourceTable = SourceTable("U6ZgbI2MVawm3Isgc54cfeFtnnd", "tblFdBGfrA7DJmYS")
    rank_base_token: str = "EEKNbZ8b8aqv6msOaTscotBDn5f"
    rank_history_table_id: str = "tblpsYye65OvL2D5"
    rank_site_config_table_id: str = "tbl9gFFEy6lMMwSc"
    impression_tasks: SourceTable = SourceTable("Q8LCbeJG6ao6xzsRGZOcn2c8ndh", "tbl56JtPjhiuk640")
    wanci_registry: SourceTable = SourceTable("W8LPboJSMaVqlwsizQ8cPVDIn2c", "tbl2g78DcPnxWNwO")
    wanci_weekly: SourceTable = SourceTable("W8LPboJSMaVqlwsizQ8cPVDIn2c", "tbl3OipVxS8wyjKk")

    rank_country_tables: dict[str, str] = field(default_factory=lambda: {
        "US": "tblYip7IoTSRDw9A",
        "UK": "tblrPwwHCz4tWu3Y",
        "DE": "tbl2pNVeJy2Gnxyc",
        "FR": "tblijR2MZbVHDCQN",
        "JP": "tbl8wbPrAfst3WTQ",
        "CA": "tbl8MqFWEKaIeR9l",
        "MX": "tblh04d486irjaie",
        "ES": "tbl1muYuUDcNHhtO",
        "IT": "tblla0Xjrnk1UVj4",
    })

    def validate(self) -> None:
        missing = []
        if not self.feishu_app_id:
            missing.append("FEISHU_APP_ID")
        if not self.feishu_app_secret:
            missing.append("FEISHU_APP_SECRET")
        if missing:
            raise RuntimeError("missing environment variables: " + ", ".join(missing))
