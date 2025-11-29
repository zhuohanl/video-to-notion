"""
Build aligned segments from Video Indexer insights: merge shot/speaker breakpoints,
gather transcript windows, and attach frame paths. Save manifest locally and optionally upload to Blob.

Usage (env-first):
  python scripts/step5_build_segments.py --job-id <id>

Key inputs (env or flags):
  JOB_ID
  VIDEO_INDEXER_ACCOUNT_ID, VIDEO_INDEXER_LOCATION, VIDEO_INDEXER_SUBSCRIPTION_KEY
  VIDEO_INDEXER_API_BASE (default https://api.videoindexer.ai)
  Index source: --index-file (default tmp/index.json) or --index-blob (default {jobId}/index.json)
  Storage auth: --auth-mode key|aad (default key), plus:
    key: AZURE_STORAGE_CONNECTION_STRING
    aad: AZURE_STORAGE_ACCOUNT and az login
  Containers: AZURE_STORAGE_CONTAINER_VI (index), AZURE_STORAGE_CONTAINER_MANIFESTS (default manifests)
  Output: --output (default tmp/manifest.json), --skip-upload to keep local only

Requires: requests, azure-storage-blob, azure-identity (for AAD), python-dotenv (optional).
"""

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

import requests
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # optional convenience
    def load_dotenv():
        return False


def get_access_token(api_base: str, location: str, account_id: str, subscription_key: str) -> str:
    url = f"{api_base}/Auth/{location}/Accounts/{account_id}/AccessToken"
    params = {"allowEdit": "true"}
    headers = {"Ocp-Apim-Subscription-Key": subscription_key}
    resp = requests.get(url, params=params, headers=headers, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"Access token request failed: {resp.status_code} {resp.text}")
    return resp.text.strip().strip('"')


def make_blob_service(args) -> BlobServiceClient:
    if args.auth_mode == "aad":
        credential = DefaultAzureCredential(exclude_interactive_browser_credential=False)
        account_url = f"https://{args.storage_account}.blob.core.windows.net"
        return BlobServiceClient(account_url=account_url, credential=credential)
    return BlobServiceClient.from_connection_string(args.storage_conn)


