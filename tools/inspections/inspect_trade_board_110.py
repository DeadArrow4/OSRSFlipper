from __future__ import annotations

from inspection_path import PROJECT_ROOT

BASE_DIR = PROJECT_ROOT


def main() -> int:
    print("OSRSFlipper 1.1.0 Trade Board wiring inspection")
    print("=" * 64)

    targets = [
        BASE_DIR / "dashboard.py",
        BASE_DIR / "dashboard_tabs" / "__init__.py",
        BASE_DIR / "dashboard_callbacks" / "__init__.py",
    ]

    keywords = [
        "Trade Board",
        "trade board",
        "trade-board",
        "trade_board",
        "tradeboard",
        "DataTable",
        "columns=",
        "data=",
    ]

    for path in targets:
        if not path.exists():
            continue

        print()
        print(f"FILE: {path.relative_to(BASE_DIR)}")
        print("-" * 64)

        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        found = False

        for index, line in enumerate(lines, start=1):
            if any(keyword in line for keyword in keywords):
                found = True
                start = max(1, index - 2)
                end = min(len(lines), index + 2)

                print(f"\nContext around line {index}:")
                for line_no in range(start, end + 1):
                    marker = ">" if line_no == index else " "
                    print(f"{marker} {line_no}: {lines[line_no - 1]}")

        if not found:
            print("No Trade Board/DataTable keywords found in this file.")

    print()
    print("Next: paste this output back so the Trade Board trend columns can be wired safely.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
