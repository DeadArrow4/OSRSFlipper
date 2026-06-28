import argparse
import json
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from account_context import BASE_DIR
from app_version import get_version_info, get_version_line


RELEASES_DIR = BASE_DIR / "releases"


RELEASE_FILES = [
    # Core app
    "account_context.py",
    "account_manager.py",
    "advisor.py",
    "api.py",
    "app_version.py",
    "backup_manager.py",
    "collector.py",
    "dashboard.py",
    "dashboard_callbacks/__init__.py",
    "dashboard_tabs/__init__.py",
    "dashboard_components.py",
    "dashboard_data.py",
    "dashboard_formatters.py",
    "dashboard_theme.py",
    "database.py",
    "first_run_setup.py",
    "health_check.py",
    "main.py",
    "migration_manager.py",
    "openai_key_manager.py",
    "openai_key_tester.py",
    "openai_usage_manager.py",
    "osrs_control_center.py",
    "prepare_release.py",
    "recommender.py",
    "release_check.py",
    "safety_manager.py",
    "scanner.py",
    "security_runtime.py",
    "settings_manager.py",
    "trade_ai_context.py",
    "trade_importer.py",
    "trade_tracker.py",
    "trend_analyzer.py",
    "update_install.py",

    # Utilities
    "remove_shared_openai_key.py",
    "remove_shared_openai_key.bat",
    "create_desktop_shortcut.bat",
    "build_and_create_shortcut.bat",
    "build_exe.bat",
]


OPTIONAL_DIRS = [
    "assets"
]


EXCLUDED_PRIVATE_ITEMS = [
    ".env",
    ".osrs_runtime",
    "osrs_flip_scanner.db",
    "logs",
    "backups",
    "exports",
    "releases",
    "runelite_imports",
    "__pycache__",
    ".venv",
    "dist",
    "build",
    "*.spec"
]


DEFAULT_REQUIREMENTS = [
    "dash",
    "pandas",
    "plotly",
    "requests",
    "openai",
    "python-dotenv",
    "pyinstaller"
]


