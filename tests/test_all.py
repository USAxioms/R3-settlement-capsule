"""
Settlement Capsule — comprehensive test suite.
Zero third-party dependencies.
"""
import sys, os, json, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wad18 as W
from ledger            import Ledger, InsufficientBalance, ConservationViolation
from trade             import (Trade, SettlementResult,
                                SETTLED, FAILED_INSUFFICIENT_SELLER,
                                FAILED_INSUFFICIENT_BUYER, RESULT_CODES)
from settlement_engine import (settle, settle_batch, net_positions,
                                total_supply, settlement_summary)

SCALE = W.SCALE
ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── Helpers ───────────────────────────────────────────────────────────────

def _qty(units):
    return W.from_int(units)

def _ledger(**kwargs):
    """Build ledger from keyword args: participant_instrument=units."""
    balances = {}
    for key, units in kwargs.items():
        p, i = key.split("_", 1)
        balances[(p, i)] = _qty(units)
    return Ledger(balances)

def _trade(seller, buyer, si, sq, bi, bq, tid="T"):
    return Trade(tid, seller, buyer, si, _qty(sq), bi, _qty(bq))


# ══════════════════════════════════════════════════════════
# WAD-18 basics
# ══════════════════════════════════════════════════════════

class TestWAD18(unittest.TestCase):

    def test_from_int_exact(self):
        self.assertEqual(W.from_int(100), 100 * SCALE)

    def test_zero_is_zero(self):
        self.assertEqual(W.ZERO, 0)

    def test_assert_wad_rejects_float(self):
        with self.assertRaises(TypeError):
            W.assert_wad(1.0)

    def test_clamp_preserves_wad18(self):
        result = W.clamp(W.from_int(5), W.ZERO, W.from_int(10))
        self.assertEqual(result, W.from_int(5))


# ══════════════════════════════════════════════════════════
# Ledger
# ══════════════════════════════════════════════════════════

class TestLedger(unittest.TestCase):

    def test_zero_balance_for_unknown_account(self):
        ledger = Ledger()
        self.assertEqual(ledger.balance("ALICE", "AAPL"), W.ZERO)

    def test_initial_balance_set_correctly(self):
        ledger = _ledger(ALICE_AAPL=1000)
        self.assertEqual(ledger.balance("ALICE", "AAPL"), _qty(1000))

    def test_negative_initial_balance_rejected(self):
        with self.assertRaises(ValueError):
            Ledger({("ALICE", "AAPL"): -1})

    def test_float_initial_balance_rejected(self):
        with self.assertRaises(TypeError):
            Ledger({("ALICE", "AAPL"): 1.0})

    def test_total_supply_sums_correctly(self):
        ledger = _ledger(ALICE_AAPL=600, BOB_AAPL=400)
        self.assertEqual(ledger.total_supply("AAPL"), _qty(1000))

    def test_total_supply_excludes_other_instruments(self):
        ledger = _ledger(ALICE_AAPL=600, ALICE_MSFT=200)
        self.assertEqual(ledger.total_supply("AAPL"), _qty(600))

    def test_state_hash_deterministic(self):
        l1 = _ledger(ALICE_AAPL=100, BOB_USD=500)
        l2 = _ledger(ALICE_AAPL=100, BOB_USD=500)
        self.assertEqual(l1.state_hash(), l2.state_hash())

    def test_state_hash_changes_on_balance_change(self):
        l1 = _ledger(ALICE_AAPL=100)
        l2 = _ledger(ALICE_AAPL=101)
        self.assertNotEqual(l1.state_hash(), l2.state_hash())

    def test_credit_increases_balance(self):
        ledger = _ledger(ALICE_AAPL=100)
        ledger._credit("ALICE", "AAPL", _qty(50))
        self.assertEqual(ledger.balance("ALICE", "AAPL"), _qty(150))

    def test_debit_decreases_balance(self):
        ledger = _ledger(ALICE_AAPL=100)
        ledger._debit("ALICE", "AAPL", _qty(30))
        self.assertEqual(ledger.balance("ALICE", "AAPL"), _qty(70))

    def test_debit_raises_insufficient_balance(self):
        ledger = _ledger(ALICE_AAPL=100)
        with self.assertRaises(InsufficientBalance):
            ledger._debit("ALICE", "AAPL", _qty(101))

    def test_debit_exact_balance_succeeds(self):
        """Debit exactly the full balance → 0 remaining, no error."""
        ledger = _ledger(ALICE_AAPL=100)
        ledger._debit("ALICE", "AAPL", _qty(100))
        self.assertEqual(ledger.balance("ALICE", "AAPL"), W.ZERO)

    def test_conservation_check_passes_unchanged(self):
        ledger = _ledger(ALICE_AAPL=600, BOB_AAPL=400)
        ref    = ledger.snapshot()
        report = ledger.conservation_check(ref)
        self.assertTrue(report["AAPL"]["conserved"])

    def test_conservation_check_detects_violation(self):
        ledger = _ledger(ALICE_AAPL=600, BOB_AAPL=400)
        ref    = ledger.snapshot()
        ledger._credit("CAROL", "AAPL", _qty(1))  # creates supply from nothing
        with self.assertRaises(ConservationViolation):
            ledger.conservation_check(ref)

    def test_snapshot_is_independent(self):
        ledger = _ledger(ALICE_AAPL=100)
        snap   = ledger.snapshot()
        ledger._credit("ALICE", "AAPL", _qty(50))
        self.assertEqual(snap.balance("ALICE", "AAPL"), _qty(100))
        self.assertEqual(ledger.balance("ALICE", "AAPL"), _qty(150))


