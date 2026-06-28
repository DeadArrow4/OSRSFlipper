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
    private static final int MAX_TRADE_HISTORY = 2000;
    private static final DateTimeFormatter ISO_UTC = DateTimeFormatter.ISO_INSTANT.withZone(ZoneOffset.UTC);
    private static final Gson GSON = new Gson();

    @Inject
    private Client client;

    @Inject
    private ItemManager itemManager;

    @Inject
    private OsrsFlipperTelemetryConfig config;

    private final Map<Integer, Instant> offerFirstSeenBySlot = new HashMap<>();
    private final Map<Integer, Map<String, Object>> lastOffersBySlot = new HashMap<>();
    private final Map<String, Map<String, Object>> completedOffersByKey = new LinkedHashMap<>();
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
        loadExistingOfferHistory();
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
            payload.put("lastOffers", buildLastOffersPayload());
            payload.put("trades", buildTradesPayload());

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
        List<Map<String, Object>> activeOffers = buildGrandExchangeOffers();

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
        payload.put("active_ge_offers", activeOffers);
        payload.put("lastOffers", buildLastOffersPayload());
        payload.put("trades", buildTradesPayload());

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
                lastOffersBySlot.remove(slot);
                offerFirstSeenBySlot.remove(slot);
                continue;
            }

            String itemName = itemName(itemId);
            int gePrice = itemGePrice(itemId);
            String state = String.valueOf(offer.getState()).toUpperCase();
            String side = inferSide(state);
            Map<String, Object> lastOffer = buildLastOfferRow(slot, offer, itemName, gePrice, state);
            lastOffersBySlot.put(slot, lastOffer);

            int quantityFilled = offer.getQuantitySold();
            int quantityRemaining = Math.max(0, totalQuantity - quantityFilled);
            boolean collectionPending = isImportableCompletedState(state, quantityFilled) && quantityRemaining <= 0;

            if (isImportableCompletedState(state, quantityFilled))
            {
                rememberCompletedOffer(itemId, itemName, lastOffer);
            }

            if (!isActiveState(state) && !collectionPending)
            {
                continue;
            }

            offerFirstSeenBySlot.putIfAbsent(slot, Instant.now());

            Map<String, Object> row = new LinkedHashMap<>();
            row.put("slot", slot);
            row.put("item_id", itemId);
            row.put("item_name", itemName);
            row.put("side", side);
            row.put("price", offer.getPrice());
            row.put("ge_price", gePrice);
            row.put("quantity_total", totalQuantity);
            row.put("quantity_filled", quantityFilled);
            row.put("quantity_remaining", quantityRemaining);
            row.put("spent", offer.getSpent());
            row.put("filled_buy_value", "buy".equals(side) ? (gePrice > 0 ? (long) gePrice * quantityFilled : offer.getSpent()) : 0L);
            row.put("filled_sell_gp", "sell".equals(side) ? offer.getSpent() : 0L);
            row.put("filled_ge_value", gePrice > 0 ? (long) gePrice * quantityFilled : offer.getSpent());
            row.put("remaining_ge_value", gePrice > 0 ? (long) gePrice * quantityRemaining : (long) offer.getPrice() * quantityRemaining);
            row.put("remaining_offer_value", (long) offer.getPrice() * quantityRemaining);
            row.put("state", state);
            row.put("offer_age_minutes", offerAgeMinutes(slot));

            offers.add(row);
        }

        return offers;
    }

    private Map<String, Object> buildLastOfferRow(int slot, GrandExchangeOffer offer, String itemName, int gePrice, String state)
    {
        int itemId = offer.getItemId();
        int totalQuantity = Math.max(0, offer.getTotalQuantity());
        int completedQuantity = Math.max(0, offer.getQuantitySold());
        int remainingQuantity = Math.max(totalQuantity - completedQuantity, 0);
        int price = offer.getPrice();
        long nowMillis = Instant.now().toEpochMilli();
        long tradeStartedAt = existingTradeStartedAt(slot, itemId, totalQuantity, price, nowMillis);
        String uuid = buildOfferUuid(slot, itemId, state, price, totalQuantity, completedQuantity, tradeStartedAt);

        Map<String, Object> row = new LinkedHashMap<>();
        row.put("uuid", uuid);
        row.put("id", itemId);
        row.put("name", itemName);
        row.put("s", slot);
        row.put("b", isBuyState(state));
        row.put("p", price);
        row.put("gePrice", gePrice);
        row.put("cQIT", completedQuantity);
        row.put("tQIT", totalQuantity);
        row.put("tSFO", offer.getSpent());
        row.put("filledSellGp", isBuyState(state) ? 0L : offer.getSpent());
        row.put("tAA", remainingQuantity);
        row.put("filledGeValue", gePrice > 0 ? (long) gePrice * completedQuantity : offer.getSpent());
        row.put("remainingGeValue", gePrice > 0 ? (long) gePrice * remainingQuantity : (long) price * remainingQuantity);
        row.put("t", nowMillis);
        row.put("st", state);
        row.put("tradeStartedAt", tradeStartedAt);
        row.put("beforeLogin", false);

        return row;
    }

    private long existingTradeStartedAt(int slot, int itemId, int totalQuantity, int price, long defaultValue)
    {
        Map<String, Object> existing = lastOffersBySlot.get(slot);

        if (existing == null)
        {
            return defaultValue;
        }

        if (safeInt(existing.get("id"), -1) != itemId)
        {
            return defaultValue;
        }

        if (safeInt(existing.get("tQIT"), -1) != totalQuantity)
        {
            return defaultValue;
        }

        if (safeInt(existing.get("p"), -1) != price)
        {
            return defaultValue;
        }

        return safeLong(existing.get("tradeStartedAt"), defaultValue);
    }

    private String buildOfferUuid(int slot, int itemId, String state, int price, int totalQuantity, int completedQuantity, long tradeStartedAt)
    {
        return "osrsflipper-" + slot + "-" + itemId + "-" + state + "-" + price + "-"
            + totalQuantity + "-" + completedQuantity + "-" + tradeStartedAt;
    }

    private boolean isActiveState(String state)
    {
        return "BUYING".equals(state) || "SELLING".equals(state);
    }

    private boolean isBuyState(String state)
    {
        if (state == null)
        {
            return false;
        }

        String value = state.toLowerCase();
        return value.contains("buy") || value.contains("bought");
    }

    private String inferSide(String state)
    {
        String value = String.valueOf(state).toLowerCase();

        if (value.contains("buy") || value.contains("bought"))
        {
            return "buy";
        }

        if (value.contains("sell") || value.contains("sold"))
        {
            return "sell";
        }

        return "unknown";
    }

    private boolean isImportableCompletedState(String state, int completedQuantity)
    {
        if (completedQuantity <= 0)
        {
            return false;
        }

        return "BOUGHT".equals(state)
            || "SOLD".equals(state)
            || "CANCELLED_BUY".equals(state)
            || "CANCELED_BUY".equals(state)
            || "CANCELLED_SELL".equals(state)
            || "CANCELED_SELL".equals(state);
    }

    private void rememberCompletedOffer(int itemId, String itemName, Map<String, Object> lastOffer)
    {
        String key = completedOfferKey(itemId, lastOffer);

        if (completedOffersByKey.containsKey(key))
        {
            return;
        }

        Map<String, Object> event = new LinkedHashMap<>(lastOffer);
        event.put("id", itemId);
        event.put("name", itemName);
        completedOffersByKey.put(key, event);

        while (completedOffersByKey.size() > MAX_TRADE_HISTORY)
        {
            String firstKey = completedOffersByKey.keySet().iterator().next();
            completedOffersByKey.remove(firstKey);
        }
    }

    private String completedOfferKey(int itemId, Map<String, Object> offer)
    {
        return itemId + "|" + String.valueOf(offer.get("uuid"));
    }

    private Map<String, Object> buildLastOffersPayload()
    {
        Map<String, Object> rows = new LinkedHashMap<>();

        for (int slot = 0; slot < 8; slot++)
        {
            Map<String, Object> offer = lastOffersBySlot.get(slot);

            if (offer != null)
            {
                rows.put(String.valueOf(slot), new LinkedHashMap<>(offer));
            }
        }

        return rows;
    }

    private List<Map<String, Object>> buildTradesPayload()
    {
        Map<String, Map<String, Object>> grouped = new LinkedHashMap<>();

        for (Map<String, Object> event : completedOffersByKey.values())
        {
            int itemId = safeInt(event.get("id"), 0);
            String itemName = String.valueOf(event.getOrDefault("name", "Item " + itemId));
            String groupKey = itemId + "|" + itemName;

            Map<String, Object> trade = grouped.get(groupKey);

            if (trade == null)
            {
                trade = new LinkedHashMap<>();
                trade.put("id", itemId);
                trade.put("name", itemName);

                Map<String, Object> history = new LinkedHashMap<>();
                history.put("sO", new ArrayList<Map<String, Object>>());
                trade.put("h", history);

                grouped.put(groupKey, trade);
            }

            Map<String, Object> history = getMap(trade.get("h"));
            Object offersObject = history.get("sO");

            if (offersObject instanceof List)
            {
                @SuppressWarnings("unchecked")
                List<Map<String, Object>> offers = (List<Map<String, Object>>) offersObject;
                offers.add(new LinkedHashMap<>(event));
            }
        }

        return new ArrayList<>(grouped.values());
    }

    private void loadExistingOfferHistory()
    {
        try
        {
            Path output = telemetryOutputPath();

            if (!Files.exists(output))
            {
                return;
            }

            String text = Files.readString(output, StandardCharsets.UTF_8);

            @SuppressWarnings("unchecked")
            Map<String, Object> payload = GSON.fromJson(text, Map.class);

            if (payload == null)
            {
                return;
            }

            loadLastOffers(payload.get("lastOffers"));
            loadCompletedTrades(payload.get("trades"));
        }
        catch (Exception ex)
        {
            log.warn("Could not load existing OSRSFlipper telemetry history", ex);
        }
    }

    private void loadLastOffers(Object value)
    {
        if (!(value instanceof Map))
        {
            return;
        }

        @SuppressWarnings("unchecked")
        Map<String, Object> offers = (Map<String, Object>) value;

        for (Map.Entry<String, Object> entry : offers.entrySet())
        {
            Map<String, Object> offer = getMap(entry.getValue());

            if (offer.isEmpty())
            {
                continue;
            }

            int slot = safeInt(entry.getKey(), safeInt(offer.get("s"), -1));

            if (slot >= 0 && slot < 8)
            {
                lastOffersBySlot.put(slot, new LinkedHashMap<>(offer));
            }
        }
    }

    private void loadCompletedTrades(Object value)
    {
        if (!(value instanceof List))
        {
            return;
        }

        @SuppressWarnings("unchecked")
        List<Object> trades = (List<Object>) value;

        for (Object tradeObject : trades)
        {
            Map<String, Object> trade = getMap(tradeObject);

            if (trade.isEmpty())
            {
                continue;
            }

            int itemId = safeInt(trade.get("id"), 0);
            String itemName = String.valueOf(trade.getOrDefault("name", "Item " + itemId));
            Map<String, Object> history = getMap(trade.get("h"));
            Object offersObject = history.get("sO");

            if (!(offersObject instanceof List))
            {
                continue;
            }

            @SuppressWarnings("unchecked")
            List<Object> offers = (List<Object>) offersObject;

            for (Object offerObject : offers)
            {
                Map<String, Object> offer = getMap(offerObject);

                if (offer.isEmpty())
                {
                    continue;
                }

                offer.putIfAbsent("id", itemId);
                offer.putIfAbsent("name", itemName);
                completedOffersByKey.put(completedOfferKey(itemId, offer), new LinkedHashMap<>(offer));
            }
        }
    }

    private Map<String, Object> getMap(Object value)
    {
        if (!(value instanceof Map))
        {
            return new LinkedHashMap<>();
        }

        @SuppressWarnings("unchecked")
        Map<String, Object> map = (Map<String, Object>) value;

        return map;
    }

    private int safeInt(Object value, int defaultValue)
    {
        if (value == null)
        {
            return defaultValue;
        }

        if (value instanceof Number)
        {
            return ((Number) value).intValue();
        }

        try
        {
            return Integer.parseInt(String.valueOf(value));
        }
        catch (Exception ex)
        {
            return defaultValue;
        }
    }

    private long safeLong(Object value, long defaultValue)
    {
        if (value == null)
        {
            return defaultValue;
        }

        if (value instanceof Number)
        {
            return ((Number) value).longValue();
        }

        try
        {
            return Long.parseLong(String.valueOf(value));
        }
        catch (Exception ex)
        {
            return defaultValue;
        }
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

    private int itemGePrice(int itemId)
    {
        try
        {
            return Math.max(0, itemManager.getItemPrice(itemId));
        }
        catch (Exception ex)
        {
            return 0;
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
