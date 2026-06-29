from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent
PLUGIN_DIR = PROJECT_ROOT / "runelite_companion" / "osrsflipper-telemetry-plugin-wrapper"
LEGACY_PLUGIN_DIR = PROJECT_ROOT / "runelite_companion" / "osrsflipper-telemetry-plugin"
EXPORT_ROOT = PROJECT_ROOT / "dist" / "runelite-plugin"
EXPORT_DIR = EXPORT_ROOT / "osrsflipper-telemetry-plugin"
PROPERTIES_FILE = "runelite-plugin.properties"
PLUGIN_CLASS = "com.osrsflipper.telemetry.OsrsFlipperTelemetryPlugin"

REQUIRED_PROPERTIES = {
    "displayName",
    "author",
    "description",
    "tags",
    "plugins",
    "version",
    "build",
}

EXCLUDE_DIRS = {
    ".gradle",
    ".git",
    "build",
    "out",
}


def _parse_properties(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}

    if not path.exists():
        return values

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()

        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()

    return values


def _license_text() -> tuple[str, Path | None]:
    for path in (PLUGIN_DIR / "LICENSE", PROJECT_ROOT / "LICENSE"):
        if path.exists():
            return path.read_text(encoding="utf-8", errors="ignore"), path

    return "", None


def _license_status() -> dict[str, Any]:
    text, path = _license_text()

    if not text:
        return {
            "level": "FAIL",
            "message": "No LICENSE found for the plugin package.",
        }

    normalized = text.lower()
    if "bsd 2-clause" in normalized or "bsd-2-clause" in normalized:
        return {
            "level": "PASS",
            "message": f"BSD-2-Clause license found at {path}.",
        }

    return {
        "level": "WARN",
        "message": (
            f"License found at {path}, but it is not BSD-2-Clause. "
            "RuneLite Plugin Hub submissions commonly require BSD-2-Clause; confirm before submitting."
        ),
    }


def _check_path(path: Path, label: str) -> dict[str, Any]:
    if path.exists():
        return {"level": "PASS", "message": f"{label}: found ({path})."}

    return {"level": "FAIL", "message": f"{label}: missing ({path})."}


def inspect_plugin_package() -> dict[str, Any]:
    props_path = PLUGIN_DIR / PROPERTIES_FILE
    props = _parse_properties(props_path)
    missing_props = sorted(REQUIRED_PROPERTIES.difference(props))

    checks: list[dict[str, Any]] = [
        _check_path(PLUGIN_DIR, "Plugin project"),
        _check_path(props_path, "Plugin properties"),
        _check_path(PLUGIN_DIR / "build.gradle", "Gradle build"),
        _check_path(PLUGIN_DIR / "settings.gradle", "Gradle settings"),
        _check_path(PLUGIN_DIR / "gradlew.bat", "Gradle wrapper"),
        _check_path(
            PLUGIN_DIR / "src" / "main" / "java" / "com" / "osrsflipper" / "telemetry" / "OsrsFlipperTelemetryPlugin.java",
            "Plugin class",
        ),
        _check_path(
            PLUGIN_DIR / "src" / "main" / "java" / "com" / "osrsflipper" / "telemetry" / "OsrsFlipperTelemetryConfig.java",
            "Plugin config",
        ),
        _check_path(
            PLUGIN_DIR / "src" / "test" / "java" / "com" / "osrsflipper" / "telemetry" / "OsrsFlipperTelemetryPluginTest.java",
            "Development launcher",
        ),
    ]

    if missing_props:
        checks.append(
            {
                "level": "FAIL",
                "message": f"{PROPERTIES_FILE} missing required field(s): {', '.join(missing_props)}.",
            }
        )
    else:
        checks.append({"level": "PASS", "message": f"{PROPERTIES_FILE}: required fields present."})

    if props.get("plugins") == PLUGIN_CLASS:
        checks.append({"level": "PASS", "message": f"Plugin entry points to {PLUGIN_CLASS}."})
    else:
        checks.append(
            {
                "level": "FAIL",
                "message": f"Plugin entry must be {PLUGIN_CLASS}; got {props.get('plugins')!r}.",
            }
        )

    if props.get("build") == "standard":
        checks.append({"level": "PASS", "message": "Plugin Hub build mode is standard."})
    else:
        checks.append({"level": "WARN", "message": "Plugin Hub build mode should be build=standard."})

    checks.append(_license_status())

    fail_count = sum(1 for check in checks if check["level"] == "FAIL")
    warn_count = sum(1 for check in checks if check["level"] == "WARN")

    return {
        "ok": fail_count == 0,
        "ready_for_submission": fail_count == 0 and warn_count == 0,
        "warning_count": warn_count,
        "fail_count": fail_count,
        "plugin_dir": str(PLUGIN_DIR),
        "export_dir": str(EXPORT_DIR),
        "properties": props,
        "checks": checks,
    }


