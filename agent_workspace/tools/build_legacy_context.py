from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTEXT_ROOT = PROJECT_ROOT / "agent_workspace" / "legacy_context"
FULL_COPY_ROOT = CONTEXT_ROOT / "full_copy"
BY_STAGE_ROOT = CONTEXT_ROOT / "by_stage"

SOURCE_DIRS = [
    "0_mark_down_gen",
    "1_Extract_Exp_Figs",
    "2_Extract_SMILES",
    "3_Extract_Formula_by_Figs",
    "4_Extract_Exp_Vals",
    "active_legacy_utils",
]

EXCLUDED_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".git",
    ".venv",
    "venv",
    "env",
    "_batch_jobs",
    "outputs",
    "output",
    "paper_runs",
    "Exp_Excel_Blocks",
    "pdf_page_renders",
    "separated_panels_gemini",
    "markdown_sentence_index",
    "Example_Figs",
    "examples",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".gif",
    ".pdf",
}

SECRET_FILE_NAMES = {
    "vertex.json",
    "gemini_api.txt",
}

STAGE_INDEX = {
    "00_marker": {
        "purpose": "PDF-to-markdown Marker conversion command pattern and output placement.",
        "reference_paths": [
            "full_copy/0_mark_down_gen/00_Marker.py",
        ],
        "notes": "Read for prior marker invocation pattern. Do not auto-run conversion unless explicitly requested.",
    },
    "02b_manual_review": {
        "purpose": "Manual selection UI behavior, manual_select semantics, and review marker conventions.",
        "reference_paths": [
            "full_copy/0_mark_down_gen/02B_FT_manual_selector_gui.py",
        ],
        "notes": "Manual UI reference only. Do not auto-run UI from extraction stages.",
    },
    "03_split_excel_blocks_batch": {
        "purpose": "Excel/source-data sheet splitting, block IDs, block previews, and deterministic helper conventions.",
        "reference_paths": [
            "full_copy/0_mark_down_gen/03_split_excel_blocks.py",
            "full_copy/0_mark_down_gen/03_split_excel_blocks_batch.py",
            "full_copy/0_mark_down_gen/sheet_block_splitter.py",
        ],
        "notes": "Read for prior Excel block shape and naming conventions. Do not execute API-dependent paths.",
    },
    "04_ft_excel_matcher": {
        "purpose": "Prior figure/table-to-Excel-block matching schema and context construction.",
        "reference_paths": [
            "full_copy/0_mark_down_gen/04_FT-Excel_matcher.py",
        ],
        "notes": "Use for expected mapping fields and matching reasoning only.",
    },
    "04_figure_separate": {
        "purpose": "Prior panel separation and source-image mapping conventions.",
        "reference_paths": [
            "full_copy/0_mark_down_gen/04_figure_saperate_gemini.py",
        ],
        "notes": "Use to understand old panel conventions. Do not run VLM calls.",
    },
    "05_smiles_structure_resolution": {
        "purpose": "Legacy text/name SMILES reference code. Current unified outputs force SMILES columns blank.",
        "reference_paths": [
            "full_copy/2_Extract_SMILES/",
        ],
        "notes": "Reference only. Do not use image-structure recognition to populate active outputs.",
    },
    "06_unified_lnpdb_extraction": {
        "purpose": "Prior experimental-condition, formulation, and experimental-value extraction patterns.",
        "reference_paths": [
            "full_copy/1_Extract_Exp_Figs/",
            "full_copy/3_Extract_Formula_by_Figs/",
            "full_copy/4_Extract_Exp_Vals/",
        ],
        "notes": "Use only for old output shapes and edge cases. Active contracts override legacy behavior.",
    },
}

PROHIBITED_IMPORTS = [
    "find_api.py",
    "LLM_API.py",
    "LLM_Batch.py",
    "google.genai",
    "Vertex/Gemini/GCS code",
]


def is_secret_file(path: Path) -> bool:
    name = path.name.lower()
    if name in SECRET_FILE_NAMES:
        return True
    return path.suffix.lower() == ".json" and (
        "service_account" in name
        or "service-account" in name
        or "credential" in name
        or "secret" in name
    )


def should_skip(path: Path, source_root: Path) -> bool:
    rel = path.relative_to(source_root)
    if any(part in EXCLUDED_DIR_NAMES for part in rel.parts):
        return True
    if path.is_file():
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            return True
        if is_secret_file(path):
            return True
        if path.stat().st_size > 5_000_000:
            return True
    return False


def copy_source_tree(source_name: str, copied_files: list[str], missing_files: list[str]) -> None:
    source = PROJECT_ROOT / source_name
    target = FULL_COPY_ROOT / source_name
    if not source.exists():
        missing_files.append(source_name)
        return
    for path in sorted(source.rglob("*")):
        if should_skip(path, source):
            continue
        rel = path.relative_to(source)
        dest = target / rel
        if path.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        copied_files.append(str(dest.relative_to(CONTEXT_ROOT)).replace("\\", "/"))


