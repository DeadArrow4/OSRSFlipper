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
  "active_ge_offers": []
}
```

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
cd C:\OSRSFlipper\runelite_companion\osrsflipper-telemetry-plugin
gradle run
```

If you do not have Gradle installed, use IntelliJ's Gradle runner or copy these files into a fresh clone of the official RuneLite example plugin.

## Notes

Bank GP is only reliable when RuneLite has a bank container available. Inventory GP and active GE offers are the first useful live telemetry targets.
