# Amazon Ops Dashboard

Unified daily execution dashboard for Amazon operations.

## What This Service Does

This service aggregates existing fact sources into the Feishu Base
`亚马逊运营日看板`.

It does not replace source systems. Source tables and workflows remain the
ground truth. This service only creates a daily execution entrance for
operators.

## Feishu Resources

- Base: `Ol0ubJol8a6OlKsAhc9cEKngnBe`
- URL: `https://u1wpma3xuhr.feishu.cn/base/Ol0ubJol8a6OlKsAhc9cEKngnBe`
- Summary table: `tblns68SBBMRmweX`
- Action table: `tblSLfuQnYxoFYzn`
- Health table: `tblqIkbjVZBZGCV2`
- Dashboard: `blkilOFJalDRBEMv`

## API

```text
GET  /dashboard/health
POST /dashboard/run?mode=dry_run
POST /dashboard/run?mode=commit
```

If `DASHBOARD_API_TOKEN` is set, `POST /dashboard/run` requires:

```text
Authorization: Bearer <DASHBOARD_API_TOKEN>
```

## Environment

Required:

```text
FEISHU_BITABLE_APP_ID
FEISHU_BITABLE_APP_SECRET
```

Optional:

```text
FEISHU_APP_ID
FEISHU_APP_SECRET
DASHBOARD_API_TOKEN
DASHBOARD_BASE_TOKEN
DASHBOARD_SUMMARY_TABLE_ID
DASHBOARD_ACTION_TABLE_ID
DASHBOARD_HEALTH_TABLE_ID
SEARCH_TERM_SUMMARY_URL
SEARCH_TERM_API_TOKEN
AMZ_REVIEW_AUDIT_SUMMARY_URL
AMZ_REVIEW_AUDIT_API_TOKEN
```

`FEISHU_BITABLE_APP_ID` / `FEISHU_BITABLE_APP_SECRET` are preferred over the
generic `FEISHU_APP_ID` pair because this service writes Bitable records.

`SEARCH_TERM_SUMMARY_URL` should return JSON with either `actions` or `items`.
Each action can include: `owner`, `type`, `site`, `asin`, `keyword`,
`severity`, `suggested_action`, `source_url`.

`AMZ_REVIEW_AUDIT_SUMMARY_URL` should point to the customer-service endpoint:

```text
https://kol-auto.zeabur.app/cs/amz-review-audit/run?kind=all&mode=dry_run&notify=false
```

Set `AMZ_REVIEW_AUDIT_API_TOKEN` to the same internal bearer token used by the
customer-service service. The dashboard consumes only summary metrics and turns
`7天复检失败 / 待处理差评 / 14天以上未解决` into action rows.

## Local Dry Run

```bash
python -m amazon_ops_dashboard.run_once --mode dry_run
```

## Deployment Notes

This is designed for Zeabur as a small FastAPI service. n8n should call:

- 09:40 BJ: `POST /dashboard/run?mode=commit`
- 13:30 BJ: `POST /dashboard/run?mode=commit`

The 13:30 run is intentionally the same endpoint; Rank and Wanci data will be
fresher if their source jobs have already completed.

Current n8n workflow:

- ID: `3UVUiybjy4afjQDC`
- Name: `AMZ - 亚马逊运营日看板刷新`
- Status: inactive until the Zeabur service URL and token are configured.
