#!/usr/bin/env python3
"""
Epoch 309 Restitution Calculator — Kimi cPoC validation failure (bootstrap carry-over)

Issue:
  Epoch 309 was the first bootstrap attempt after Kimi was restored by governance
  proposal #79 (passed June 26, 2026). The 5 bootstrap operators entered
  validation_weights and submitted valid Kimi commits, but experienced the same
  confirmation weight suppression seen in e306–e307 — non-Kimi operators ran at
  97–100% confirm ratios while Kimi operators were suppressed to 0–91%.

  The operators entered the epoch group successfully (bootstrap eligibility
  conditions were met). Their reward loss is attributable to the same unresolved
  Kimi validation path failure, not to bootstrap ineligibility.

Eligibility:
  All 5 bootstrap operators who submitted Kimi commits, entered validation_weights,
  and received less than their correct share of rewards.

Compensation methodology (consistent with e306, e307, e267–e276):
  correct_reward = weight / EpochGroupData.total_weight × epoch_reward
  compensation   = max(0, correct_reward − actual_rewards_received)

Delegation: all Kimi operators entered the epoch group. No delegation
penalty compensation needed.
"""

import json
import math
import subprocess
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../../gonka-segment-report/.env"))

ARCHIVE_NODE = os.getenv("ARCHIVE_NODE_URL", "http://204.12.168.157:26657")
BINARY       = os.getenv("INFERENCED_BINARY", "/Users/fixtwin/gonka/gonka/inferenced")

EPOCH     = 309
POC_START = 4767174
EPOCH_END = 4782964

KIMI_MODEL = "moonshotai/Kimi-K2.6"

INITIAL_EPOCH_REWARD = 323_000_000_000_000
DECAY_RATE           = -475e-6
GENESIS_EPOCH        = 1
epoch_theoretical_reward = INITIAL_EPOCH_REWARD * math.exp(DECAY_RATE * (EPOCH - GENESIS_EPOCH))

HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Chain fetchers
# ---------------------------------------------------------------------------

