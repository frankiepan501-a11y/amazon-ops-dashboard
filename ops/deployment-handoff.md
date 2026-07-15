# Deployment Handoff

## Current State

Implemented and verified:

- GitHub repo pushed: `frankiepan501-a11y/amazon-ops-dashboard`
- Zeabur service deployed:
  - Project: `n8n-aments` / `69856f0c2e156a6efa59a9a9`
  - Service: `amazon-ops-dashboard` / `6a56fc3cb0e767d928f28ba9`
  - Domain: `https://amazon-ops-dashboard.zeabur.app`
  - Verified code commit: `beb2fb3`
- Feishu Base created: `Ol0ubJol8a6OlKsAhc9cEKngnBe`
- Tables created:
  - `负责人日汇总`: `tblns68SBBMRmweX`
  - `待处理事项`: `tblSLfuQnYxoFYzn`
  - `数据源健康`: `tblqIkbjVZBZGCV2`
- Dashboard created: `blkilOFJalDRBEMv`
- Latest cloud commit verification on 2026-07-15:
  - 7 summary rows
  - 2448 action rows
  - 6 source-health rows
  - write result: `summary updated=7`, `actions updated=2448`, `health updated=6`
- n8n workflow created:
  - ID: `3UVUiybjy4afjQDC`
  - Name: `AMZ - 亚马逊运营日看板刷新`
  - Active: `true`
  - Schedule: 09:40 + 13:30 BJ
  - `activeVersionId`: `be169eb3-8730-4d2d-b7a1-1ec9046581b9`
- Web dashboard:
  - `GET /` is now the operator-facing Amazon operations cockpit.
  - `GET /api/dashboard` reads the three Feishu dashboard tables and reorganizes
    rows into KPIs, business modules, priority actions, source health, owner
    workload, and a detail pool.
  - `GET /wanci` is a dedicated Wanci plan workspace. It reads the Wanci weekly
    snapshot source table and the dashboard action table via `GET /api/wanci`,
    then shows plan progress, listing changes, open/completed todos, owner
    progress, and source-record drill-downs.
  - The Feishu Base remains the source-of-truth/detail layer; the web page is
    the management presentation layer.
  - Latest production API check: `human_open=2448`, `p0=986`, `p1=1442`,
    `abnormal_sources=5`, `modules=6`, `health=6`, `owners=8`.

## Deployed Configuration

Zeabur service env:

- `FEISHU_BITABLE_APP_ID`
- `FEISHU_BITABLE_APP_SECRET`
- `DASHBOARD_API_TOKEN`

n8n service env:

- `AMAZON_OPS_DASHBOARD_URL=https://amazon-ops-dashboard.zeabur.app`
- `AMAZON_OPS_DASHBOARD_TOKEN` matches the dashboard service bearer token

Not yet configured:

- `SEARCH_TERM_SUMMARY_URL`
- `SEARCH_TERM_API_TOKEN`
- `AMZ_REVIEW_AUDIT_SUMMARY_URL`
- `AMZ_REVIEW_AUDIT_API_TOKEN`

## Verification Commands

```bash
python -m amazon_ops_dashboard.run_once --mode dry_run
python -m amazon_ops_dashboard.run_once --mode commit
```

Cloud verification:

```bash
GET  https://amazon-ops-dashboard.zeabur.app/dashboard/health
POST https://amazon-ops-dashboard.zeabur.app/dashboard/run?mode=commit
```

Expected health after 2026-07-15 cloud run:

- `A31`: stale/overdue according to source freshness
- `Rank`: normal
- `搜索词v2`: error until `SEARCH_TERM_SUMMARY_URL` is configured
- `展示份额`: stale because the latest completed report is 85 days old
- `万词作战台`: stale because the latest weekly snapshot is over 7 days old
- `差评审计`: not connected until the customer-service summary endpoint is configured

Implementation note:

- Writes are filtered to the destination Bitable table's actual field list before
  upsert. This prevents optional future metrics, such as review-audit fields, from
  blocking today's core dashboard writes when those columns have not been created.

## 2026-07-06 Dashboard V1.1 View Audit Update

Purpose: shift the Base from a manager summary screen toward an operator
execution entrance. Source systems remain unchanged.

Feishu Base changes made:

- Dashboard blocks renamed/reconfigured:
  - `全员P0待办`
  - `全员P1待办`
  - `A31待办总量（含积压）`
  - `Rank风险词`
  - `搜索词v2错误源`
  - `万词待办总量`
  - `按负责人P0/P1`
  - `按来源P0/P1`
  - `数据源健康状态`
  - Added `错误/过期数据源`
  - Added `展示份额过期源`
- `待处理事项` views added:
  - `01 今日优先处理 P0-P1`: filters `状态 in 待处理/处理中`
    and `严重级别 in P0/P1`; groups by `负责人 / 严重级别 / 来源`.
  - `02 Rank风险优先`: filters Rank open items; groups by
    `负责人 / 指标 / 严重级别`.
  - `03 万词待办拆分`: filters Wanci open items; groups by
    `负责人 / 指标 / 严重级别`.
- `数据源健康` views added:
  - `01 数据源异常优先`: filters `错误 / 过期 / 临期`, sorts by
    `距今天数 desc`.
  - `02 展示份额需上传CSV`: filters stale/error/near-stale impression share.

Known limitations after V1.1:

- Feishu Dashboard block API only supports charts/statistics; it does not embed
  an actionable record table. The operator execution entrance is therefore the
  `待处理事项` table view `01 今日优先处理 P0-P1`.
- `搜索词v2` remains an error source until `SEARCH_TERM_SUMMARY_URL` is
  configured.
- `展示份额` remains stale until a new CSV/report is uploaded.
