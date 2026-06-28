# OSRSFlipper Telemetry RuneLite Companion

This is the read-only RuneLite-side companion for OSRSFlipper 1.2.0.

It exports local telemetry to:

```text
C:\OSRSFlipper\runtime\runelite_state.json
```

OSRSFlipper then imports that file with:

```powershell
python runelite_state_importer.py import
```

## What it exports

```json
{
  "schema_version": 1,
  "source": "runelite_osrsflipper_telemetry_plugin",
  "account_name": "Your RSN",
  "captured_at": "2026-06-27T00:00:00Z",
  "inventory_gp": 8000000,
  "bank_gp": 2000000,
  "include_bank_gp": true,
  "raw_gp_available": 10000000,
  "active_ge_offers": [],
  "lastOffers": {},
  "trades": []
}
```

The `lastOffers` and `trades` sections intentionally use the same historical
shape OSRSFlipper previously consumed from external RuneLite trade-history JSON.
That lets OSRSFlipper import completed BOUGHT/SOLD/CANCELLED offers and analyze
current GE slots from this plugin instead of depending on a separate plugin.

## Safety

This plugin is read-only.

It does not:
- click
- buy
- sell
- cancel
- reprice
- automate trading
- send data to a remote server

It only writes a local JSON file that OSRSFlipper reads.

## Development test

Open this folder in IntelliJ as a Gradle project, or run:

```powershell
cd C:\OSRSFlipper\runelite_companion\osrsflipper-telemetry-plugin-wrapper
.\gradlew.bat run
```

The development runner starts RuneLite with this plugin registered as a local
built-in plugin. That is why it works before the plugin is available in a
normal Jagex-launched RuneLite client.

## Normal RuneLite install path

A normal Jagex-launched RuneLite client does not scan this local project
folder. To make OSRSFlipper Telemetry appear there, package the companion plugin
as a Plugin Hub submission and install it from RuneLite's Plugin Hub after it is
accepted.

From the OSRSFlipper project root:

```powershell
python runelite_telemetry_control.py plugin-status
python runelite_telemetry_control.py package-plugin
python runelite_telemetry_control.py build-plugin
```

The package command writes a clean submission copy to:

```text
C:\OSRSFlipper\dist\runelite-plugin\osrsflipper-telemetry-plugin
```

The source-controlled submission checklist is:

```text
C:\OSRSFlipper\runelite_companion\PLUGIN_HUB_SUBMISSION.md
```

Until that Plugin Hub path is complete, use:

```powershell
python runelite_telemetry_control.py start-dev
```

## Notes

Bank GP is only reliable when RuneLite has a bank container available. Inventory GP and active GE offers are the first useful live telemetry targets.
