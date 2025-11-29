"""
Step 6: Summarize aligned segments using Azure OpenAI.

Reads manifest.json (local or blob), summarizes each segment's text, and writes summaries alongside originals.

Usage (env-first):
  python scripts/step6_summarize_segments.py --job-id <id>

Inputs/env:
  JOB_ID
  Manifest source: --manifest-file (default tmp/manifest.json) or --manifest-blob (default {jobId}/manifest.json)
  Storage auth: --auth-mode key|aad (default key)
    key: AZURE_STORAGE_CONNECTION_STRING
    aad: AZURE_STORAGE_ACCOUNT and az login
  Containers: AZURE_STORAGE_CONTAINER_MANIFESTS (default manifests)
  OpenAI: OPENAI_ENDPOINT, OPENAI_API_KEY, OPENAI_DEPLOYMENT
  Output: --output (default tmp/manifest_with_summaries.json), --skip-upload to keep local only

Requires: azure-storage-blob, azure-identity (for aad), openai>=1.0, python-dotenv (optional).
"""

import argparse
import json
import os
import sys
from pathlib import Path

from openai import AzureOpenAI
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


def upload_manifest(bsc: BlobServiceClient, container: str, blob_name: str, data: dict):
    container_client = bsc.get_container_client(container)
    try:
        container_client.create_container()
    except Exception:
        pass
    container_client.upload_blob(
        name=blob_name,
        data=json.dumps(data).encode("utf-8"),
        overwrite=True,
        content_type="application/json",
    )
    print(f"Uploaded manifest with summaries to: {container}/{blob_name}")


def summarize_segments(client: AzureOpenAI, deployment: str, manifest: dict) -> dict:
    segments = manifest.get("segments", [])
    summarized = []
    for seg in segments:
        text = seg.get("text") or ""
        prompt = f"Summarize concisely:\n{text}\n"
        summary = ""
        if text.strip():
            resp = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": "You are a concise technical note-taker. Return 1-3 sentences summarizing the content. For key concepts, keep them as close to the original transcript as possible"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=128,
                temperature=0.2,
            )
            summary = resp.choices[0].message.content.strip()
        seg_out = dict(seg)
        seg_out["summary"] = summary
        summarized.append(seg_out)
    out = dict(manifest)
    out["segments"] = summarized
    return out


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", default=os.getenv("JOB_ID"))
    parser.add_argument("--manifest-file", default="tmp/manifest.json")
    parser.add_argument("--manifest-blob", default=None)
    parser.add_argument("--manifests-container", default=os.getenv("AZURE_STORAGE_CONTAINER_MANIFESTS", "manifests"))
    parser.add_argument("--auth-mode", choices=["key", "aad"], default=os.getenv("AZURE_STORAGE_AUTH_MODE", "key"))
    parser.add_argument("--storage-conn", default=os.getenv("AZURE_STORAGE_CONNECTION_STRING"))
    parser.add_argument("--storage-account", default=os.getenv("AZURE_STORAGE_ACCOUNT"))
    parser.add_argument("--output", default="tmp/manifest_with_summaries.json")
    parser.add_argument("--skip-upload", action="store_true")
    parser.add_argument("--openai-endpoint", default=os.getenv("OPENAI_ENDPOINT"))
    parser.add_argument("--openai-api-key", default=os.getenv("OPENAI_API_KEY"))
    parser.add_argument("--openai-deployment", default=os.getenv("OPENAI_DEPLOYMENT"))
    args = parser.parse_args()

    if not args.job_id:
        sys.exit("Missing job id")
    if not args.openai_endpoint or not args.openai_api_key or not args.openai_deployment:
        sys.exit("Missing OpenAI settings (endpoint/key/deployment)")
    if (args.manifest_blob or not args.skip_upload) and args.auth_mode == "key" and not args.storage_conn:
        sys.exit("Missing storage connection string for key auth")
    if (args.manifest_blob or not args.skip_upload) and args.auth_mode == "aad" and not args.storage_account:
        sys.exit("Missing storage account for AAD auth")

    bsc = None
    if args.manifest_blob or not args.skip_upload:
        bsc = make_blob_service(args)

    if args.manifest_blob:
        blob_path = args.manifest_blob or f"{args.job_id}/manifest.json"
        print(f"Reading manifest from blob {args.manifests_container}/{blob_path} ...")
        manifest = read_manifest_blob(bsc, args.manifests_container, blob_path)
    else:
        print(f"Reading manifest from local file {args.manifest_file} ...")
        manifest = read_manifest_local(Path(args.manifest_file))

    client = AzureOpenAI(
        api_version="2024-07-01-preview",
        azure_endpoint=args.openai_endpoint,
        api_key=args.openai_api_key,
    )

    print("Summarizing segments...")
    manifest_out = summarize_segments(client, args.openai_deployment, manifest)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest_out, indent=2), encoding="utf-8")
    print(f"Saved manifest with summaries locally: {out_path}")

    if not args.skip_upload and bsc:
        blob_out = f"{args.job_id}/manifest_with_summaries.json"
        upload_manifest(bsc, args.manifests_container, blob_out, manifest_out)

    print("Done.")


if __name__ == "__main__":
    main()
