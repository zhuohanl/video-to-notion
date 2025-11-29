# VI Prototype – Step 7: Render HTML/Markdown

Goal: Take summarized manifest and produce a Notion-ready HTML or Markdown file with frames and text.

## Script
- Path: `scripts/step7_render_output.py`
- Requirements: `azure-storage-blob`, `azure-identity` (for AAD), `python-dotenv` (optional).

## Inputs (env or flags)
- `JOB_ID`
- Manifest source:
  - Local: `--manifest-file` (default `tmp/manifest_with_summaries.json`)
  - Blob: `--manifest-blob` (default `{jobId}/manifest_with_summaries.json`) + storage auth
- Storage auth:
  - `--auth-mode key|aad` (default `key`)
  - For `key`: `AZURE_STORAGE_CONNECTION_STRING`
  - For `aad`: `AZURE_STORAGE_ACCOUNT` and `az login`
- Containers:
  - `AZURE_STORAGE_CONTAINER_MANIFESTS` (default `manifests`) for reading manifest if blob
  - `AZURE_STORAGE_CONTAINER_OUTPUTS` (default `outputs`) for uploading rendered file
- Output:
  - `--format html|md` (default `html`)
  - `--output` (default `tmp/output.html` or `.md`)
  - `--skip-upload` to keep local only
  - `--frame-base-url` to prefix relative frame paths (e.g., `https://<acct>.blob.core.windows.net/frames`)
  - `--frame-local-dir` to resolve frames for local file:// preview (defaults to the manifest directory when reading from a local file)

## Run examples
Local manifest, HTML, upload with AAD:
```pwsh
python scripts/step7_render_output.py `
  --job-id $env:JOB_ID `
  --format html `
  --manifest-file tmp/manifest_with_summaries.json `
  --auth-mode aad `
  --storage-account $env:AZURE_STORAGE_ACCOUNT `
  --outputs-container $env:AZURE_STORAGE_CONTAINER_OUTPUTS
```

Manifest from blob, Markdown, key auth:
```pwsh
python scripts/step7_render_output.py `
  --job-id $env:JOB_ID `
  --format md `
  --manifest-blob "$($env:JOB_ID)/manifest_with_summaries.json" `
  --auth-mode key `
  --storage-conn $env:AZURE_STORAGE_CONNECTION_STRING `
  --manifests-container $env:AZURE_STORAGE_CONTAINER_MANIFESTS `
  --outputs-container $env:AZURE_STORAGE_CONTAINER_OUTPUTS
```

## What it does
1) Load summarized manifest (local or blob).
2) Render HTML or Markdown: image per segment (using `framePath`), metadata (timestamp, speaker), and `summary` text (fallback to `text`).
3) Save locally; optionally upload to Blob `outputs/{jobId}/output.<fmt>`.

## Notes
- Assumes frames in `framePath` are reachable (e.g., SAS or public URLs). Ensure frames use short-lived SAS if private.
- If frames are stored by relative path (e.g., `frames/{jobId}/{ts}.jpg`), set `--frame-base-url` to your frames container URL so the HTML points to valid URLs. For local preview, use `--frame-local-dir` (or rely on the default manifest directory) to turn paths into `file://...`.
- Template is simple; customize styling as needed.