# ══════════════════════════════════════════════════════════
# Trade validation
# ══════════════════════════════════════════════════════════

class TestTrade(unittest.TestCase):

    def test_valid_trade_constructed(self):
        t = _trade("ALICE", "BOB", "AAPL", 100, "USD", 17500)
        self.assertEqual(t.sell_quantity, _qty(100))

    def test_zero_sell_quantity_rejected(self):
        with self.assertRaises(ValueError):
            Trade("T", "A", "B", "AAPL", W.ZERO, "USD", _qty(100))

    def test_zero_buy_quantity_rejected(self):
        with self.assertRaises(ValueError):
            Trade("T", "A", "B", "AAPL", _qty(100), "USD", W.ZERO)

    def test_negative_quantity_rejected(self):
        with self.assertRaises(ValueError):
            Trade("T", "A", "B", "AAPL", -1, "USD", _qty(100))

    def test_self_trade_rejected(self):
        with self.assertRaises(ValueError):
            _trade("ALICE", "ALICE", "AAPL", 100, "USD", 17500)

    def test_float_quantity_rejected(self):
        with self.assertRaises(TypeError):
            Trade("T", "A", "B", "AAPL", 1.0, "USD", _qty(100))

    def test_roundtrip_dict(self):
        t  = _trade("ALICE", "BOB", "AAPL", 100, "USD", 17500, "T1")
        t2 = Trade.from_dict(t.to_dict())
        self.assertEqual(t2.sell_quantity, t.sell_quantity)
        self.assertEqual(t2.buyer,         t.buyer)


# ══════════════════════════════════════════════════════════
# PO1: Atomicity — both legs or neither
# ══════════════════════════════════════════════════════════

class TestAtomicity(unittest.TestCase):

    def test_failed_seller_leaves_ledger_unchanged(self):
        """Atomicity: seller insufficient → ledger unchanged."""
        ledger = _ledger(ALICE_AAPL=10, BOB_USD=17500)
        h_pre  = ledger.state_hash()
        t      = _trade("ALICE", "BOB", "AAPL", 100, "USD", 17500)
        result = settle(ledger, t)
        self.assertEqual(result.code, FAILED_INSUFFICIENT_SELLER)
        self.assertEqual(ledger.state_hash(), h_pre)
        self.assertEqual(ledger.balance("ALICE", "AAPL"), _qty(10))
        self.assertEqual(ledger.balance("BOB", "USD"),    _qty(17500))

    def test_failed_buyer_leaves_ledger_unchanged(self):
        """Atomicity: buyer insufficient → ledger unchanged."""
        ledger = _ledger(ALICE_AAPL=1000, BOB_USD=100)
        h_pre  = ledger.state_hash()
        t      = _trade("ALICE", "BOB", "AAPL", 100, "USD", 17500)
        result = settle(ledger, t)
        self.assertEqual(result.code, FAILED_INSUFFICIENT_BUYER)
        self.assertEqual(ledger.state_hash(), h_pre)

    def test_settled_trade_changes_exactly_four_balances(self):
        """Atomicity: all four balance mutations occur on success."""
        ledger = _ledger(ALICE_AAPL=1000, ALICE_USD=0,
                         BOB_AAPL=0,     BOB_USD=17500)
        t = _trade("ALICE", "BOB", "AAPL", 100, "USD", 17500)
        settle(ledger, t)
        self.assertEqual(ledger.balance("ALICE", "AAPL"), _qty(900))
        self.assertEqual(ledger.balance("ALICE", "USD"),  _qty(17500))
        self.assertEqual(ledger.balance("BOB",   "AAPL"), _qty(100))
        self.assertEqual(ledger.balance("BOB",   "USD"),  W.ZERO)


