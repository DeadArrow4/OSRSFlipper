# OSRSFlipper Telemetry Plugin Hub Submission

This checklist tracks the normal RuneLite Plugin Hub path for the read-only
OSRSFlipper Telemetry companion plugin.

Official reference:
https://github.com/runelite/plugin-hub/blob/master/README.md

## Local Package

From the OSRSFlipper project root:

```powershell
python runelite_telemetry_control.py plugin-status
python runelite_telemetry_control.py build-plugin
python runelite_telemetry_control.py package-plugin
```

The clean plugin package is written to:

```text
C:\OSRSFlipper\dist\runelite-plugin\osrsflipper-telemetry-plugin
```

## Companion Plugin Repository

Publish the clean package folder as its own public GitHub repository.

Before submitting, confirm the repository contains:

- `LICENSE` with BSD-2-Clause text.
- `README.md` explaining the plugin behavior and safety boundary.
- `runelite-plugin.properties`.
- `build.gradle` and `settings.gradle`.
- Source under `src/main/java`.
- Tests or development launcher under `src/test/java`.
- Optional `icon.png` no larger than 48x72 px if we add one later.

The plugin is intentionally read-only. It must not click, buy, sell, cancel,
reprice, automate trading, or send OSRS data to a remote service.

By default, all plugin file I/O must stay under RuneLite's plugin-specific
data folder:

```text
%USERPROFILE%\.runelite\osrsflipper-telemetry
```

The output path may remain user-configurable, but a blank/fresh setting must
write `runelite_state.json`, its temporary file, status file, and startup marker
inside that folder.

## Plugin Hub Marker

After publishing the companion plugin repository, copy the generated marker
template from:

```text
C:\OSRSFlipper\dist\runelite-plugin\plugin-hub-marker-template.properties
```

Then create a new file in a fork of `runelite/plugin-hub` under `plugins/`.
The marker must contain:

```properties
repository=https://github.com/<owner>/osrsflipper-telemetry-plugin.git
commit=<40-character-commit-sha>
```

The commit must be the full 40-character hash for the exact companion plugin
version being submitted.

## Review Notes

RuneLite reviewers check that Plugin Hub plugins are not malicious and do not
break Jagex third-party client rules. Keeping this plugin local-only,
read-only, and dependency-light should make review easier.
