"""Learning spine — retro auditor (B5, §S7).

Every terminal outcome feeds a retro auditor (in the B3.6 maintenance window) that produces CANDIDATE
changes for operator review — never auto-applied (SC-2). B5.0 ships the trigger substrate (scheduler +
retro_run event); the compositional engine (T0 pattern-match + LLM-for-residue, OQ-B5-4=C) lands in B5.1.
"""
