"""
Ledger — WAD-18 account balances.

The ledger is a map: (participant_id, instrument_id) → balance (WAD-18).

Conservation law (the core invariant):
  ∀ instrument i:  ∑_j balance(j, i)  =  constant

This law is enforced as a WAD-18 exact integer equality.  Floating-point
drift cannot violate it because there is no floating-point arithmetic.

All monetary quantities are represented as WAD-18 integers.  In the
settlement domain, a "quantity" of any instrument (shares, bonds, cash,
tokens) is expressed as units × 10^18.  This gives 18 decimal places of
sub-unit precision with no rounding or truncation.

Solvency invariant:
  ∀ (participant, instrument):  balance ≥ 0

This is enforced by debit(): attempting to debit more than the current
balance raises InsufficientBalance rather than producing a negative balance.
"""

import hashlib, json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wad18 as W

ZERO = W.ZERO


class InsufficientBalance(Exception):
    pass


class Ledger:
    """
    Immutable-snapshot ledger of WAD-18 account balances.

    The ledger is mutable in the sense that balances change with each
    settlement, but every state transition is auditable via state_hash().
    The conservation law is verified by conservation_check() after every
    atomic settlement.
    """

    def __init__(self, balances: dict = None):
        """
        Parameters
        ----------
        balances : dict mapping (participant_id, instrument_id) → int (WAD-18)
        """
        self._b = {}
        for (p, i), v in (balances or {}).items():
            W.assert_wad(v)
            if v < ZERO:
                raise ValueError(
                    "negative initial balance for (%s, %s): %r" % (p, i, v))
            self._b[(str(p), str(i))] = v

    # ── read ──────────────────────────────────────────────────────────────

    def balance(self, participant: str, instrument: str) -> int:
        """Return WAD-18 balance; 0 if account not yet opened."""
        return self._b.get((str(participant), str(instrument)), ZERO)

    def participants(self) -> list:
        return sorted({p for p, _ in self._b})

    def instruments(self) -> list:
        return sorted({i for _, i in self._b})

    def total_supply(self, instrument: str) -> int:
        """Sum of all balances for instrument i — must be constant. [WAD-18]"""
        return sum(
            v for (_, instr), v in self._b.items()
            if instr == str(instrument)
        )

    def to_dict(self) -> dict:
        return {"%s|%s" % (p, i): v for (p, i), v in sorted(self._b.items())}

    def state_hash(self) -> str:
        """SHA-256 of the canonical sorted balance map.

        Two ledgers with identical balances produce identical hashes.
        Any single-cent discrepancy produces a different hash.
        """
        canon = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canon.encode()).hexdigest()

    # ── write (internal — called only by settlement engine) ───────────────

    def _credit(self, participant: str, instrument: str, amount: int) -> None:
        """Add amount to balance.  amount must be positive WAD-18."""
        W.assert_wad(amount)
        if amount <= ZERO:
            raise ValueError("credit amount must be positive: %r" % amount)
        key = (str(participant), str(instrument))
        self._b[key] = self._b.get(key, ZERO) + amount

    def _debit(self, participant: str, instrument: str, amount: int) -> None:
        """Subtract amount from balance.  Raises InsufficientBalance if
        the balance would go negative."""
        W.assert_wad(amount)
        if amount <= ZERO:
            raise ValueError("debit amount must be positive: %r" % amount)
        key = (str(participant), str(instrument))
        current = self._b.get(key, ZERO)
        if current < amount:
            raise InsufficientBalance(
                "(%s, %s): balance %r < required %r"
                % (str(participant), str(instrument), current, amount)
            )
        self._b[key] = current - amount

    # ── conservation check ────────────────────────────────────────────────

    def conservation_check(self, reference: "Ledger") -> dict:
        """
        Verify the conservation law against a reference ledger state.

        For every instrument that exists in either ledger, the total supply
        must be identical (WAD-18 exact equality).

        Returns a dict mapping instrument → (reference_total, current_total, ok).
        Raises ConservationViolation if any instrument fails.
        """
        instruments = set(self.instruments()) | set(reference.instruments())
        report = {}
        violations = []
        for instr in sorted(instruments):
            ref_total  = reference.total_supply(instr)
            curr_total = self.total_supply(instr)
            ok = (ref_total == curr_total)
            report[instr] = {
                "reference_total":  ref_total,
                "current_total":    curr_total,
                "conserved":        ok,
                "drift":            curr_total - ref_total,
            }
            if not ok:
                violations.append(instr)
        if violations:
            raise ConservationViolation(
                "conservation violated for instruments: %s" % violations,
                report
            )
        return report

    def snapshot(self) -> "Ledger":
        """Return a shallow copy for pre/post comparison."""
        return Ledger(dict(self._b))


class ConservationViolation(Exception):
    def __init__(self, msg, report):
        super().__init__(msg)
        self.report = report
