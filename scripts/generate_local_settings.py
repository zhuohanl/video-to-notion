"""
Generate local.settings.json for Azure Functions from a .env file.

Usage:
  python scripts/generate_local_settings.py [--env .env] [--output local.settings.json]

Notes:
- Expects key=value lines; ignores blanks and lines starting with '#'.
- Sets FUNCTIONS_WORKER_RUNTIME=python.
- Mirrors AZURE_STORAGE_CONNECTION_STRING into AzureWebJobsStorage for Functions host.
"""

import argparse
import json
import os
from pathlib import Path


def parse_env(path: Path) -> dict:
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default=".env", help="Path to .env file")
    parser.add_argument(
        "--output", default="local.settings.json", help="Output Functions settings file"
    )
    args = parser.parse_args()

    env_path = Path(args.env)
    if not env_path.exists():
        raise SystemExit(f"Missing env file: {env_path}")

    env_vars = parse_env(env_path)

    values = {"FUNCTIONS_WORKER_RUNTIME": "python"}
    # Copy everything from .env into Values for convenience
    values.update(env_vars)
    # Ensure Functions storage binding is populated
    if "AZURE_STORAGE_CONNECTION_STRING" in env_vars:
        values["AzureWebJobsStorage"] = env_vars["AZURE_STORAGE_CONNECTION_STRING"]

    data = {"IsEncrypted": False, "Values": values}

    output_path = Path(args.output)
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {output_path} with {len(values)} Values entries.")


if __name__ == "__main__":
    main()
