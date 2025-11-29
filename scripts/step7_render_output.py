"""
Step 7: Render HTML/Markdown from summarized segments.

Reads manifest_with_summaries.json (local or blob) and produces an HTML or Markdown file with image refs and text.

Usage (env-first):
  python scripts/step7_render_output.py --job-id <id> --format html

Inputs/env:
  JOB_ID
  Source: --manifest-file (default tmp/manifest_with_summaries.json) or --manifest-blob (default {jobId}/manifest_with_summaries.json)
  Storage auth: --auth-mode key|aad (default key), plus:
    key: AZURE_STORAGE_CONNECTION_STRING
    aad: AZURE_STORAGE_ACCOUNT and az login
  Containers: AZURE_STORAGE_CONTAINER_MANIFESTS (default manifests)
  Output: --format html|md (default html), --output (default tmp/output.html|md), --skip-upload
  Upload target: AZURE_STORAGE_CONTAINER_OUTPUTS (default outputs)

Requires: azure-storage-blob, azure-identity (for aad), python-dotenv (optional).
"""

import argparse
import json
import os
import sys
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv():
        return False


def make_blob_service(args) -> BlobServiceClient:
    if args.auth_mode == "aad":
        cred = DefaultAzureCredential(exclude_interactive_browser_credential=False)
        return BlobServiceClient(
            account_url=f"https://{args.storage_account}.blob.core.windows.net",
            credential=cred,
        )
    return BlobServiceClient.from_connection_string(args.storage_conn)


