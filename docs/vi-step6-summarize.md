# VI Prototype – Step 6: Summaries

Goal: Summarize each aligned segment and persist a manifest with summaries for rendering.

## Script
- Path: `scripts/step6_summarize_segments.py`
- Requirements: `openai`, `azure-storage-blob`, `azure-identity` (for AAD), `python-dotenv` (optional).

## Inputs (env or flags)
- `JOB_ID`
- Manifest source:
  - Local: `--manifest-file` (default `tmp/manifest.json`)
  - Blob: `--manifest-blob` (default `{jobId}/manifest.json`) + storage auth
- Storage auth:
  - `--auth-mode key|aad` (default `key`)
  - For `key`: `AZURE_STORAGE_CONNECTION_STRING`
  - For `aad`: `AZURE_STORAGE_ACCOUNT` and `az login`
- Containers:
  - `AZURE_STORAGE_CONTAINER_MANIFESTS` (default `manifests`)
- OpenAI:
  - `OPENAI_ENDPOINT`, `OPENAI_API_KEY`, `OPENAI_DEPLOYMENT`
- Output:
  - `--output` (default `tmp/manifest_with_summaries.json`)
  - `--skip-upload` to keep local only

## Run examples
Local manifest, upload with AAD:
```pwsh
python scripts/step6_summarize_segments.py `
  --job-id $env:JOB_ID `
  --manifest-file tmp/manifest.json `
  --auth-mode aad `
  --storage-account $env:AZURE_STORAGE_ACCOUNT `
  --manifests-container $env:AZURE_STORAGE_CONTAINER_MANIFESTS
```

Manifest from blob, key auth:
```pwsh
python scripts/step6_summarize_segments.py `
  --job-id $env:JOB_ID `
  --manifest-blob "$($env:JOB_ID)/manifest.json" `
  --auth-mode key `
  --storage-conn $env:AZURE_STORAGE_CONNECTION_STRING `
  --manifests-container $env:AZURE_STORAGE_CONTAINER_MANIFESTS
```

## What it does
1) Load `manifest.json` (local or blob).
2) Call Azure OpenAI to summarize each segment’s `text` into 1–3 sentences (temperature=0.2).
3) Write `manifest_with_summaries.json` locally and optionally upload to `manifests/{jobId}/manifest_with_summaries.json`.

## Notes
- Summaries are added under `summary` per segment; original `text` is preserved.
- Requires `OPENAI_*` envs and access to the deployment you specify.