# ══════════════════════════════════════════════════════════
# PO0: Conservation — zero drift
# ══════════════════════════════════════════════════════════

class TestConservation(unittest.TestCase):
    """PO0: total supply of every instrument is invariant."""

    def _check(self, ledger, instrument, expected_units):
        self.assertEqual(ledger.total_supply(instrument), _qty(expected_units))

    def test_conservation_after_single_settlement(self):
        ledger = _ledger(ALICE_AAPL=1000, BOB_USD=17500)
        self._check(ledger, "AAPL", 1000)
        self._check(ledger, "USD",  17500)
        settle(ledger, _trade("ALICE", "BOB", "AAPL", 100, "USD", 17500))
        self._check(ledger, "AAPL", 1000)
        self._check(ledger, "USD",  17500)

    def test_conservation_after_chain_of_settlements(self):
        """Five sequential trades; total supply constant throughout."""
        ledger = _ledger(
            ALICE_AAPL=1000, ALICE_USD=0,
            BOB_AAPL=0,      BOB_USD=100000,
            CAROL_AAPL=500,  CAROL_USD=50000,
        )
        aapl_supply = ledger.total_supply("AAPL")
        usd_supply  = ledger.total_supply("USD")

        trades = [
            _trade("ALICE", "BOB",   "AAPL", 200, "USD", 36000, "T1"),
            _trade("ALICE", "CAROL", "AAPL", 100, "USD", 18000, "T2"),
            _trade("BOB",   "CAROL", "USD",  5000, "AAPL", 25,   "T3"),
            _trade("CAROL", "ALICE", "USD",  1000, "AAPL", 5,    "T4"),
            _trade("BOB",   "ALICE", "AAPL", 50,  "USD",  9000,  "T5"),
        ]
        for t in trades:
            settle(ledger, t)
            self.assertEqual(ledger.total_supply("AAPL"), aapl_supply)
            self.assertEqual(ledger.total_supply("USD"),  usd_supply)

    def test_conservation_report_in_result(self):
        ledger = _ledger(ALICE_AAPL=100, BOB_USD=5000)
        t      = _trade("ALICE", "BOB", "AAPL", 50, "USD", 5000)
        result = settle(ledger, t)
        self.assertTrue(result.conservation_report["AAPL"]["conserved"])
        self.assertTrue(result.conservation_report["USD"]["conserved"])

    def test_zero_drift_wad18_exact(self):
        """Conservation holds as WAD-18 exact integer, not float approximation."""
        ledger = _ledger(ALICE_AAPL=1, BOB_USD=3)
        supply_before = ledger.total_supply("AAPL") + ledger.total_supply("USD")
        settle(ledger, _trade("ALICE", "BOB", "AAPL", 1, "USD", 3))
        supply_after  = ledger.total_supply("AAPL") + ledger.total_supply("USD")
        # Exact integer equality — not within epsilon
        self.assertEqual(supply_before, supply_after)


# ══════════════════════════════════════════════════════════
# PO2: Solvency — no negative balance ever
# ══════════════════════════════════════════════════════════

class TestSolvency(unittest.TestCase):

    def test_no_negative_balance_after_settlement(self):
        ledger = _ledger(ALICE_AAPL=100, BOB_USD=17500)
        settle(ledger, _trade("ALICE", "BOB", "AAPL", 100, "USD", 17500))
        for p in ledger.participants():
            for i in ledger.instruments():
                self.assertGreaterEqual(ledger.balance(p, i), W.ZERO)

    def test_exact_zero_balance_is_valid(self):
        ledger = _ledger(ALICE_AAPL=50, BOB_USD=9000)
        result = settle(ledger, _trade("ALICE", "BOB", "AAPL", 50, "USD", 9000))
        self.assertEqual(result.code, SETTLED)
        self.assertEqual(ledger.balance("ALICE", "AAPL"), W.ZERO)
        self.assertEqual(ledger.balance("BOB", "USD"),    W.ZERO)

    def test_one_unit_over_balance_fails(self):
        """Selling 101 when balance is 100 must fail, not go negative."""
        ledger = _ledger(ALICE_AAPL=100, BOB_USD=99999)
        result = settle(ledger, _trade("ALICE", "BOB", "AAPL", 101, "USD", 99999))
        self.assertEqual(result.code, FAILED_INSUFFICIENT_SELLER)
        self.assertEqual(ledger.balance("ALICE", "AAPL"), _qty(100))


