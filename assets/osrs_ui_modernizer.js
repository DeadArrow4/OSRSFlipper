// OSRSFlipper 1.1.1 UI helper
// Safe modern tabs, orphan Filters header hide, compact Trade Board toolbar.
// No database access and no scanner/trading logic changes.

(function () {
  "use strict";

  function normalize(text) {
    return (text || "").replace(/\s+/g, " ").trim();
  }

  function findTabsBar() {
    const selected = document.querySelector(".tab--selected");
    if (!selected) return null;

    let node = selected.parentElement;

    while (node && node !== document.body) {
      const directTabs = Array.from(node.children || []).filter(function (child) {
        return child.classList && (child.classList.contains("tab") || child.classList.contains("tab--selected"));
      });

      if (directTabs.length >= 2) {
        return node;
      }

      node = node.parentElement;
    }

    return selected.parentElement;
  }

  function modernizeTabs() {
    const bar = findTabsBar();

    if (!bar) return null;

    bar.classList.add("osrs-top-tabs-bar");

    if (!bar.querySelector(".osrs-nav-brand")) {
      const brand = document.createElement("div");
      brand.className = "osrs-nav-brand";
      brand.textContent = "OSRSFlipper";
      bar.insertBefore(brand, bar.firstChild);
    }

    return bar;
  }

  function hideOrphanFiltersHeader(bar) {
    if (!bar) return;

    const barRect = bar.getBoundingClientRect();

    Array.from(document.querySelectorAll("body *")).forEach(function (node) {
      if (!node || node === document.body || node === document.documentElement) return;
      if (node === bar || bar.contains(node)) return;

      const text = normalize(node.innerText || node.textContent || "");
      if (text !== "Filters") return;

      const rect = node.getBoundingClientRect();
      if (!rect) return;
      if (rect.top >= barRect.top) return;
      if (rect.bottom > barRect.top + 4) return;

      let target = node;
      let current = node;

      while (current && current.parentElement && current.parentElement !== document.body) {
        const parent = current.parentElement;
        const parentText = normalize(parent.innerText || parent.textContent || "");
        const parentRect = parent.getBoundingClientRect();

        if (
          parentText === "Filters" &&
          parentRect &&
          parentRect.top < barRect.top &&
          parentRect.bottom <= barRect.top + 4 &&
          parentRect.height <= 140
        ) {
          target = parent;
          current = parent;
        } else {
          break;
        }
      }

      target.classList.add("osrs-hide-orphan-filters-header");
      target.setAttribute("aria-hidden", "true");
      target.style.setProperty("display", "none", "important");
    });
  }

  function findTradeBoardPage() {
    return document.querySelector(".trade-board-page");
  }

  function sectionCandidates(page) {
    if (!page) return [];

    const preferred = Array.from(page.querySelectorAll(".settings-section"));

    if (preferred.length) return preferred;

    return Array.from(page.children || []).filter(function (node) {
      return normalize(node.innerText || node.textContent || "").length > 0;
    });
  }

  function findSection(page, matcher) {
    const candidates = sectionCandidates(page);

    for (const node of candidates) {
      const text = normalize(node.innerText || node.textContent || "");
      if (matcher(text, node)) return node;
    }

    return null;
  }

  function findAllSections(page, matcher) {
    const matches = [];
    const candidates = sectionCandidates(page);

    candidates.forEach(function (node) {
      const text = normalize(node.innerText || node.textContent || "");
      if (matcher(text, node)) matches.push(node);
    });

    return matches;
  }

  function makeButton(label, key) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "osrs-toolbar-button";
    button.textContent = label;
    button.dataset.panelKey = key;
    return button;
  }

  function extractCardTitle(cardText) {
    const known = [
      "Latest Run", "Buy Now", "Test Small", "Overnight", "Avoid / Wait",
      "Visible Rows", "Best Profit", "Trend History", "Trend Filters", "Trend Boost"
    ];

    for (const title of known) {
      if (cardText.includes(title)) return title;
    }

    const parts = cardText.split(" ");
    return parts.slice(0, 2).join(" ");
  }

  function extractCardValue(cardText, title) {
    let cleaned = cardText.replace(title, "").trim();
    if (!cleaned) return "";

    const tokens = cleaned.split(" ");
    return tokens.slice(0, 3).join(" ");
  }

  function buildSummaryStrip(kpiPanel) {
    const strip = document.createElement("div");
    strip.className = "osrs-tradeboard-summary-strip";

    if (!kpiPanel) return strip;

    const cards = Array.from(kpiPanel.querySelectorAll(".kpi-card, .metric-card, .summary-card, .stat-card, .setting-card"));
    const source = cards.length ? cards : Array.from(kpiPanel.children || []);

    source.slice(0, 8).forEach(function (card) {
      const text = normalize(card.innerText || card.textContent || "");
      if (!text) return;

      const title = extractCardTitle(text);
      const value = extractCardValue(text, title);

      if (!title || !value) return;

      const pill = document.createElement("span");
      pill.className = "osrs-summary-pill";

      const label = document.createElement("span");
      label.className = "osrs-summary-pill-label";
      label.textContent = title;

      const valueEl = document.createElement("span");
      valueEl.className = "osrs-summary-pill-value";
      valueEl.textContent = value;

      pill.appendChild(label);
      pill.appendChild(valueEl);
      strip.appendChild(pill);
    });

    return strip;
  }

  function openPanel(page, drawer, panels, key, buttons) {
    Object.keys(panels).forEach(function (panelKey) {
      const panel = panels[panelKey];
      if (!panel) return;

      if (panelKey === key) {
        panel.classList.add("osrs-panel-open");
        drawer.appendChild(panel);
      } else {
        panel.classList.remove("osrs-panel-open");
      }
    });

    buttons.forEach(function (button) {
      button.classList.toggle("osrs-active", button.dataset.panelKey === key);
    });

    drawer.classList.add("osrs-drawer-open");
    drawer.dataset.openPanel = key;
  }

  function closeDrawer(drawer, buttons, panels) {
    drawer.classList.remove("osrs-drawer-open");
    drawer.dataset.openPanel = "";

    buttons.forEach(function (button) {
      button.classList.remove("osrs-active");
    });

    Object.keys(panels).forEach(function (panelKey) {
      if (panels[panelKey]) panels[panelKey].classList.remove("osrs-panel-open");
    });
  }

  function setupTradeBoardCompactToolbar() {
    const page = findTradeBoardPage();
    if (!page || page.dataset.osrsCompactToolbar === "ready") return;

    const controls = findSection(page, function (text) {
      return (
        text.includes("Risk profile") &&
        (text.includes("Rows") || text.includes("Minimum total profit")) &&
        text.includes("Refresh Trade Board")
      );
    });

    const trendFilters = findSection(page, function (text) {
      return text.includes("Trend direction") && text.includes("Trend confidence");
    });

    const trendBoost = findSection(page, function (text) {
      return text.includes("Trend boost mode") || (text.includes("Trend Boost") && text.includes("Annotate only"));
    });

    const kpiPanels = findAllSections(page, function (text, node) {
      return (
        text.includes("Latest Run") &&
        text.includes("Visible Rows") &&
        text.includes("Best Profit")
      ) || (
        node.classList &&
        node.classList.contains("kpi-grid") &&
        text.includes("Best Profit")
      );
    });

    const kpiPanel = kpiPanels[0] || null;

    if (!controls && !trendFilters && !trendBoost && !kpiPanel) return;

    page.classList.add("osrs-tradeboard-compact-active");

    [controls, trendFilters, trendBoost].forEach(function (panel) {
      if (panel) panel.classList.add("osrs-tradeboard-config-panel");
    });

    if (kpiPanel) kpiPanel.classList.add("osrs-tradeboard-kpi-panel");

    const toolbar = document.createElement("div");
    toolbar.className = "osrs-tradeboard-toolbar";

    const left = document.createElement("div");
    left.className = "osrs-tradeboard-toolbar-left";

    const right = document.createElement("div");
    right.className = "osrs-tradeboard-toolbar-right";

    const title = document.createElement("div");
    title.className = "osrs-tradeboard-title-chip";
    title.textContent = "Trade Board";

    left.appendChild(title);

    const panels = {
      controls: controls,
      trendFilters: trendFilters,
      trendBoost: trendBoost
    };

    const buttons = [];

    if (controls) buttons.push(makeButton("Controls", "controls"));
    if (trendFilters) buttons.push(makeButton("Trend Filters", "trendFilters"));
    if (trendBoost) buttons.push(makeButton("Trend Boost", "trendBoost"));

    buttons.forEach(function (button) {
      button.addEventListener("click", function () {
        const key = button.dataset.panelKey;

        if (drawer.classList.contains("osrs-drawer-open") && drawer.dataset.openPanel === key) {
          closeDrawer(drawer, buttons, panels);
        } else {
          openPanel(page, drawer, panels, key, buttons);
        }
      });

      left.appendChild(button);
    });

    const summary = buildSummaryStrip(kpiPanel);
    right.appendChild(summary);

    toolbar.appendChild(left);
    toolbar.appendChild(right);

    const drawer = document.createElement("div");
    drawer.className = "osrs-tradeboard-drawer";

    const drawerHeader = document.createElement("div");
    drawerHeader.className = "osrs-tradeboard-drawer-header";

    const drawerTitle = document.createElement("div");
    drawerTitle.className = "osrs-tradeboard-drawer-title";
    drawerTitle.textContent = "Trade Board settings";

    const close = document.createElement("button");
    close.type = "button";
    close.className = "osrs-toolbar-button";
    close.textContent = "Close";
    close.addEventListener("click", function () {
      closeDrawer(drawer, buttons, panels);
    });

    drawerHeader.appendChild(drawerTitle);
    drawerHeader.appendChild(close);
    drawer.appendChild(drawerHeader);

    const firstPanel = controls || trendFilters || trendBoost || kpiPanel;
    firstPanel.parentElement.insertBefore(toolbar, firstPanel);
    toolbar.parentElement.insertBefore(drawer, toolbar.nextSibling);

    page.dataset.osrsCompactToolbar = "ready";
  }

  function setupTradeBoardDataSubtabs() {
    if (document.querySelector(".trading-workspace-page")) return;

    const page = findTradeBoardPage();
    if (!page || page.dataset.osrsDataSubtabs === "ready") return;

    const openSlot = findSection(page, function (text) {
      return text.includes("Open Slot Actions");
    });

    const ranked = findSection(page, function (text) {
      return text.includes("Ranked Trade Recommendations");
    });

    if (!openSlot || !ranked) return;

    const switcher = document.createElement("div");
    switcher.className = "trade-board-data-switcher";

    const panels = {
      ranked: ranked,
      openSlot: openSlot
    };

    function select(key) {
      Object.keys(panels).forEach(function (panelKey) {
        panels[panelKey].classList.toggle("osrs-subtab-hidden", panelKey !== key);
      });

      Array.from(switcher.querySelectorAll(".osrs-subtab-button")).forEach(function (button) {
        button.classList.toggle("osrs-subtab-active", button.dataset.targetKey === key);
      });
    }

    [
      { key: "ranked", label: "Ranked Recommendations" },
      { key: "openSlot", label: "Open Slot Actions" }
    ].forEach(function (spec) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "osrs-subtab-button";
      button.dataset.targetKey = spec.key;
      button.textContent = spec.label;
      button.addEventListener("click", function () {
        select(spec.key);
      });
      switcher.appendChild(button);
    });

    const firstPanel = ranked.compareDocumentPosition(openSlot) & Node.DOCUMENT_POSITION_PRECEDING ? openSlot : ranked;
    firstPanel.parentElement.insertBefore(switcher, firstPanel);

    select("ranked");
    page.dataset.osrsDataSubtabs = "ready";
  }

  function runUiPass() {
    const bar = modernizeTabs();
    hideOrphanFiltersHeader(bar);
    setupTradeBoardCompactToolbar();
    setupTradeBoardDataSubtabs();
  }

  function scheduleUiPass() {
    window.requestAnimationFrame(function () {
      runUiPass();
      window.setTimeout(runUiPass, 150);
      window.setTimeout(runUiPass, 500);
      window.setTimeout(runUiPass, 1200);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", scheduleUiPass);
  } else {
    scheduleUiPass();
  }

  const observer = new MutationObserver(scheduleUiPass);

  observer.observe(document.documentElement, {
    childList: true,
    subtree: true
  });
})();
