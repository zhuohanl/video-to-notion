# VI Prototype – Step 1: Sample Assets and Config

What you need to prepare before running the VI-first prototype.

## Sample video
- URL: https://youtu.be/UiCtBkC9hgs
- For tests, trim/downsample to 5m20s to control Video Indexer cost (done in step 2 with ffmpeg).

## Env/config
- Copy `.env.example` to `.env` and fill placeholders (no secrets committed). This is the single source of truth.
- When running Azure Functions locally, generate `local.settings.json` from `.env`:
  - `python scripts/generate_local_settings.py --env .env --output local.settings.json`

Required keys/placeholders:
- `VIDEO_URL` — sample YouTube link above.
- `JOB_ID` — e.g., `demo-uiCt`.
- Storage: `AZURE_STORAGE_ACCOUNT`, `AZURE_STORAGE_CONNECTION_STRING`, containers `raw`, `video-indexer`, `frames`, `outputs`.
- Video Indexer: `VIDEO_INDEXER_ACCOUNT_ID`, `VIDEO_INDEXER_LOCATION` (e.g., `trial`, `westus2`, `westeurope`), `VIDEO_INDEXER_SUBSCRIPTION_KEY`, `VIDEO_INDEXER_API_BASE=https://api.videoindexer.ai`.
- OpenAI: `OPENAI_ENDPOINT`, `OPENAI_API_KEY`, `OPENAI_DEPLOYMENT` (e.g., `gpt-4o-mini`).
- Optional: `KEY_VAULT_NAME` if pulling secrets at runtime.

## Blob containers
- Names: `raw`, `video-indexer`, `frames`, `outputs`.
- Create them once per storage account. Helper script: `./scripts/bootstrap-storage.ps1 -StorageAccountName <name> [-ResourceGroup <rg>]` (uses `az` login).

## Verification checklist
- `.env` exists locally with real values.
- `local.settings.json` generated (for Functions local run) via the script above.
- Target storage account has the four containers above.
- You can `az login` and `az storage account show --name <name>` successfully.
