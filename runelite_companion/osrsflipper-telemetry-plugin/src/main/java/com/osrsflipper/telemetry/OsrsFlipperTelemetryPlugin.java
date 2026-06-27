package com.osrsflipper.telemetry;

import net.runelite.client.eventbus.Subscribe;
import com.google.gson.Gson;
import com.google.inject.Provides;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import javax.inject.Inject;
import lombok.extern.slf4j.Slf4j;
import net.runelite.api.Client;
import net.runelite.api.GameState;
import net.runelite.api.GrandExchangeOffer;
import net.runelite.api.InventoryID;
import net.runelite.api.Item;
import net.runelite.api.ItemContainer;
import net.runelite.api.Player;
import net.runelite.api.events.GameStateChanged;
import net.runelite.api.events.GameTick;
import net.runelite.api.events.GrandExchangeOfferChanged;
import net.runelite.api.events.ItemContainerChanged;
import net.runelite.client.config.ConfigManager;
import net.runelite.client.game.ItemManager;
import net.runelite.client.plugins.Plugin;
import net.runelite.client.plugins.PluginDescriptor;

@Slf4j
@PluginDescriptor(
    name = "OSRSFlipper Telemetry",
    description = "Read-only local telemetry exporter for OSRSFlipper capital-aware recommendations",
    tags = {"grand exchange", "flipping", "osrsflipper", "telemetry"}
)
public class OsrsFlipperTelemetryPlugin extends Plugin
{
    private static final int COINS_ITEM_ID = 995;
    private static final DateTimeFormatter ISO_UTC = DateTimeFormatter.ISO_INSTANT.withZone(ZoneOffset.UTC);
    private static final Gson GSON = new Gson();

    @Inject
    private Client client;

    @Inject
    private ItemManager itemManager;

    @Inject
    private OsrsFlipperTelemetryConfig config;

    private final Map<Integer, Instant> offerFirstSeenBySlot = new HashMap<>();
    private int ticksSinceExport = 0;

    @Provides
    OsrsFlipperTelemetryConfig provideConfig(ConfigManager configManager)
    {
        return configManager.getConfig(OsrsFlipperTelemetryConfig.class);
    }

    @Override
    protected void startUp()
    {
        ticksSinceExport = 0;
        log.warn("OSRSFlipper Telemetry plugin STARTED. enabled={}, outputPath={}", config.enabled(), config.outputPath());
        writeStartupMarker("startup");
        writeMinimalTelemetry("startup");
    }

    @Override
    protected void shutDown()
    {
        log.warn("OSRSFlipper Telemetry plugin STOPPED.");
        writeStartupMarker("shutdown");
        writeMinimalTelemetry("shutdown");
    }

    @Subscribe
    public void onGameTick(GameTick event)
    {
        if (!config.enabled())
        {
            return;
        }

        ticksSinceExport++;

        int interval = Math.max(1, config.exportIntervalTicks());

        if (ticksSinceExport >= interval)
        {
            ticksSinceExport = 0;
            exportFullTelemetry("game_tick");
        }
    }

    @Subscribe
    public void onGrandExchangeOfferChanged(GrandExchangeOfferChanged event)
    {
        if (!config.enabled())
        {
            return;
        }

        int slot = event.getSlot();
        GrandExchangeOffer offer = event.getOffer();

        if (offer != null && offer.getTotalQuantity() > 0)
        {
            offerFirstSeenBySlot.putIfAbsent(slot, Instant.now());
        }

        exportFullTelemetry("ge_offer_changed");
    }

    @Subscribe
    public void onItemContainerChanged(ItemContainerChanged event)
    {
        if (!config.enabled())
        {
            return;
        }

        int containerId = event.getContainerId();

        if (containerId == InventoryID.INVENTORY.getId() || containerId == InventoryID.BANK.getId())
        {
            exportFullTelemetry("item_container_changed");
        }
    }

    @Subscribe
    public void onGameStateChanged(GameStateChanged event)
    {
        if (!config.enabled())
        {
            return;
        }

        if (event.getGameState() == GameState.LOGGED_IN)
        {
            exportFullTelemetry("logged_in");
        }
    }

