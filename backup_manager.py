import argparse
import json
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from account_context import BASE_DIR
from app_version import get_version_info


BACKUP_DIR = BASE_DIR / "backups"


PRIVATE_BACKUP_FILES = [
    "osrs_flip_scanner.db",
    ".env",
    ".osrs_runtime/current_user.json",
    "logs/health_check.txt",
    "logs/release_check.txt",
    "logs/migration_report.txt",
    "logs/safety_review.csv",
]


def now_stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def safe_arcname(path):
    try:
        return str(path.relative_to(BASE_DIR)).replace("\\", "/")
    except Exception:
        return path.name


def add_file_if_exists(zip_handle, path, manifest_files):
    path = Path(path)

    if not path.exists() or not path.is_file():
        return False

    arcname = safe_arcname(path)
    zip_handle.write(path, arcname)
    manifest_files.append({
        "path": arcname,
        "size_bytes": path.stat().st_size
    })
    return True


def create_private_backup(reason="manual", include_logs=True):
    """
    Creates a private local backup zip.

    This backup may include private data:
    - SQLite database
    - encrypted per-account OpenAI key records
    - local account records
    - current session
    - .env, if present
    - selected logs/reports

    Do not share this zip publicly.
    """
    BACKUP_DIR.mkdir(exist_ok=True)

    version = get_version_info()
    stamp = now_stamp()
    backup_path = BACKUP_DIR / f"private_backup_{version.get('app_version', 'unknown')}_{stamp}.zip"

    manifest = {
        "created_at": now_utc(),
        "reason": reason,
        "type": "private_backup",
        "app_version": version,
        "base_dir": str(BASE_DIR),
        "warning": "This backup can contain private local data. Do not share publicly.",
        "files": [],
        "missing": []
    }

    files_to_backup = list(PRIVATE_BACKUP_FILES)

    if not include_logs:
        files_to_backup = [
            item for item in files_to_backup
            if not item.startswith("logs/")
        ]

    with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_handle:
        for rel_path in files_to_backup:
            path = BASE_DIR / rel_path

            if not add_file_if_exists(zip_handle, path, manifest["files"]):
                manifest["missing"].append(rel_path)

        # Also include a lightweight manifest inside the zip.
        zip_handle.writestr(
            "backup_manifest.json",
            json.dumps(manifest, indent=2)
        )

    return {
        "path": str(backup_path),
        "manifest": manifest,
        "file_count": len(manifest["files"]),
        "missing_count": len(manifest["missing"])
    }


def main():
    parser = argparse.ArgumentParser(
        description="Create a private OSRSFlipper backup before updates."
    )

    parser.add_argument("--reason", default="manual")
    parser.add_argument("--no-logs", action="store_true")

    args = parser.parse_args()

    result = create_private_backup(
        reason=args.reason,
        include_logs=not args.no_logs
    )

    print("\n==============================")
    print(" OSRSFlipper Private Backup")
    print("==============================")
    print(f"Backup: {result['path']}")
    print(f"Files: {result['file_count']}")
    print(f"Missing optional files: {result['missing_count']}")
    print()
    print("This backup may contain private data. Do not share it publicly.")


if __name__ == "__main__":
    main()
