"""
Fetch keyframes from Video Indexer insights and save/upload them.

Supports reading index data from a local file or from Blob Storage.

Usage (env-first):
  python scripts/step4_vi_fetch_keyframes.py --job-id <id>

# Local index, AAD upload
  python scripts/step4_vi_fetch_keyframes.py --index-file tmp/index.json --auth-mode aad

# Blob index, key auth
  python scripts/step4_vi_fetch_keyframes.py --index-blob "$($env:JOB_ID)/index.json" --auth-mode key


Key inputs (env or flags):
  JOB_ID
  VIDEO_INDEXER_ACCOUNT_ID
  VIDEO_INDEXER_LOCATION
  VIDEO_INDEXER_SUBSCRIPTION_KEY
  VIDEO_INDEXER_API_BASE (default https://api.videoindexer.ai)
  Source of index data:
    --index-file <path> (default tmp/index.json), or
    --index-blob <path> (default {jobId}/index.json) with storage info
  Storage:
    --auth-mode key|aad (default key)
    --storage-conn (for key auth)
    --storage-account (for aad auth)
    --vi-container (default video-indexer)  # where index.json sits if using blob source
    --frames-container (default frames)     # where to upload frames
  Output:
    --output-dir (default tmp/frames/{jobId})
    --skip-upload (keep frames local only)

Requires: requests, azure-storage-blob, azure-identity (for aad), python-dotenv (optional).
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import requests
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # optional convenience
    def load_dotenv():
        return False


def get_access_token(api_base: str, location: str, account_id: str, subscription_key: str) -> str:
    # Acquire short-lived token for VI API calls.
    url = f"{api_base}/Auth/{location}/Accounts/{account_id}/AccessToken"
    params = {"allowEdit": "true"}
    headers = {"Ocp-Apim-Subscription-Key": subscription_key}
    resp = requests.get(url, params=params, headers=headers, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"Access token request failed: {resp.status_code} {resp.text}")
    return resp.text.strip().strip('"')


def read_index_local(path: Path) -> dict:
    # Load index.json from local disk.
    return json.loads(path.read_text(encoding="utf-8"))


def make_blob_service(args) -> BlobServiceClient:
    # Build Blob client for either key auth or AAD.
    if args.auth_mode == "aad":
        credential = DefaultAzureCredential(exclude_interactive_browser_credential=False)
        account_url = f"https://{args.storage_account}.blob.core.windows.net"
        return BlobServiceClient(account_url=account_url, credential=credential)
    return BlobServiceClient.from_connection_string(args.storage_conn)


def read_index_blob(bsc: BlobServiceClient, container: str, blob_name: str) -> dict:
    # Load index.json from blob storage.
    blob_client = bsc.get_blob_client(container=container, blob=blob_name)
    data = blob_client.download_blob().readall()
    return json.loads(data)


def parse_keyframes(index_data: dict) -> Tuple[str, List[Tuple[str, int]]]:
    """
    Returns (video_id, list of (thumbnailId, startMs)).
    Pulls shot keyframes (first instance per keyframe).
    """
    video_id = index_data.get("id") or index_data.get("videoId")
    shots = (
        index_data.get("videos", [{}])[0]
        .get("insights", {})
        .get("shots", [])
    )
    results: List[Tuple[str, int]] = []
    for shot in shots:
        keyframes = shot.get("keyFrames") or []
        for kf in keyframes:
            inst = (kf.get("instances") or [{}])[0]
            thumb_id = inst.get("thumbnailId")
            start = inst.get("start")
            if not thumb_id or start is None:
                continue
            # convert start (e.g., "0:00:02.000") to ms
            start_ms = time_to_ms(str(start))
            results.append((thumb_id, start_ms))
            break  # one per shot
    if not video_id:
        raise RuntimeError("video_id not found in index data")
    return video_id, results


def time_to_ms(ts: str) -> int:
    # format: h:mm:ss.sss
    parts = ts.split(":")
    if len(parts) != 3:
        return 0
    h, m, s = parts
    seconds = float(h) * 3600 + float(m) * 60 + float(s)
    return int(seconds * 1000)


def fetch_thumbnail(api_base: str, location: str, account_id: str, video_id: str, token: str, thumb_id: str) -> bytes:
    # Download a specific thumbnail (JPEG) from VI for a given video/keyframe.
    url = f"{api_base}/{location}/Accounts/{account_id}/Videos/{video_id}/Thumbnails/{thumb_id}"
    params = {"accessToken": token, "format": "Jpeg"}
    resp = requests.get(url, params=params, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Thumbnail fetch failed for {thumb_id}: {resp.status_code} {resp.text}")
    return resp.content


def save_and_maybe_upload(
    frames: List[Tuple[str, int]],
    video_id: str,
    token: str,
    api_base: str,
    location: str,
    account_id: str,
    output_dir: Path,
    bsc: BlobServiceClient | None,
    frames_container: str,
    job_id: str,
):
    output_dir.mkdir(parents=True, exist_ok=True)
    for thumb_id, start_ms in frames:
        # Fetch, save locally, and optionally upload each frame.
        img_bytes = fetch_thumbnail(api_base, location, account_id, video_id, token, thumb_id)
        filename = f"{start_ms}.jpg"
        local_path = output_dir / filename
        local_path.write_bytes(img_bytes)
        print(f"Saved {local_path}")
        if bsc:
            blob_name = f"{job_id}/{filename}"
            bsc.get_blob_client(container=frames_container, blob=blob_name).upload_blob(
                img_bytes, overwrite=True, content_type="image/jpeg"
            )
            print(f"Uploaded frame to blob: {frames_container}/{blob_name}")


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    # Inputs: job id, index source, storage, VI creds, output settings.
    parser.add_argument("--job-id", default=os.getenv("JOB_ID"))
    parser.add_argument("--index-file", default=os.getenv("VI_INDEX_FILE", "tmp/index.json"), help="Local index JSON path")
    parser.add_argument("--index-blob", default=None, help="Index blob path (default {jobId}/index.json if provided)")
    parser.add_argument("--vi-container", default=os.getenv("AZURE_STORAGE_CONTAINER_VI", "video-indexer"))
    parser.add_argument("--frames-container", default=os.getenv("AZURE_STORAGE_CONTAINER_FRAMES", "frames"))
    parser.add_argument("--storage-conn", default=os.getenv("AZURE_STORAGE_CONNECTION_STRING"))
    parser.add_argument("--storage-account", default=os.getenv("AZURE_STORAGE_ACCOUNT"))
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
    parser.add_argument("--output-dir", default=None, help="Local output dir for frames (default tmp/frames/{jobId})")
    parser.add_argument("--skip-upload", action="store_true", help="Do not upload frames to Blob")
    args = parser.parse_args()

    # Validate inputs for VI and storage access.
    if not args.job_id:
        sys.exit("Missing --job-id or env JOB_ID")
    if not args.account_id or not args.location or not args.subscription_key:
        sys.exit("Missing Video Indexer credentials")

    bsc: BlobServiceClient | None = None
    if args.index_blob or not args.skip_upload:
        if args.auth_mode == "key":
            if not args.storage_conn:
                sys.exit("Missing storage connection string for key auth")
            bsc = BlobServiceClient.from_connection_string(args.storage_conn)
        else:
            if not args.storage_account:
                sys.exit("Missing storage account name for AAD auth")
            cred = DefaultAzureCredential(exclude_interactive_browser_credential=False)
            bsc = BlobServiceClient(account_url=f"https://{args.storage_account}.blob.core.windows.net", credential=cred)

    # 1) Loads `index.json` from local file or blob
    if args.index_blob:
        blob_path = args.index_blob or f"{args.job_id}/index.json"
        if not bsc:
            sys.exit("Blob client not initialized; cannot read index from blob.")
        print(f"Reading index from blob {args.vi_container}/{blob_path} ...")
        index_data = read_index_blob(bsc, args.vi_container, blob_path)
    else:
        print(f"Reading index from local file {args.index_file} ...")
        index_data = read_index_local(Path(args.index_file))

    # 2) Requests a VI access token
    token = get_access_token(args.api_base, args.location, args.account_id, args.subscription_key)

    # 3) From insights, extracts shot keyframes (first instance per shot) and their start timestamps
    video_id, frames = parse_keyframes(index_data)
    print(f"Found {len(frames)} keyframes.")

    output_dir = Path(args.output_dir or f"tmp/frames/{args.job_id}")
    uploader = None if args.skip_upload else bsc

    # 4) Fetches each thumbnail via VI API, saves as `{startMs}.jpg` in `tmp/frames/{jobId}` (or your `--output-dir`)
    # 5) Uploads frames to Blob `frames/{jobId}/{startMs}.jpg` unless `--skip-upload`
    save_and_maybe_upload(
        frames,
        video_id,
        token,
        args.api_base,
        args.location,
        args.account_id,
        output_dir,
        uploader,
        args.frames_container,
        args.job_id,
    )
    print("Done.")


if __name__ == "__main__":
    main()
