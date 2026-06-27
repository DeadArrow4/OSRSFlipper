package com.osrsflipper.telemetry;

import net.runelite.client.RuneLite;
import net.runelite.client.externalplugins.ExternalPluginManager;

public class OsrsFlipperTelemetryPluginTest
{
    public static void main(String[] args) throws Exception
    {
        ExternalPluginManager.loadBuiltin(OsrsFlipperTelemetryPlugin.class);
        RuneLite.main(args);
    }
}
