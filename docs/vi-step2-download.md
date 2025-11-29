# VI Prototype – Step 2: Download and Trim

Goal: Download the sample YouTube video, trim to 5m20s to control VI cost, and upload to Blob Storage at `raw/vid/{jobId}.mp4`.

## Script
- Path: `scripts/download_and_trim.py`
- Requirements: `yt-dlp` (on PATH), `ffmpeg` (on PATH), Python packages `azure-storage-blob` and optionally `python-dotenv` (add `azure-identity` if using AAD).
- Inputs (env or flags):
  - `VIDEO_URL` (default: `https://youtu.be/UiCtBkC9hgs`)
  - `JOB_ID` (e.g., `demo-uiCt`)
  - Auth: `--auth-mode key|aad` (default `key`). For `key`, use `AZURE_STORAGE_CONNECTION_STRING`. For `aad`, set `AZURE_STORAGE_ACCOUNT` and ensure `az login`/DefaultAzureCredential works.
  - `AZURE_STORAGE_CONNECTION_STRING` (required for key auth)
  - `AZURE_STORAGE_ACCOUNT` (required for AAD auth)
  - `AZURE_STORAGE_CONTAINER_RAW` (default `raw`)
  - Storage check (key auth only): `--resource-group` (for verifying key auth), `--skip-shared-key-check` to bypass `allowSharedKeyAccess` validation
  - Re-encode controls (to reduce size without changing duration): `--max-width` (default 1280), `--crf` (default 23), `--audio-bitrate` (default 128k), `--preset` (default veryfast), `--no-reencode` to skip re-encode (larger files)
  - Upload tuning: `--upload-timeout` (seconds, default 600), `--upload-concurrency` (default 4), `--no-upload-progress` to silence progress
  - Output dir: `./tmp` by default
- Upload target: blob `vid/{jobId}.mp4` in the raw container.

## Install deps (one-time)
```bash
python -m pip install azure-storage-blob yt-dlp python-dotenv
```

## Run (PowerShell example)
```pwsh
python scripts/download_and_trim.py `
  --video-url $env:VIDEO_URL `
  --job-id $env:JOB_ID `
  --auth-mode key `
  --connection-string $env:AZURE_STORAGE_CONNECTION_STRING `
  --raw-container raw `
  --resource-group <rg> `
  --max-width 1280 `
  --crf 23 `
  --audio-bitrate 128k `
  --preset veryfast `
  --upload-timeout 600 `
  --upload-concurrency 4 `
  # add --no-upload-progress to silence progress output
  --output-dir ./tmp
```
AAD example:
```pwsh
python scripts/download_and_trim.py `
  --video-url $env:VIDEO_URL `
  --job-id $env:JOB_ID `
  --auth-mode aad `
  --account-name $env:AZURE_STORAGE_ACCOUNT `
  --raw-container raw `
  --max-width 1280 `
  --crf 23 `
  --audio-bitrate 128k `
  --preset veryfast `
  --upload-timeout 600 `
  --upload-concurrency 4 `
  --output-dir ./tmp
```
If env vars are set in `.env`, you can just run `python scripts/download_and_trim.py`.

## What to expect
- Local files in `./tmp/{jobId}.mp4` (full) and `./tmp/{jobId}_trimmed.mp4`.
- Blob uploaded to container `raw` at `vid/{jobId}.mp4`.
- Duration trimmed to 5m20s.

## Verification
- Check blob exists:
  ```bash
  az storage blob show --container-name raw --name vid/{jobId}.mp4 --account-name <acct>
  ```
- Spot-check duration of trimmed file:
  ```bash
  ffprobe -i ./tmp/{jobId}_trimmed.mp4 -show_entries format=duration -v quiet -of csv="p=0"
  ```
- Spot-check filesize and consider tweaking:
  - Lower `--max-width` (e.g., 960) or increase `--crf` (e.g., 25) to reduce size further with moderate quality loss.
