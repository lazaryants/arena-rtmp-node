#!/usr/bin/env python3
"""Check or explicitly migrate the node configuration without printing secrets."""

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config_migrations import migrate_config  # noqa: E402
from app.config_store import CURRENT_SCHEMA_VERSION, ConfigStore  # noqa: E402


def fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def protected_backup(path, version):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.backup-v{version}-{stamp}")
    if backup.exists():
        raise FileExistsError(f"backup already exists: {backup}")
    temporary_path = None
    try:
        with path.open("rb") as source, tempfile.NamedTemporaryFile(
            mode="w+b",
            dir=path.parent,
            prefix=f".{backup.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            os.fchmod(temporary.fileno(), 0o600)
            shutil.copyfileobj(source, temporary)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, backup)
        temporary_path = None
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    fsync_directory(path.parent)
    return backup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="create a protected backup and atomically install the migration",
    )
    arguments = parser.parse_args()

    path = arguments.config.resolve()
    original_stat = path.stat()
    with path.open("r", encoding="utf-8") as file:
        original = json.load(file)
    migrated, original_version = migrate_config(original)

    if original_version == CURRENT_SCHEMA_VERSION:
        print(f"Configuration schema is current: {CURRENT_SCHEMA_VERSION}")
        return 0
    if not arguments.apply:
        print(
            f"Migration required: schema {original_version} -> "
            f"{CURRENT_SCHEMA_VERSION}. No files changed."
        )
        return 2

    backup = protected_backup(path, original_version)
    ConfigStore(path).save(migrated)
    os.chown(path, original_stat.st_uid, original_stat.st_gid)
    path.chmod(0o600)
    with path.open("rb") as file:
        os.fsync(file.fileno())
    fsync_directory(path.parent)
    print(
        f"Migrated schema {original_version} -> {CURRENT_SCHEMA_VERSION}. "
        f"Protected backup: {backup}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
