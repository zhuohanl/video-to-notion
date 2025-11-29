"""
Upload a video to Azure Video Indexer via SAS URL, poll until processed, and save the insights JSON locally and to Blob.

Usage (env-first):
  python scripts/vi_upload_and_poll.py --job-id <id>

Key env vars / flags:
  VIDEO_INDEXER_ACCOUNT_ID
  VIDEO_INDEXER_LOCATION (e.g., trial, westus2, westeurope)
  VIDEO_INDEXER_SUBSCRIPTION_KEY
  VIDEO_INDEXER_API_BASE (default https://api.videoindexer.ai)
  AZURE_STORAGE_CONNECTION_STRING
  AZURE_STORAGE_CONTAINER_RAW (default raw)     # where vid/{jobId}.mp4 lives
  AZURE_STORAGE_CONTAINER_VI (default video-indexer)  # where to write index.json
  JOB_ID, VIDEO_URL (optional overrides)

Requires: requests, azure-storage-blob, python-dotenv (optional).
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from azure.identity import DefaultAzureCredential
from azure.storage.blob import (
    BlobServiceClient,
    BlobSasPermissions,
    generate_blob_sas,
)

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # optional convenience
    def load_dotenv():
        return False


POLL_INTERVAL = 30  # seconds
POLL_TIMEOUT = 60 * 30  # 30 minutes


def get_access_token(api_base: str, location: str, account_id: str, subscription_key: str) -> str:
    url = f"{api_base}/Auth/{location}/Accounts/{account_id}/AccessToken"
    params = {"allowEdit": "true"}
    headers = {"Ocp-Apim-Subscription-Key": subscription_key}
    resp = requests.get(url, params=params, headers=headers, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"Access token request failed: {resp.status_code} {resp.text}")
    return resp.text.strip().strip('"')


def build_blob_sas_url_with_key(conn_str: str, container: str, blob_name: str, ttl_hours: int = 24) -> str:
    account = BlobServiceClient.from_connection_string(conn_str)
    account_key = getattr(account.credential, "account_key", None)  # type: ignore[attr-defined]
    if not account_key:
        raise RuntimeError(
            "No account key found in storage connection string. "
            "Ensure key-based auth is enabled and the connection string contains AccountKey. "
            "Alternatively, provide --video-sas-url to skip SAS generation."
        )
    sas = generate_blob_sas(
        account_name=account.account_name,
        container_name=container,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(timezone.utc) + timedelta(hours=ttl_hours),
    )
    blob_client = account.get_blob_client(container=container, blob=blob_name)
    return f"{blob_client.url}?{sas}"


def build_blob_sas_url_with_aad(
    account_name: str,
    container: str,
    blob_name: str,
    credential: DefaultAzureCredential,
    ttl_hours: int = 24,
) -> str:
    account_url = f"https://{account_name}.blob.core.windows.net"
    service = BlobServiceClient(account_url=account_url, credential=credential)
    start = datetime.now(timezone.utc) - timedelta(minutes=5)
    expiry = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    udk = service.get_user_delegation_key(key_start_time=start, key_expiry_time=expiry)
    sas = generate_blob_sas(
        account_name=account_name,
        container_name=container,
        blob_name=blob_name,
        user_delegation_key=udk,
        permission=BlobSasPermissions(read=True),
        expiry=expiry,
        start=start,
    )
    blob_client = service.get_blob_client(container=container, blob=blob_name)
    return f"{blob_client.url}?{sas}"


def upload_video(
    api_base: str,
    location: str,
    account_id: str,
    token: str,
    video_name: str,
    video_url: str,
    language: str = "en-US",
) -> str:
    url = f"{api_base}/{location}/Accounts/{account_id}/Videos"
    params = {
        "accessToken": token,
        "name": video_name,
        "privacy": "Private",
        "videoUrl": video_url,
        "videoLanguage": language,
    }
    resp = requests.post(url, params=params, timeout=30)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Video upload failed: {resp.status_code} {resp.text}")
    data = resp.json()
    vid = data.get("id")
    if not vid:
        raise RuntimeError(f"No video id in response: {data}")
    return vid


def poll_index(
    api_base: str,
    location: str,
    account_id: str,
    token: str,
    video_id: str,
    interval: int = POLL_INTERVAL,
    timeout: int = POLL_TIMEOUT,
):
    url = f"{api_base}/{location}/Accounts/{account_id}/Videos/{video_id}/Index"
    params = {"accessToken": token}
    start = time.time()
    while True:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"Index poll failed: {resp.status_code} {resp.text}")
        data = resp.json()
        state = data.get("state")
        print(f"[poll] state={state}")
        if state == "Processed":
            return data
        if state in ("Failed", "Error"):
            raise RuntimeError(f"Video Indexer processing failed: {data}")
        if time.time() - start > timeout:
            raise TimeoutError("Polling timed out")
        time.sleep(interval)


def save_index_local(data: dict, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Saved index locally: {path}")


def upload_index_blob(
    blob_service_client: BlobServiceClient,
    container: str,
    blob_name: str,
    data: dict,
):
    container_client = blob_service_client.get_container_client(container)
    container_client.upload_blob(
        name=blob_name,
        data=json.dumps(data).encode("utf-8"),
        overwrite=True,
        content_type="application/json",
    )
    print(f"Uploaded index to blob: {container}/{blob_name}")


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", default=os.getenv("JOB_ID"), required=False)
    parser.add_argument("--video-url", default=os.getenv("VIDEO_URL"), required=False, help="YouTube URL (unused if blob is used)")
    parser.add_argument("--api-base", default=os.getenv("VIDEO_INDEXER_API_BASE", "https://api.videoindexer.ai"))
    parser.add_argument("--account-id", default=os.getenv("VIDEO_INDEXER_ACCOUNT_ID"))
    parser.add_argument("--location", default=os.getenv("VIDEO_INDEXER_LOCATION"))
    parser.add_argument("--subscription-key", default=os.getenv("VIDEO_INDEXER_SUBSCRIPTION_KEY"))
    parser.add_argument("--storage-conn", default=os.getenv("AZURE_STORAGE_CONNECTION_STRING"))
    parser.add_argument("--storage-account", default=os.getenv("AZURE_STORAGE_ACCOUNT"))
    parser.add_argument("--raw-container", default=os.getenv("AZURE_STORAGE_CONTAINER_RAW", "raw"))
    parser.add_argument("--vi-container", default=os.getenv("AZURE_STORAGE_CONTAINER_VI", "video-indexer"))
    parser.add_argument("--blob-path", default=None, help="Blob path for the trimmed video, default vid/{jobId}.mp4")
    parser.add_argument("--video-sas-url", default=None, help="Provide a pre-built SAS URL; skips SAS generation")
    parser.add_argument("--language", default="en-US")
    parser.add_argument("--ttl-hours", type=int, default=24, help="SAS TTL hours for the video URL")
    parser.add_argument("--output", default="tmp/index.json", help="Local path to save index JSON")
    parser.add_argument("--skip-blob-upload", action="store_true", help="Skip uploading index.json to Blob")
    parser.add_argument(
        "--auth-mode",
        choices=["key", "aad"],
        default=os.getenv("AZURE_STORAGE_AUTH_MODE", "key"),
        help="Storage auth mode for SAS generation: 'key' (connection string) or 'aad' (user delegation SAS via DefaultAzureCredential).",
    )
    args = parser.parse_args()

    if not args.job_id:
        sys.exit("Missing --job-id or env JOB_ID")
    if not args.account_id or not args.location or not args.subscription_key:
        sys.exit("Missing Video Indexer credentials (account id, location, subscription key)")
    if args.auth_mode == "key" and not args.storage_conn:
        sys.exit("Missing storage connection string (AZURE_STORAGE_CONNECTION_STRING) for key auth")
    if args.auth_mode == "aad" and not args.storage_account:
        sys.exit("Missing storage account name (AZURE_STORAGE_ACCOUNT) for AAD auth")

    blob_path = args.blob_path or f"vid/{args.job_id}.mp4"

    # Build or use provided SAS URL for the trimmed video in Blob.
    if args.video_sas_url:
        sas_url = args.video_sas_url
        print("Using provided SAS URL for video.")
    else:
        print(f"Building SAS URL for blob '{blob_path}' in container '{args.raw_container}'...")
        if args.auth_mode == "aad":
            credential = DefaultAzureCredential(exclude_interactive_browser_credential=False)
            sas_url = build_blob_sas_url_with_aad(
                account_name=args.storage_account,
                container=args.raw_container,
                blob_name=blob_path,
                credential=credential,
                ttl_hours=args.ttl_hours,
            )
        else:
            sas_url = build_blob_sas_url_with_key(args.storage_conn, args.raw_container, blob_path, ttl_hours=args.ttl_hours)

    # Get VI access token.
    print("Requesting Video Indexer access token...")
    token = get_access_token(args.api_base, args.location, args.account_id, args.subscription_key)

    # Upload and start indexing.
    print("Uploading video to Video Indexer and starting indexing...")
    video_id = upload_video(
        args.api_base,
        args.location,
        args.account_id,
        token,
        video_name=args.job_id,
        video_url=sas_url,
        language=args.language,
    )
    print(f"Video Indexer upload started. video_id={video_id}")

    # Poll for completion.
    print("Polling for indexing completion...")
    index_data = poll_index(args.api_base, args.location, args.account_id, token, video_id)

    # Save locally.
    save_index_local(index_data, Path(args.output))

    # Load index_data from the local file
    with open(args.output, "r", encoding="utf-8") as f:
        index_data = json.load(f)

    # Save to Blob if desired.
    if not args.skip_blob_upload:
        target_blob = f"{args.job_id}/index.json" if args.job_id else "index.json"
        # Choose auth mode for uploading the index as well.
        if args.auth_mode == "aad":
            credential = DefaultAzureCredential(exclude_interactive_browser_credential=False)
            account_url = f"https://{args.storage_account}.blob.core.windows.net"
            upload_bsc = BlobServiceClient(account_url=account_url, credential=credential)
        else:
            upload_bsc = BlobServiceClient.from_connection_string(args.storage_conn)
        upload_index_blob(upload_bsc, args.vi_container, target_blob, index_data)

    print("Done.")


if __name__ == "__main__":
    main()