def format_plugin_package_status(report: dict[str, Any] | None = None) -> str:
    data = report or inspect_plugin_package()
    lines = [
        "RuneLite normal-client packaging status",
        "========================================",
        f"Plugin project: {data['plugin_dir']}",
        f"Package output: {data['export_dir']}",
        "",
        "Important:",
        "- A normal Jagex-launched RuneLite client will not scan this local project folder.",
        "- To appear in normal RuneLite, OSRSFlipper Telemetry must be installed through RuneLite Plugin Hub or be bundled into a custom RuneLite build.",
        "- The dev client remains the local fallback until the Plugin Hub path is complete.",
        "",
        "Checks:",
    ]

    for check in data["checks"]:
        lines.append(f"- {check['level']}: {check['message']}")

    lines.extend(
        [
            "",
            f"Blocking failures: {data['fail_count']}",
            f"Warnings: {data['warning_count']}",
        ]
    )

    if data["ready_for_submission"]:
        lines.append("Result: package metadata looks ready for Plugin Hub submission.")
    elif data["ok"]:
        lines.append("Result: package can be built, but resolve warnings before Plugin Hub submission.")
    else:
        lines.append("Result: fix blocking failures before packaging.")

    return "\n".join(lines)


def _should_skip(path: Path) -> bool:
    return any(part in EXCLUDE_DIRS for part in path.parts)


def _copy_plugin_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        resolved_destination = destination.resolve()
        resolved_export_root = EXPORT_ROOT.resolve()

        if resolved_export_root not in resolved_destination.parents and resolved_destination != resolved_export_root:
            raise RuntimeError(f"Refusing to delete unexpected package path: {destination}")

        if (destination / ".git").exists():
            for item in destination.iterdir():
                if item.name == ".git":
                    continue

                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
        else:
            shutil.rmtree(destination)

    destination.mkdir(parents=True, exist_ok=True)

    for item in source.rglob("*"):
        relative = item.relative_to(source)

        if _should_skip(relative):
            continue

        target = destination / relative

        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)


def _write_submission_helpers() -> None:
    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)

    marker = EXPORT_ROOT / "plugin-hub-marker-template.properties"
    marker.write_text(
        "\n".join(
            [
                "# Copy this into the RuneLite plugin-hub/plugins directory after publishing the companion plugin repo.",
                "# The commit value must be the full 40-character Git commit hash for the submitted plugin version.",
                "repository=https://github.com/<owner>/osrsflipper-telemetry-plugin.git",
                "commit=<40-character-commit-sha>",
                "",
            ]
        ),
        encoding="utf-8",
    )

    checklist = EXPORT_ROOT / "SUBMISSION_CHECKLIST.md"
    checklist.write_text(
        "\n".join(
            [
                "# OSRSFlipper Telemetry Plugin Hub Checklist",
                "",
                "1. Publish `dist/runelite-plugin/osrsflipper-telemetry-plugin` as its own public GitHub repository.",
                "2. Confirm the published repository includes the BSD-2-Clause `LICENSE` file.",
                "3. Build and test locally with `gradlew.bat clean test shadowJar --no-daemon`.",
                "4. Confirm `runelite-plugin.properties` has displayName, author, description, tags, plugins, version, and `build=standard`.",
                "5. Confirm the README clearly documents that the plugin is read-only and defaults file I/O to `.runelite/osrsflipper-telemetry`.",
                "6. Fork `runelite/plugin-hub` and add a plugin marker from `plugin-hub-marker-template.properties`.",
                "7. Open the Plugin Hub pull request and wait for approval.",
                "8. After approval, install OSRSFlipper Telemetry from RuneLite's Plugin Hub in the Jagex-launched client.",
                "",
                "Until step 8 is complete, use `python runelite_telemetry_control.py start-dev` for live telemetry.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def package_plugin_repository() -> dict[str, Any]:
    report = inspect_plugin_package()

    if not report["ok"]:
        return {
            "ok": False,
            "message": "Plugin package has blocking failures.",
            "status": report,
        }

    _copy_plugin_tree(PLUGIN_DIR, EXPORT_DIR)

    root_license = PROJECT_ROOT / "LICENSE"
    export_license = EXPORT_DIR / "LICENSE"
    if root_license.exists():
        shutil.copy2(root_license, export_license)

    _write_submission_helpers()

    return {
        "ok": True,
        "message": f"Packaged RuneLite companion plugin at {EXPORT_DIR}.",
        "export_dir": str(EXPORT_DIR),
        "status": report,
    }


def build_plugin() -> dict[str, Any]:
    gradlew = PLUGIN_DIR / "gradlew.bat"

    if not gradlew.exists():
        return {
            "ok": False,
            "returncode": 2,
            "output": f"Gradle wrapper not found: {gradlew}",
        }

    command = [str(gradlew), "clean", "test", "shadowJar", "--no-daemon"]
    proc = subprocess.run(
        command,
        cwd=str(PLUGIN_DIR),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "output": proc.stdout,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect and package the OSRSFlipper RuneLite telemetry plugin.")
    parser.add_argument("command", nargs="?", default="status", choices=["status", "package", "build"])
    args = parser.parse_args(argv)

    if args.command == "status":
        print(format_plugin_package_status())
        return 0

    if args.command == "package":
        result = package_plugin_repository()
        print(result["message"])
        print(format_plugin_package_status(result["status"]))
        return 0 if result["ok"] else 1

    if args.command == "build":
        result = build_plugin()
        print(result["output"])
        return 0 if result["ok"] else int(result["returncode"] or 1)

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