    private void writeMinimalTelemetry(String reason)
    {
        try
        {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("schema_version", 1);
            payload.put("source", "runelite_osrsflipper_telemetry_plugin");
            payload.put("payload_kind", "minimal");
            payload.put("export_reason", reason);
            payload.put("account_name", "default");
            payload.put("captured_at", ISO_UTC.format(Instant.now()));
            payload.put("inventory_gp", 0);
            payload.put("bank_gp", 0);
            payload.put("include_bank_gp", safeIncludeBankGp());
            payload.put("raw_gp_available", 0);
            payload.put("active_ge_offers", new ArrayList<Map<String, Object>>());

            writePayload(payload, "MINIMAL_OK", null);
        }
        catch (Exception ex)
        {
            writeStatusFile(safeOutputPath(), "MINIMAL_ERROR", ex);
            log.error("Unable to write OSRSFlipper minimal telemetry", ex);
        }
    }

    private void exportFullTelemetry(String reason)
    {
        if (!config.enabled())
        {
            log.warn("OSRSFlipper Telemetry export skipped because plugin config is disabled.");
            return;
        }

        try
        {
            Map<String, Object> payload = buildPayload(reason);
            writePayload(payload, "FULL_OK", null);
        }
        catch (Exception ex)
        {
            writeStatusFile(safeOutputPath(), "FULL_ERROR", ex);
            log.error("Unable to write OSRSFlipper full telemetry", ex);
        }
    }

    private Map<String, Object> buildPayload(String reason)
    {
        int inventoryGp = getCoins(InventoryID.INVENTORY);
        int bankGp = safeIncludeBankGp() ? getCoins(InventoryID.BANK) : 0;

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("schema_version", 1);
        payload.put("source", "runelite_osrsflipper_telemetry_plugin");
        payload.put("payload_kind", "full");
        payload.put("export_reason", reason);
        payload.put("account_name", getAccountName());
        payload.put("captured_at", ISO_UTC.format(Instant.now()));
        payload.put("inventory_gp", inventoryGp);
        payload.put("bank_gp", bankGp);
        payload.put("include_bank_gp", safeIncludeBankGp());
        payload.put("raw_gp_available", inventoryGp + bankGp);
        payload.put("active_ge_offers", buildGrandExchangeOffers());

        return payload;
    }

    private boolean safeIncludeBankGp()
    {
        try
        {
            return config.includeBankGp();
        }
        catch (Exception ex)
        {
            return true;
        }
    }

    private String getAccountName()
    {
        Player local = client.getLocalPlayer();

        if (local == null || local.getName() == null || local.getName().isBlank())
        {
            return "default";
        }

        return local.getName();
    }

    private int getCoins(InventoryID inventoryID)
    {
        ItemContainer container = client.getItemContainer(inventoryID);

        if (container == null)
        {
            return 0;
        }

        long total = 0;

        for (Item item : container.getItems())
        {
            if (item != null && item.getId() == COINS_ITEM_ID)
            {
                total += item.getQuantity();
            }
        }

        return total > Integer.MAX_VALUE ? Integer.MAX_VALUE : (int) total;
    }

    private List<Map<String, Object>> buildGrandExchangeOffers()
    {
        List<Map<String, Object>> offers = new ArrayList<>();
        GrandExchangeOffer[] geOffers = client.getGrandExchangeOffers();

        if (geOffers == null)
        {
            return offers;
        }

        for (int slot = 0; slot < geOffers.length; slot++)
        {
            GrandExchangeOffer offer = geOffers[slot];

            if (offer == null)
            {
                continue;
            }

            int itemId = offer.getItemId();
            int totalQuantity = offer.getTotalQuantity();

            if (itemId <= 0 || totalQuantity <= 0)
            {
                offerFirstSeenBySlot.remove(slot);
                continue;
            }

            int quantityFilled = offer.getQuantitySold();
            int quantityRemaining = Math.max(0, totalQuantity - quantityFilled);

            if (quantityRemaining <= 0)
            {
                offerFirstSeenBySlot.remove(slot);
                continue;
            }

            offerFirstSeenBySlot.putIfAbsent(slot, Instant.now());

            Map<String, Object> row = new LinkedHashMap<>();
            row.put("slot", slot);
            row.put("item_id", itemId);
            row.put("item_name", itemName(itemId));
            row.put("side", inferSide(offer));
            row.put("price", offer.getPrice());
            row.put("quantity_total", totalQuantity);
            row.put("quantity_filled", quantityFilled);
            row.put("quantity_remaining", quantityRemaining);
            row.put("spent", offer.getSpent());
            row.put("state", String.valueOf(offer.getState()));
            row.put("offer_age_minutes", offerAgeMinutes(slot));

            offers.add(row);
        }

        return offers;
    }

