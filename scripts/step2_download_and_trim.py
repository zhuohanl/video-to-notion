"""
Download a YouTube video, trim to 5m20s, and upload to Blob Storage.

Usage:
  python scripts/step2_download_and_trim.py --video-url <url> --job-id <id> \
    --connection-string "<storage-connection-string>" \
    [--raw-container raw] [--output-dir ./tmp]

Defaults pull from env if set:
  VIDEO_URL, JOB_ID, AZURE_STORAGE_CONNECTION_STRING, AZURE_STORAGE_CONTAINER_RAW

Requirements:
  - ffmpeg (installed on PATH)
  - python packages: yt-dlp, azure-storage-blob, python-dotenv (optional)
"""

import argparse
import os
import subprocess
import shutil
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # optional convenience
    def load_dotenv():
        return False

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient


TRIM_DURATION = "00:05:20"


def run(cmd, cwd=None):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result.stdout


def download_video(video_url: str, target_path: Path):
    target_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["yt-dlp", "-f", "best[ext=mp4]/best", "-o", str(target_path), video_url]
    run(cmd)


def trim_video(
    input_path: Path,
    output_path: Path,
    duration: str = TRIM_DURATION,
    reencode: bool = True,
    max_width: int = 1280,
    crf: int = 23,
    audio_bitrate: str = "128k",
    preset: str = "veryfast",
):
    """
    Trim and optionally re-encode to shrink size.
    - reencode=True: scale to max_width, libx264 CRF + AAC audio.
    - reencode=False: stream copy (fast, large files).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if reencode:
        scale_filter = f"scale='min({max_width},iw)':-2"
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-t",
            duration,
            "-vf",
            scale_filter,
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    else:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-t",
            duration,
            "-c",
            "copy",
            str(output_path),
        ]
    run(cmd)


def parse_conn_string(conn: str) -> dict:
    parts = [p for p in conn.split(";") if p]
    kv = {}
    for part in parts:
        if "=" in part:
            k, v = part.split("=", 1)
            kv[k.strip()] = v.strip()
    return kv


def get_az_cmd() -> str | None:
    for name in ("az", "az.cmd", "az.bat"):
        found = shutil.which(name)
        if found:
            return found
    return None


def ensure_shared_key_enabled(account_name: str, resource_group: str):
    """
    Verify allowSharedKeyAccess is enabled. Requires az and a provided resource group.
    """
    az_cmd = get_az_cmd()
    if not az_cmd:
        raise SystemExit("Azure CLI not found on PATH. Install az or pass --skip-shared-key-check to continue.")

    print(f"Checking allowSharedKeyAccess for '{account_name}' in rg '{resource_group}'...", flush=True)
    res = subprocess.run(
        [
            az_cmd,
            "storage",
            "account",
            "show",
            "--name",
            account_name,
            "--resource-group",
            resource_group,
            "--query",
            "allowSharedKeyAccess",
            "-o",
            "tsv",
        ],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        raise SystemExit(
            f"Failed to query allowSharedKeyAccess for '{account_name}'. "
            "Ensure you have permission or pass --skip-shared-key-check."
        )
    flag = res.stdout.strip().lower()
    if flag != "true":
        raise SystemExit(
            f"allowSharedKeyAccess is {flag!r} for storage account '{account_name}'. Enable key auth or pass "
            "--skip-shared-key-check to override (not recommended)."
        )
    print(f"allowSharedKeyAccess is enabled for storage account '{account_name}' (rg: {resource_group}).")


def upload_blob(
    blob_service_client: BlobServiceClient,
    container: str,
    blob_path: str,
    file_path: Path,
    timeout: int = 600,
    max_concurrency: int = 4,
    show_progress: bool = True,
):
    container_client = blob_service_client.get_container_client(container)
    blob_client = container_client.get_blob_client(blob_path)
    total_bytes = file_path.stat().st_size

    def make_progress_hook(total: int):
        state = {"last_bucket": -1}

        def _hook(bytes_transferred, *_, **__):
            if total <= 0:
                return
            pct = int(bytes_transferred * 100 / total)
            bucket = pct // 5  # print every ~5%
            if bucket != state["last_bucket"]:
                state["last_bucket"] = bucket
                print(f"Upload progress: {pct}% ({bytes_transferred}/{total} bytes)", flush=True)

        return _hook

    progress_hook = make_progress_hook(total_bytes) if show_progress else None

    with file_path.open("rb") as data:
        blob_client.upload_blob(
            data,
            overwrite=True,
            max_concurrency=max_concurrency,
            timeout=timeout,
            progress_hook=progress_hook,
        )


def main():
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--video-url", default=os.getenv("VIDEO_URL"), required=False)
    parser.add_argument("--job-id", default=os.getenv("JOB_ID"), required=False)
    parser.add_argument(
        "--connection-string",
        default=os.getenv("AZURE_STORAGE_CONNECTION_STRING"),
        required=False,
    )
    parser.add_argument(
        "--account-name",
        default=os.getenv("AZURE_STORAGE_ACCOUNT"),
        required=False,
        help="Storage account name (required for AAD auth)",
    )
    parser.add_argument(
        "--raw-container",
        default=os.getenv("AZURE_STORAGE_CONTAINER_RAW", "raw"),
        required=False,
    )
    parser.add_argument(
        "--resource-group",
        required=False,
        default=os.getenv("AZURE_STORAGE_RESOURCE_GROUP") or os.getenv("AZURE_RESOURCE_GROUP"),
        help="Resource group for storage account (for shared key check)",
    )
    parser.add_argument("--output-dir", default="./tmp", required=False)
    parser.add_argument("--upload-timeout", type=int, default=600, help="Upload timeout per request in seconds")
    parser.add_argument("--upload-concurrency", type=int, default=4, help="Max concurrency for block uploads")
    parser.add_argument("--no-upload-progress", action="store_true", help="Disable upload progress output")
    parser.add_argument("--max-width", type=int, default=1280, help="Max video width when re-encoding")
    parser.add_argument("--crf", type=int, default=23, help="CRF for libx264 (lower = higher quality/larger size)")
    parser.add_argument("--audio-bitrate", default="128k", help="Audio bitrate when re-encoding (e.g., 96k, 128k)")
    parser.add_argument("--preset", default="veryfast", help="libx264 preset (ultrafast..placebo)")
    parser.add_argument("--no-reencode", action="store_true", help="Skip re-encode; use stream copy (larger files)")
    parser.add_argument("--skip-shared-key-check", action="store_true", help="Skip verifying allowSharedKeyAccess via az")
    parser.add_argument(
        "--auth-mode",
        choices=["key", "aad"],
        default=os.getenv("AZURE_STORAGE_AUTH_MODE", "key"),
        help="Storage auth mode: 'key' (connection string) or 'aad' (DefaultAzureCredential).",
    )
    args = parser.parse_args()

    if not args.video_url:
        sys.exit("Missing --video-url (or env VIDEO_URL)")
    if not args.job_id:
        sys.exit("Missing --job-id (or env JOB_ID)")
    if args.auth_mode == "key" and not args.connection_string:
        sys.exit("Missing --connection-string (or env AZURE_STORAGE_CONNECTION_STRING) for key auth")
    if args.auth_mode == "aad" and not args.account_name:
        sys.exit("Missing --account-name (or env AZURE_STORAGE_ACCOUNT) for AAD auth")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_path = output_dir / f"{args.job_id}.mp4"
    trimmed_path = output_dir / f"{args.job_id}_trimmed.mp4"
    blob_path = f"vid/{args.job_id}.mp4"

    print(f"Downloading {args.video_url} -> {raw_path}")
    download_video(args.video_url, raw_path)

    if args.no_reencode:
        print(f"Trimming (stream copy) to {TRIM_DURATION} -> {trimmed_path}")
        trim_video(raw_path, trimmed_path, duration=TRIM_DURATION, reencode=False)
    else:
        print(
            f"Trimming + re-encoding to {TRIM_DURATION} -> {trimmed_path} "
            f"(max_width={args.max_width}, crf={args.crf}, audio_bitrate={args.audio_bitrate}, preset={args.preset})"
        )
        trim_video(
            raw_path,
            trimmed_path,
            duration=TRIM_DURATION,
            reencode=True,
            max_width=args.max_width,
            crf=args.crf,
            audio_bitrate=args.audio_bitrate,
            preset=args.preset,
        )

    if args.auth_mode == "key":
        conn_parts = parse_conn_string(args.connection_string)
        account_name = conn_parts.get("AccountName")
        if not args.skip_shared_key_check and account_name and args.resource_group:
            ensure_shared_key_enabled(account_name, resource_group=args.resource_group)
        elif not args.skip_shared_key_check and not account_name:
            print("Warning: Could not parse AccountName from connection string; skipping shared key check.", file=sys.stderr)
        elif not args.skip_shared_key_check and not args.resource_group:
            print("Warning: Resource group not provided; skipping shared key check. Set --resource-group or AZURE_STORAGE_RESOURCE_GROUP.", file=sys.stderr)
        blob_service_client = BlobServiceClient.from_connection_string(args.connection_string)
    else:
        credential = DefaultAzureCredential(exclude_interactive_browser_credential=False)
        account_url = f"https://{args.account_name}.blob.core.windows.net"
        blob_service_client = BlobServiceClient(account_url=account_url, credential=credential)

    print(f"Uploading to container '{args.raw_container}' blob '{blob_path}'")
    upload_blob(
        blob_service_client=blob_service_client,
        container=args.raw_container,
        blob_path=blob_path,
        file_path=trimmed_path,
        timeout=args.upload_timeout,
        max_concurrency=args.upload_concurrency,
        show_progress=not args.no_upload_progress,
    )

    print("Done.")


if __name__ == "__main__":
    main()
