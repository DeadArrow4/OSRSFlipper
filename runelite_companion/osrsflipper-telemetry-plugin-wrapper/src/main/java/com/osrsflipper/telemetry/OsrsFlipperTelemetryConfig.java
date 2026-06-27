package com.osrsflipper.telemetry;

import net.runelite.client.config.Config;
import net.runelite.client.config.ConfigGroup;
import net.runelite.client.config.ConfigItem;

@ConfigGroup("osrsflippertelemetry")
public interface OsrsFlipperTelemetryConfig extends Config
{
    @ConfigItem(
        keyName = "enabled",
        name = "Enable telemetry export",
        description = "Write read-only OSRSFlipper telemetry to a local JSON file."
    )
    default boolean enabled()
    {
        return true;
    }

    @ConfigItem(
        keyName = "outputPath",
        name = "Output path",
        description = "Local JSON file OSRSFlipper will import."
    )
    default String outputPath()
    {
        return "C:\\OSRSFlipper\\runtime\\runelite_state.json";
    }

    @ConfigItem(
        keyName = "includeBankGp",
        name = "Include bank GP",
        description = "Include bank coins in the exported raw GP value when the bank container is available."
    )
    default boolean includeBankGp()
    {
        return true;
    }

    @ConfigItem(
        keyName = "exportIntervalTicks",
        name = "Export interval ticks",
        description = "Export every N game ticks. Lower is more current; higher writes less often."
    )
    default int exportIntervalTicks()
    {
        return 2;
    }
}
