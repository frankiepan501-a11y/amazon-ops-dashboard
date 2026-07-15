import json
import unittest

from amazon_ops_dashboard.aggregator import Aggregator
from amazon_ops_dashboard.config import Config


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class _FakeOpener:
    def __init__(self, payload):
        self.payload = payload

    def open(self, request, timeout=120):
        return _FakeResponse(self.payload)


class ReviewAuditCollectorTest(unittest.TestCase):
    def test_review_audit_metrics_create_actions(self):
        import amazon_ops_dashboard.aggregator as ag

        payload = {
            "ok": True,
            "recheck": {
                "metrics": {
                    "7天复检失败数": 2,
                    "14天以上未解决数": 1,
                    "首页无差评恢复数": 3,
                    "负责人待处理数/已处理未改善数": {
                        "黄奕纯": {"待处理": 4, "已处理未改善": 2},
                        "陈翔宇": {"待处理": 1, "已处理未改善": 0},
                    },
                }
            },
        }
        original = ag.urllib.request.build_opener
        try:
            ag.urllib.request.build_opener = lambda *args, **kwargs: _FakeOpener(payload)
            cfg = Config(
                feishu_app_id="id",
                feishu_app_secret="secret",
                amz_review_audit_summary_url="https://example.test/audit",
                amz_review_audit_api_token="tok",
            )
            agg = Aggregator(cfg, lark=None)
            actions, health = agg.collect_review_audit()
        finally:
            ag.urllib.request.build_opener = original

        self.assertEqual(4, len(actions))
        metrics = {(a.owner, a.metric): a.current_value for a in actions}
        self.assertEqual("2条", metrics[("黄奕纯", "7天复检失败")])
        self.assertEqual("4条", metrics[("黄奕纯", "待处理差评")])
        self.assertEqual("1条", metrics[("陈翔宇", "待处理差评")])
        self.assertEqual("1条", metrics[("未分配", "14天以上未解决")])
        self.assertEqual("正常", health[0].freshness)
        self.assertIn("首页恢复=3", health[0].suggested_action)


if __name__ == "__main__":
    unittest.main()
