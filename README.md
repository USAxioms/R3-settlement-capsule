# 🛡️ Deterministic Reproducibility & CVM Verification Architecture

This repository contains a containerized execution environment engineered under strict **Weak Axiomatic Decidability ($WAD18$)** and **Russell Recursive Refinement ($R^3$)** determinism standards. Every execution capsule is designed to be torn down and rebuilt from scratch with zero floating-point drift and absolute byte-identical verification.

---

## 🏛️ Capsule Valuation Model (CVM) Verification Pipeline

The Capsule Valuation Model harness ensures that valuation outputs, state logs, and execution traces are cryptographically verified against specification parameters before output state persistence.

### Key Verification Safeguards
* **Canonical SHA-256 Serialization:** Manifest hashes are computed against sorted-key JSON byte streams with compact separators (`sort_keys=True`, `separators=(',', ':')`) to guarantee cross-language and cross-platform key-order invariance.
* **Persistent State Preservation:** Build routines isolate transient logs and temporary caches for cleanup while preserving baseline state outputs (`cvm_value.json`) behind explicit staleness checks.
* **Self-Referential Exclusion:** Automated audit passes exclude post-execution verification sidecars (`cvm_manifest.json`) from baseline diff comparisons, preventing circular build failures during clean-room reruns.

---

## 🚀 Clean-Room Execution & Validation Procedure

To execute a fresh verification pass from an extracted, clean repository state:

```bash
# 1. Evaluate baseline staleness and purge transient execution caches
python3 -m cvm_manifest --check-staleness

# 2. Execute full deterministic build sequence
./run.sh