# ══════════════════════════════════════════════════════════
# PO3: Reproducibility
# ══════════════════════════════════════════════════════════

class TestReproducibility(unittest.TestCase):

    def test_same_initial_state_same_result(self):
        def run():
            l = _ledger(ALICE_AAPL=1000, BOB_USD=17500)
            settle(l, _trade("ALICE", "BOB", "AAPL", 100, "USD", 17500))
            return l.state_hash()
        self.assertEqual(run(), run())

    def test_state_hash_is_order_independent(self):
        """Two ledgers built in different insertion order have same hash."""
        l1 = Ledger({("A", "X"): _qty(100), ("B", "Y"): _qty(200)})
        l2 = Ledger({("B", "Y"): _qty(200), ("A", "X"): _qty(100)})
        self.assertEqual(l1.state_hash(), l2.state_hash())


# ══════════════════════════════════════════════════════════
# PO6: Self-trade rejection
# ══════════════════════════════════════════════════════════

class TestSelfTrade(unittest.TestCase):

    def test_self_trade_rejected_at_construction(self):
        """Trade object with seller==buyer must not be constructable."""
        with self.assertRaises(ValueError):
            Trade("T", "ALICE", "ALICE", "AAPL", _qty(100), "USD", _qty(1000))


# ══════════════════════════════════════════════════════════
# Settlement result codes
# ══════════════════════════════════════════════════════════

class TestResultCodes(unittest.TestCase):

    def test_all_result_codes_in_set(self):
        for code in [SETTLED, FAILED_INSUFFICIENT_SELLER, FAILED_INSUFFICIENT_BUYER]:
            self.assertIn(code, RESULT_CODES)

    def test_settled_result_has_settled_true(self):
        ledger = _ledger(ALICE_AAPL=100, BOB_USD=5000)
        r = settle(ledger, _trade("ALICE", "BOB", "AAPL", 50, "USD", 5000))
        self.assertTrue(r.settled)

    def test_failed_result_has_settled_false(self):
        ledger = _ledger(ALICE_AAPL=10, BOB_USD=5000)
        r = settle(ledger, _trade("ALICE", "BOB", "AAPL", 100, "USD", 5000))
        self.assertFalse(r.settled)

    def test_hash_unchanged_on_failure(self):
        ledger = _ledger(ALICE_AAPL=10)
        h = ledger.state_hash()
        r = settle(ledger, _trade("ALICE", "BOB", "AAPL", 100, "USD", 1000))
        self.assertEqual(r.ledger_hash_before, r.ledger_hash_after)
        self.assertEqual(r.ledger_hash_after, h)

    def test_hash_changes_on_success(self):
        ledger = _ledger(ALICE_AAPL=100, BOB_USD=5000)
        r = settle(ledger, _trade("ALICE", "BOB", "AAPL", 50, "USD", 5000))
        self.assertNotEqual(r.ledger_hash_before, r.ledger_hash_after)


# ══════════════════════════════════════════════════════════
# Batch settlement
# ══════════════════════════════════════════════════════════

class TestBatch(unittest.TestCase):

    def test_batch_returns_one_result_per_trade(self):
        ledger  = _ledger(ALICE_AAPL=1000, BOB_USD=100000)
        trades  = [_trade("ALICE", "BOB", "AAPL", 100, "USD", 17500, f"T{i}")
                   for i in range(5)]
        results = settle_batch(ledger, trades)
        self.assertEqual(len(results), 5)

    def test_batch_failed_trade_does_not_block_subsequent(self):
        """A failed trade must not prevent later trades from settling."""
        ledger = _ledger(
            ALICE_AAPL=100, BOB_USD=17500,
            CAROL_AAPL=500, DEALER_USD=50000
        )
        trades = [
            _trade("ALICE", "BOB",    "AAPL", 200, "USD", 35000, "T1"),  # fails (only 100)
            _trade("CAROL", "DEALER", "AAPL", 100, "USD", 18000, "T2"),  # settles
        ]
        results = settle_batch(ledger, trades)
        self.assertEqual(results[0].code, FAILED_INSUFFICIENT_SELLER)
        self.assertEqual(results[1].code, SETTLED)

    def test_batch_conservation_across_all_trades(self):
        ledger = _ledger(ALICE_AAPL=1000, BOB_USD=100000)
        aapl_supply = ledger.total_supply("AAPL")
        usd_supply  = ledger.total_supply("USD")
        trades = [_trade("ALICE", "BOB", "AAPL", 100, "USD", 17500, f"T{i}")
                  for i in range(5)]
        settle_batch(ledger, trades)
        self.assertEqual(ledger.total_supply("AAPL"), aapl_supply)
        self.assertEqual(ledger.total_supply("USD"),  usd_supply)


