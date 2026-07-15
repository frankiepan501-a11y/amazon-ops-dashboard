import unittest

from amazon_ops_dashboard.config import Config
from amazon_ops_dashboard.dashboard_view import build_dashboard_payload, build_wanci_payload


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

    def test_wanci_payload_groups_snapshots_and_related_todos(self):
        cfg = Config(feishu_app_id="id", feishu_app_secret="secret")
        fake = _FakeLark({
            cfg.wanci_registry.table_id: [
                {
                    "record_id": "reg1",
                    "fields": {
                        "负责运营": "林明坚",
                        "站点": "US",
                        "ASIN": "B0WANCITest",
                        "产品": "测试手柄",
                        "状态": "在跑",
                        "是否每天更新": "会每天更新",
                    },
                }
            ],
            cfg.wanci_weekly.table_id: [
                {
                    "record_id": "wanci1",
                    "fields": {
                        "快照时间": "2026-07-14",
                        "负责运营": "林明坚",
                        "站点": "US",
                        "ASIN": "B0WANCITest",
                        "产品": "测试手柄",
                        "失职": "否",
                        "预算耗尽": 2,
                        "有rank追踪": "否",
                        "listing状态": "异常",
                        "收录Δ": -3,
                        "首页Δ": 1,
                    },
                },
                {
                    "record_id": "wanci0",
                    "fields": {
                        "快照时间": "2026-07-07",
                        "负责运营": "林明坚",
                        "站点": "US",
                        "ASIN": "B0WANCITest",
                        "产品": "测试手柄",
                        "有rank追踪": "是",
                        "listing状态": "正常",
                        "收录Δ": 2,
                        "首页Δ": 0,
                    },
                },
            ],
            cfg.action_table_id: [
                {
                    "record_id": "act1",
                    "fields": {
                        "事项键": "Wanci:wanci1:预算耗尽",
                        "来源": "万词作战台",
                        "负责人": "林明坚",
                        "严重级别": "P1",
                        "状态": "待处理",
                        "站点": "US",
                        "ASIN": "B0WANCITest",
                        "产品": "测试手柄",
                        "指标": "预算耗尽",
                        "当前值": "2",
                        "源记录ID": "wanci1",
                    },
                }
            ],
            cfg.health_table_id: [],
            cfg.summary_table_id: [],
        })

        payload = build_wanci_payload(cfg, fake)

        self.assertEqual(1, payload["summary"]["plans"])
        self.assertEqual(1, payload["summary"]["todo_open"])
        self.assertEqual(1, payload["summary"]["listing_abnormal"])
        self.assertEqual(1, payload["summary"]["no_rank_tracking"])
        plan = payload["plans"][0]
        self.assertEqual("待处理", plan["stage"])
        self.assertEqual(2, len(plan["history"]))
        self.assertEqual(1, len(plan["open_actions"]))
        self.assertIn("未建 Rank 追踪", plan["issues"])

    def test_wanci_registry_rank_overrides_stale_snapshot_rank_status(self):
        cfg = Config(feishu_app_id="id", feishu_app_secret="secret")
        fake = _FakeLark({
            cfg.wanci_registry.table_id: [
                {
                    "record_id": "reg1",
                    "fields": {
                        "负责运营": "林明坚",
                        "站点": "DE",
                        "ASIN": "B0WANCITest",
                        "产品": "测试手柄",
                        "状态": "在跑",
                        "是否每天更新": "会每天更新",
                        "rank子表id": "tblRank",
                    },
                }
            ],
            cfg.wanci_weekly.table_id: [
                {
                    "record_id": "snap1",
                    "fields": {
                        "快照时间": "2026-07-14",
                        "负责运营": "林明坚",
                        "站点": "DE",
                        "ASIN": "B0WANCITest",
                        "产品": "测试手柄",
                        "有rank追踪": "否",
                        "listing状态": "正常",
                    },
                }
            ],
            cfg.action_table_id: [],
        })

        payload = build_wanci_payload(cfg, fake)

        self.assertEqual(1, payload["summary"]["plans"])
        self.assertEqual(1, payload["summary"]["active_plans"])
        self.assertEqual(0, payload["summary"]["no_rank_tracking"])
        plan = payload["plans"][0]
        self.assertEqual("是", plan["rank_tracking"])
        self.assertNotIn("未建 Rank 追踪", plan["issues"])

    def test_wanci_registry_active_without_snapshot_is_missing_review(self):
        cfg = Config(feishu_app_id="id", feishu_app_secret="secret")
        fake = _FakeLark({
            cfg.wanci_registry.table_id: [
                {
                    "record_id": "reg1",
                    "fields": {
                        "负责运营": "陈翔宇",
                        "站点": "UK",
                        "ASIN": "B0NOSNAP",
                        "产品": "无快照产品",
                        "状态": "在跑",
                        "是否每天更新": "会每天更新",
                        "rank子表id": "tblRank",
                    },
                }
            ],
            cfg.wanci_weekly.table_id: [],
            cfg.action_table_id: [],
        })

        payload = build_wanci_payload(cfg, fake)

        self.assertEqual(1, payload["summary"]["missing_snapshots"])
        plan = payload["plans"][0]
        self.assertEqual("是", plan["rank_tracking"])
        self.assertIn("暂无周复审快照", plan["issues"])


if __name__ == "__main__":
    unittest.main()
