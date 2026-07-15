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
GET  /
GET  /api/dashboard
GET  /wanci
GET  /api/wanci
GET  /dashboard/health
POST /dashboard/run?mode=dry_run
POST /dashboard/run?mode=commit
```

`GET /` is the operator-facing dashboard. It reads the Feishu Base rows through
`GET /api/dashboard` and reorganizes them into summary KPIs, business modules,
priority actions, source health, owner workload, and a detail pool.

`GET /wanci` is the dedicated Wanci plan workspace. It reads the Wanci registry
table as the current project truth, then overlays the weekly snapshot table and
dashboard action table through `GET /api/wanci`. It groups rows by site/ASIN,
and shows task progress, listing changes, related todos, and source-record
links.

P1 data-source audit on 2026-07-15 found that weekly snapshots had stopped at
2026-06-29 because n8n workflow `QvvnQEUW4g17tOdm` had a broken connection:
the duplicate `DOW Filter (Mon)` node pointed to itself, leaving `/review`
unconnected. The workflow was repaired to
`每周一09:00BJ -> DOW Filter (Mon) -> 调/review复审` and reactivated. The Wanci
page now uses registry `rank子表id` to decide Rank tracking status, preventing
stale snapshots from falsely reporting active projects as missing Rank tracking.

P1 wording fix on 2026-07-15: the Wanci page now separates projects that cannot
be reviewed because required registry data is missing from projects where the
review job actually failed. Operator-facing labels use plain wording:
`资料没填全` means the registry row is missing `负责运营`, `店铺sid`, or
`seller_sku`; `复查失败` means those fields are present but no review record was
created.

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

Production URL:

```text
https://amazon-ops-dashboard.zeabur.app
```

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
- Status: active
- Schedule: 09:40 + 13:30 BJ
