"""Settlement Capsule Pipeline."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wad18 as W
from ledger            import Ledger
from trade             import Trade
from settlement_engine import settle, settlement_summary
from csl               import CSL

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA   = os.path.join(ROOT, "data", "initial_state.json")
LEDGER = os.path.join(ROOT, "audit", "csl_ledger.json")
LOGS   = os.path.join(ROOT, "logs")


def _wad18_from_units(units: int) -> int:
    """Convert integer units to WAD-18 (1 unit = 10^18)."""
    return W.from_int(units)


def run():
    os.makedirs(LOGS, exist_ok=True)
    csl  = CSL(LEDGER)
    raw  = json.load(open(DATA))

    # ── Build initial ledger ──────────────────────────────────────────────
    balances = {}
    for entry in raw["initial_balances"]:
        key = (entry["participant"], entry["instrument"])
        balances[key] = _wad18_from_units(entry["quantity_units"])
    ledger = Ledger(balances)

    # ── Record initial state in CSL (GENESIS) ────────────────────────────
    initial_supplies = {instr: ledger.total_supply(instr)
                        for instr in ledger.instruments()}
    csl.append({
        "capsule":         "settlement-capsule",
        "version":         "1.0.0",
        "arithmetic":      "WAD-18 exact integer — zero floating-point drift",
        "settlement_model":"Delivery vs Payment (DvP), atomic 4-leg execution",
        "conservation_law":"total_supply(i) = constant ∀ instrument i",
        "initial_state_hash": ledger.state_hash(),
        "initial_supplies":   {k: str(v) for k, v in initial_supplies.items()},
        "network":         "DISABLED — blockchain anchoring deferred",
    }, label="GENESIS")
    print(f"[CSL 0] Genesis.  H={csl.root_hash()[:20]}...")

    # ── Execute trades ────────────────────────────────────────────────────
    results = []
    for td in raw["trades"]:
        trade = Trade(
            trade_id        = td["trade_id"],
            seller          = td["seller"],
            buyer           = td["buyer"],
            sell_instrument = td["sell_instrument"],
            sell_quantity   = _wad18_from_units(td["sell_quantity_units"]),
            buy_instrument  = td["buy_instrument"],
            buy_quantity    = _wad18_from_units(td["buy_quantity_units"]),
            timestamp       = "2026-11-02T00:00:00Z",
        )
        result       = settle(ledger, trade)
        exp          = td.get("expected_result")
        pass_result  = result.code == exp
        label        = td.get("label", trade.trade_id)

        csl.append({
            "trade_id":        trade.trade_id,
            "label":           label,
            "code":            result.code,
            "settled":         result.settled,
            "hash_before":     result.ledger_hash_before[:16],
            "hash_after":      result.ledger_hash_after[:16],
            "conservation_ok": all(v["conserved"]
                                   for v in result.conservation_report.values()),
            "expected":        exp,
            "pass":            pass_result,
        }, label=label)

        result_dict = result.to_dict()
        result_dict.update({"label": label, "expected": exp, "pass": pass_result})
        results.append(result_dict)

        mark = "✓" if pass_result else "✗"
        print(f"  {mark} [{trade.trade_id}] {result.code:<32} "
              f"{td['sell_quantity_units']} {td['sell_instrument']} "
              f"→ {td['buy_quantity_units']} {td['buy_instrument']}")

    # ── Final conservation check ──────────────────────────────────────────
    final_supplies = {instr: ledger.total_supply(instr)
                      for instr in ledger.instruments()}
    all_conserved = all(
        final_supplies[instr] == initial_supplies[instr]
        for instr in initial_supplies
    )

    summary = settlement_summary([
        type("R", (), {"settled": r["settled"], "code": r["code"],
                       "conservation_report": {}})()
        for r in results
    ])

    all_pass = all(r["pass"] for r in results)
    csl.append({
        "all_conserved":    all_conserved,
        "all_pass":         all_pass,
        "final_hash":       ledger.state_hash(),
        "H_final":          csl.root_hash(),
        "n_settled":        summary["settled"],
        "n_failed":         summary["failed"],
        "supply_unchanged": {k: (final_supplies[k] == initial_supplies[k])
                             for k in initial_supplies},
    }, label="FINALIZATION")

    json.dump({
        "results": results,
        "summary": summary,
        "all_conserved": all_conserved,
        "final_ledger": ledger.to_dict(),
    }, open(os.path.join(LOGS, "settlements.json"), "w"),
               indent=2, sort_keys=True)

    print(f"\n{'='*60}")
    print(f"  Settled:       {summary['settled']}/{summary['total_trades']}")
    print(f"  All conserved: {all_conserved}")
    print(f"  All pass:      {all_pass}")
    print(f"  H_final:       {csl.root_hash()[:32]}...")
    print(f"{'='*60}")
    return results


if __name__ == "__main__":
    run()
