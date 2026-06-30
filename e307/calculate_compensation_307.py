#!/usr/bin/env python3
"""
Epoch 307 Restitution Calculator — Kimi cPoC validation failure (continued)

Issue:
  The Kimi cPoC validation failure that began in e306 worsened in e307. Confirm
  ratios for Kimi operators collapsed to near zero (0–86%), while non-Kimi
  operators ran at 97–160%. Additionally, 2 Kimi operators submitted valid
  commits but were excluded from validation_weights entirely.

  Three non-Kimi operators also had zero confirmation_weight in e307
  (gonka15p7s7..., gonka1kx9..., gonka1y2a9p5...) — these are independent
  failures unrelated to the Kimi validation issue and are excluded from this
  case.

Compensation methodology:
  For operators in validation_weights with Kimi commits:
    correct_reward = weight / EpochGroupData.total_weight × epoch_reward
    compensation   = max(0, correct_reward − actual_rewards_received)

  For the 2 operators excluded from validation_weights entirely
  (gonka1qa90... and gonka1uhq...): weight is reconstructed from on-chain
  commit counts × weight_scale_factor.
  The denominator is EpochGroupData.total_weight in all cases — the same
  value the chain used to distribute MiniMax rewards. Reconstructed weight
  is NOT added to the denominator; that would reduce everyone's share below
  what the chain's own accounting implies.

  Weight scale factor for moonshotai/Kimi-K2.6 at e307 poc_start
  (height 4,736,392): 0.78

Eligibility:
  All operators with Kimi commits who suffered reward loss due to the
  Kimi validation failure — including mixed operators (Kimi + other models).
  The full weight is used as the correct-reward baseline; this compensates
  for the total reward loss regardless of which model component was affected.

Delegation: verified no ModeNone penalty applicable. The 2 excluded operators
had no delegators pointing Kimi at them (verified on-chain at snapshot height).
"""

import json
import math
import subprocess
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../../gonka-segment-report/.env"))

ARCHIVE_NODE = os.getenv("ARCHIVE_NODE_URL", "http://204.12.168.157:26657")
BINARY       = os.getenv("INFERENCED_BINARY", "/Users/fixtwin/gonka/gonka/inferenced")

EPOCH     = 307
POC_START = 4736392
EPOCH_END = 4752182

KIMI_MODEL          = "moonshotai/Kimi-K2.6"
KIMI_WEIGHT_FACTOR  = 0.78  # weight_scale_factor from chain params at height 4,736,392

