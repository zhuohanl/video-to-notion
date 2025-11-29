# Video Indexer Path Prototype Plan

Objective: Stand up a minimal end-to-end flow for the Video Indexer (VI)–first path: submit YouTube URL → download to Blob → VI upload/index → fetch insights + keyframes → align segments → emit HTML/MD with frame URLs. No production hardening; focus on proving the path and measuring latency.

- Sample video: https://youtu.be/UiCtBkC9hgs

## Scope
- Use a single sample public YouTube URL.
- One environment (dev/subscription) with minimal RBAC for contributors.
- Keep outputs in Blob; Notion push is optional and can be stubbed.
- Instrument timings for each major step.

## Prereqs
- Azure subscription with: Video Indexer account, Blob Storage, Functions app (consumption or premium), Key Vault, App Insights.
- API credentials: VI account/location/key, OpenAI key (for summaries), storage connection string/SAS.
- Tools locally: az CLI, azure-functions-core-tools, ffmpeg + yt-dlp (for download), Python runtime for Functions.
- Single-source env in `.env` (copy from `.env.example`); generate `local.settings.json` via `python scripts/generate_local_settings.py` when running Functions locally.

## Work Breakdown
1) **Sample assets and config**
   - Pick 1 YouTube URL (<= 20 min).
   - Create `local.settings.json` or env vars: `VIDEO_INDEXER_ACCOUNT_ID`, `VIDEO_INDEXER_LOCATION`, `VIDEO_INDEXER_SUBSCRIPTION_KEY`, `STORAGE_CONNECTION`, `OPENAI_KEY`, `OPENAI_ENDPOINT`, `CONTAINER=raw`.
   - Define Blob containers: `raw`, `video-indexer`, `frames`, `outputs`.
2) **Download step (Container Job or local script for prototype)**
   - Use `yt-dlp` to download MP4 to `raw/vid/{jobId}.mp4`.
   - Downsample/trim to 5m20s to reduce VI cost during tests (ffmpeg trim).
   - Emit basic metadata (duration, size).
3) **VI upload/index**
   - Call VI `Upload Video and Index` with SAS URL of the MP4; store returned `videoId`.
   - Poll `Get-Video-Index` until state is `Processed`; record elapsed time.
   - Save full insights JSON to `video-indexer/{jobId}/index.json`.
4) **Keyframe fetch**
   - From insights, read shots/scenes and keyframe `thumbnailId`.
   - Fetch representative thumbnails via VI API; write to `frames/{jobId}/{shotStartMs}.jpg`.
5) **Segment assembly**
   - Build breakpoint list: shot boundaries + speaker changes (if diarization present).
   - For each segment, gather transcript lines between breakpoints; attach frame URL and speaker label.
   - Persist aligned manifest JSON to `manifests/{jobId}.json`.
6) **Summaries**
   - Use Azure OpenAI to summarize each segment window into 1–3 sentences; retain original transcript.
   - Capture token usage and latency.
7) **Render output**
   - Generate simple Markdown or HTML: image + paragraph per segment, include timestamps and speaker names.
   - Save to `outputs/{jobId}.md` (and/or `.html`).
8) **Instrumentation and validation**
   - Log timings per step; note errors from VI or OpenAI.
   - Manual spot-check: frames match slide/speaker transitions; transcript alignment looks correct.
9) **(Optional) Notion stub**
   - If desired, create a stub that would post the Markdown to Notion, but this can remain out-of-scope for the first loop.

## Open Questions / Decisions
- Acceptable polling interval/timeouts for VI indexing (per-minute limits, regional constraints).
- Confirm trim policy: 5m20s max duration for test runs to reduce VI cost.
- How many frames to keep: options from VI — one representative keyframe per shot/scene via `thumbnailId`; can also request time-based thumbnails via `Get Thumbnail by ID` (keyframe) or `Get Thumbnail by Video and Timestamp` for custom timestamps (e.g., speaker-only breaks). Default plan: keep one keyframe per shot and add time-based thumbnails for speaker-only transitions.

## Deliverables
- Updated docs describing the measured timings and any issues.
- A minimal set of scripts/functions to run the path locally (added in a subsequent step after approval of this plan).
