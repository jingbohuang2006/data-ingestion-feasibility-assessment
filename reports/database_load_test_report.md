# Controlled PostgreSQL Load-Test Report

Date: 2026-07-14

PostgreSQL: 14, disposable local cluster
Migration head: `0002_integration_readiness`

## Migration proof

The live integration suite successfully performed upgrade to head, schema inspection, downgrade to base, re-upgrade to head, representative inserts, constraint failures, and execution of every SQL example. A first real attempt exposed that the original revision ID exceeded Alembic's 32-character version column; the internal ID was shortened to `0001_initial` before the successful proof.

## Layer counts

| Layer | apple-small-500 | apple-large-10000 |
| --- | ---: | ---: |
| Run targets | 5 | 20 |
| Collection requests | 11 | 152 |
| Raw payload occurrences | 11 | 144 |
| Raw review records | 500 | 6,600 |
| Normalized reviews | 500 | 6,396 |
| Review observations | 500 | 6,600 |
| Quality flags | 60 | 512 |
| Missing/failure evidence rows | 1 | 40 |

## Duplicate, failure, and quality results

The small run contained 500 new observations and no repeated appearances. It preserved ten successful review pages and one empty page.

The large run contained 6,396 new observations and 204 contextual repeated appearances, all preserved as `duplicate_skipped`; no repeated appearance was silently discarded. Request evidence contains 132 successful review pages, 12 empty pages, 8 pagination-limit/unavailable-page attempts, and 0 other failed requests. The 40 missing/failure evidence rows comprise those 20 request outcomes plus 20 target-shortfall records. No raw records were excluded or failed parsing in the preserved inputs. Quality flags comprise low-signal reviews plus missing-title warnings where applicable.

## Integrity and reconciliation

Both runs produced:

- zero raw records without an observation
- zero normalized reviews without an observation
- zero lineage-context conflicts
- zero constraint or integrity failures during load

Identical payload hashes were separately inserted for two requests in integration testing, proving that repeated content no longer loses request-level evidence. A parse-error raw record with no source review ID was also inserted and retained with a traceable observation.

## Data-driven behavior

The preserved `apple-small-500` summary reports a configured target of 10,000 even though the folder/run identifier and preserved dataset represent the 500-row validation run. The loader therefore treats the immutable run identifier suffix (`500` or `10000`) and actual normalized count as the controlled-load target/result, while preserving the complete, unmodified source summary under `ingestion_runs.config.source_summary`. No schema column was overloaded to hide this artifact inconsistency.

The large data confirmed that payload hashes cannot be globally unique and that duplicate identity must include app/storefront context. The implemented schema and loader reflect both behaviors.