def read_index_local(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_index_blob(bsc: BlobServiceClient, container: str, blob_name: str) -> dict:
    blob_client = bsc.get_blob_client(container=container, blob=blob_name)
    data = blob_client.download_blob().readall()
    return json.loads(data)


def time_to_ms(ts: str) -> int:
    # format: h:mm:ss.sss
    parts = ts.split(":")
    if len(parts) != 3:
        return 0
    h, m, s = parts
    seconds = float(h) * 3600 + float(m) * 60 + float(s)
    return int(seconds * 1000)


def extract_shot_boundaries(index_data: dict) -> List[int]:
    shots = (
        index_data.get("videos", [{}])[0]
        .get("insights", {})
        .get("shots", [])
    )
    starts: List[int] = []
    for shot in shots:
        inst = (shot.get("instances") or [{}])[0]
        start = inst.get("start")
        if start is None:
            continue
        starts.append(time_to_ms(str(start)))
    return sorted(set(starts))


def extract_speaker_changes(index_data: dict) -> List[int]:
    transcript = (
        index_data.get("videos", [{}])[0]
        .get("insights", {})
        .get("transcript", [])
    )
    # transcript entries already sorted; mark when speakerId changes
    changes: List[int] = []
    prev_speaker = None
    for entry in transcript:
        speaker = entry.get("speakerId")
        inst = (entry.get("instances") or [{}])[0]
        start = inst.get("start")
        if start is None:
            continue
        start_ms = time_to_ms(str(start))
        if speaker != prev_speaker and speaker is not None:
            changes.append(start_ms)
        prev_speaker = speaker
    return sorted(set(changes))


def extract_transcript_entries(index_data: dict) -> List[dict]:
    transcript = (
        index_data.get("videos", [{}])[0]
        .get("insights", {})
        .get("transcript", [])
    )
    entries = []
    for entry in transcript:
        text = entry.get("text") or ""
        speaker = entry.get("speakerId")
        inst = (entry.get("instances") or [{}])[0]
        start = inst.get("start")
        if start is None:
            continue
        start_ms = time_to_ms(str(start))
        entries.append({"startMs": start_ms, "speaker": speaker, "text": text})
    entries.sort(key=lambda e: e["startMs"])
    return entries


def build_segments(
    breakpoints: List[int],
    transcript_entries: List[dict],
    shot_frame_map: Dict[int, str],
    available_frames: Dict[int, str] | None = None,
) -> List[dict]:
    segments: List[dict] = []

    def choose_frame(start_ms: int) -> str | None:
        # Prefer available frames on disk (from frames_dir) if provided; otherwise fall back to shot map.
        if available_frames:
            candidates = [ts for ts in available_frames.keys() if ts <= start_ms]
            if candidates:
                ts = max(candidates)
                return available_frames[ts]
            # fallback to nearest overall
            ts = min(available_frames.keys(), key=lambda x: abs(x - start_ms))
            return available_frames[ts]
        # Fallback to shot map (keyframes)
        candidate_frames = [ts for ts in shot_frame_map.keys() if ts <= start_ms]
        frame_ts = max(candidate_frames) if candidate_frames else (min(shot_frame_map.keys()) if shot_frame_map else None)
        return shot_frame_map.get(frame_ts) if frame_ts is not None else None

    for i in range(len(breakpoints) - 1):
        start_ms = breakpoints[i]
        end_ms = breakpoints[i + 1]
        window = [t for t in transcript_entries if start_ms <= t["startMs"] < end_ms]
        text = " ".join([w["text"] for w in window]).strip()
        speakers = [w["speaker"] for w in window if w.get("speaker") is not None]
        speaker = speakers[0] if speakers else None
        frame_path = choose_frame(start_ms)
        segments.append(
            {
                "segmentStartMs": start_ms,
                "segmentEndMs": end_ms,
                "framePath": frame_path,
                "speaker": speaker,
                "text": text,
                "source": "VI",
            }
        )
    return segments


def load_available_frames(frames_dir: Path) -> Dict[int, str]:
    frames = {}
    if not frames_dir.exists():
        return frames
    for f in frames_dir.glob("*.jpg"):
        try:
            ts = int(f.stem)
            frames[ts] = str(f.resolve())
        except ValueError:
            continue
    return frames


def upload_manifest(bsc: BlobServiceClient, container: str, blob_name: str, data: dict):
    container_client = bsc.get_container_client(container)
    try:
        container_client.create_container()
    except Exception:
        # ignore if exists or creation not needed
        pass
    container_client.upload_blob(
        name=blob_name,
        data=json.dumps(data).encode("utf-8"),
        overwrite=True,
        content_type="application/json",
    )
    print(f"Uploaded manifest to blob: {container}/{blob_name}")


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    # Inputs: job, index source, storage, VI creds
    parser.add_argument("--job-id", default=os.getenv("JOB_ID"))
    parser.add_argument("--index-file", default=os.getenv("VI_INDEX_FILE", "tmp/index.json"), help="Local index JSON path")
    parser.add_argument("--index-blob", default=None, help="Index blob path (default {jobId}/index.json if provided)")
    parser.add_argument("--vi-container", default=os.getenv("AZURE_STORAGE_CONTAINER_VI", "video-indexer"))
    parser.add_argument("--manifests-container", default=os.getenv("AZURE_STORAGE_CONTAINER_MANIFESTS", "manifests"))
    parser.add_argument("--storage-conn", default=os.getenv("AZURE_STORAGE_CONNECTION_STRING"))
    parser.add_argument("--storage-account", default=os.getenv("AZURE_STORAGE_ACCOUNT"))
    parser.add_argument("--frames-dir", default=None, help="Directory containing extracted frames (default tmp/frames/{jobId})")
    parser.add_argument(
        "--auth-mode",
        choices=["key", "aad"],
        default=os.getenv("AZURE_STORAGE_AUTH_MODE", "key"),
        help="Storage auth for blob access (index download/upload).",
    )
    parser.add_argument("--api-base", default=os.getenv("VIDEO_INDEXER_API_BASE", "https://api.videoindexer.ai"))
    parser.add_argument("--account-id", default=os.getenv("VIDEO_INDEXER_ACCOUNT_ID"))
    parser.add_argument("--location", default=os.getenv("VIDEO_INDEXER_LOCATION"))
    parser.add_argument("--subscription-key", default=os.getenv("VIDEO_INDEXER_SUBSCRIPTION_KEY"))
    parser.add_argument("--output", default=None, help="Local output manifest path (default tmp/manifest.json)")
    parser.add_argument("--skip-upload", action="store_true", help="Do not upload manifest to Blob")
    args = parser.parse_args()

    # Validate inputs.
    if not args.job_id:
        sys.exit("Missing --job-id or env JOB_ID")
    if not args.account_id or not args.location or not args.subscription_key:
        sys.exit("Missing Video Indexer credentials")
    if (args.index_blob or not args.skip_upload) and args.auth_mode == "key" and not args.storage_conn:
        sys.exit("Missing storage connection string for key auth")
    if (args.index_blob or not args.skip_upload) and args.auth_mode == "aad" and not args.storage_account:
        sys.exit("Missing storage account name for AAD auth")

    bsc: BlobServiceClient | None = None
    if args.index_blob or not args.skip_upload:
        bsc = make_blob_service(args)

    # Load index data from local or blob.
    if args.index_blob:
        blob_path = args.index_blob or f"{args.job_id}/index.json"
        if not bsc:
            sys.exit("Blob client not initialized; cannot read index from blob.")
        print(f"Reading index from blob {args.vi_container}/{blob_path} ...")
        index_data = read_index_blob(bsc, args.vi_container, blob_path)
    else:
        print(f"Reading index from local file {args.index_file} ...")
        index_data = read_index_local(Path(args.index_file))

    # Get VI token (for completeness; not used for alignment but available if needed).
    token = get_access_token(args.api_base, args.location, args.account_id, args.subscription_key)
    _ = token  # placeholder; token not required for alignment logic here.

    # Build breakpoints: shots + speaker changes.
    shot_starts = extract_shot_boundaries(index_data)
    speaker_changes = extract_speaker_changes(index_data)
    breakpoints = sorted(set(shot_starts + speaker_changes))
    # Ensure we have at least a starting breakpoint.
    if not breakpoints:
        sys.exit("No breakpoints found in insights (shots or speaker changes).")

    # Map shot frame paths (assumes frames saved as frames/{jobId}/{shotStartMs}.jpg).
    shot_frame_map = {s: f"frames/{args.job_id}/{s}.jpg" for s in shot_starts}
    frames_dir = Path(args.frames_dir) if args.frames_dir else Path(f"tmp/frames/{args.job_id}")
    available_frames = load_available_frames(frames_dir)

    transcripts = extract_transcript_entries(index_data)
    segments = build_segments(breakpoints, transcripts, shot_frame_map, available_frames)

    output_path = Path(args.output or "tmp/manifest.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"jobId": args.job_id, "segments": segments}
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Saved manifest locally: {output_path}")

    if not args.skip_upload and bsc:
        manifest_blob = f"{args.job_id}/manifest.json"
        upload_manifest(bsc, args.manifests_container, manifest_blob, payload)

    print("Done.")


if __name__ == "__main__":
    main()
