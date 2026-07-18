"""Adversarial self-tester (B3.7, §Implementation sequencing B3).

Known-bad probes that exercise each gate's deny path on a cadence (run in the B3.6 maintenance
window). A gate that stops denying a known-bad intent has regressed — caught here, not in prod.
"""
