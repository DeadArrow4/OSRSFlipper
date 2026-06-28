/*
OSRSFlipper v1.0.3 Runtime Dropdown Focus Fix

File:
C:\OSRSFlipper\assets\dropdown_fix.js

Use this as the ONLY dropdown JavaScript helper.

Purpose:
- Fixes the remaining white outer border/ring around the dropdown search bar.
- Uses an alternative approach from the earlier CSS-only selectors:
  it walks the actual clicked/focused dropdown element and its parent chain,
  then removes white border/outline/box-shadow inline with !important.

Safe behavior:
- No MutationObserver.
- No permanent interval.
- No Python/callback changes.
- Runs briefly only after dropdown click/focus/typing events.
*/

(function () {
    "use strict";

    const BG = "#05080a";
    const PANEL = "#101820";
    const HOVER = "#1d2b32";
    const SELECTED = "rgba(20, 184, 166, 0.24)";
    const BORDER = "#304247";
    const FOCUS = "#4b666b";
    const RING = "inset 0 0 0 1px rgba(20, 184, 166, 0.10)";
    const TEXT = "#f8fafc";
    const MUTED = "#8ea0a6";
    const OPTION_TEXT = "#d6dee2";

    function setImp(el, prop, value) {
        if (el && el.style) {
            el.style.setProperty(prop, value, "important");
        }
    }

    function classText(el) {
        if (!el) {
            return "";
        }

        if (typeof el.className === "string") {
            return el.className;
        }

        if (el.className && typeof el.className.baseVal === "string") {
            return el.className.baseVal;
        }

        return "";
    }

    function isPrimaryDropdownContainer(el) {
        if (!el || !el.classList) {
            return false;
        }

        return (
            el.classList.contains("dash-dropdown-search-container") ||
            el.classList.contains("dash-dropdown-grid-container") ||
            el.classList.contains("Select-control") ||
            el.classList.contains("Select-menu-outer") ||
            el.classList.contains("Select-menu") ||
            el.getAttribute("role") === "listbox"
        );
    }

    function isOption(el) {
        const cls = classText(el);
        const role = el.getAttribute("role") || "";

        return (
            role === "option" ||
            cls.includes("Select-option") ||
            cls.includes("VirtualizedSelectOption") ||
            cls.includes("option") ||
            cls.includes("Option")
        );
    }

    function darkBase(el) {
        setImp(el, "background", BG);
        setImp(el, "background-color", BG);
        setImp(el, "color", TEXT);
        setImp(el, "-webkit-text-fill-color", TEXT);
        setImp(el, "color-scheme", "dark");
    }

    function removeWhiteFocus(el) {
        if (!el) {
            return;
        }

        darkBase(el);

        setImp(el, "outline", "0 solid transparent");
        setImp(el, "outline-color", "transparent");
        setImp(el, "outline-style", "none");
        setImp(el, "outline-width", "0");
        setImp(el, "box-shadow", "none");
        setImp(el, "-webkit-box-shadow", "none");
        setImp(el, "border-color", BORDER);
    }

    function applyBlueRing(el) {
        if (!el) {
            return;
        }

        darkBase(el);

        setImp(el, "border", "1px solid " + FOCUS);
        setImp(el, "border-color", FOCUS);
        setImp(el, "outline", "0 solid transparent");
        setImp(el, "outline-color", "transparent");
        setImp(el, "outline-style", "none");
        setImp(el, "outline-width", "0");
        setImp(el, "box-shadow", RING);
        setImp(el, "-webkit-box-shadow", RING);
    }

    function styleInput(el) {
        darkBase(el);

        setImp(el, "border", "0 solid transparent");
        setImp(el, "border-color", "transparent");
        setImp(el, "outline", "0 solid transparent");
        setImp(el, "outline-color", "transparent");
        setImp(el, "outline-style", "none");
        setImp(el, "outline-width", "0");
        setImp(el, "box-shadow", "none");
        setImp(el, "-webkit-box-shadow", "none");
        setImp(el, "-webkit-appearance", "none");
        setImp(el, "appearance", "none");
        setImp(el, "caret-color", TEXT);
    }

    function styleOption(el) {
        const cls = classText(el);
        const selected = el.getAttribute("aria-selected") === "true" || cls.includes("Selected") || cls.includes("is-selected");
        const focused = cls.includes("Focused") || cls.includes("is-focused");

        const bg = selected ? SELECTED : focused ? HOVER : BG;
        const fg = selected || focused ? TEXT : OPTION_TEXT;

        setImp(el, "background", bg);
        setImp(el, "background-color", bg);
        setImp(el, "color", fg);
        setImp(el, "-webkit-text-fill-color", fg);
        setImp(el, "border-color", "rgba(51, 65, 85, 0.55)");
        setImp(el, "outline", "0 solid transparent");
        setImp(el, "box-shadow", "none");
        setImp(el, "-webkit-box-shadow", "none");

        el.querySelectorAll("*").forEach(function (child) {
            setImp(child, "background", "transparent");
            setImp(child, "background-color", "transparent");
            setImp(child, "color", fg);
            setImp(child, "-webkit-text-fill-color", fg);
            setImp(child, "outline", "0 solid transparent");
            setImp(child, "box-shadow", "none");
            setImp(child, "-webkit-box-shadow", "none");
        });
    }

    function fixAncestorChain(startEl) {
        let el = startEl;
        let depth = 0;

        while (el && el !== document.body && depth < 12) {
            const tag = (el.tagName || "").toLowerCase();
            const cls = classText(el);
            const isInput = tag === "input" || tag === "textarea" || cls.includes("input") || cls.includes("Input");

            if (isOption(el)) {
                styleOption(el);
            } else if (isInput) {
                styleInput(el);
            } else if (isPrimaryDropdownContainer(el)) {
                applyBlueRing(el);
            } else if (
                cls.includes("dash-dropdown") ||
                cls.includes("Select") ||
                cls.includes("dropdown") ||
                cls.includes("Dropdown") ||
                cls.includes("search") ||
                cls.includes("Search") ||
                cls.includes("grid") ||
                cls.includes("Grid")
            ) {
                removeWhiteFocus(el);
            }

            el = el.parentElement;
            depth += 1;
        }
    }

    function fixDropdownSubtrees() {
        const selectors = [
            ".dash-dropdown",
            ".dash-dropdown *",
            ".Select",
            ".Select *",
            ".Select-control",
            ".Select-control *",
            ".Select-menu-outer",
            ".Select-menu-outer *",
            ".Select-menu",
            ".Select-menu *",
            ".VirtualizedSelectGrid",
            ".VirtualizedSelectGrid *",
            ".ReactVirtualized__Grid",
            ".ReactVirtualized__Grid *",
            ".ReactVirtualized__Grid__innerScrollContainer",
            ".ReactVirtualized__Grid__innerScrollContainer *",
            ".dash-dropdown-grid-container",
            ".dash-dropdown-grid-container *",
            ".dash-dropdown-search-container",
            ".dash-dropdown-search-container *",
            "[role='listbox']",
            "[role='listbox'] *"
        ];

        selectors.forEach(function (selector) {
            document.querySelectorAll(selector).forEach(function (el) {
                const tag = (el.tagName || "").toLowerCase();
                const cls = classText(el);
                const isInput = tag === "input" || tag === "textarea" || cls.includes("input") || cls.includes("Input");

                if (isOption(el)) {
                    styleOption(el);
                } else if (isInput) {
                    styleInput(el);
                } else if (isPrimaryDropdownContainer(el)) {
                    applyBlueRing(el);
                } else {
                    removeWhiteFocus(el);
                }
            });
        });

        document.querySelectorAll(".dash-dropdown-search-container svg, .dash-dropdown-search-container path, .dash-dropdown-grid-container svg, .dash-dropdown-grid-container path").forEach(function (el) {
            setImp(el, "fill", MUTED);
            setImp(el, "stroke", MUTED);
        });
    }

    function injectLateStyle() {
        if (document.getElementById("osrs-runtime-dropdown-focus-style")) {
            return;
        }

        const style = document.createElement("style");
        style.id = "osrs-runtime-dropdown-focus-style";
        style.textContent = `
            .dash-dropdown-search-container,
            .dash-dropdown-grid-container,
            .Select.is-open > .Select-control,
            .Select.is-focused > .Select-control,
            .dash-dropdown:focus-within .Select-control {
                background: ${BG} !important;
                background-color: ${BG} !important;
                color: ${TEXT} !important;
                -webkit-text-fill-color: ${TEXT} !important;
                border: 1px solid ${FOCUS} !important;
                border-color: ${FOCUS} !important;
                outline: 0 solid transparent !important;
                outline-color: transparent !important;
                box-shadow: ${RING} !important;
                -webkit-box-shadow: ${RING} !important;
                color-scheme: dark !important;
            }

            .dash-dropdown-search-container *,
            .dash-dropdown-grid-container *,
            .Select-input,
            .Select-input *,
            .Select-input input,
            .Select-control input {
                background: ${BG} !important;
                background-color: ${BG} !important;
                color: ${TEXT} !important;
                -webkit-text-fill-color: ${TEXT} !important;
                outline: 0 solid transparent !important;
                outline-color: transparent !important;
                box-shadow: none !important;
                -webkit-box-shadow: none !important;
                color-scheme: dark !important;
            }

            .dash-dropdown-search-container input,
            .dash-dropdown-grid-container input,
            .Select-input input,
            .Select-control input {
                border: 0 solid transparent !important;
                border-color: transparent !important;
                -webkit-appearance: none !important;
                appearance: none !important;
            }
        `;

        document.head.appendChild(style);
    }

    function runFix(startEl) {
        injectLateStyle();

        if (startEl) {
            fixAncestorChain(startEl);
        }

        const active = document.activeElement;

        if (active) {
            fixAncestorChain(active);
        }

        fixDropdownSubtrees();
    }

    function burst(startEl) {
        [0, 20, 50, 100, 200, 400, 800, 1200, 1800].forEach(function (delay) {
            window.setTimeout(function () {
                runFix(startEl);
            }, delay);
        });
    }

    function insideDropdown(event) {
        const t = event.target;

        return Boolean(
            t &&
            t.closest &&
            (
                t.closest(".dash-dropdown") ||
                t.closest(".Select") ||
                t.closest(".dash-dropdown-grid-container") ||
                t.closest(".dash-dropdown-search-container") ||
                t.closest("[role='listbox']")
            )
        );
    }

    ["mousedown", "mouseup", "click", "focus", "focusin", "keydown", "keyup", "input", "pointerdown", "pointerup"].forEach(function (eventName) {
        document.addEventListener(eventName, function (event) {
            if (insideDropdown(event)) {
                burst(event.target);
            }
        }, true);
    });

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
            burst(null);
        });
    } else {
        burst(null);
    }
})();
