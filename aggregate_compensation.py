#!/usr/bin/env python3
"""
Aggregate compensation across all epochs into a single per-address summary.

Outputs:
  aggregate_compensation.json  — machine-readable, sorted by total descending
  aggregate_compensation.csv   — spreadsheet-friendly
"""

import csv
import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))

EPOCHS = {
    306: "compensation_306.json",
    307: "compensation_307.json",
    309: "compensation_309.json",
}


def load_entries(epoch, fname):
    path = os.path.join(HERE, "e%d" % epoch, fname)
    with open(path) as f:
        d = json.load(f)
    return [(e["address"], int(e.get("compensation_ngonka", 0)))
            for e in d.get("compensation", [])]


def main():
    by_addr = defaultdict(lambda: defaultdict(int))

    for epoch, fname in EPOCHS.items():
        for addr, amt in load_entries(epoch, fname):
            by_addr[addr][epoch] += amt

    rows = sorted(
        [(addr, ep_map, sum(ep_map.values())) for addr, ep_map in by_addr.items()],
        key=lambda x: x[2],
        reverse=True,
    )
    grand_total = sum(r[2] for r in rows)
    epochs = list(EPOCHS.keys())

    header = "%-46s  %s  %s" % (
        "address",
        "  ".join("e%-6d" % e for e in epochs),
        "TOTAL (GONKA)",
    )
    print(header)
    print("-" * len(header))
    for addr, ep_map, total in rows:
        cols = "  ".join("%7.1f" % (ep_map.get(e, 0) / 1e9) for e in epochs)
        print("%-46s  %s  %14.2f" % (addr, cols, total / 1e9))
    print("-" * len(header))
    totals_row = "  ".join(
        "%7.1f" % (sum(by_addr[a].get(e, 0) for a in by_addr) / 1e9)
        for e in epochs
    )
    print("%-46s  %s  %14.2f" % ("TOTAL", totals_row, grand_total / 1e9))
    print()
    print("Unique addresses : %d" % len(rows))
    print("Grand total      : %.2f GONKA" % (grand_total / 1e9))

    out_json = {
        "grand_total_ngonka": grand_total,
        "grand_total_gonka":  round(grand_total / 1e9, 6),
        "unique_addresses":   len(rows),
        "epochs_covered":     ["e%d" % e for e in epochs],
        "compensation": [
            {
                "address":      addr,
                "total_ngonka": total,
                "total_gonka":  round(total / 1e9, 6),
                "by_epoch": {
                    "e%d" % e: round(ep_map[e] / 1e9, 6)
                    for e in epochs
                    if ep_map.get(e, 0) > 0
                },
            }
            for addr, ep_map, total in rows
        ],
    }
    json_path = os.path.join(HERE, "aggregate_compensation.json")
    with open(json_path, "w") as f:
        json.dump(out_json, f, indent=2)

    csv_path = os.path.join(HERE, "aggregate_compensation.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["address", "total_gonka"] + ["e%d" % e for e in epochs])
        for addr, ep_map, total in rows:
            w.writerow(
                [addr, "%.6f" % (total / 1e9)]
                + ["%.6f" % (ep_map.get(e, 0) / 1e9) for e in epochs],
            )

    print()
    print("Saved: %s" % json_path)
    print("Saved: %s" % csv_path)


if __name__ == "__main__":
    main()
