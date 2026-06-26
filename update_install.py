import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_TARGET = Path(r"C:\OSRSFlipper")


PRIVATE_PRESERVE_NAMES = {
    ".env",
    ".osrs_runtime",
    "osrs_flip_scanner.db",
    "logs",
    "backups",
    "exports",
    "releases",
    "runelite_imports",
    ".venv",
    "__pycache__",
    "build",
}

PRIVATE_PRESERVE_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".log",
}

PRIVATE_BACKUP_ITEMS = [
    "osrs_flip_scanner.db",
    ".env",
    ".osrs_runtime",
    "logs/health_check.txt",
    "logs/release_check.txt",
    "logs/migration_report.txt",
    "logs/safety_review.csv",
]

REPORT_NAME = "update_install_report.txt"


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def now_stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def same_path(left, right):
    try:
        return Path(left).resolve().samefile(Path(right).resolve())
    except Exception:
        return str(Path(left).resolve()).lower() == str(Path(right).resolve()).lower()


def is_private_or_runtime_path(path, source_root):
    rel = Path(path).relative_to(source_root)
    parts = rel.parts

    if not parts:
        return False

    if parts[0] in PRIVATE_PRESERVE_NAMES:
        return True

    if rel.name.lower().endswith(".spec"):
        return True

    if rel.suffix.lower() in PRIVATE_PRESERVE_SUFFIXES and parts[0] not in ("dist",):
        return True

    if "__pycache__" in parts:
        return True

    return False


def get_release_version(source_root):
    app_version_file = source_root / "app_version.py"

    if not app_version_file.exists():
        return "unknown"

    namespace = {}

    try:
        exec(app_version_file.read_text(encoding="utf-8"), namespace)
        return str(namespace.get("APP_VERSION", "unknown"))
    except Exception:
        return "unknown"


def get_python_runner(target_root):
    venv_python = target_root / ".venv" / "Scripts" / "python.exe"

    if venv_python.exists():
        return str(venv_python)

    return sys.executable


def ensure_target(target_root):
    target_root.mkdir(parents=True, exist_ok=True)
    (target_root / "logs").mkdir(exist_ok=True)
    (target_root / "backups").mkdir(exist_ok=True)


def add_backup_file(zip_handle, target_root, rel_path, files, missing):
    source = target_root / rel_path

    if source.exists() and source.is_file():
        zip_handle.write(source, rel_path.replace("\\", "/"))
        files.append({
            "path": rel_path.replace("\\", "/"),
            "size_bytes": source.stat().st_size
        })
        return True

    missing.append(rel_path)
    return False


def create_pre_update_backup(target_root, reason="pre-update"):
    backups_dir = target_root / "backups"
    backups_dir.mkdir(exist_ok=True)

    version = get_release_version(Path(__file__).resolve().parent)
    backup_path = backups_dir / f"pre_update_backup_{version}_{now_stamp()}.zip"

    manifest = {
        "type": "pre_update_backup",
        "created_at": now_utc(),
        "reason": reason,
        "target_root": str(target_root),
        "release_version": version,
        "warning": "Private backup. Do not share publicly.",
        "files": [],
        "missing": []
    }

    with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_handle:
        for rel_path in PRIVATE_BACKUP_ITEMS:
            add_backup_file(
                zip_handle,
                target_root,
                rel_path,
                manifest["files"],
                manifest["missing"]
            )

        zip_handle.writestr(
            "backup_manifest.json",
            json.dumps(manifest, indent=2)
        )

    return {
        "path": str(backup_path),
        "files": len(manifest["files"]),
        "missing": len(manifest["missing"]),
        "manifest": manifest
    }


def collect_release_files(source_root):
    files = []

    for path in source_root.rglob("*"):
        if not path.is_file():
            continue

        if is_private_or_runtime_path(path, source_root):
            continue

        # Do not copy update reports from the release source.
        if path.name == REPORT_NAME:
            continue

        files.append(path)

    return files


def copy_release_files(source_root, target_root, dry_run=False):
    copied = []
    skipped = []

    for source in collect_release_files(source_root):
        rel = source.relative_to(source_root)
        target = target_root / rel

        if dry_run:
            copied.append({
                "source": str(source),
                "target": str(target),
                "bytes": source.stat().st_size,
                "dry_run": True
            })
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

        copied.append({
            "source": str(source),
            "target": str(target),
            "bytes": target.stat().st_size,
            "dry_run": False
        })

    return copied, skipped


def run_command(command, cwd):
    started = now_utc()

    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=300
        )

        return {
            "command": command,
            "started_at": started,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-6000:],
            "stderr": completed.stderr[-6000:],
            "ok": completed.returncode == 0
        }

    except Exception as error:
        return {
            "command": command,
            "started_at": started,
            "returncode": None,
            "stdout": "",
            "stderr": str(error),
            "ok": False
        }


def run_post_update_steps(target_root, run_migrations=True, run_release_check=True):
    python_runner = get_python_runner(target_root)
    results = []

    if run_migrations and (target_root / "migration_manager.py").exists():
        results.append(
            run_command(
                [python_runner, "migration_manager.py"],
                cwd=target_root
            )
        )

    if run_release_check and (target_root / "release_check.py").exists():
        results.append(
            run_command(
                [python_runner, "release_check.py"],
                cwd=target_root
            )
        )

    return results


