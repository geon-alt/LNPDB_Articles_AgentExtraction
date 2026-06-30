# active_legacy_utils

`active_legacy_utils/` contains selected reusable helpers extracted from copied legacy code.
It is not the legacy pipeline and is not wired into the active workflow yet.

Policy:
- No provider-client, cloud batch, or remote judgment code belongs here.
- No image-based molecule-structure recognition code belongs here.
- The active workflow remains `Agent_Task_Runner.py` using `external_agent` or `heuristic` stages.
- Current unified outputs keep formulation/component SMILES columns blank.
- Experimental values are populated only from reliable mapped Excel/source-data blocks.
- Graph image digitization remains disabled.

These modules are intended for later, explicit reuse in active API-free paths after review.

