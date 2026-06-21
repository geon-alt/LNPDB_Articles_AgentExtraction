# README for Codex CLI / Claude Code

This project is a workspace for external coding agents to operate the existing LNPDB article extraction pipeline. Do not build a new Python LLM backend or move scripts out of `0_mark_down_gen/`.

The recommended default for active judgment stages is API-free: `external_agent` mode creates a task markdown file for Codex CLI / Claude Code, and `heuristic` mode writes deterministic low-confidence helper outputs without Gemini.

Start here:

1. Read `agent_workspace/AGENT_INSTRUCTIONS.md`.
2. Read `agent_workspace/PIPELINE_SPEC.md`.
3. Read `agent_workspace/STAGE_CONTRACTS.md`.
4. Inspect `agent_workspace/agent_state.json` and `agent_workspace/task_queue.json`.
5. Use `Agent_Task_Runner.py` to observe, run, validate, and log stages.

Basic commands:

```bash
python Agent_Task_Runner.py observe --paper-folder "<PAPER_FOLDER>"
python Agent_Task_Runner.py next --paper-folder "<PAPER_FOLDER>"
python Agent_Task_Runner.py run --stage "03_figure_mapping" --paper-folder "<PAPER_FOLDER>" --dry-run
python Agent_Task_Runner.py run --stage "03_figure_mapping" --paper-folder "<PAPER_FOLDER>"
python Agent_Task_Runner.py validate --stage "03_figure_mapping" --paper-folder "<PAPER_FOLDER>"
```

## How to run API-free workflow

1. Complete pre-agent stages through manual review.
2. Ensure `<PAPER_FOLDER>/.manual_select_review_done` exists.
3. Run the active stage with the default `external_agent` mode:

```bash
python Agent_Task_Runner.py run --stage "03_figure_mapping" --paper-folder "<PAPER_FOLDER>"
```

4. Read the generated task file under `agent_workspace/tasks/`.
5. Have Codex CLI / Claude Code inspect the paper folder and produce the expected output JSON/CSV directly.
6. Validate:

```bash
python Agent_Task_Runner.py validate --stage "03_figure_mapping" --paper-folder "<PAPER_FOLDER>"
```

## How to switch stage mode

Edit `STAGE_EXECUTION_MODE` in `Agent_Task_Runner.py`:

```python
STAGE_EXECUTION_MODE = {
    "03_figure_mapping": "external_agent",
    "03_split_excel_blocks_batch": "external_agent",
    "04_figure_separate": "external_agent",
    "04_ft_excel_matcher": "external_agent",
}
```

Allowed values:

- `external_agent`: create `agent_workspace/tasks/*.md`; do not import legacy Gemini scripts.
- `heuristic`: generate deterministic API-free low-confidence outputs.
- `legacy`: run old Gemini/API scripts.

Recommended defaults:

- `03_figure_mapping`: `external_agent`
- `03_split_excel_blocks_batch`: `external_agent` or `heuristic`
- `04_figure_separate`: `external_agent`
- `04_ft_excel_matcher`: `external_agent`

Legacy mode requires old Gemini dependencies and credentials. API-free `external_agent` and `heuristic` modes must work without `find_api.py`, `LLM_API.py`, `LLM_Batch.py`, Vertex credentials, or Gemini credentials.

Important gates:

- `00_marker`, `01_make_ft_csv`, `02_ft_selector`, and `02b_manual_review` are pre-agent stages.
- `03_figure_mapping` and later are active agent stages.
- Active agent stages require `<PAPER_FOLDER>/.manual_select_review_done`.
- Current repository filename is `0_mark_down_gen/04_figure_saperate_gemini.py`; the stage name remains `04_figure_separate`.

Human review command:

```bash
streamlit run 0_mark_down_gen/02B_FT_manual_selector_gui.py -- --paper-folder "<PAPER_FOLDER>"
```
