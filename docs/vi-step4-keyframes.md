# VI Prototype – Step 4: Keyframe Fetch

Goal: Read Video Indexer insights (local or from Blob), fetch shot keyframes via VI thumbnail API, save them locally, and optionally upload to Blob.

## Script
- Path: `scripts/step4_vi_fetch_keyframes.py`
- Requirements: `requests`, `azure-storage-blob`, `azure-identity` (for AAD), `python-dotenv` (optional).

## Inputs (env or flags)
- `JOB_ID`
- VI creds: `VIDEO_INDEXER_ACCOUNT_ID`, `VIDEO_INDEXER_LOCATION`, `VIDEO_INDEXER_SUBSCRIPTION_KEY`, optional `VIDEO_INDEXER_API_BASE` (default `https://api.videoindexer.ai`).
- Index source (choose one):
  - Local: `--index-file` (default `tmp/index.json`)
  - Blob: `--index-blob` (default `{jobId}/index.json`) + storage auth
- Storage auth for blob access/upload:
  - `--auth-mode key|aad` (default `key`)
  - For `key`: `AZURE_STORAGE_CONNECTION_STRING`
  - For `aad`: `AZURE_STORAGE_ACCOUNT` and `az login` (DefaultAzureCredential)
- Containers:
  - `AZURE_STORAGE_CONTAINER_VI` (default `video-indexer`) for index.json if reading from blob
  - `AZURE_STORAGE_CONTAINER_FRAMES` (default `frames`) for uploading frames
- Output:
  - `--output-dir` (default `tmp/frames/{jobId}`)
  - `--skip-upload` to keep frames local only

## Run examples
Local index, upload frames with AAD:
```pwsh
python scripts/step4_vi_fetch_keyframes.py `
  --job-id $env:JOB_ID `
  --index-file tmp/index.json `
  --auth-mode aad `
  --storage-account $env:AZURE_STORAGE_ACCOUNT `
  --frames-container $env:AZURE_STORAGE_CONTAINER_FRAMES
```

Index from blob, upload frames, key auth:
```pwsh
python scripts/step4_vi_fetch_keyframes.py `
  --job-id $env:JOB_ID `
  --index-blob "$($env:JOB_ID)/index.json" `
  --auth-mode key `
  --storage-conn $env:AZURE_STORAGE_CONNECTION_STRING `
  --vi-container $env:AZURE_STORAGE_CONTAINER_VI `
  --frames-container $env:AZURE_STORAGE_CONTAINER_FRAMES
```

## What it does
1) Loads `index.json` from local file or blob.
2) Requests a VI access token.
3) Extracts shot keyframes (first instance per shot) and their start timestamps.
4) Fetches each thumbnail via VI API, saves as `{startMs}.jpg` in `tmp/frames/{jobId}` (or your `--output-dir`).
5) Uploads frames to Blob `frames/{jobId}/{startMs}.jpg` unless `--skip-upload`.

## Notes
- Frames are shot keyframes; you can extend the script to also fetch speaker-only frames if needed.
- AAD mode requires `az login` and the right permissions on the storage account. Key mode requires shared-key access on the account. If shared keys are disabled, use AAD mode.