# ══════════════════════════════════════════════════════════
# Netting
# ══════════════════════════════════════════════════════════

class TestNetting(unittest.TestCase):

    def test_offsetting_trades_net_to_zero(self):
        """ALICE sells 100 AAPL to BOB, BOB sells 100 AAPL back to ALICE:
        net position for both is zero in AAPL."""
        trades = [
            _trade("ALICE", "BOB", "AAPL", 100, "USD", 17500, "T1"),
            _trade("BOB", "ALICE", "AAPL", 100, "USD", 17500, "T2"),
        ]
        nets = net_positions(trades)
        self.assertEqual(nets.get(("ALICE", "AAPL"), W.ZERO), W.ZERO)
        self.assertEqual(nets.get(("BOB",   "AAPL"), W.ZERO), W.ZERO)
        self.assertEqual(nets.get(("ALICE", "USD"),  W.ZERO), W.ZERO)
        self.assertEqual(nets.get(("BOB",   "USD"),  W.ZERO), W.ZERO)

    def test_net_positions_are_wad18(self):
        trades = [_trade("A", "B", "X", 100, "Y", 200)]
        nets   = net_positions(trades)
        for v in nets.values():
            self.assertIsInstance(v, int)
            self.assertNotIsInstance(v, bool)

    def test_net_sum_is_zero_per_instrument(self):
        """Conservation: sum of all net positions per instrument = 0."""
        trades = [
            _trade("A", "B", "X", 100, "Y", 50, "T1"),
            _trade("B", "C", "X", 60,  "Y", 30, "T2"),
            _trade("C", "A", "Y", 40,  "X", 80, "T3"),
        ]
        nets = net_positions(trades)
        for instr in ["X", "Y"]:
            total = sum(v for (_, i), v in nets.items() if i == instr)
            self.assertEqual(total, W.ZERO)


# ══════════════════════════════════════════════════════════
# Reference pipeline
# ══════════════════════════════════════════════════════════

class TestReferencePipeline(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        raw  = json.load(open(os.path.join(ROOT, "data", "initial_state.json")))
        balances = {}
        for entry in raw["initial_balances"]:
            balances[(entry["participant"], entry["instrument"])] = \
                W.from_int(entry["quantity_units"])
        cls.ledger = Ledger(balances)
        cls.initial_supplies = {
            instr: cls.ledger.total_supply(instr)
            for instr in cls.ledger.instruments()
        }
        cls.results = []
        for td in raw["trades"]:
            t = Trade(td["trade_id"], td["seller"], td["buyer"],
                      td["sell_instrument"], W.from_int(td["sell_quantity_units"]),
                      td["buy_instrument"],  W.from_int(td["buy_quantity_units"]),
                      "2026-11-02T00:00:00Z")
            r = settle(cls.ledger, t)
            r_dict = r.to_dict()
            r_dict["expected"] = td["expected_result"]
            cls.results.append(r_dict)

    def test_all_decisions_match_expected(self):
        for r in self.results:
            self.assertEqual(r["code"], r["expected"],
                             f"Trade mismatch: {r['trade_id']}")

    def test_final_conservation_holds(self):
        for instr, ref in self.initial_supplies.items():
            self.assertEqual(self.ledger.total_supply(instr), ref,
                             f"Conservation violated for {instr}")

    def test_all_settled_trades_show_conservation_ok(self):
        for r in self.results:
            if r["settled"]:
                self.assertTrue(r["conservation_ok"],
                                f"Conservation failed for {r['trade_id']}")

    def test_settlement_summary_correct(self):
        n_settled = sum(1 for r in self.results if r["settled"])
        self.assertEqual(n_settled, 4)

    def test_no_negative_balances_in_final_ledger(self):
        for p in self.ledger.participants():
            for i in self.ledger.instruments():
                self.assertGreaterEqual(self.ledger.balance(p, i), W.ZERO,
                                        f"Negative balance: ({p}, {i})")


if __name__ == "__main__":
    unittest.main(verbosity=2)
