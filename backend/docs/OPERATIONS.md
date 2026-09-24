# Operations runbook

The operational pipeline uses real database state and Massive data only. It never falls back to fixtures or synthetic market data.

## 1. Configure and migrate

Copy `.env.example` to `.env` and set `DATABASE_URL` and `MASSIVE_API_KEY`. Do not commit `.env` or paste secrets into reports. Then:

```bash
cd backend
alembic upgrade head
```

`PROVIDER_DATA_DELAY_MINUTES` defaults to 180, based on the first operational validation in which the aggregate was still unavailable 35 minutes after the close. A `LATEST` session is eligible only after its actual XNYS close plus this conservative provider delay; adjust it only with observed provider availability.

## 2. Import the current S&P 500 snapshot

Use a CSV whose source and observation date you can identify. The default column is `ticker`:

```bash
python -m app.cli.import_universe \
  --csv /path/to/sp500.csv \
  --snapshot-date 2026-09-23 \
  --source "provider-or-source URL/version"
```

The import is idempotent for `(universe, snapshot_date, source)` and replaces only that exact snapshot. It does not add rows to `universe_memberships`. A current list must never be used as historical membership; historical scans require separately licensed or authoritative point-in-time intervals.

## 3. Ingest daily bars

The default selection is the latest current S&P 500 snapshot and the default horizon is 260 completed sessions:

```bash
python -m app.cli.ingest_market_data \
  --lookback-sessions 260 --concurrency 2 --requests-per-minute 5
```

For a controlled validation batch:

```bash
python -m app.cli.ingest_market_data \
  --tickers AAPL,MSFT,NVDA \
  --start-date 2025-09-01 --end-date 2026-09-22 \
  --output reports/ingestion.json
```

The command downloads only missing session ranges, uses bounded concurrency, honors provider retry/rate-limit behavior and reports requests, received bars, inserted bars and per-symbol errors. Re-running a complete range is a cache hit. Reports under `backend/reports/` are intentionally ignored by Git.

Before a large historical load, estimate it without provider calls:

```bash
python -m app.cli.ingest_market_data --lookback-years 5 --dry-run --requests-per-minute 5
```

## 4. Diagnose completeness

```bash
python -m app.cli.check_completeness \
  --start-date 2025-09-01 --end-date 2026-09-22 \
  --output reports/completeness.json
```

The report compares stored bars with XNYS sessions and exposes missing and unexpected dates per ticker. Gaps remain explicit; the system never forward-fills or creates zero-volume bars.

## 5. Run the scanner

```bash
python -m app.cli.run_scan --mode LATEST --output reports/latest-scan.json
python -m app.cli.run_scan --mode HISTORICAL --as-of-date 2026-09-22
```

`LATEST` uses the current snapshot. `HISTORICAL` refuses to substitute it and returns `UNIVERSE_DATA_UNAVAILABLE` if genuine point-in-time membership is absent. Opportunities and their deterministic explanations are persisted idempotently.

## Operational validation checklist

1. Record the snapshot source, date, constituent count and import output.
2. Record the Massive ingestion report and confirm failures/rate-limit events.
3. Run completeness and investigate every missing or unexpected session.
4. Run `LATEST`; record resolved session, requested/processed/skipped/failed counts and opportunities.
5. Re-run the same scan and confirm no duplicate opportunity identity is created.
6. Retain generated reports outside source control and never include credentials.

## Current limits

- No historical constituent dataset is bundled.
- Completeness checks presence, not tick-level correctness.
- Massive REST adjusted aggregates are split-adjusted, not dividend-adjusted.
- Backtesting is documented in `BACKTESTING.md`; ML, portfolio construction and order execution remain out of scope.