def now_stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def make_json_safe(value):
    """
    Converts Path and other non-JSON-native values into JSON-safe values.
    This keeps release_manifest.json from failing on WindowsPath objects.
    """
    if isinstance(value, Path):
        return str(value)

    if isinstance(value, dict):
        return {
            str(key): make_json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [
            make_json_safe(item)
            for item in value
        ]

    if isinstance(value, tuple):
        return [
            make_json_safe(item)
            for item in value
        ]

    return value


def copy_file(src, dst, manifest):
    if not src.exists() or not src.is_file():
        manifest["missing"].append(str(src.relative_to(BASE_DIR)) if src.is_relative_to(BASE_DIR) else str(src))
        return False

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

    manifest["files"].append({
        "path": str(dst.relative_to(manifest["release_dir"])).replace("\\", "/"),
        "source": str(src),
        "size_bytes": dst.stat().st_size
    })
    return True


def copy_dir(src, dst, manifest):
    if not src.exists() or not src.is_dir():
        manifest["missing"].append(str(src.relative_to(BASE_DIR)) if src.is_relative_to(BASE_DIR) else str(src))
        return False

    for item in src.rglob("*"):
        if item.is_file() and "__pycache__" not in item.parts:
            rel = item.relative_to(src)
            copy_file(item, dst / rel, manifest)

    return True


def write_requirements(release_dir, manifest):
    existing = BASE_DIR / "requirements.txt"
    target = release_dir / "requirements.txt"

    use_existing = False

    if existing.exists():
        try:
            use_existing = existing.read_text(encoding="utf-8").strip() != ""
        except Exception:
            use_existing = existing.stat().st_size > 0

    if use_existing:
        shutil.copy2(existing, target)
        source = str(existing)
    else:
        target.write_text("\n".join(DEFAULT_REQUIREMENTS) + "\n", encoding="utf-8")
        source = "generated"

    manifest["files"].append({
        "path": "requirements.txt",
        "source": source,
        "size_bytes": target.stat().st_size
    })


def write_release_notes(release_dir, manifest):
    version = get_version_info()
    text = f"""{get_version_line()}

Release type: {version.get('build_channel')}
Created: {now_utc()}

Included:
- Control center EXE if already built
- Dashboard and support scripts
- First-run setup wizard
- Account manager
- Per-account encrypted OpenAI API key support
- AI usage logging and daily request limits
- API key test tool
- Database migrations
- Health check
- Release check
- Trade safety review
- OSRSFlipper RuneLite telemetry importer

Not included:
- Private database
- Saved account data
- Saved encrypted API key records
- .env
- Logs
- Backups
- Exports
- Python virtual environment

Install notes:
1. Extract this release folder to the target machine.
2. Install Python if needed.
3. Install requirements with: python -m pip install -r requirements.txt
4. Run: python first_run_setup.py
5. Build or launch with: python osrs_control_center.py
6. If using the EXE, run OSRSFlipper.exe from the dist folder or rebuild with build_exe.bat.

Security notes:
- Do not enter your Jagex/OSRS password into OSRSFlipper.
- Each user must save their own OpenAI API key.
- Shared .env OPENAI_API_KEY fallback is disabled.
"""
    target = release_dir / "RELEASE_NOTES.txt"
    target.write_text(text, encoding="utf-8")
    manifest["files"].append({
        "path": "RELEASE_NOTES.txt",
        "source": "generated",
        "size_bytes": target.stat().st_size
    })


def write_install_readme(release_dir, manifest):
    text = f"""OSRSFlipper Install / Update

Version:
{get_version_line()}

Quick start:
1. Open PowerShell in this folder.
2. Install packages:
   python -m pip install -r requirements.txt
3. Run setup:
   python first_run_setup.py
4. Run release check:
   python release_check.py
5. Start app:
   python osrs_control_center.py

For EXE use:
- If dist\\OSRSFlipper.exe is included, run that.
- If not included, run build_exe.bat first.

Private data:
This clean release package intentionally does not include:
- osrs_flip_scanner.db
- .env
- logs
- backups
- exports
- .osrs_runtime
- saved encrypted OpenAI keys

Before updating an existing install:
1. Run:
   python backup_manager.py --reason pre-update
2. Copy these release files over your existing C:\\OSRSFlipper folder.
3. Run:
   python migration_manager.py
   python release_check.py
"""
    target = release_dir / "README_INSTALL.txt"
    target.write_text(text, encoding="utf-8")
    manifest["files"].append({
        "path": "README_INSTALL.txt",
        "source": "generated",
        "size_bytes": target.stat().st_size
    })


def write_manifest(release_dir, manifest):
    target = release_dir / "release_manifest.json"
    manifest["created_at"] = now_utc()

    safe_manifest = make_json_safe(manifest)
    target.write_text(json.dumps(safe_manifest, indent=2), encoding="utf-8")

    manifest["files"].append({
        "path": "release_manifest.json",
        "source": "generated",
        "size_bytes": target.stat().st_size
    })


def create_zip(release_dir):
    zip_path = release_dir.with_suffix(".zip")

    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_handle:
        for item in release_dir.rglob("*"):
            if item.is_file():
                zip_handle.write(item, item.relative_to(release_dir.parent))

    return zip_path


def prepare_clean_release_package(include_exe=True, zip_release=True, run_check=False):
    version = get_version_info()
    safe_version = str(version.get("app_version", "unknown")).replace("/", "-")
    release_name = f"OSRSFlipper_{safe_version}_{now_stamp()}"

    RELEASES_DIR.mkdir(exist_ok=True)
    release_dir = RELEASES_DIR / release_name

    if release_dir.exists():
        shutil.rmtree(release_dir)

    release_dir.mkdir(parents=True)

    manifest = {
        "type": "clean_release",
        "release_dir": release_dir,
        "app_version": version,
        "base_dir": str(BASE_DIR),
        "excluded_private_items": EXCLUDED_PRIVATE_ITEMS,
        "files": [],
        "missing": [],
        "warnings": []
    }

    if run_check:
        try:
            from release_check import run_release_check
            result = run_release_check(strict=False, write_report=True)
            manifest["release_check_status"] = result.get("status")
            manifest["release_check_counts"] = result.get("counts")

            if result.get("status") == "FAIL":
                manifest["warnings"].append("Release check returned FAIL before packaging.")
        except Exception as error:
            manifest["warnings"].append(f"Could not run release check before packaging: {error}")

    for rel_path in RELEASE_FILES:
        copy_file(BASE_DIR / rel_path, release_dir / rel_path, manifest)

    for rel_dir in OPTIONAL_DIRS:
        copy_dir(BASE_DIR / rel_dir, release_dir / rel_dir, manifest)

    if include_exe:
        exe_path = BASE_DIR / "dist" / "OSRSFlipper.exe"

        if exe_path.exists():
            copy_file(exe_path, release_dir / "dist" / "OSRSFlipper.exe", manifest)
        else:
            manifest["warnings"].append("dist/OSRSFlipper.exe was not found. Run build_exe.bat before packaging if you want the EXE included.")

    write_requirements(release_dir, manifest)
    write_release_notes(release_dir, manifest)
    write_install_readme(release_dir, manifest)
    write_manifest(release_dir, manifest)

    zip_path = None

    if zip_release:
        zip_path = create_zip(release_dir)

    return {
        "release_dir": str(release_dir),
        "zip_path": str(zip_path) if zip_path else "",
        "manifest": make_json_safe({
            **manifest,
            "release_dir": str(release_dir)
        }),
        "file_count": len(manifest["files"]),
        "missing_count": len(manifest["missing"]),
        "warning_count": len(manifest["warnings"])
    }


def main():
    parser = argparse.ArgumentParser(
        description="Create a clean OSRSFlipper release folder without private data."
    )

    parser.add_argument("--no-exe", action="store_true", help="Do not include dist/OSRSFlipper.exe.")
    parser.add_argument("--no-zip", action="store_true", help="Do not create a zip file.")
    parser.add_argument("--run-check", action="store_true", help="Run release_check.py before packaging.")

    args = parser.parse_args()

    result = prepare_clean_release_package(
        include_exe=not args.no_exe,
        zip_release=not args.no_zip,
        run_check=args.run_check
    )

    print("\n==============================")
    print(" OSRSFlipper Clean Release")
    print("==============================")
    print(f"Release folder: {result['release_dir']}")

    if result.get("zip_path"):
        print(f"Zip: {result['zip_path']}")

    print(f"Files: {result['file_count']}")
    print(f"Missing optional/required files: {result['missing_count']}")
    print(f"Warnings: {result['warning_count']}")
    print()
    print("This package intentionally excludes private database, .env, logs, backups, exports, and runtime session data.")


if __name__ == "__main__":
    main()
