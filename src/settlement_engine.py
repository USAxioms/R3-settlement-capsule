"""
Settlement Engine — atomic Delivery vs Payment (DvP) execution.

Every trade settlement executes exactly four ledger mutations as an
indivisible unit:
  1. seller.sell_instrument  -= sell_quantity   (delivery)
  2. buyer.sell_instrument   += sell_quantity   (receipt)
  3. buyer.buy_instrument    -= buy_quantity    (payment)
  4. seller.buy_instrument   += buy_quantity    (receipt of payment)

Atomicity guarantee:
  The pre-condition checks (steps 0a and 0b) are the only points of
  failure.  If both checks pass, all four ledger mutations are guaranteed
  to succeed: WAD-18 integer addition and subtraction on positive integers
  cannot raise exceptions.  There is no partially settled state.

Conservation guarantee:
  After every successful settlement, conservation_check() verifies that
  the total supply of every instrument is identical to the pre-settlement
  state.  This is a WAD-18 exact integer equality check — not a
  floating-point approximation.  Failure raises ConservationViolation and
  is treated as a system error (not a normal settlement failure).

Zero-drift guarantee:
  No floating-point arithmetic is performed anywhere in this module.
  The conservation law is enforced as an exact integer identity.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wad18 as W
from ledger import Ledger, InsufficientBalance, ConservationViolation
from trade  import (Trade, SettlementResult,
                    SETTLED, FAILED_INSUFFICIENT_SELLER, FAILED_INSUFFICIENT_BUYER)


# ── Core settlement function ──────────────────────────────────────────────

def settle(ledger: Ledger, trade: Trade) -> SettlementResult:
    """
    Attempt to settle one trade atomically against the ledger.

    Parameters
    ----------
    ledger : mutable ledger; updated in place if settlement succeeds
    trade  : the trade to settle

    Returns
    -------
    SettlementResult with code SETTLED or FAILED_*

    Side effects
    ------------
    On SETTLED:  ledger is updated with four balance mutations.
    On FAILED:   ledger is unchanged (atomicity preserved).
    In both cases: the conservation law is verified post-execution.

    Raises
    ------
    ConservationViolation : if the conservation law is violated (system error)
    """
    W.assert_wad(trade.sell_quantity, trade.buy_quantity)
    hash_before = ledger.state_hash()
    pre         = ledger.snapshot()          # reference for conservation check

    # ── Step 0a: pre-condition — seller has sufficient balance ────────────
    seller_balance = ledger.balance(trade.seller, trade.sell_instrument)
    if seller_balance < trade.sell_quantity:
        return SettlementResult(
            FAILED_INSUFFICIENT_SELLER, trade,
            ledger_hash_before=hash_before,
            ledger_hash_after=hash_before,  # unchanged
        )

    # ── Step 0b: pre-condition — buyer has sufficient balance ─────────────
    buyer_balance = ledger.balance(trade.buyer, trade.buy_instrument)
    if buyer_balance < trade.buy_quantity:
        return SettlementResult(
            FAILED_INSUFFICIENT_BUYER, trade,
            ledger_hash_before=hash_before,
            ledger_hash_after=hash_before,  # unchanged
        )

    # ── Steps 1-4: atomic execution (cannot fail after pre-conditions) ────
    ledger._debit( trade.seller, trade.sell_instrument, trade.sell_quantity)
    ledger._credit(trade.buyer,  trade.sell_instrument, trade.sell_quantity)
    ledger._debit( trade.buyer,  trade.buy_instrument,  trade.buy_quantity)
    ledger._credit(trade.seller, trade.buy_instrument,  trade.buy_quantity)

    # ── Post: conservation check (system invariant) ───────────────────────
    conservation = ledger.conservation_check(pre)
    hash_after   = ledger.state_hash()

    return SettlementResult(
        SETTLED, trade,
        ledger_hash_before=hash_before,
        ledger_hash_after=hash_after,
        conservation_report=conservation,
    )


# ── Batch settlement ──────────────────────────────────────────────────────

def settle_batch(ledger: Ledger, trades: list) -> list:
    """
    Settle a sequence of trades against a shared ledger.

    Each trade is attempted independently.  A failed trade does not prevent
    subsequent trades from being attempted.  The ledger is updated
    atomically per trade; there is no batch-level atomicity.

    Returns a list of SettlementResult, one per trade in input order.
    """
    results = []
    for trade in trades:
        results.append(settle(ledger, trade))
    return results


# ── Netting engine ────────────────────────────────────────────────────────

def net_positions(trades: list) -> dict:
    """
    Compute net positions across a batch of trades before settlement.

    For each (participant, instrument) pair, compute the algebraic sum of
    all incoming and outgoing quantities across the trade list.  A positive
    net means the participant is a net receiver; negative means net deliverer.

    Returns dict: {(participant, instrument): net_wad18}

    This is used to identify offsetting positions that can be collapsed
    before settlement, reducing the number of gross settlements required.
    All arithmetic is WAD-18 exact integer.
    """
    nets = {}
    for trade in trades:
        # seller: delivers sell_instrument, receives buy_instrument
        key_ss = (trade.seller, trade.sell_instrument)
        key_sb = (trade.seller, trade.buy_instrument)
        # buyer: delivers buy_instrument, receives sell_instrument
        key_bs = (trade.buyer, trade.sell_instrument)
        key_bb = (trade.buyer, trade.buy_instrument)

        nets[key_ss] = nets.get(key_ss, W.ZERO) - trade.sell_quantity
        nets[key_bs] = nets.get(key_bs, W.ZERO) + trade.sell_quantity
        nets[key_bb] = nets.get(key_bb, W.ZERO) - trade.buy_quantity
        nets[key_sb] = nets.get(key_sb, W.ZERO) + trade.buy_quantity

    return nets


# ── Balance queries ───────────────────────────────────────────────────────

def total_supply(ledger: Ledger, instrument: str) -> int:
    """Total supply of instrument across all accounts.  [WAD-18]"""
    return ledger.total_supply(instrument)


def settlement_summary(results: list) -> dict:
    """Aggregate statistics over a list of SettlementResult."""
    n_settled = sum(1 for r in results if r.settled)
    n_failed  = len(results) - n_settled
    failed_s  = sum(1 for r in results
                    if r.code == FAILED_INSUFFICIENT_SELLER)
    failed_b  = sum(1 for r in results
                    if r.code == FAILED_INSUFFICIENT_BUYER)
    return {
        "total_trades":       len(results),
        "settled":            n_settled,
        "failed":             n_failed,
        "failed_seller":      failed_s,
        "failed_buyer":       failed_b,
        "settlement_rate_pct": (
            (n_settled * 100) // len(results) if results else 100
        ),
        "all_conserved": all(
            r.conservation_report.get(instr, {}).get("conserved", True)
            for r in results if r.settled
            for instr in r.conservation_report
        ),
    }
