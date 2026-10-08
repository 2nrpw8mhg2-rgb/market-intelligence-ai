# Minimal Prospective Signal Registry

## Status

Implementation only. The registry is disabled by default. No canonical signal has been registered, no scheduler has been installed, and no performance outcome is calculated by this subsystem.

Sessions from 2026-09-23 through 2026-10-08 are not contemporaneously registered holdout observations. A dry-run for an earlier session is labeled `RETROACTIVE`. Canonical registration rejects a session before the explicitly configured activation session.

## Safety model

The registry separates three stores:

1. The application database supplies identity-native PIT membership and unadjusted OHLCV inputs.
2. Complete reproducibility snapshots are compressed into private, content-addressed storage. This storage can contain licensed data and must never be pushed to GitHub.
3. A separate private GitHub repository receives signal metadata and hashes only. Its remote commit is an independent operational anchor, but its timing guarantee remains weaker than a trusted cryptographic timestamp authority.

The main repository's `backend/data/` path is ignored, but production snapshot and ledger directories should preferably live in a separately backed-up, access-controlled location outside the checkout.

## Prospective PIT-universe maintenance

### Authoritative source

Until an automated licensed index feed is approved, the required manual source is the official S&P Dow Jones Indices announcement or press release published by S&P Global for additions, removals, replacements, and effective timing. A secondary news report is not sufficient to establish the canonical effective time.

### Daily procedure

Before every canonical registration, the operator must:

1. Check the official S&P Dow Jones Indices announcements for every publication since the previous confirmed check.
2. Record the source URL/reference, publication timestamp when available, and operator confirmation timestamp.
3. Record all announced but not yet effective changes.
4. Apply only changes whose stated effective date and time apply to session D. “Effective prior to the open” applies to that session; an announcement alone never changes eligibility.
5. Resolve every addition to an existing stable `security_id`, or create a new identity only when evidence proves it is a new security rather than a ticker change.
6. Preserve ticker aliases and their valid intervals. A ticker change retains the same `security_id`.
7. Verify removals and identity/lifecycle treatment.
8. Generate the identity-native membership snapshot and confirm its SHA-256 hash in a signed operator confirmation file.
9. Explicitly confirm that no intervening effective change was missed.

This check is required before every registration. A weekly check is not sufficient. Missing source evidence, ambiguous effective timing, an unresolved new identity, a hash mismatch, or uncertain freshness must stop registration.

Example confirmation structure:

```json
{
  "session_date": "2026-10-09",
  "source_name": "S&P Dow Jones Indices official announcements",
  "source_reference": "official source reference",
  "source_publication_at": "2026-10-09T18:00:00Z",
  "operator_confirmed_at": "2026-10-09T21:15:00Z",
  "universe_snapshot_hash": "64 lowercase hexadecimal characters",
  "pending_changes": [],
  "effective_changes_checked": true,
  "no_intervening_changes_confirmed": true
}
```

The actual hash must be generated from the sorted membership snapshot. Placeholder values are rejected.

## Data readiness and timing

For XNYS session D, the application obtains the actual next XNYS opening timestamp from `exchange_calendars`. It does not hardcode a Lisbon opening time.

- Local `TIMELY`: required D-session data are confirmed ready and registration is created before next open.
- Prospectively qualified `TIMELY`: local `TIMELY` plus independently generated, record-specific server timing evidence proving that the remote anchor existed before next open.
- `LATE`: local creation or remote verification occurs at or after next open.
- `FAILED`: readiness, identity, input, write, or anchoring requirements fail.

The operator must supply a timezone-aware data-ready timestamp and evidence identifying the successful ingestion/readiness check. A timestamp before the actual XNYS close is rejected. Missing session bars, invalid features, scanner processing failures, stale membership, or ambiguous identity fail closed.

## Complete input snapshots

For every member, the registry preserves all persisted unadjusted daily OHLCV observations supplied to the frozen scanner through session D, not only the final features. It also preserves:

- the exact membership and alias snapshot;
- source, confidence, and provenance fields;
- the operator's universe confirmation;
- provider and price-representation metadata;
- data-ready evidence and timestamps;
- deterministic schema version and content hash.

Snapshots use canonical JSON, deterministic gzip (`mtime=0`), SHA-256 content addressing, atomic replacement, file and directory fsync, and private permissions. The scanner is run against this immutable in-memory snapshot, so its signals and the archived input cannot diverge.

## Ledger and corrections

The local ledger uses one immutable file per record. Every entry contains its sequence, previous hash, and current SHA-256 hash. The head file is atomically replaced. Verification detects altered content, reordered files, missing sequence numbers, head mismatch, missing trading sessions, missing snapshots, and missing/invalid remote receipts.

