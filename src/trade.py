"""
Trade — the unit of settlement.

A trade is a bilateral agreement to exchange a quantity of one instrument
for a quantity of another.  It is a value object: immutable once created.

Fields
------
trade_id        : unique identifier
seller          : participant delivering sell_instrument
buyer           : participant delivering buy_instrument
sell_instrument : asset being delivered by seller
sell_quantity   : WAD-18 quantity of sell_instrument
buy_instrument  : asset being delivered by buyer
buy_quantity    : WAD-18 quantity of buy_instrument
timestamp       : ISO-8601 string (for audit; does not affect settlement)

Constraints (enforced at construction)
---------------------------------------
- sell_quantity > 0
- buy_quantity  > 0
- seller != buyer  (self-trade rejected)
- sell_instrument != buy_instrument is NOT required: same-instrument
  transfers (e.g. cash-to-cash internal book entries) are valid
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wad18 as W


class Trade:

    def __init__(self,
                 trade_id: str,
                 seller: str,
                 buyer: str,
                 sell_instrument: str,
                 sell_quantity: int,
                 buy_instrument: str,
                 buy_quantity: int,
                 timestamp: str = ""):
        W.assert_wad(sell_quantity, buy_quantity)
        if sell_quantity <= W.ZERO:
            raise ValueError("sell_quantity must be positive: %r" % sell_quantity)
        if buy_quantity <= W.ZERO:
            raise ValueError("buy_quantity must be positive: %r" % buy_quantity)
        if str(seller) == str(buyer):
            raise ValueError("self-trade rejected: seller == buyer == %r" % seller)

        self.trade_id        = str(trade_id)
        self.seller          = str(seller)
        self.buyer           = str(buyer)
        self.sell_instrument = str(sell_instrument)
        self.sell_quantity   = int(sell_quantity)
        self.buy_instrument  = str(buy_instrument)
        self.buy_quantity    = int(buy_quantity)
        self.timestamp       = str(timestamp)

    def to_dict(self) -> dict:
        return {
            "trade_id":        self.trade_id,
            "seller":          self.seller,
            "buyer":           self.buyer,
            "sell_instrument": self.sell_instrument,
            "sell_quantity":   self.sell_quantity,
            "buy_instrument":  self.buy_instrument,
            "buy_quantity":    self.buy_quantity,
            "timestamp":       self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Trade":
        return cls(
            trade_id        = d["trade_id"],
            seller          = d["seller"],
            buyer           = d["buyer"],
            sell_instrument = d["sell_instrument"],
            sell_quantity   = d["sell_quantity"],
            buy_instrument  = d["buy_instrument"],
            buy_quantity    = d["buy_quantity"],
            timestamp       = d.get("timestamp", ""),
        )


# ── Settlement result codes ───────────────────────────────────────────────

SETTLED                     = "SETTLED"
FAILED_INSUFFICIENT_SELLER  = "FAILED_INSUFFICIENT_SELLER"
FAILED_INSUFFICIENT_BUYER   = "FAILED_INSUFFICIENT_BUYER"

RESULT_CODES = frozenset([
    SETTLED,
    FAILED_INSUFFICIENT_SELLER,
    FAILED_INSUFFICIENT_BUYER,
])


class SettlementResult:

    def __init__(self, code: str, trade: Trade,
                 ledger_hash_before: str = "",
                 ledger_hash_after:  str = "",
                 conservation_report: dict = None):
        assert code in RESULT_CODES, "invalid result code: %r" % code
        self.code                = code
        self.trade               = trade
        self.settled             = (code == SETTLED)
        self.ledger_hash_before  = ledger_hash_before
        self.ledger_hash_after   = ledger_hash_after
        self.conservation_report = conservation_report or {}

    def to_dict(self) -> dict:
        return {
            "code":                self.code,
            "settled":             self.settled,
            "trade_id":            self.trade.trade_id,
            "ledger_hash_before":  self.ledger_hash_before,
            "ledger_hash_after":   self.ledger_hash_after,
            "conservation_ok":     all(
                v["conserved"] for v in self.conservation_report.values()
            ) if self.conservation_report else True,
        }
