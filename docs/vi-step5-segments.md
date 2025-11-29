# VI Prototype – Step 5: Segment Assembly

Goal: Merge shot and speaker breakpoints, align transcript windows to frames, and produce a manifest for downstream summarization/export.

## Script
- Path: `scripts/step5_build_segments.py`
- Requirements: `requests`, `azure-storage-blob`, `azure-identity` (for AAD), `python-dotenv` (optional).

## Inputs (env or flags)
- `JOB_ID`
- VI creds: `VIDEO_INDEXER_ACCOUNT_ID`, `VIDEO_INDEXER_LOCATION`, `VIDEO_INDEXER_SUBSCRIPTION_KEY`, optional `VIDEO_INDEXER_API_BASE`
- Index source:
  - Local: `--index-file` (default `tmp/index.json`)
  - Blob: `--index-blob` (default `{jobId}/index.json`) plus storage auth
- Storage auth (for blob read/upload):
  - `--auth-mode key|aad` (default `key`)
  - For `key`: `AZURE_STORAGE_CONNECTION_STRING`
  - For `aad`: `AZURE_STORAGE_ACCOUNT` and `az login` (DefaultAzureCredential)
- Containers:
  - `AZURE_STORAGE_CONTAINER_VI` (default `video-indexer`) for index.json if reading from blob
  - `AZURE_STORAGE_CONTAINER_MANIFESTS` (default `manifests`) for uploading manifest.json (created if missing)
- Frames:
  - `--frames-dir` (default `tmp/frames/{jobId}`) to locate downloaded keyframes when building segment-to-frame links
- Output:
  - `--output` (default `tmp/manifest.json`)
  - `--skip-upload` to keep manifest local only

## Run examples
Local index, upload manifest with AAD:
```pwsh
python scripts/step5_build_segments.py `
  --job-id $env:JOB_ID `
  --index-file tmp/index.json `
  --auth-mode aad `
  --storage-account $env:AZURE_STORAGE_ACCOUNT `
  --frames-dir tmp/frames/$($env:JOB_ID) `
  --manifests-container $env:AZURE_STORAGE_CONTAINER_MANIFESTS
```

Index from blob, key auth:
```pwsh
python scripts/step5_build_segments.py `
  --job-id $env:JOB_ID `
  --index-blob "$($env:JOB_ID)/index.json" `
  --auth-mode key `
  --storage-conn $env:AZURE_STORAGE_CONNECTION_STRING `
  --frames-dir tmp/frames/$($env:JOB_ID) `
  --vi-container $env:AZURE_STORAGE_CONTAINER_VI `
  --manifests-container $env:AZURE_STORAGE_CONTAINER_MANIFESTS
```

## What it does
1) Load `index.json` (local or blob).
2) Extract shot boundaries and speaker-change timestamps; merge/sort to a unified breakpoint list.
3) Extract transcript entries with timestamps and speaker labels.
4) Build segments between breakpoints, concatenating transcript text and selecting the speaker (first in window). Frame is chosen from the nearest shot keyframe at or before the segment start (assumes frames at `frames/{jobId}/{shotStartMs}.jpg`).
5) Save `manifest.json` locally (with segments) and optionally upload to Blob `manifests/{jobId}/manifest.json`.

## Notes
- This uses shot keyframes only; if you capture speaker-only thumbnails, you can extend the frame selection logic to prefer those for speaker transitions.
- Output schema: `{ jobId, segments: [{ segmentStartMs, segmentEndMs, framePath, speaker, text, source }] }`.
