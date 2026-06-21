# Runbook

Use this runbook when a coding agent starts in the repository.

## 1. Read Project Instructions

Read:

- `README_FOR_CODEX_OR_CLAUDE.md`
- `agent_workspace/AGENT_INSTRUCTIONS.md`
- `agent_workspace/PIPELINE_SPEC.md`
- `agent_workspace/STAGE_CONTRACTS.md`
- `agent_workspace/OUTPUT_SCHEMA.md`
- `agent_workspace/TROUBLESHOOTING.md`

## 2. Observe State

```bash
python Agent_Task_Runner.py observe --paper-folder "<PAPER_FOLDER>"
```

Also inspect:

- `agent_workspace/agent_state.json`
- `agent_workspace/task_queue.json`
- latest log in `agent_workspace/logs/`
- files under `<PAPER_FOLDER>`

## 3. Find Next Stage

```bash
python Agent_Task_Runner.py next --paper-folder "<PAPER_FOLDER>"
```

If the next stage is `02b_manual_review`, stop and ask a human to run:

```bash
streamlit run 0_mark_down_gen/02B_FT_manual_selector_gui.py -- --paper-folder "<PAPER_FOLDER>"
```

## 4. Run an Eligible Stage

Dry run first when uncertain:

```bash
python Agent_Task_Runner.py run --stage "<STAGE_NAME>" --paper-folder "<PAPER_FOLDER>" --dry-run
```

Then run:

```bash
python Agent_Task_Runner.py run --stage "<STAGE_NAME>" --paper-folder "<PAPER_FOLDER>"
```

## 5. Validate

```bash
python Agent_Task_Runner.py validate --stage "<STAGE_NAME>" --paper-folder "<PAPER_FOLDER>"
```

If validation fails, read the stage log and troubleshoot before retrying.

## 6. Log and Continue

The runner updates state automatically. If you run a legacy script manually, update:

- `agent_workspace/agent_state.json`
- `agent_workspace/task_queue.json`
- `agent_workspace/logs/<paper-name>.jsonl`

Then call `next` again.

