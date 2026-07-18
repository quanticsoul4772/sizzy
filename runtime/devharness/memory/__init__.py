"""Cross-project memory — federated, verified-before-trusted (B5.5, §S7; OQ-B5-3=B; Inv 17).

Each project carries its own proj_memory. Cross-project sharing is explicit operator-driven export/
import: an imported entry is **untrusted** (verified_locally=0) until verified against fresh local
evidence (Inv 17). Locally-created entries are trusted in this project's context from the start.
"""