def write_readme() -> None:
    (CONTEXT_ROOT / "README.md").write_text(
        """# Legacy Context

This folder is reference-only. It gives external agents a stable place to inspect prior implementation logic, output shapes, naming conventions, and deterministic helper code.

It is not the active runtime path. Original legacy folders remain in their original repository locations for compatibility, and this context copy may be regenerated from those source folders.

External agents may read files here during task completion. Do not execute or import Gemini/API-dependent legacy scripts in the active workflow. Do not use `find_api.py`, `LLM_API.py`, `LLM_Batch.py`, `google.genai`, Vertex/Gemini/GCS code unless the operator explicitly requests legacy mode.

Active workflow policies:
- `agent_workspace/AGENT_INSTRUCTIONS.md`, `PIPELINE_SPEC.md`, `STAGE_CONTRACTS.md`, and `OUTPUT_SCHEMA.md` override legacy behavior.
- SMILES output columns are forced blank.
- Molecule-structure-image-based SMILES extraction is disabled.
- Excel-backed experimental values may be populated only with Excel/source-data provenance.
- Graph image digitization remains disabled.
""",
        encoding="utf-8",
    )


def write_stage_readmes() -> None:
    for stage, info in STAGE_INDEX.items():
        stage_dir = BY_STAGE_ROOT / stage
        stage_dir.mkdir(parents=True, exist_ok=True)
        refs = "\n".join(f"- `{path}`" for path in info["reference_paths"])
        prohibited = "\n".join(f"- `{item}`" for item in PROHIBITED_IMPORTS)
        stage_dir.joinpath("README.md").write_text(
            f"""# {stage}

Purpose: {info["purpose"]}

Reference paths:
{refs}

Allowed use:
- Read-only reference for prior deterministic logic, expected output shapes, and naming conventions.

Do not use:
{prohibited}
- Do not execute or import Gemini/API-dependent scripts in active workflow.

Notes:
{info["notes"]}
""",
            encoding="utf-8",
        )


def write_index() -> None:
    lines = [
        "# Legacy Code Index",
        "",
        "This index points external agents to stage-relevant legacy reference files. Current active contracts override legacy behavior.",
        "",
        "| Stage | Files to read | Why useful | Allowed use | Do-not-use warnings |",
        "|---|---|---|---|---|",
    ]
    for stage, info in STAGE_INDEX.items():
        refs = "<br>".join(f"`{path}`" for path in info["reference_paths"])
        lines.append(
            f"| `{stage}` | {refs} | {info['purpose']} | read-only reference | Do not execute/import Gemini/API-dependent scripts. |"
        )
    (CONTEXT_ROOT / "LEGACY_CODE_INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_manifest(copied_files: list[str], missing_files: list[str]) -> dict:
    stage_entries = [
        {
            "stage": stage,
            "purpose": info["purpose"],
            "reference_paths": ["agent_workspace/legacy_context/" + path for path in info["reference_paths"]],
            "prohibited_imports": PROHIBITED_IMPORTS,
            "notes": info["notes"],
        }
        for stage, info in STAGE_INDEX.items()
    ]
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_project_root": str(PROJECT_ROOT),
        "copied_files": sorted(copied_files),
        "missing_files": sorted(missing_files),
        "stages": stage_entries,
        "excluded_files_with_reason": [
            {"pattern": "__pycache__/ .pytest_cache/ virtualenv dirs *.pyc", "reason": "cache/build artifacts"},
            {"pattern": "vertex.json gemini_api.txt service account json credential/secret json", "reason": "credentials/secrets"},
            {"pattern": "_batch_jobs/ outputs/ paper output folders image/pdf binaries large files", "reason": "generated or large outputs"},
        ],
        "stage_to_context_files": {
            stage: ["agent_workspace/legacy_context/" + path for path in info["reference_paths"]]
            for stage, info in STAGE_INDEX.items()
        },
        "api_dependent_reference_files": [
            "agent_workspace/legacy_context/full_copy/0_mark_down_gen/03_split_excel_blocks_batch.py",
            "agent_workspace/legacy_context/full_copy/0_mark_down_gen/03_figure_mapping.py",
            "agent_workspace/legacy_context/full_copy/0_mark_down_gen/04_figure_saperate_gemini.py",
            "agent_workspace/legacy_context/full_copy/0_mark_down_gen/04_FT-Excel_matcher.py",
        ],
        "api_free_reference_files": [
            "agent_workspace/legacy_context/full_copy/0_mark_down_gen/sheet_block_splitter.py",
            "agent_workspace/legacy_context/full_copy/active_legacy_utils/",
        ],
        "prohibited_imports": PROHIBITED_IMPORTS,
        "notes": [
            "legacy_context is for explicit agent reference only.",
            "Original legacy folders remain in place.",
            "Active workflow does not execute Gemini/API legacy scripts by default.",
            "This context copy may be regenerated by agent_workspace/tools/build_legacy_context.py.",
        ],
    }


def main() -> None:
    if FULL_COPY_ROOT.exists():
        shutil.rmtree(FULL_COPY_ROOT)
    if BY_STAGE_ROOT.exists():
        shutil.rmtree(BY_STAGE_ROOT)
    CONTEXT_ROOT.mkdir(parents=True, exist_ok=True)
    FULL_COPY_ROOT.mkdir(parents=True, exist_ok=True)
    BY_STAGE_ROOT.mkdir(parents=True, exist_ok=True)

    copied_files: list[str] = []
    missing_files: list[str] = []
    for source_name in SOURCE_DIRS:
        copy_source_tree(source_name, copied_files, missing_files)

    write_readme()
    write_stage_readmes()
    write_index()
    manifest = build_manifest(copied_files, missing_files)
    (CONTEXT_ROOT / "legacy_context_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"copied_files": len(copied_files), "missing_files": missing_files}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