def read_manifest_local(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_manifest_blob(bsc: BlobServiceClient, container: str, blob_name: str) -> dict:
    blob = bsc.get_blob_client(container=container, blob=blob_name)
    data = blob.download_blob().readall()
    return json.loads(data)


def upload_output(bsc: BlobServiceClient, container: str, blob_name: str, data: str, content_type: str):
    container_client = bsc.get_container_client(container)
    try:
        container_client.create_container()
    except Exception:
        pass
    container_client.upload_blob(
        name=blob_name,
        data=data.encode("utf-8"),
        overwrite=True,
        content_type=content_type,
    )
    print(f"Uploaded output to blob: {container}/{blob_name}")


def absolutize_frame(manifest: dict, frame_base_url: str | None, frame_local_dir: Path | None) -> dict:
    """
    If framePath is relative, turn it into frameUrl using base URL or local file:// for preview.
    """
    out = dict(manifest)
    segments = []
    for seg in manifest.get("segments", []):
        seg_out = dict(seg)
        frame = seg.get("framePath")
        if frame:
            # If already absolute URL/file URI, keep as-is.
            if frame.lower().startswith(("http://", "https://", "file://")):
                pass
            else:
                frame_path = Path(frame)
                if frame_path.is_absolute():
                    seg_out["frameUrl"] = frame_path.as_uri()
                elif frame_base_url:
                    prefix = frame_base_url.rstrip("/")
                    seg_out["frameUrl"] = f"{prefix}/{frame.lstrip('/')}"
                elif frame_local_dir:
                    local_path = (frame_local_dir / frame).resolve()
                    seg_out["frameUrl"] = local_path.as_uri()
        segments.append(seg_out)
    out["segments"] = segments
    return out


def render_md(manifest: dict) -> str:
    lines = []
    lines.append(f"# {manifest.get('jobId', 'Video Notes')}")
    for seg in manifest.get("segments", []):
        ts = seg.get("segmentStartMs")
        frame = seg.get("frameUrl") or seg.get("framePath")
        speaker = seg.get("speaker")
        summary = seg.get("summary") or seg.get("text") or ""
        if frame:
            lines.append(f"![frame]({frame})")
        meta = []
        if ts is not None:
            meta.append(f"t={ts}ms")
        if speaker is not None:
            meta.append(f"speaker={speaker}")
        if meta:
            lines.append(f"*{' | '.join(meta)}*")
        lines.append("")
        lines.append(summary)
        lines.append("")
    return "\n".join(lines)


def render_html(manifest: dict) -> str:
    parts = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'><title>Video Notes</title></head><body>",
        f"<h1>{manifest.get('jobId', 'Video Notes')}</h1>",
    ]
    for seg in manifest.get("segments", []):
        ts = seg.get("segmentStartMs")
        frame = seg.get("frameUrl") or seg.get("framePath")
        speaker = seg.get("speaker")
        summary = seg.get("summary") or seg.get("text") or ""
        parts.append("<div style='margin-bottom:24px;'>")
        if frame:
            parts.append(f"<img src='{frame}' alt='frame' style='max-width:100%;height:auto;'/>")
        meta = []
        if ts is not None:
            meta.append(f"t={ts}ms")
        if speaker is not None:
            meta.append(f"speaker={speaker}")
        if meta:
            parts.append(f"<div><em>{' | '.join(meta)}</em></div>")
        parts.append(f"<p>{summary}</p>")
        parts.append("</div>")
    parts.append("</body></html>")
    return "\n".join(parts)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", default=os.getenv("JOB_ID"))
    parser.add_argument("--manifest-file", default="tmp/manifest_with_summaries.json")
    parser.add_argument("--manifest-blob", default=None)
    parser.add_argument("--manifests-container", default=os.getenv("AZURE_STORAGE_CONTAINER_MANIFESTS", "manifests"))
    parser.add_argument("--auth-mode", choices=["key", "aad"], default=os.getenv("AZURE_STORAGE_AUTH_MODE", "key"))
    parser.add_argument("--storage-conn", default=os.getenv("AZURE_STORAGE_CONNECTION_STRING"))
    parser.add_argument("--storage-account", default=os.getenv("AZURE_STORAGE_ACCOUNT"))
    parser.add_argument("--format", choices=["html", "md"], default="html")
    parser.add_argument("--output", default=None)
    parser.add_argument("--skip-upload", action="store_true")
    parser.add_argument("--outputs-container", default=os.getenv("AZURE_STORAGE_CONTAINER_OUTPUTS", "outputs"))
    parser.add_argument("--frame-base-url", default=os.getenv("FRAME_BASE_URL"), help="Prefix for relative frame paths, e.g., https://acct.blob.core.windows.net/frames")
    parser.add_argument("--frame-local-dir", default=None, help="Local dir containing frames for file:// resolution during local preview")
    args = parser.parse_args()

    if not args.job_id:
        sys.exit("Missing job id")
    if (args.manifest_blob or not args.skip_upload) and args.auth_mode == "key" and not args.storage_conn:
        sys.exit("Missing storage connection string for key auth")
    if (args.manifest_blob or not args.skip_upload) and args.auth_mode == "aad" and not args.storage_account:
        sys.exit("Missing storage account for AAD auth")

    bsc = None
    if args.manifest_blob or not args.skip_upload:
        bsc = make_blob_service(args)

    if args.manifest_blob:
        blob_path = args.manifest_blob or f"{args.job_id}/manifest_with_summaries.json"
        print(f"Reading manifest from blob {args.manifests_container}/{blob_path} ...")
        manifest = read_manifest_blob(bsc, args.manifests_container, blob_path)
        # If no base URL is provided for frames, and manifest is from blob, we cannot infer local path.
        frame_local_dir = Path(args.frame_local_dir) if args.frame_local_dir else None
    else:
        print(f"Reading manifest from local file {args.manifest_file} ...")
        manifest = read_manifest_local(Path(args.manifest_file))
        # Default local frame dir to the manifest's parent if none provided.
        if args.frame_local_dir:
            frame_local_dir = Path(args.frame_local_dir)
        else:
            frame_local_dir = Path(args.manifest_file).resolve().parent

    # Normalize frame paths to absolute URLs or file:// for local preview.
    manifest = absolutize_frame(manifest, args.frame_base_url, frame_local_dir)

    if args.format == "md":
        rendered = render_md(manifest)
        content_type = "text/markdown"
        out_path = args.output or "tmp/output.md"
    else:
        rendered = render_html(manifest)
        content_type = "text/html"
        out_path = args.output or "tmp/output.html"

    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(rendered, encoding="utf-8")
    print(f"Saved output locally: {out_file}")

    if not args.skip_upload and bsc:
        blob_out = f"{args.job_id}/output.{args.format}"
        upload_output(bsc, args.outputs_container, blob_out, rendered, content_type)

    print("Done.")


if __name__ == "__main__":
    main()