def write_report(target_root, report):
    logs_dir = target_root / "logs"
    logs_dir.mkdir(exist_ok=True)

    report_path = logs_dir / REPORT_NAME

    text_lines = []
    text_lines.append("OSRSFLIPPER UPDATE INSTALL REPORT")
    text_lines.append("=================================")
    text_lines.append(f"Started: {report['started_at']}")
    text_lines.append(f"Finished: {report['finished_at']}")
    text_lines.append(f"Source: {report['source_root']}")
    text_lines.append(f"Target: {report['target_root']}")
    text_lines.append(f"Release version: {report['release_version']}")
    text_lines.append(f"Dry run: {report['dry_run']}")
    text_lines.append(f"Backup: {report.get('backup', {}).get('path', 'skipped')}")
    text_lines.append(f"Copied files: {len(report.get('copied_files', []))}")
    text_lines.append("")

    text_lines.append("POST UPDATE STEPS")
    text_lines.append("-----------------")

    for result in report.get("post_update_results", []):
        command_text = " ".join(str(part) for part in result.get("command", []))
        status = "PASS" if result.get("ok") else "FAIL"
        text_lines.append(f"[{status}] {command_text}")
        if result.get("stdout"):
            text_lines.append("STDOUT:")
            text_lines.append(result["stdout"])
        if result.get("stderr"):
            text_lines.append("STDERR:")
            text_lines.append(result["stderr"])
        text_lines.append("")

    text_lines.append("COPIED FILES")
    text_lines.append("------------")

    for item in report.get("copied_files", [])[:500]:
        text_lines.append(f"{item.get('target')} ({item.get('bytes')} bytes)")

    if len(report.get("copied_files", [])) > 500:
        text_lines.append(f"... {len(report['copied_files']) - 500} more files omitted")

    text_lines.append("")
    text_lines.append("JSON SUMMARY")
    text_lines.append("------------")
    text_lines.append(json.dumps(report, indent=2))

    report_path.write_text("\n".join(text_lines), encoding="utf-8")

    return report_path


def install_update(
    source_root=None,
    target_root=DEFAULT_TARGET,
    dry_run=False,
    no_backup=False,
    no_migrations=False,
    no_release_check=False,
    allow_same_folder=False
):
    source_root = Path(source_root or Path(__file__).resolve().parent).resolve()
    target_root = Path(target_root).resolve()

    if same_path(source_root, target_root) and not allow_same_folder:
        raise RuntimeError(
            "Source and target are the same folder. Run update_install.py from a clean release folder, "
            "or pass --allow-same-folder if you only want to test the logic."
        )

    started = now_utc()
    ensure_target(target_root)

    report = {
        "started_at": started,
        "finished_at": None,
        "source_root": str(source_root),
        "target_root": str(target_root),
        "release_version": get_release_version(source_root),
        "dry_run": dry_run,
        "backup": None,
        "copied_files": [],
        "skipped_files": [],
        "post_update_results": [],
        "warnings": [],
    }

    if not no_backup and not dry_run:
        report["backup"] = create_pre_update_backup(
            target_root,
            reason="update-install"
        )
    elif no_backup:
        report["warnings"].append("Backup skipped by --no-backup.")
    elif dry_run:
        report["warnings"].append("Backup skipped because this was a dry run.")

    copied, skipped = copy_release_files(
        source_root=source_root,
        target_root=target_root,
        dry_run=dry_run
    )

    report["copied_files"] = copied
    report["skipped_files"] = skipped

    if not dry_run:
        report["post_update_results"] = run_post_update_steps(
            target_root=target_root,
            run_migrations=not no_migrations,
            run_release_check=not no_release_check
        )

    report["finished_at"] = now_utc()

    if not dry_run:
        report_path = write_report(target_root, report)
        report["report_path"] = str(report_path)
    else:
        report["report_path"] = ""

    return report


def main():
    parser = argparse.ArgumentParser(
        description="Safely update an existing OSRSFlipper install from a clean release folder."
    )

    parser.add_argument(
        "--target",
        default=str(DEFAULT_TARGET),
        help="Existing OSRSFlipper install folder to update."
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Clean release folder. Defaults to the folder containing update_install.py."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument("--no-migrations", action="store_true")
    parser.add_argument("--no-release-check", action="store_true")
    parser.add_argument("--allow-same-folder", action="store_true")

    args = parser.parse_args()

    result = install_update(
        source_root=args.source,
        target_root=args.target,
        dry_run=args.dry_run,
        no_backup=args.no_backup,
        no_migrations=args.no_migrations,
        no_release_check=args.no_release_check,
        allow_same_folder=args.allow_same_folder
    )

    print("\n==============================")
    print(" OSRSFlipper Update Installer")
    print("==============================")
    print(f"Source: {result['source_root']}")
    print(f"Target: {result['target_root']}")
    print(f"Release version: {result['release_version']}")
    print(f"Dry run: {result['dry_run']}")
    print(f"Copied files: {len(result['copied_files'])}")

    if result.get("backup"):
        print(f"Backup: {result['backup']['path']}")

    if result.get("report_path"):
        print(f"Report: {result['report_path']}")

    failed_steps = [
        item for item in result.get("post_update_results", [])
        if not item.get("ok")
    ]

    if failed_steps:
        print()
        print("Post-update step failures were detected. Review the report.")
        raise SystemExit(1)

    print()
    print("Update install complete.")


if __name__ == "__main__":
    main()
