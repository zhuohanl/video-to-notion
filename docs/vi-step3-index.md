# VI Prototype – Step 3: Upload to Video Indexer and Poll

Goal: Upload the trimmed video in Blob to Azure Video Indexer (VI), poll until processed, and save the insights JSON locally and to Blob.

## Script
- Path: `scripts/step3_vi_upload_and_poll.py`
- Requirements: `requests`, `azure-storage-blob`, `python-dotenv` (optional).

## Inputs (env or flags)
- `JOB_ID` (e.g., `demo-uiCt`)
- `AZURE_STORAGE_CONNECTION_STRING`
- `AZURE_STORAGE_ACCOUNT` (required if using AAD/user delegation SAS)
- `AZURE_STORAGE_CONTAINER_RAW` (default `raw`)
- `AZURE_STORAGE_CONTAINER_VI` (default `video-indexer`)
- `VIDEO_INDEXER_ACCOUNT_ID`
- `VIDEO_INDEXER_LOCATION` (e.g., `trial`, `westus2`, `westeurope`)
- `VIDEO_INDEXER_SUBSCRIPTION_KEY`
- Optional: `VIDEO_INDEXER_API_BASE` (default `https://api.videoindexer.ai`)
- Optional: `VIDEO_SAS_URL` via `--video-sas-url` to bypass SAS generation
- Optional: `VIDEO_INDEXER_API_BASE` (default `https://api.videoindexer.ai`)
- Optional: `AZURE_STORAGE_RESOURCE_GROUP` (not required for this step)
- Blob path for the trimmed video: defaults to `vid/{jobId}.mp4`
- Language: `--language` (default `en-US`)
- SAS TTL: `--ttl-hours` (default 24)
- Output file: `--output` (default `tmp/index.json`)
- `--skip-blob-upload` to avoid writing index.json back to Blob
- Auth for SAS generation: `--auth-mode key|aad` (default `key`). For `aad`, the script builds a user-delegation SAS using DefaultAzureCredential (`az login`).

## Run (PowerShell example)
```pwsh
python scripts/step3_vi_upload_and_poll.py `
  --job-id $env:JOB_ID `
  --storage-conn $env:AZURE_STORAGE_CONNECTION_STRING `
  --account-id $env:VIDEO_INDEXER_ACCOUNT_ID `
  --location $env:VIDEO_INDEXER_LOCATION `
  --subscription-key $env:VIDEO_INDEXER_SUBSCRIPTION_KEY `
  --raw-container $env:AZURE_STORAGE_CONTAINER_RAW `
  --vi-container $env:AZURE_STORAGE_CONTAINER_VI `
  --blob-path "vid/$($env:JOB_ID).mp4" `
  --auth-mode key `
  --output "tmp/index.json"
# If you already have a SAS URL for the video, add:
#  --video-sas-url "<https://...blob.core.windows.net/raw/vid/{jobId}.mp4?<sas>>"
```
AAD example (user delegation SAS):
```pwsh
python scripts/step3_vi_upload_and_poll.py `
  --job-id $env:JOB_ID `
  --storage-account $env:AZURE_STORAGE_ACCOUNT `
  --account-id $env:VIDEO_INDEXER_ACCOUNT_ID `
  --location $env:VIDEO_INDEXER_LOCATION `
  --subscription-key $env:VIDEO_INDEXER_SUBSCRIPTION_KEY `
  --raw-container $env:AZURE_STORAGE_CONTAINER_RAW `
  --vi-container $env:AZURE_STORAGE_CONTAINER_VI `
  --blob-path "vid/$($env:JOB_ID).mp4" `
  --auth-mode aad `
  --output "tmp/index.json"
```
If env vars are set in `.env`, you can usually just run `python scripts/step3_vi_upload_and_poll.py --job-id <id>`.

## What it does
1) Builds a read SAS URL for `raw/vid/{jobId}.mp4` (24h TTL by default).
2) Requests a VI access token using your subscription key.
3) Calls `Videos` API to upload by URL and start indexing.
4) Polls `Index` until `state=Processed` (default timeout 30 min, interval 30s).
5) Saves `index.json` locally (default `tmp/index.json`).
6) Uploads `index.json` to Blob `video-indexer/{jobId}/index.json` (unless `--skip-blob-upload`).

## Notes
- Ensure the trimmed video exists in Blob at `raw/vid/{jobId}.mp4`.
- VI free/trial accounts may have concurrency and duration limits; adjust `POLL_TIMEOUT` in the script if needed.
- If you want a different language, pass `--language <locale>`.