    private String inferSide(GrandExchangeOffer offer)
    {
        String state = String.valueOf(offer.getState()).toLowerCase();

        if (state.contains("buy"))
        {
            return "buy";
        }

        if (state.contains("sell"))
        {
            return "sell";
        }

        return "unknown";
    }

    private long offerAgeMinutes(int slot)
    {
        Instant firstSeen = offerFirstSeenBySlot.get(slot);

        if (firstSeen == null)
        {
            return 0;
        }

        return Math.max(0, Duration.between(firstSeen, Instant.now()).toMinutes());
    }

    private String itemName(int itemId)
    {
        try
        {
            return itemManager.getItemComposition(itemId).getName();
        }
        catch (Exception ex)
        {
            return "Item " + itemId;
        }
    }

    private void writePayload(Map<String, Object> payload, String status, Exception error) throws IOException
    {
        Path output = telemetryOutputPath();
        Path parent = output.getParent();

        if (parent != null)
        {
            Files.createDirectories(parent);
        }

        String json = GSON.toJson(payload);
        Path temp = output.resolveSibling(output.getFileName().toString() + ".tmp");

        Files.writeString(temp, json + System.lineSeparator(), StandardCharsets.UTF_8);

        try
        {
            Files.move(temp, output, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
        }
        catch (IOException atomicMoveFailed)
        {
            Files.move(temp, output, StandardCopyOption.REPLACE_EXISTING);
        }

        writeStatusFile(output, status, error);
        log.warn("OSRSFlipper telemetry exported to {} with status {}", output, status);
    }

    private Path telemetryOutputPath()
    {
        String configuredPath = config.outputPath();

        if (configuredPath == null || configuredPath.isBlank())
        {
            configuredPath = "C:\\OSRSFlipper\\runtime\\runelite_state.json";
        }

        return Path.of(configuredPath.trim()).toAbsolutePath();
    }

    private Path safeOutputPath()
    {
        try
        {
            return telemetryOutputPath();
        }
        catch (Exception ex)
        {
            return Path.of("C:\\OSRSFlipper\\runtime\\runelite_state.json").toAbsolutePath();
        }
    }

    private void writeStartupMarker(String event)
    {
        try
        {
            Path output = telemetryOutputPath();
            Path parent = output.getParent();

            if (parent != null)
            {
                Files.createDirectories(parent);
            }

            Path marker = output.resolveSibling("runelite_plugin_started.txt");
            String text = "event=" + event + System.lineSeparator()
                + "enabled=" + config.enabled() + System.lineSeparator()
                + "outputPath=" + output + System.lineSeparator()
                + "time=" + ISO_UTC.format(Instant.now()) + System.lineSeparator();

            Files.writeString(marker, text, StandardCharsets.UTF_8);
        }
        catch (Exception ex)
        {
            log.error("Unable to write OSRSFlipper startup marker", ex);
        }
    }

    private void writeStatusFile(Path output, String status, Exception error)
    {
        try
        {
            Path parent = output.getParent();

            if (parent != null)
            {
                Files.createDirectories(parent);
            }

            Path statusPath = output.resolveSibling(output.getFileName().toString() + ".status.txt");
            StringBuilder builder = new StringBuilder();

            builder.append("status=").append(status).append(System.lineSeparator());
            builder.append("path=").append(output).append(System.lineSeparator());
            builder.append("time=").append(ISO_UTC.format(Instant.now())).append(System.lineSeparator());

            if (error != null)
            {
                builder.append("error=").append(error.getClass().getName()).append(": ").append(error.getMessage()).append(System.lineSeparator());
            }

            Files.writeString(statusPath, builder.toString(), StandardCharsets.UTF_8);
        }
        catch (Exception ignored)
        {
            // Do not let status-file failures break telemetry export.
        }
    }
}