# Non-Kimi operators with zero conf_w for independent reasons — excluded from this case
INDEPENDENT_ZERO_CONF = {
    "gonka15p7s7w2hx0y8095lddd4ummm2y0kwpwljk00aq",  # no commits at all
    "gonka1kx9mca3xm8u8ypzfuhmxey66u0ufxhs7nm6wc5",  # MiniMax+Qwen only, no Kimi
    "gonka1y2a9p56kv044327uycmqdexl7zs82fs5ryv5le",   # MiniMax only, no Kimi
}

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
    result = {}
    for c in d["commits"]:
        addr = c["participant_address"]
        result.setdefault(addr, {})
        result[addr][c["model_id"]] = result[addr].get(c["model_id"], 0) + int(c["count"])
    kimi_addrs = {addr for addr, models in result.items() if KIMI_MODEL in models}
    print(f"  -> {len(kimi_addrs)} addresses with Kimi commits")
    return result, kimi_addrs


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
    print(f"=== Epoch {EPOCH} Restitution Calculator (Kimi cPoC validation failure) ===\n")
    print("Fetching data from chain...")

    commits, kimi_addrs  = fetch_commits()
    vw, total_weight     = fetch_group_data()
    all_addrs            = set(x["member_address"] for x in vw) | kimi_addrs
    performance          = fetch_performance(all_addrs)
    print()

    vw_by_addr = {x["member_address"]: x for x in vw}

    # Identify operators excluded from vw entirely
    excluded_from_vw = {addr for addr in kimi_addrs if addr not in vw_by_addr}
    if excluded_from_vw:
        print(f"Kimi operators excluded from validation_weights (reconstructing weight from commits):")
        for addr in sorted(excluded_from_vw):
            kimi_count = commits[addr].get(KIMI_MODEL, 0)
            reconstructed = kimi_count * KIMI_WEIGHT_FACTOR
            print(f"  {addr}  kimi_commits={kimi_count:,}  reconstructed_weight={reconstructed:,.1f}")
        print()

    # Reconstruct weight for excluded operators and adjust total_weight denominator
    reconstructed_weights = {}
    for addr in excluded_from_vw:
        kimi_count = commits[addr].get(KIMI_MODEL, 0)
        reconstructed_weights[addr] = kimi_count * KIMI_WEIGHT_FACTOR

    total_reconstructed = sum(reconstructed_weights.values())

    print(f"Epoch {EPOCH} theoretical reward pool     : {epoch_theoretical_reward / 1e9:,.4f} GONKA")
    print(f"On-chain total_weight (denominator)      : {total_weight:,}")
    print(f"Reconstructed weight (excluded ops)      : {total_reconstructed:,.1f}")
    print()

    skipped = []
    results = []

    # Process operators in validation_weights with Kimi commits
    for addr in sorted(kimi_addrs - excluded_from_vw):
        v = vw_by_addr[addr]
        w = int(v.get("weight", 0))

        if w == 0:
            skipped.append((addr, "weight = 0"))
            continue

        if addr in INDEPENDENT_ZERO_CONF:
            skipped.append((addr, "zero conf_w for independent reasons — not Kimi-related"))
            continue

        actual       = performance.get(addr, 0)
        correct      = w / total_weight * epoch_theoretical_reward
        compensation = max(0.0, correct - actual)

        if compensation <= 0:
            skipped.append((addr, "no underpayment"))
            continue

        cw = int(v.get("confirmation_weight", 0)) if v.get("confirmation_weight") else 0
        results.append({
            "address":               addr,
            "weight":                w,
            "confirmation_weight":   cw,
            "confirm_ratio":         round(cw / w * 100, 2) if w else 0,
            "reconstructed":         False,
            "correct_reward_ngonka": int(correct),
            "correct_reward_gonka":  correct / 1e9,
            "actual_rewards_ngonka": actual,
            "actual_rewards_gonka":  actual / 1e9,
            "compensation_ngonka":   int(compensation),
            "compensation_gonka":    compensation / 1e9,
        })

    # Process operators excluded from vw (reconstructed weight)
    for addr in sorted(excluded_from_vw):
        w_reconstructed = reconstructed_weights[addr]
        actual          = performance.get(addr, 0)
        correct         = w_reconstructed / total_weight * epoch_theoretical_reward
        compensation    = max(0.0, correct - actual)

        if compensation <= 0:
            skipped.append((addr, "no underpayment (reconstructed)"))
            continue

        results.append({
            "address":               addr,
            "weight":                0,
            "confirmation_weight":   0,
            "confirm_ratio":         0.0,
            "reconstructed":         True,
            "reconstructed_weight":  round(w_reconstructed, 2),
            "kimi_commits":          commits[addr].get(KIMI_MODEL, 0),
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
    print(f"COMPENSATION SUMMARY — Epoch {EPOCH} (Kimi cPoC validation failure)")
    print(f"{'='*120}")
    print(f"{'Address':<50} {'weight':>10} {'conf_w':>8} {'ratio':>7} {'correct':>14} {'actual':>14} {'owed':>14}")
    print(f"{'-'*120}")
    for r in results:
        w_str = f"{r['reconstructed_weight']:,.1f}*" if r.get("reconstructed") else f"{r['weight']:,}"
        cw_str = "—" if r.get("reconstructed") else f"{r['confirmation_weight']:,}"
        ratio_str = "—" if r.get("reconstructed") else f"{r['confirm_ratio']:.1f}%"
        print(f"{r['address']:<50} "
              f"{w_str:>10} "
              f"{cw_str:>8} "
              f"{ratio_str:>7} "
              f"{r['correct_reward_gonka']:>14,.4f} "
              f"{r['actual_rewards_gonka']:>14,.4f} "
              f"{r['compensation_gonka']:>14,.4f}")
    print(f"{'-'*120}")
    print(f"  * reconstructed from commits × weight_scale_factor ({KIMI_WEIGHT_FACTOR})")
    print(f"  Affected participants : {len(results)}")
    print(f"  Total compensation   : {total_comp / 1e9:,.4f} GONKA\n")

    def out(name):
        return os.path.join(HERE, name)

    with open(out(f"compensation_{EPOCH}.csv"), "w") as f:
        f.write("address,weight,confirmation_weight,confirm_ratio_pct,reconstructed,"
                "correct_reward_ngonka,correct_reward_gonka,"
                "actual_rewards_ngonka,actual_rewards_gonka,"
                "compensation_ngonka,compensation_gonka\n")
        for r in results:
            f.write(f"{r['address']},"
                    f"{r.get('reconstructed_weight', r['weight'])},"
                    f"{r['confirmation_weight']},{r['confirm_ratio']},"
                    f"{r.get('reconstructed', False)},"
                    f"{r['correct_reward_ngonka']},{r['correct_reward_gonka']:.4f},"
                    f"{r['actual_rewards_ngonka']},{r['actual_rewards_gonka']:.4f},"
                    f"{r['compensation_ngonka']},{r['compensation_gonka']:.4f}\n")
    print(f"Saved to e{EPOCH}/compensation_{EPOCH}.csv")

    with open(out(f"compensation_{EPOCH}.json"), "w") as f:
        json.dump({
            "epoch":                           EPOCH,
            "epoch_theoretical_reward_ngonka": int(epoch_theoretical_reward),
            "epoch_theoretical_reward_gonka":  epoch_theoretical_reward / 1e9,
            "total_weight_on_chain":           total_weight,
            "total_reconstructed_weight":      total_reconstructed,
            "kimi_weight_scale_factor":        KIMI_WEIGHT_FACTOR,
            "denominator_mode":                "total_weight_on_chain",
            "excluded_from_vw":                sorted(excluded_from_vw),
            "affected_participants":           len(results),
            "total_compensation_ngonka":       total_comp,
            "total_compensation_gonka":        total_comp / 1e9,
            "compensation":                    results,
        }, f, indent=2)
    print(f"Saved to e{EPOCH}/compensation_{EPOCH}.json")


if __name__ == "__main__":
    main()
