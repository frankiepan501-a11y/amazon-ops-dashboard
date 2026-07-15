import unittest

from amazon_ops_dashboard.config import Config
from amazon_ops_dashboard.dashboard_view import build_dashboard_payload


class _FakeLark:
    def __init__(self, tables):
        self.tables = tables

    def list_records(self, app_token, table_id, limit=5000):
        return self.tables.get(table_id, [])[:limit]


class DashboardViewTest(unittest.TestCase):
    def test_payload_separates_human_actions_from_monitor_rows(self):
        cfg = Config(feishu_app_id="id", feishu_app_secret="secret")
        fake = _FakeLark({
            cfg.action_table_id: [
                {
                    "record_id": "rec1",
                    "fields": {
                        "事项键": "Rank:rec1:missing",
                        "来源": "Rank",
                        "负责人": "陈翔宇",
                        "严重级别": "P1",
                        "状态": "待处理",
                        "站点": "US",
                        "ASIN": "B0TEST",
                        "指标": "自然排名",
                        "当前值": "未上榜",
                        "建议动作": "检查收录",
                    },
                },
                {
                    "record_id": "rec2",
                    "fields": {
                        "事项键": "Wanci:rec2:old",
                        "来源": "万词作战台",
                        "负责人": "林明坚",
                        "严重级别": "P2",
                        "状态": "无需处理",
                        "指标": "预算耗尽",
                    },
                },
            ],
            cfg.health_table_id: [
                {
                    "record_id": "health1",
                    "fields": {
                        "健康键": "Rank",
                        "来源": "Rank",
                        "新鲜度": "正常",
                        "记录数": 1,
                    },
                },
                {
                    "record_id": "health2",
                    "fields": {
                        "健康键": "搜索词v2",
                        "来源": "搜索词v2",
                        "新鲜度": "错误",
                        "错误信息": "未配置",
                    },
                },
            ],
            cfg.summary_table_id: [],
        })

        payload = build_dashboard_payload(cfg, fake)

        self.assertEqual(1, payload["kpis"]["human_open"])
        self.assertEqual(1, payload["kpis"]["p1"])
        self.assertEqual(1, payload["kpis"]["abnormal_sources"])
        self.assertEqual(1, len(payload["priority_actions"]))
        self.assertEqual(1, len(payload["monitor_actions"]))
        self.assertEqual("Rank", payload["priority_actions"][0]["source"])


if __name__ == "__main__":
    unittest.main()