Retrying an identical session record is idempotent. A different record for an existing session is rejected. Corrections must be new append-only records; existing entries must never be edited or removed. Interrupted head updates can be recovered only after the complete chain itself validates.

Zero-signal sessions are explicit canonical records with an empty signal list.

## Independent GitHub anchor

Create a separate **private** GitHub repository manually. Do not reuse this application repository. Clone it locally and ensure GitHub CLI authentication can read its visibility. Embedded credentials in HTTPS remote URLs are rejected.

Only the following are anchored:

- session and UTC timestamps;
- `security_id`, valid ticker alias, score, and rank;
- strategy, parameter, input, universe, and record hashes;
- exact code commit and schema version;
- hash-chain metadata and timing classification.

Raw OHLCV, input snapshots, `.env`, API keys, credentials, and provider secrets are never copied to the anchor repository.

The adapter verifies that the repository is private, commits the metadata record, pushes it, and confirms that the commit is remotely observable. The receipt explicitly labels its evidence `REMOTE_SHA_OBSERVED_LOCAL_CLOCK_WEAK`. It records only a locally observed verification time and therefore **cannot qualify a signal as independently TIMELY**.

Client-authored author/committer dates, local push-completion time, and repository-wide `pushed_at` metadata are insufficient. The GitHub Events API exposes a server-generated `PushEvent.created_at` attributable to a pushed ref/head, but GitHub documents that the Events API can lag from 30 seconds to 6 hours; it is therefore not accepted here as a reliable pre-`NEXT_OPEN` control. See the official [events endpoint documentation](https://docs.github.com/en/rest/activity/events) and [PushEvent schema](https://docs.github.com/en/rest/using-the-rest-api/github-event-types#pushevent).

Activation remains blocked until a record-specific server timestamp mechanism is selected, implemented, retained, and tested against a real private registry repository. Until then, `holdout_qualification` is always `NOT_INDEPENDENTLY_TIMESTAMPED`, even when the local record and remote SHA are otherwise timely.

## Configuration

Canonical registration requires all variables below. They must be provided through private environment configuration and must not be committed:

```text
PROSPECTIVE_REGISTRY_ENABLED=true
PROSPECTIVE_REGISTRY_LEDGER_DIR=/private/absolute/path/ledger
PROSPECTIVE_REGISTRY_SNAPSHOT_DIR=/private/absolute/path/snapshots
PROSPECTIVE_REGISTRY_ANCHOR_REPO=/private/absolute/path/private-github-clone
PROSPECTIVE_REGISTRY_ANCHOR_REMOTE=origin
PROSPECTIVE_REGISTRY_RELEASE_TAG=<approved-release-tag>
PROSPECTIVE_REGISTRY_ACTIVATION_SESSION=<first-approved-XNYS-session>
```

`register-session` also requires a clean main checkout where HEAD, the approved release tag, and `origin/main` resolve to the same commit.

## CLI

Run from `backend/` with the application's normal Python environment.

Dry-run uses temporary isolated snapshot storage and never writes a canonical ledger record:

```bash
python -m app.cli.prospective_registry dry-run \
  --session YYYY-MM-DD \
  --data-ready-at YYYY-MM-DDTHH:MM:SSZ \
  --data-ready-evidence "completed provider ingestion/check identifier" \
  --universe-confirmation /private/path/universe-confirmation.json
```

Canonical registration remains disabled unless every activation variable and safeguard passes:

```bash
python -m app.cli.prospective_registry register-session \
  --session YYYY-MM-DD \
  --data-ready-at YYYY-MM-DDTHH:MM:SSZ \
  --data-ready-evidence "completed provider ingestion/check identifier" \
  --universe-confirmation /private/path/universe-confirmation.json
```

Integrity verification calculates no investment return:

```bash
python -m app.cli.prospective_registry verify
```

## Activation prerequisites

All conditions are mandatory:

1. implementation review approved;
2. complete tests passing;
3. frozen strategy and research artifacts unchanged;
4. registry code committed;
5. annotated registry release tag created;
6. code checkpoint pushed to `origin/main`;
7. application working tree clean;
8. separate private GitHub registry repository created and configured;
9. force-push/deletion protection configured for its canonical branch;
10. record-specific independent server timestamp mechanism implemented and proven in production-like testing;
11. private snapshot/ledger storage provisioned, capacity-checked, backed up, and access-tested;
12. licensed-data retention confirmed;
13. manual PIT maintenance performed and reviewed for the target session;
14. data-ready evidence available;
15. dry-run completed successfully before the deadline;
16. `verify` completed successfully, including local/remote inventory equality;
17. explicit human activation approval recorded;
18. activation session set to the first genuinely contemporaneous registration session.

No scheduler is deployed by this implementation. A macOS morning execution remains a manual operational action until separately approved.
