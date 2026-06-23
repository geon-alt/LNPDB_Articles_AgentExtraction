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

Unified extraction:

```bash
python Agent_Task_Runner.py run --stage 06_unified_lnpdb_extraction --paper-folder "<PAPER_FOLDER>"
python Agent_Task_Runner.py validate --stage 06_unified_lnpdb_extraction --paper-folder "<PAPER_FOLDER>"
```

API-free active-stage sequence:

```bash
python Agent_Task_Runner.py run --stage 03_figure_mapping --paper-folder "<PAPER_FOLDER>"
python Agent_Task_Runner.py run --stage 03_split_excel_blocks_batch --paper-folder "<PAPER_FOLDER>"
python Agent_Task_Runner.py run --stage 04_figure_separate --paper-folder "<PAPER_FOLDER>"
python Agent_Task_Runner.py run --stage 04_ft_excel_matcher --paper-folder "<PAPER_FOLDER>"
python Agent_Task_Runner.py run --stage 05_smiles_structure_resolution --paper-folder "<PAPER_FOLDER>"
python Agent_Task_Runner.py run --stage 06_unified_lnpdb_extraction --paper-folder "<PAPER_FOLDER>"
python Agent_Task_Runner.py run --stage 07_finalize_unified_table --paper-folder "<PAPER_FOLDER>"
```

Automatic external CLI agent orchestration:

```bash
python Agent_Task_Runner.py run-agent-active --paper-folder "<PAPER_FOLDER>" --agent codex
python Agent_Task_Runner.py run-agent-active --paper-folder "<PAPER_FOLDER>" --agent codex --stream-agent-output
```

Custom command examples:

```bash
python Agent_Task_Runner.py run-agent-active --paper-folder "<PAPER_FOLDER>" --agent custom --agent-command "codex exec --cd \"{project_root}\" --dangerously-bypass-approvals-and-sandbox --add-dir \"{paper_folder}\" -"
python Agent_Task_Runner.py run-agent-active --paper-folder "<PAPER_FOLDER>" --agent custom --agent-command "cmd /c codex exec --cd \"{project_root}\" --dangerously-bypass-approvals-and-sandbox --add-dir \"{paper_folder}\" -"
```

Limit stages or retry behavior:

```bash
python Agent_Task_Runner.py run-agent-active --paper-folder "<PAPER_FOLDER>" --agent codex --stages 03_figure_mapping 04_figure_separate 06_unified_lnpdb_extraction
python Agent_Task_Runner.py run-agent-active --paper-folder "<PAPER_FOLDER>" --agent codex --max-agent-retries 2 --continue-on-error
python Agent_Task_Runner.py run-agent-active --paper-folder "<PAPER_FOLDER>" --agent codex --no-skip-valid
python Agent_Task_Runner.py run-agent-active --paper-folder "<PAPER_FOLDER>" --agent codex --stream-agent-output
```

`run-agent-active` creates task markdown for `external_agent` stages, sends the prompt to the chosen CLI agent through stdin when the command includes `-` or `{prompt_stdin}`, validates outputs, appends validation feedback to the task file on failure, retries up to `--max-agent-retries`, and proceeds stage by stage. Valid stages are skipped by default and logged as `stage_skip_valid`. Use `--stream-agent-output` to see Codex/Claude stdout and stderr in real time while still preserving log tails.

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
