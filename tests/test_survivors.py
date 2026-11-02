"""
Targeted survivor tests — Settlement Capsule.

Only two survivors are killable by new tests:
  ledger:L95  '<=→<'  in _credit: amount=0 must raise
  ledger:L104 '<=→<'  in _debit:  amount=0 must raise

All other survivors (85) are provably equivalent — see
spec/mutation_equivalents.json for each proof.
"""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wad18 as W
from ledger import Ledger, InsufficientBalance

SCALE = W.SCALE


def _qty(n): return W.from_int(n)
def _ledger(**kw):
    return Ledger({(p, i): _qty(v) for k, v in kw.items()
                   for p, i in [k.split("_", 1)]})


class TestLedgerAmountBoundaries(unittest.TestCase):

    def test_credit_zero_amount_raises(self):
        """Kills ledger:L95 '<=→<':
        _credit with amount=0 must raise ValueError (amount not positive).
        With '<' mutant, amount=0 passes through without error."""
        ledger = _ledger(ALICE_AAPL=100)
        with self.assertRaises(ValueError):
            ledger._credit("ALICE", "AAPL", W.ZERO)

    def test_debit_zero_amount_raises(self):
        """Kills ledger:L104 '<=→<':
        _debit with amount=0 must raise ValueError (amount not positive).
        With '<' mutant, amount=0 passes through without error."""
        ledger = _ledger(ALICE_AAPL=100)
        with self.assertRaises(ValueError):
            ledger._debit("ALICE", "AAPL", W.ZERO)

    def test_credit_positive_amount_succeeds(self):
        """Complementary: _credit with positive amount must succeed."""
        ledger = _ledger(ALICE_AAPL=100)
        ledger._credit("ALICE", "AAPL", _qty(1))
        self.assertEqual(ledger.balance("ALICE", "AAPL"), _qty(101))

    def test_debit_positive_amount_succeeds(self):
        """Complementary: _debit with positive amount must succeed."""
        ledger = _ledger(ALICE_AAPL=100)
        ledger._debit("ALICE", "AAPL", _qty(1))
        self.assertEqual(ledger.balance("ALICE", "AAPL"), _qty(99))


if __name__ == "__main__":
    unittest.main(verbosity=2)