def run_cli(args, height=None):
    cmd = [BINARY] + args + ["--node", ARCHIVE_NODE, "-o", "json"]
    if height:
        cmd += ["--height", str(height)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def fetch_commits():
    print(f"  Fetching PoC commits at height {EPOCH_END}...")
    d = run_cli(["query", "inference", "all-poc-v2-store-commits", str(POC_START)], height=EPOCH_END)
    if not d or "commits" not in d:
        raise RuntimeError("Failed to fetch PoC commits")
    with open(os.path.join(HERE, f"epoch{EPOCH}_commits.json"), "w") as f:
        json.dump(d, f, indent=2)
    kimi_addrs = {c["participant_address"] for c in d["commits"] if c["model_id"] == KIMI_MODEL}
    print(f"  -> {len(kimi_addrs)} addresses with Kimi commits")
    return kimi_addrs


def fetch_group_data():
    print(f"  Fetching epoch group data at height {EPOCH_END}...")
    d = run_cli(["query", "inference", "show-epoch-group-data", str(EPOCH)], height=EPOCH_END)
    if not d:
        raise RuntimeError("Failed to fetch epoch group data")
    with open(os.path.join(HERE, f"epoch{EPOCH}_group_data.json"), "w") as f:
        json.dump(d, f, indent=2)
    vw = d["epoch_group_data"]["validation_weights"]
    total_weight = int(d["epoch_group_data"].get("total_weight") or 0)
    print(f"  -> {len(vw)} members, total_weight={total_weight:,}")
    return vw, total_weight


def fetch_performance(addresses):
    print(f"  Fetching performance summaries for {len(addresses)} addresses...")
    result = {}
    for addr in sorted(addresses):
        d = run_cli(["query", "inference", "show-epoch-performance-summary-by-participant",
                     str(EPOCH), addr])
        result[addr] = int(d.get("epochPerformanceSummary", {}).get("rewarded_coins", 0)) if d else 0
    with open(os.path.join(HERE, f"epoch{EPOCH}_performance.json"), "w") as f:
        json.dump([{"participant_id": k, "rewarded_coins": str(v)} for k, v in result.items()], f, indent=2)
    print("  -> done")
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print(f"=== Epoch {EPOCH} Restitution Calculator (Kimi cPoC validation failure — bootstrap) ===\n")
    print("Fetching data from chain...")

    kimi_addrs       = fetch_commits()
    vw, total_weight = fetch_group_data()
    all_addrs        = [x["member_address"] for x in vw]
    performance      = fetch_performance(all_addrs)
    print()

    vw_by_addr = {x["member_address"]: x for x in vw}

    # Sanity check — all Kimi commit addresses should be in vw for e309
    excluded_from_vw = kimi_addrs - set(vw_by_addr.keys())
    if excluded_from_vw:
        print(f"WARNING: {len(excluded_from_vw)} Kimi commit addresses not in vw: {excluded_from_vw}")

    print(f"Epoch {EPOCH} theoretical reward pool : {epoch_theoretical_reward / 1e9:,.4f} GONKA")
    print(f"Total weight (denominator)            : {total_weight:,}")
    print(f"Kimi bootstrap operators              : {len(kimi_addrs)}")
    print()

    skipped = []
    results = []

    for addr in sorted(kimi_addrs):
        v = vw_by_addr.get(addr)
        if not v:
            skipped.append((addr, "not in validation_weights"))
            continue

        w = int(v.get("weight", 0))
        if w == 0:
            skipped.append((addr, "weight = 0"))
            continue

        actual       = performance.get(addr, 0)
        correct      = w / total_weight * epoch_theoretical_reward
        compensation = max(0.0, correct - actual)

        if compensation <= 0:
            skipped.append((addr, "no underpayment (actual >= correct)"))
            continue

        cw = int(v.get("confirmation_weight", 0)) if v.get("confirmation_weight") else 0
        results.append({
            "address":               addr,
            "weight":                w,
            "confirmation_weight":   cw,
            "confirm_ratio":         round(cw / w * 100, 2) if w else 0,
            "correct_reward_ngonka": int(correct),
            "correct_reward_gonka":  correct / 1e9,
            "actual_rewards_ngonka": actual,
            "actual_rewards_gonka":  actual / 1e9,
            "compensation_ngonka":   int(compensation),
            "compensation_gonka":    compensation / 1e9,
        })

    results.sort(key=lambda x: x["compensation_ngonka"], reverse=True)
    total_comp = sum(r["compensation_ngonka"] for r in results)

    if skipped:
        print("Skipped addresses:")
        for addr, reason in skipped:
            print(f"  {addr}  ({reason})")
        print()

    print(f"{'='*120}")
    print(f"COMPENSATION SUMMARY — Epoch {EPOCH} (Kimi cPoC validation failure — bootstrap)")
    print(f"{'='*120}")
    print(f"{'Address':<50} {'weight':>8} {'conf_w':>8} {'ratio':>7} {'correct':>14} {'actual':>14} {'owed':>14}")
    print(f"{'-'*120}")
    for r in results:
        print(f"{r['address']:<50} "
              f"{r['weight']:>8,} "
              f"{r['confirmation_weight']:>8,} "
              f"{r['confirm_ratio']:>6.1f}% "
              f"{r['correct_reward_gonka']:>14,.4f} "
              f"{r['actual_rewards_gonka']:>14,.4f} "
              f"{r['compensation_gonka']:>14,.4f}")
    print(f"{'-'*120}")
    print(f"  Affected participants : {len(results)}")
    print(f"  Total compensation   : {total_comp / 1e9:,.4f} GONKA\n")

    def out(name):
        return os.path.join(HERE, name)

    with open(out(f"compensation_{EPOCH}.csv"), "w") as f:
        f.write("address,weight,confirmation_weight,confirm_ratio_pct,"
                "correct_reward_ngonka,correct_reward_gonka,"
                "actual_rewards_ngonka,actual_rewards_gonka,"
                "compensation_ngonka,compensation_gonka\n")
        for r in results:
            f.write(f"{r['address']},{r['weight']},{r['confirmation_weight']},{r['confirm_ratio']},"
                    f"{r['correct_reward_ngonka']},{r['correct_reward_gonka']:.4f},"
                    f"{r['actual_rewards_ngonka']},{r['actual_rewards_gonka']:.4f},"
                    f"{r['compensation_ngonka']},{r['compensation_gonka']:.4f}\n")
    print(f"Saved to e{EPOCH}/compensation_{EPOCH}.csv")

    with open(out(f"compensation_{EPOCH}.json"), "w") as f:
        json.dump({
            "epoch":                           EPOCH,
            "epoch_theoretical_reward_ngonka": int(epoch_theoretical_reward),
            "epoch_theoretical_reward_gonka":  epoch_theoretical_reward / 1e9,
            "total_weight":                    total_weight,
            "denominator_mode":                "total_weight",
            "affected_participants":           len(results),
            "total_compensation_ngonka":       total_comp,
            "total_compensation_gonka":        total_comp / 1e9,
            "compensation":                    results,
        }, f, indent=2)
    print(f"Saved to e{EPOCH}/compensation_{EPOCH}.json")


if __name__ == "__main__":
    main()
