# Deployment Handoff

## Current State

Implemented and verified:

- Feishu Base created: `Ol0ubJol8a6OlKsAhc9cEKngnBe`
- Tables created:
  - `负责人日汇总`: `tblns68SBBMRmweX`
  - `待处理事项`: `tblSLfuQnYxoFYzn`
  - `数据源健康`: `tblqIkbjVZBZGCV2`
- Dashboard created: `blkilOFJalDRBEMv`
- First commit completed:
  - 7 summary rows
  - 2589 action rows
  - 5 source-health rows
- n8n workflow created:
  - ID: `3UVUiybjy4afjQDC`
  - Name: `AMZ - 亚马逊运营日看板刷新`
  - Active: `false`

## Zeabur Blocker

The local environment has `ZEABUR_API_KEY`, but it does not have GitHub CLI or a
GitHub token. Creating a new Zeabur Git service requires a pushed GitHub repo.

Minimum next deployment step:

1. Push this directory to a GitHub repo named `amazon-ops-dashboard`.
2. Create a Zeabur Git service in project `n8n-aments`.
3. Set environment variables:
   - `FEISHU_BITABLE_APP_ID`
   - `FEISHU_BITABLE_APP_SECRET`
   - `DASHBOARD_API_TOKEN`
   - `SEARCH_TERM_SUMMARY_URL` when the search-term v2 endpoint is ready
   - `SEARCH_TERM_API_TOKEN` if that endpoint requires auth
4. Add generated domain `amazon-ops-dashboard.zeabur.app` or update n8n env
   `AMAZON_OPS_DASHBOARD_URL`.
5. Set n8n env `AMAZON_OPS_DASHBOARD_TOKEN`.
6. Activate workflow `3UVUiybjy4afjQDC`.

## Verification Commands

```bash
python -m amazon_ops_dashboard.run_once --mode dry_run
python -m amazon_ops_dashboard.run_once --mode commit
```

Expected health after current local run:

- `A31`: normal
- `Rank`: normal
- `搜索词v2`: error until `SEARCH_TERM_SUMMARY_URL` is configured
- `展示份额`: stale because the latest completed report is 76 days old
- `万词作战台`: normal

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
