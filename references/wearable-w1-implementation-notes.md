# W1 implementation notes: local Garmin FIT ingestion

## Scope

This implementation is offline-only and has no cloud login, account sync, or
wellness import. It is deliberately separate from `runner_readiness`,
`baseline_prediction`, and every prediction/governance path.

## Command shape

```powershell
python -m wearable_ingest ingest --source <private-root>\activity.fit --private-root <private-root> --consent-file <private-root>\consent.json --dry-run
python -m wearable_ingest ingest-batch --source <private-root>\a.fit --source <private-root>\b.fit --private-root <private-root> --consent-file <private-root>\consent.json --dry-run
python -m wearable_ingest ingest-batch --source-dir <private-root>\approved-activities --private-root <private-root> --consent-file <private-root>\consent.json
python -m wearable_ingest delete --request-id wearable-req-... --private-root <private-root>
```

`--private-root` is required and the source plus consent receipt must be inside
it. The program never creates or assumes a machine-specific private path.

## Stored fields and retention

For a real non-dry import, output is written only below the supplied private
root as `wearable-imports/wearable-req-*`. The raw FIT copy, a normalized
activity aggregate per accepted FIT, one batch-derived aggregate summary, and
request-bound receipts are created there. The batch command accepts either an
explicit source list or one controlled source directory; it does not scan
outside that selection or re-import files already stored under
`wearable-imports`. It preflights every file before writing. Invalid, outside-
window, same-batch duplicate, and previously completed SHA-256 duplicate files
are recorded as rejected in the manifest and never enter raw, normalized, or
derived artifacts. An all-rejected batch writes nothing. The normalizer retains only start timestamp,
duration, distance, ascent, GPS/HR presence, and session average HR. It never
persists coordinate points, second-level HR streams, wellness data, device
information, or account identifiers.

The consent receipt controls the confirmed 90-day raw and 365-day derived
retention values. W1 does not include an automatic retention scheduler.

## FIT decoding limitation

The dependency-free decoder accepts standard uncompressed definition/data
records plus FIT compressed-timestamp data records when a preceding standard
timestamp is available. It reconstructs only FIT field 253 internally to read
the current message, then discards it; no record stream is retained. A
compressed record without a prior timestamp, without the standard field-253
definition, or with a truncated payload fails closed. Broader FIT-profile
compatibility should be added only with separately reviewed fixtures and
privacy tests.
