from __future__ import annotations

import csv
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


UNIFIED_COLUMNS = [
    "Paper_ID",
    "Item_ID",
    "visual_type",
    "source_type",
    "source_image",
    "source_pdf",
    "source_page",
    "selected_source_for_paneling",
    "excel_file",
    "excel_sheet",
    "block_id",
    "block_csv_path",
    "Aqueous_buffer",
    "Dialysis_buffer",
    "Mixing_method",
    "Model",
    "Model_type",
    "Model_target",
    "Route_of_administration",
    "Cargo",
    "Cargo_type",
    "Dose_ug_nucleicacid",
    "Experiment_method",
    "Experiment_batching",
    "formulation_id",
    "Formulation_Name",
    "IL_name",
    "IL_SMILES",
    "IL_molarratio",
    "HL_name",
    "HL_SMILES",
    "HL_molarratio",
    "CHL_name",
    "CHL_SMILES",
    "CHL_molarratio",
    "PEG_name",
    "PEG_SMILES",
    "PEG_molarratio",
    "Fifth_component_name",
    "Fifth_component_SMILES",
    "Fifth_component_molarratio",
    "IL_to_nucleicacid_massratio",
    "condition_1_name",
    "condition_1_value",
    "condition_2_name",
    "condition_2_value",
    "condition_3_name",
    "condition_3_value",
    "condition_4_name",
    "condition_4_value",
    "metric_type",
    "original_values",
    "aggregated_value",
    "unit",
    "replicate_type",
    "evidence_text",
    "evidence_image",
    "evidence_excel",
    "confidence",
    "manual_required",
    "reason",
]

OUTPUT_SMILES_COLUMNS = [
    "IL_SMILES",
    "HL_SMILES",
    "CHL_SMILES",
    "PEG_SMILES",
    "Fifth_component_SMILES",
]

FLAG_COLUMNS = ["Paper_ID", "Item_ID", "block_id", "field", "issue", "severity", "reason"]

NUMERIC_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
TAIL_RE = re.compile(r"^C(?:10|12|14)$", re.I)


METRICS = {
    "figure 2b": ("MC38 cell luminescence after FLuc pLNP treatment", ""),
    "figure 2c": ("ex vivo tumour FLuc luminescence total flux", ""),
    "figure 3b": ("secreted IL-12 in cell culture medium", ""),
    "figure 3c": ("intracellular IL-12 in lysed MC38 cells", ""),
    "figure 3e": ("anti-mouse IL-12 PE mean fluorescence intensity", "MFI"),
    "figure 3i": ("CD69 positive OT-I CD3 T cells", "%"),
    "figure 3j": ("CD25 positive OT-I CD3 T cells", "%"),
    "figure 3k": ("PD-1 positive OT-I CD3 T cells", "%"),
    "figure 4g": ("splenic CD8 T cells among CD3 T cells", "%"),
    "figure 4h": ("splenic CD4 T cells among CD3 T cells", "%"),
    "figure 4i": ("splenic effector memory CD8 T cells", "%"),
    "figure 4j": ("splenic effector memory CD4 T cells", "%"),
    "figure 4k": ("splenic central memory CD8 T cells", "%"),
    "figure 4l": ("splenic central memory CD4 T cells", "%"),
    "figure 4m": ("splenic regulatory T cells", "%"),
    "figure 5b": ("tumour CD8 T cells among CD3 T cells", "%"),
    "figure 5c": ("tumour CD4 T cells among CD3 T cells", "%"),
    "figure 5d": ("PD-1 positive CD8 T cells in tumour", "%"),
    "figure 5e": ("PD-1 positive CD4 T cells in tumour", "%"),
    "figure 5f": ("TNF-alpha level in tumour tissue", ""),
    "figure 5g": ("IFN-gamma level in tumour tissue", ""),
    "figure 5i": ("IFN-gamma gene expression relative to PBS", "fold change"),
    "figure 6b": ("tumour volume after rechallenge", "mm3"),
    "figure 6c": ("individual tumour volume after rechallenge", "mm3"),
    "figure 6k": ("CD8 T cells among CD3 T cells in contralateral tumour", "%"),
    "figure 6l": ("CD4 T cells among CD3 T cells in contralateral tumour", "%"),
}

GROUP_METRIC_TERMS = {
    "tumor volume": ("tumour volume", "mm3"),
    "tumour volume": ("tumour volume", "mm3"),
    "body weight": ("body weight", "g"),
}

FIGURE_CONTEXT = {
    "figure 2": {
        "model": "MC38 cells or MC38 tumour-bearing mice",
        "model_type": "in vitro and in vivo mouse tumour model",
        "target": "MC38 colon adenocarcinoma",
        "route": "in vitro treatment; intratumoural injection for panel c",
        "cargo": "FLuc mRNA",
        "dose": "50 ng/well for in vitro screening; 2.5 ug per mouse for in vivo panel c",
        "method": "luciferase bioluminescence assay / IVIS imaging",
        "batching": "n=3 where stated for panel c",
    },
    "figure 3": {
        "model": "MC38 cells and OT-I CD3 T cell co-culture",
        "model_type": "in vitro cell culture",
        "target": "MC38 / MC38-OVA",
        "route": "in vitro treatment",
        "cargo": "IL-12 mRNA",
        "dose": "0.5 ug/ml mRNA per well",
        "method": "ELISA, immunofluorescence, flow cytometry, HPLC",
        "batching": "n=4 for panels b,c,i-k; n varies for panel e",
    },
    "figure 4": {
        "model": "MC38 tumour-bearing C57BL/6 mice",
        "model_type": "in vivo mouse tumour model",
        "target": "MC38 tumour / spleen immune cells",
        "route": "intratumoural injection on days 6, 8 and 10",
        "cargo": "IL-12 mRNA or FLuc mRNA depending on group",
        "dose": "2.5 ug mRNA per mouse",
        "method": "flow cytometry / tumour caliper monitoring",
        "batching": "n=5 for spleen flow cytometry panels g-m",
    },
    "figure 5": {
        "model": "MC38 tumour-bearing C57BL/6 mice",
        "model_type": "in vivo mouse tumour model",
        "target": "tumour microenvironment",
        "route": "intratumoural injection on days 6, 8 and 10",
        "cargo": "IL-12 mRNA or FLuc mRNA depending on group",
        "dose": "2.5 ug mRNA per mouse",
        "method": "flow cytometry, ELISA, and bulk RNA-seq",
        "batching": "n=5 for flow cytometry; n=3 for cytokines and RNA-seq",
    },
    "figure 6": {
        "model": "MC38 tumour rechallenge or bilateral tumour-bearing C57BL/6 mice",
        "model_type": "in vivo mouse tumour model",
        "target": "MC38 rechallenge / contralateral tumour",
        "route": "intratumoural injection on days 6, 8 and 10; subcutaneous rechallenge where applicable",
        "cargo": "IL-12 mRNA or FLuc mRNA depending on group",
        "dose": "2.5 ug mRNA per mouse",
        "method": "tumour caliper monitoring and flow cytometry",
        "batching": "n=5 control and n=8 treated for panels b-d; n=3 for panels k,l",
    },
}

SUPP_CONTEXT = {
    "supplementary figure 47": ("HepG2 cells", "in vitro cell culture", "HepG2 hepatocellular carcinoma", "in vitro treatment", "FLuc mRNA", "0.05 ug/well", "luciferase assay", "n=3"),
    "supplementary figure 49": ("MC38 cells", "in vitro cell culture", "MC38 colon adenocarcinoma", "in vitro treatment", "FLuc mRNA", "0.5 ug/ml", "cell viability assay", "n=3"),
    "supplementary figure 52c": ("G0-SS-AA-C12 pLNP", "physicochemical characterization", "LNP formulation", "not applicable", "FLuc mRNA", "", "DLS / zeta / RiboGreen / pKa assay", ""),
    "supplementary figure 53c": ("G0-6C-AA-C12 LNP", "physicochemical characterization", "LNP formulation", "not applicable", "FLuc mRNA", "", "DLS / zeta / RiboGreen / pKa assay", ""),
    "supplementary figure 54a": ("G0-SS-AA-C12 pLNP", "physicochemical characterization", "LNP formulation", "not applicable", "", "", "TNS pKa assay", "n=3 technical replicates"),
    "supplementary figure 54b": ("G0-6C-AA-C12 LNP", "physicochemical characterization", "LNP formulation", "not applicable", "", "", "TNS pKa assay", "n=3 technical replicates"),
    "supplementary figure 56b": ("MC38 cells", "in vitro cell culture", "MC38 colon adenocarcinoma", "in vitro treatment", "IL-12 mRNA", "0.5 ug/ml", "flow cytometry", "n=4"),
    "supplementary figure 60c": ("primary mouse CD3 T cells", "ex vivo cell culture", "CD3 T cells", "conditioned medium exposure", "IL-12 mRNA or FLuc mRNA", "0.5 ug/ml in MC38 pretreatment", "flow cytometry", "n=4"),
    "supplementary figure 60e": ("primary mouse CD3 T cells", "ex vivo cell culture", "CD3 T cells", "conditioned medium exposure", "IL-12 mRNA or FLuc mRNA", "0.5 ug/ml in MC38 pretreatment", "flow cytometry", "n=4"),
    "supplementary figure 60g": ("primary mouse CD3 T cells", "ex vivo cell culture", "CD3 T cells", "conditioned medium exposure", "IL-12 mRNA or FLuc mRNA", "0.5 ug/ml in MC38 pretreatment", "flow cytometry", "n=4"),
    "supplementary figure 61b": ("primary mouse CD4 T cells", "ex vivo cell culture", "CD4 T cells", "conditioned medium exposure", "IL-12 mRNA or FLuc mRNA", "0.5 ug/ml in MC38 pretreatment", "flow cytometry", "n=4"),
    "supplementary figure 61d": ("primary mouse CD4 T cells", "ex vivo cell culture", "CD4 T cells", "conditioned medium exposure", "IL-12 mRNA or FLuc mRNA", "0.5 ug/ml in MC38 pretreatment", "flow cytometry", "n=4"),
    "supplementary figure 61f": ("primary mouse CD4 T cells", "ex vivo cell culture", "CD4 T cells", "conditioned medium exposure", "IL-12 mRNA or FLuc mRNA", "0.5 ug/ml in MC38 pretreatment", "flow cytometry", "n=4"),
    "supplementary figure 62b": ("primary mouse CD8 T cells", "ex vivo cell culture", "CD8 T cells", "conditioned medium exposure", "IL-12 mRNA or FLuc mRNA", "0.5 ug/ml in MC38 pretreatment", "flow cytometry", "n=4"),
    "supplementary figure 62d": ("primary mouse CD8 T cells", "ex vivo cell culture", "CD8 T cells", "conditioned medium exposure", "IL-12 mRNA or FLuc mRNA", "0.5 ug/ml in MC38 pretreatment", "flow cytometry", "n=4"),
    "supplementary figure 62f": ("primary mouse CD8 T cells", "ex vivo cell culture", "CD8 T cells", "conditioned medium exposure", "IL-12 mRNA or FLuc mRNA", "0.5 ug/ml in MC38 pretreatment", "flow cytometry", "n=4"),
    "supplementary figure 67b": ("primary mouse CD3 T cells", "ex vivo cell culture", "CD3 T cell proliferation", "conditioned medium exposure", "IL-12 mRNA or FLuc mRNA", "0.5 ug/ml in MC38 pretreatment", "CFSE flow cytometry", "n=3"),
    "supplementary figure 71c": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "spleen CD4 T cells", "intratumoural injection", "IL-12 mRNA or FLuc mRNA", "2.5 ug mRNA per mouse", "flow cytometry", "n=3"),
    "supplementary figure 71d": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "spleen CD8 T cells", "intratumoural injection", "IL-12 mRNA or FLuc mRNA", "2.5 ug mRNA per mouse", "flow cytometry", "n=3"),
    "supplementary figure 71f": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "spleen regulatory T cells", "intratumoural injection", "IL-12 mRNA or FLuc mRNA", "2.5 ug mRNA per mouse", "flow cytometry", "n=3"),
    "supplementary figure 78c": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "tumour tissue", "intratumoural injection", "IL-12 mRNA or FLuc mRNA", "2.5 ug mRNA per mouse", "ELISA", "n=3"),
    "supplementary figure 78e": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "tumour CD3 T cells", "intratumoural injection", "IL-12 mRNA or FLuc mRNA", "2.5 ug mRNA per mouse", "flow cytometry", "n=3"),
    "supplementary figure 78g": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "tumour CD3 T cells", "intratumoural injection", "IL-12 mRNA or FLuc mRNA", "2.5 ug mRNA per mouse", "flow cytometry", "n=3"),
    "supplementary figure 78i": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "tumour CD3 T cells", "intratumoural injection", "IL-12 mRNA or FLuc mRNA", "2.5 ug mRNA per mouse", "flow cytometry", "n=3"),
    "supplementary figure 79c": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "tumour tissue", "intratumoural injection", "IL-12 mRNA or free IDO inhibitor depending on group", "2.5 ug mRNA per mouse; free IDO inhibitor 3.0 ug/mouse", "ELISA", "n=3"),
    "supplementary figure 79d": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "tumour tissue", "intratumoural injection", "IL-12 mRNA or free IDO inhibitor depending on group", "2.5 ug mRNA per mouse; free IDO inhibitor 3.0 ug/mouse", "ELISA", "n=3"),
    "supplementary figure 79e": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "tumour tissue", "intratumoural injection", "IL-12 mRNA or free IDO inhibitor depending on group", "2.5 ug mRNA per mouse; free IDO inhibitor 3.0 ug/mouse", "ELISA", "n=3"),
    "supplementary figure 79g": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "tumour CD8 T cells", "intratumoural injection", "IL-12 mRNA or free IDO inhibitor depending on group", "2.5 ug mRNA per mouse; free IDO inhibitor 3.0 ug/mouse", "flow cytometry", "n=3"),
    "supplementary figure 79i": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "tumour CD3 T cells", "intratumoural injection", "IL-12 mRNA or free IDO inhibitor depending on group", "2.5 ug mRNA per mouse; free IDO inhibitor 3.0 ug/mouse", "flow cytometry", "n=3"),
    "supplementary figure 79k": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "tumour CD3 T cells", "intratumoural injection", "IL-12 mRNA or free IDO inhibitor depending on group", "2.5 ug mRNA per mouse; free IDO inhibitor 3.0 ug/mouse", "flow cytometry", "n=3"),
    "supplementary figure 79m": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "tumour CD3 T cells", "intratumoural injection", "IL-12 mRNA or free IDO inhibitor depending on group", "2.5 ug mRNA per mouse; free IDO inhibitor 3.0 ug/mouse", "flow cytometry", "n=3"),
    "supplementary figure 87b": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "serum IL-6 after intravenous dosing", "intravenous injection", "IL-12 mRNA or free IDO inhibitor depending on group", "2.5 ug mRNA per mouse; free IDO inhibitor 3.0 ug/mouse", "ELISA", "n=3"),
    "supplementary figure 87c": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "serum TNF-alpha after intravenous dosing", "intravenous injection", "IL-12 mRNA or free IDO inhibitor depending on group", "2.5 ug mRNA per mouse; free IDO inhibitor 3.0 ug/mouse", "ELISA", "n=3"),
    "supplementary figure 87d": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "serum IFN-gamma after intravenous dosing", "intravenous injection", "IL-12 mRNA or free IDO inhibitor depending on group", "2.5 ug mRNA per mouse; free IDO inhibitor 3.0 ug/mouse", "ELISA", "n=3"),
    "supplementary figure 87e": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "serum IL-6 after intratumoural dosing", "intratumoural injection", "IL-12 mRNA or free IDO inhibitor depending on group", "2.5 ug mRNA per mouse; free IDO inhibitor 3.0 ug/mouse", "ELISA", "n=3"),
    "supplementary figure 87f": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "serum TNF-alpha after intratumoural dosing", "intratumoural injection", "IL-12 mRNA or free IDO inhibitor depending on group", "2.5 ug mRNA per mouse; free IDO inhibitor 3.0 ug/mouse", "ELISA", "n=3"),
    "supplementary figure 87g": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "serum IFN-gamma after intratumoural dosing", "intratumoural injection", "IL-12 mRNA or free IDO inhibitor depending on group", "2.5 ug mRNA per mouse; free IDO inhibitor 3.0 ug/mouse", "ELISA", "n=3"),
    "supplementary figure 87h": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "serum IL-6 route comparison", "intravenous or intratumoural injection", "IL-12 mRNA", "2.5 ug mRNA per mouse", "ELISA", "n=3"),
    "supplementary figure 87i": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "serum TNF-alpha route comparison", "intravenous or intratumoural injection", "IL-12 mRNA", "2.5 ug mRNA per mouse", "ELISA", "n=3"),
    "supplementary figure 87j": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "serum IFN-gamma route comparison", "intravenous or intratumoural injection", "IL-12 mRNA", "2.5 ug mRNA per mouse", "ELISA", "n=3"),
    "supplementary figure 88": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "serum AST/ALT after intravenous dosing", "intravenous injection", "IL-12 mRNA or free IDO inhibitor depending on group", "2.5 ug mRNA per mouse; free IDO inhibitor 3.0 ug/mouse", "ELISA", "n=3"),
    "supplementary figure 89": ("MC38 tumour-bearing mice", "in vivo mouse tumour model", "serum AST/ALT after intratumoural dosing", "intratumoural injection", "IL-12 mRNA or free IDO inhibitor depending on group", "2.5 ug mRNA per mouse; free IDO inhibitor 3.0 ug/mouse", "ELISA", "n=5"),
    "supplementary figure 59": ("G0-SS-AA-C12 pLNP", "in vitro release assay", "indoximod release", "not applicable", "", "", "HPLC", ""),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def find_paper_folder() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    env_folder = os.environ.get("PAPER_FOLDER")
    if env_folder:
        return Path(env_folder)
    matches_2 = list(Path("F:/").glob("*/EXTRACT-TEST/QS_2026_2"))
    if matches_2:
        return matches_2[0]
    matches = list(Path("F:/").glob("*/EXTRACT-TEST/QS_2026"))
    if not matches:
        raise FileNotFoundError("Could not locate F:/*/EXTRACT-TEST/QS_2026_2 or QS_2026")
    return matches[0]


def read_csv_dicts(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def read_csv_matrix(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return [[cell.strip() for cell in row] for row in csv.reader(fh)]


def write_csv(path: Path, rows: list[dict[str, object]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})


def backup(path: Path) -> None:
    if path.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(path, path.with_name(f"{path.name}.bak_06_unified_{stamp}"))


def selected_rows(paper_folder: Path) -> dict[str, dict[str, str]]:
    rows = read_csv_dicts(paper_folder / "fig_table_lnpdb_classified.csv")
    selected = {}
    for row in rows:
        marker = str(row.get("manual_select", "")).strip().lower()
        if marker in {"yes", "true", "1", "y", "selected"}:
            selected[row["item_id"].strip().lower()] = row
    return selected


def mapping_by_item(paper_folder: Path) -> dict[str, dict[str, object]]:
    data = json.loads((paper_folder / "total_figure_mapping.json").read_text(encoding="utf-8"))
    out = {}
    for source, value in data.items():
        if not isinstance(value, dict):
            continue
        for item_id, entry in value.items():
            if item_id == "_metadata" or not isinstance(entry, dict):
                continue
            row = dict(entry)
            row["source_folder"] = source
            out[item_id.lower()] = row
    return out


def excel_matches(paper_folder: Path, selected: dict[str, dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    matches: dict[str, list[dict[str, str]]] = {}
    path = paper_folder / "excel_mapping.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, entries in data.items():
            if isinstance(entries, list):
                matches[key.lower()] = [dict(e) for e in entries if isinstance(e, dict)]
    for item_id, row in selected.items():
        block_path = row.get("matched_block_csv_path", "").strip()
        if block_path and item_id not in matches:
            matches[item_id] = [
                {
                    "pdf_item_id": item_id,
                    "excel_item_id": row.get("excel_item_id", ""),
                    "excel_file": row.get("matched_sheet_file", ""),
                    "excel_sheet": row.get("matched_sheet", ""),
                    "block_id": row.get("matched_blocks", ""),
                    "block_csv_path": block_path,
                    "reason": row.get("excel_match_reason", ""),
                }
            ]
    return matches


def smiles_lookup(paper_folder: Path) -> tuple[dict[str, str], dict[str, str]]:
    resolved = {}
    manual = {}
    path = paper_folder / "smiles_resolved.csv"
    disallowed_terms = (
        "decimer",
        "molscribe",
        "worker_mol",
        "structure image",
        "structure_image",
        "image structure",
        "image_structure",
        "structure crop",
        "structure_crop",
        "molecule crop",
        "molecular structure",
        "mol_annotator",
        "recognition.py",
        "segmentation.py",
        "fromimage",
    )
    manual_terms = ("human_curated", "manual_verified", "manually_verified", "manual curated", "manual verified")
    if path.exists():
        for row in read_csv_dicts(path):
            source_text = " ".join(
                str(row.get(col, ""))
                for col in ("source_type", "source_path", "source_image", "resolution_method", "method", "evidence_text", "reason", "notes")
            ).lower()
            if any(term in source_text for term in disallowed_terms) and not any(term in source_text for term in manual_terms):
                continue
            names = [row.get("Name", ""), row.get("standardized_name", "")]
            aliases = re.split(r";|\|", row.get("alias", "") or "")
            for name in names + aliases:
                key = normalize_name(name)
                if key:
                    resolved[key] = row.get("resolved_smiles") or row.get("SMILES", "")
                    manual[key] = row.get("manual_required", "")
    return resolved, manual


def normalize_name(text: str) -> str:
    text = (text or "").strip()
    text = text.replace("GO-", "G0-").replace("Go-", "G0-")
    text = text.replace("Fluc", "FLuc").replace("fluc", "FLuc")
    text = re.sub(r"\s+", " ", text)
    return text.lower()


def is_numeric(text: str) -> bool:
    return bool(NUMERIC_RE.match((text or "").strip()))


def excel_context_labels(matrix: list[list[str]], limit: int = 12) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for row in matrix:
        for cell in row:
            text = compact(cell, 180)
            if not text or is_numeric(text.replace(",", "").replace("%", "").strip()):
                continue
            key = text.lower()
            if key in seen:
                continue
            labels.append(text)
            seen.add(key)
            if len(labels) >= limit:
                return labels
    return labels


def compact(text: str, limit: int = 1400) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit]


def caption_for_item(item_id: str, main_md: str, supp_md: str) -> str:
    item_id = item_id.lower()
    if item_id.startswith("supplementary figure"):
        number = item_id.replace("supplementary figure", "").strip()
        base = re.sub(r"[a-z]$", "", number)
        patterns = [f"Supplementary Fig. {base}", f"Supplementary Figure {base}"]
        source = supp_md
    else:
        match = re.match(r"figure\s+(\d+)", item_id)
        if not match:
            return ""
        number = match.group(1)
        patterns = [f"Fig. {number} |", f"Fig. {number}**|", f"**Fig. {number}"]
        source = main_md
    starts = [source.find(p) for p in patterns if source.find(p) >= 0]
    if not starts:
        return ""
    start = min(starts)
    return compact(source[start : start + 2200])


def context_for_item(item_id: str) -> dict[str, str]:
    item_id = item_id.lower()
    method_by_item = {
        "figure 2b": "luminescence",
        "figure 2c": "IVIS",
        "figure 3b": "ELISA_IL-12_secreted",
        "figure 3c": "ELISA_IL-12_intracellular",
        "figure 3e": "fluorescence_IL-12_MFI",
        "figure 3i": "flow_cytometry_CD69_T_cells",
        "figure 3j": "flow_cytometry_CD25_T_cells",
        "figure 3k": "flow_cytometry_PD-1_T_cells",
        "figure 4g": "flow_cytometry_CD8_T_cells",
        "figure 4h": "flow_cytometry_CD4_T_cells",
        "figure 4i": "flow_cytometry_CD8_effector_memory_T_cells",
        "figure 4j": "flow_cytometry_CD4_effector_memory_T_cells",
        "figure 4k": "flow_cytometry_CD8_central_memory_T_cells",
        "figure 4l": "flow_cytometry_CD4_central_memory_T_cells",
        "figure 4m": "flow_cytometry_regulatory_T_cells",
        "figure 5b": "flow_cytometry_CD8_T_cells",
        "figure 5c": "flow_cytometry_CD4_T_cells",
        "figure 5d": "flow_cytometry_PD-1_CD8_T_cells",
        "figure 5e": "flow_cytometry_PD-1_CD4_T_cells",
        "figure 5f": "ELISA_TNF-alpha",
        "figure 5g": "ELISA_IFN-gamma",
        "figure 5h": "RNA-seq",
        "figure 5i": "qPCR_IFN-gamma",
        "figure 6b": "tumor_volume",
        "figure 6c": "tumor_volume",
        "figure 6d": "survival",
        "figure 6k": "flow_cytometry_CD8_T_cells",
        "figure 6l": "flow_cytometry_CD4_T_cells",
    }
    if item_id == "figure 2b":
        return {
            "Model": "in_vitro",
            "Model_type": "MC38",
            "Model_target": "in_vitro",
            "Route_of_administration": "in_vitro",
            "Cargo": "mRNA",
            "Cargo_type": "FLuc",
            "Dose_ug_nucleicacid": "0.05",
            "Experiment_method": method_by_item[item_id],
            "Experiment_batching": "individual",
        }
    if item_id == "figure 2c":
        return {
            "Model": "in_vivo",
            "Model_type": "Mouse_MC38_tumor",
            "Model_target": "tumor",
            "Route_of_administration": "intratumoral",
            "Cargo": "mRNA",
            "Cargo_type": "FLuc",
            "Dose_ug_nucleicacid": "2.5",
            "Experiment_method": method_by_item[item_id],
            "Experiment_batching": "individual",
        }
    if item_id in {"figure 3b", "figure 3c", "figure 3e"}:
        return {
            "Model": "in_vitro",
            "Model_type": "MC38",
            "Model_target": "in_vitro",
            "Route_of_administration": "in_vitro",
            "Cargo": "mRNA",
            "Cargo_type": "IL-12",
            "Dose_ug_nucleicacid": "",
            "Experiment_method": method_by_item[item_id],
            "Experiment_batching": "individual",
        }
    if item_id in {"figure 3i", "figure 3j", "figure 3k"}:
        return {
            "Model": "ex_vivo",
            "Model_type": "OT-I_CD3_T_cells",
            "Model_target": "CD3_T_cells",
            "Route_of_administration": "in_vitro",
            "Cargo": "mRNA",
            "Cargo_type": "",
            "Dose_ug_nucleicacid": "",
            "Experiment_method": method_by_item[item_id],
            "Experiment_batching": "individual",
        }
    if item_id in {f"figure 4{letter}" for letter in "ghijklm"}:
        return {
            "Model": "in_vivo",
            "Model_type": "Mouse_MC38_tumor",
            "Model_target": "spleen",
            "Route_of_administration": "intratumoral",
            "Cargo": "mRNA",
            "Cargo_type": "",
            "Dose_ug_nucleicacid": "2.5",
            "Experiment_method": method_by_item[item_id],
            "Experiment_batching": "individual",
        }
    if item_id in {"figure 5b", "figure 5c", "figure 5d", "figure 5e", "figure 5f", "figure 5g", "figure 5h", "figure 5i"}:
        return {
            "Model": "in_vivo",
            "Model_type": "Mouse_MC38_tumor",
            "Model_target": "tumor",
            "Route_of_administration": "intratumoral",
            "Cargo": "mRNA",
            "Cargo_type": "",
            "Dose_ug_nucleicacid": "2.5",
            "Experiment_method": method_by_item[item_id],
            "Experiment_batching": "individual",
        }
    if item_id in {"figure 6b", "figure 6c", "figure 6d"}:
        return {
            "Model": "in_vivo",
            "Model_type": "Mouse_MC38_rechallenge",
            "Model_target": "tumor",
            "Route_of_administration": "subcutaneous",
            "Cargo": "mRNA",
            "Cargo_type": "IL-12",
            "Dose_ug_nucleicacid": "2.5",
            "Experiment_method": method_by_item[item_id],
            "Experiment_batching": "individual",
        }
    if item_id in {"figure 6k", "figure 6l"}:
        return {
            "Model": "in_vivo",
            "Model_type": "Mouse_bilateral_MC38_tumor",
            "Model_target": "tumor",
            "Route_of_administration": "intratumoral",
            "Cargo": "mRNA",
            "Cargo_type": "",
            "Dose_ug_nucleicacid": "2.5",
            "Experiment_method": method_by_item[item_id],
            "Experiment_batching": "individual",
        }
    if item_id.startswith("supplementary figure"):
        method = ""
        model = "in_vivo"
        model_type = "Mouse_MC38_tumor"
        target = "tumor"
        route = "intratumoral"
        cargo = "mRNA"
        cargo_type = ""
        dose = "2.5"
        if item_id in {"supplementary figure 47", "supplementary figure 49"}:
            model = "in_vitro"
            model_type = "HepG2" if item_id.endswith("47") else "MC38"
            target = "in_vitro"
            route = "in_vitro"
            cargo_type = "FLuc"
            dose = "0.05" if item_id.endswith("47") else ""
            method = "luminescence" if item_id.endswith("47") else "cell_viability"
        elif item_id in {"supplementary figure 52c", "supplementary figure 53c"}:
            model = "N/A"
            model_type = "N/A"
            target = "N/A"
            route = "N/A"
            cargo_type = "FLuc"
            dose = ""
            method = "physicochemical_characterization"
        elif item_id in {"supplementary figure 54a", "supplementary figure 54b"}:
            model = "N/A"
            model_type = "N/A"
            target = "N/A"
            route = "N/A"
            cargo = ""
            dose = ""
            method = "pKa"
        elif item_id == "supplementary figure 56b":
            model = "in_vitro"
            model_type = "MC38"
            target = "in_vitro"
            route = "in_vitro"
            cargo_type = "IL-12"
            dose = ""
            method = "flow_cytometry_IL-12"
        elif re.match(r"supplementary figure 6[0127]", item_id):
            model = "ex_vivo"
            model_type = "mouse_T_cells"
            target = "CD3_T_cells"
            route = "in_vitro"
            dose = ""
            method = "flow_cytometry"
        elif item_id.startswith("supplementary figure 71"):
            target = "spleen"
            method = "flow_cytometry_regulatory_T_cells" if item_id.endswith("f") else ("flow_cytometry_CD8_T_cells" if item_id.endswith("c") else "flow_cytometry_CD4_T_cells")
        elif item_id.startswith("supplementary figure 78") or item_id.startswith("supplementary figure 79"):
            target = "tumor"
            method = "ELISA" if item_id[-1] in {"c", "d", "e"} else "flow_cytometry"
        elif item_id.startswith("supplementary figure 87"):
            target = "serum"
            route = "intravenous" if item_id[-1] in {"b", "c", "d"} else ("intratumoral" if item_id[-1] in {"e", "f", "g"} else "")
            method = "ELISA"
        elif item_id == "supplementary figure 88":
            target = "serum"
            route = "intravenous"
            method = "ELISA_AST_ALT"
        elif item_id == "supplementary figure 89":
            target = "serum"
            route = "intratumoral"
            method = "ELISA_AST_ALT"
        elif item_id == "supplementary figure 59":
            model = "N/A"
            model_type = "N/A"
            target = "N/A"
            route = "N/A"
            cargo = ""
            dose = ""
            method = "HPLC"
        return {
            "Model": model,
            "Model_type": model_type,
            "Model_target": target,
            "Route_of_administration": route,
            "Cargo": cargo,
            "Cargo_type": cargo_type,
            "Dose_ug_nucleicacid": dose,
            "Experiment_method": method,
            "Experiment_batching": "individual",
        }
    return {}

    # Legacy fallback retained below for older paper folders; QS_2026_3 returns above.
    if item_id.startswith("figure"):
        match = re.match(r"figure\s+(\d+)", item_id)
        base = f"figure {match.group(1)}" if match else " ".join(item_id.split()[:2])
        ctx = FIGURE_CONTEXT.get(base, {})
        return {
            "Model": ctx.get("model", ""),
            "Model_type": ctx.get("model_type", ""),
            "Model_target": ctx.get("target", ""),
            "Route_of_administration": ctx.get("route", ""),
            "Cargo": ctx.get("cargo", ""),
            "Cargo_type": "mRNA" if ctx.get("cargo") else "",
            "Dose_ug_nucleicacid": ctx.get("dose", ""),
            "Experiment_method": ctx.get("method", ""),
            "Experiment_batching": ctx.get("batching", ""),
        }
    supp = SUPP_CONTEXT.get(item_id, ())
    if supp:
        model, model_type, target, route, cargo, dose, method, batching = supp
        return {
            "Model": model,
            "Model_type": model_type,
            "Model_target": target,
            "Route_of_administration": route,
            "Cargo": cargo,
            "Cargo_type": "mRNA" if "mRNA" in cargo else "",
            "Dose_ug_nucleicacid": dose,
            "Experiment_method": method,
            "Experiment_batching": batching,
        }
    return {}


def metric_for_item(item_id: str, excel_metric: str = "") -> tuple[str, str]:
    if item_id in METRICS:
        return METRICS[item_id]
    metric = excel_metric.strip()
    low = metric.lower()
    for term, value in GROUP_METRIC_TERMS.items():
        if term in low:
            return value
    return metric, ""


def formulation_from_labels(item_id: str, group_label: str, row_label: str, col_label: str) -> str:
    label = group_label or ""
    if item_id == "figure 2b" and row_label and TAIL_RE.match(col_label or ""):
        return f"{row_label}-{col_label}".replace("--", "-")
    if not label and row_label and re.search(r"(LNP|pLNP|MC3|SS-AA|6C-AA|PBS|free)", row_label, re.I):
        label = row_label
    label = label.replace("GO-", "G0-").replace("Go-", "G0-")
    label = label.replace("Fluc", "FLuc")
    label = label.replace("G0-6C-AA_C12", "G0-6C-AA-C12")
    if label in {"Control group"} and item_id in {"figure 6b", "figure 6c"}:
        label = "naive control group"
    if label in {"Treated group"} and item_id in {"figure 6b", "figure 6c"}:
        label = "G0-SS-AA-C12 IL-12 pLNP"
    return label


def distinct_formulations(item_id: str, matrix: list[list[str]]) -> list[str]:
    formulations: list[str] = []
    seen: set[str] = set()

    def add(label: str) -> None:
        label = formulation_from_labels(item_id, label.strip(), "", "")
        if not label or re.match(r"^Fig\.\s*\d+", label, re.I):
            return
        low = label.lower()
        if low in {
            "days after injection of mc38 cells",
            "tumor volume (mm3)",
            "tumour volume (mm3)",
            "row_label",
        }:
            return
        key = normalize_name(label)
        if key and key not in seen:
            seen.add(key)
            formulations.append(label)

    if item_id == "figure 2b" and matrix:
        header = matrix[0]
        tails = [cell for cell in header if TAIL_RE.match(cell or "")]
        for row in matrix[1:]:
            if not row or not row[0].strip():
                continue
            base = row[0].strip()
            for tail in sorted(set(tails), key=lambda x: int(x[1:])):
                add(f"{base}-{tail}")
        return formulations

    for row in matrix:
        for cell in row:
            text = (cell or "").strip()
            if not text or is_numeric(text.replace(",", "").replace("%", "")):
                continue
            if re.search(r"(PBS|MC3|SS-AA|6C-AA|LNP|pLNP|free IL-12|free IDO|Control group|Treated group)", text, re.I):
                add(text)

    return formulations


def infer_cargo(formulation: str, default_cargo: str) -> str:
    low = formulation.lower()
    if "pbs" in low or "control group" in low or "naive" in low:
        return ""
    if "il-12" in low or "fluc" in low or "lnp" in low or "plnp" in low or "mc3" in low:
        return "mRNA"
    return default_cargo


def fill_formulation(row: dict[str, object], formulation: str, smiles: dict[str, str]) -> None:
    row["Formulation_Name"] = formulation
    row["formulation_id"] = normalize_name(formulation).replace(" ", "_")
    low = formulation.lower()
    if not formulation or "pbs" in low or "naive" in low or "control group" in low:
        return
    if "free ido" in low:
        row["Fifth_component_name"] = "indoximod"
        return
    if "free il-12" in low:
        row["Cargo"] = "mRNA"
        row["Cargo_type"] = "IL-12"
        return

    il_name = ""
    for candidate in [
        "G0-6C-AA-C12",
        "G0-SS-AA-C10",
        "G0-SS-AA-C12",
        "G0-SS-AA-C14",
        "P2A-SS-AA-C10",
        "P2A-SS-AA-C12",
        "P2A-SS-AA-C14",
        "T3A-SS-AA-C10",
        "T3A-SS-AA-C12",
        "T3A-SS-AA-C14",
        "110-SS-AA-C10",
        "110-SS-AA-C12",
        "110-SS-AA-C14",
        "306-SS-AA-C10",
        "306-SS-AA-C12",
        "306-SS-AA-C14",
        "L2A-SS-AA-C10",
        "L2A-SS-AA-C12",
        "L2A-SS-AA-C14",
        "DAB-SS-AA-C10",
        "DAB-SS-AA-C12",
        "DAB-SS-AA-C14",
    ]:
        if candidate.lower() in low:
            il_name = candidate
            break
    if not il_name and re.search(r"\bMC3\b", formulation, re.I):
        il_name = "DLin-MC3-DMA"

    if il_name:
        row["IL_name"] = il_name
        row["IL_molarratio"] = "50"

    if il_name == "DLin-MC3-DMA":
        row["HL_name"] = "DSPC"
        row["HL_molarratio"] = "10"
        row["CHL_name"] = "cholesterol"
        row["CHL_molarratio"] = "38.5"
        row["PEG_name"] = "DMG-PEG"
        row["PEG_molarratio"] = "1.5"
    elif il_name:
        row["HL_name"] = "DOPE"
        row["HL_molarratio"] = "10"
        row["CHL_name"] = "cholesterol"
        row["CHL_molarratio"] = "38.5"
        row["PEG_name"] = "DMG-PEG"
        row["PEG_molarratio"] = "1.5"


def force_blank_output_smiles(row: dict[str, object]) -> None:
    for col in OUTPUT_SMILES_COLUMNS:
        row[col] = ""


def normalize_group_label(label: str) -> str:
    label = compact(label, 240)
    label = re.sub(r"\bGO-SS-AA", "G0-SS-AA", label, flags=re.I)
    label = re.sub(r"\bGO-6C-AA", "G0-6C-AA", label, flags=re.I)
    label = re.sub(r"\bFluc\b", "FLuc", label, flags=re.I)
    label = re.sub(r"\s+", " ", label).strip(" ;,")
    return label


def caption_supports_any(caption: str, terms: list[str]) -> bool:
    low = caption.lower()
    return any(term.lower() in low for term in terms)


def extract_caption_group_labels(caption: str) -> list[str]:
    labels: list[str] = []
    patterns = [
        r"\bPBS\b",
        r"\bMC3(?:\s+(?:FLuc|IL-12))?\s+LNP\b",
        r"\bG0-SS-AA-C12(?:\s+(?:FLuc|IL-12))?\s+pLNP\b",
        r"\bG0-6C-AA-C12(?:\s+(?:FLuc|IL-12))?\s+LNP(?:\s+plus\s+free\s+IDO inhibitor)?\b",
        r"\bfree\s+IL-12\s+mRNA\b",
        r"\bfree\s+IDO inhibitor\b",
        r"\buntreated cells\b",
        r"\bcontrol group\b",
        r"\btreated group\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, caption, flags=re.I):
            label = normalize_group_label(match.group(0))
            if label and normalize_name(label) not in {normalize_name(x) for x in labels}:
                labels.append(label)
    return labels


def fallback_template_groups(item_id: str, caption: str) -> tuple[list[str], str]:
    item = item_id.lower()
    common3 = ["PBS", "G0-SS-AA-C12 FLuc pLNP", "G0-SS-AA-C12 IL-12 pLNP"]
    common4 = ["PBS", "G0-SS-AA-C12 FLuc pLNP", "G0-6C-AA-C12 IL-12 LNP", "G0-SS-AA-C12 IL-12 pLNP"]
    cytokine5 = [
        "PBS",
        "free IL-12 mRNA",
        "free IDO inhibitor",
        "G0-6C-AA-C12 IL-12 LNP plus free IDO inhibitor",
        "G0-SS-AA-C12 IL-12 pLNP",
    ]
    broad7 = [
        "PBS",
        "free IL-12 mRNA",
        "free IDO inhibitor",
        "G0-SS-AA-C12 FLuc pLNP",
        "G0-6C-AA-C12 IL-12 LNP",
        "G0-6C-AA-C12 IL-12 LNP plus free IDO inhibitor",
        "G0-SS-AA-C12 IL-12 pLNP",
    ]
    if any(item.startswith(prefix) for prefix in ("supplementary figure 60", "supplementary figure 61", "supplementary figure 62", "supplementary figure 67")):
        return common3, "QS_2026 supplementary ex vivo/in vitro pLNP fallback template."
    if item.startswith("supplementary figure 71") or item.startswith("supplementary figure 75") or item.startswith("supplementary figure 77"):
        return common4, "QS_2026 supplementary spleen immune readout fallback template."
    if item.startswith("supplementary figure 78"):
        return common4, "QS_2026 supplementary tumour readout fallback template."
    if item.startswith("supplementary figure 79"):
        groups = cytokine5[:]
        if caption_supports_any(caption, ["FLuc pLNP", "luciferase"]):
            groups.insert(3, "G0-SS-AA-C12 FLuc pLNP")
        return groups, "QS_2026 supplementary tumour cytokine fallback template."
    if item.startswith("supplementary figure 87") or item in {"supplementary figure 88", "supplementary figure 89"}:
        return broad7, "QS_2026 supplementary route/toxicity fallback template."
    if item in {"supplementary figure 52c", "supplementary figure 53c", "supplementary figure 54a", "supplementary figure 54b"}:
        return ["G0-SS-AA-C12 FLuc pLNP"], "QS_2026 physicochemical formulation-level fallback template."
    caption_labels = extract_caption_group_labels(caption)
    return caption_labels, "Caption-listed fallback group labels."


def apply_group_metadata(row: dict[str, object], group_label: str, smiles: dict[str, str]) -> None:
    label = normalize_group_label(group_label)
    fill_formulation(row, label, smiles)
    low = label.lower()
    if any(term in low for term in ["pbs", "untreated", "control group"]):
        row["Cargo"] = ""
        row["Cargo_type"] = ""
        row["Dose_ug_nucleicacid"] = ""
        return
    if "free ido" in low and "il-12" not in low:
        row["Cargo"] = ""
        row["Cargo_type"] = ""
        row["Dose_ug_nucleicacid"] = ""
        return
    if "il-12" in low:
        row["Cargo"] = "mRNA"
        row["Cargo_type"] = "IL-12"
    elif "fluc" in low:
        row["Cargo"] = "mRNA"
        row["Cargo_type"] = "FLuc"
    elif ("lnp" in low or "plnp" in low) and not row.get("Cargo_type"):
        row["manual_required"] = "true"


def fallback_rows_for_item(
    paper_folder: Path,
    item_id: str,
    item_row: dict[str, str],
    mapping: dict[str, object],
    caption: str,
    smiles: dict[str, str],
) -> tuple[list[dict[str, object]], str]:
    groups, basis = fallback_template_groups(item_id, caption)
    groups = [normalize_group_label(group) for group in groups if normalize_group_label(group)]
    seen: set[str] = set()
    unique_groups: list[str] = []
    for group in groups:
        key = normalize_name(group)
        if key and key not in seen:
            seen.add(key)
            unique_groups.append(group)
    if not unique_groups:
        return [], basis
    caption_has_labels = any(caption_supports_any(caption, [group]) for group in unique_groups)
    source_type = "image_caption_fallback" if mapping.get("source_image") or mapping.get("selected_source_for_paneling") else "caption_fallback"
    rows: list[dict[str, object]] = []
    for group in unique_groups:
        out = base_row(paper_folder, item_id, item_row, mapping, caption)
        out.update(
            {
                "source_type": source_type,
                "condition_1_name": "fallback_source",
                "condition_1_value": "caption/image group labels",
                "condition_2_name": "formulation_or_treatment_group",
                "condition_2_value": group,
                "evidence_excel": "",
                "confidence": "medium" if caption_has_labels else "low",
                "manual_required": "false" if caption_has_labels else "true",
                "reason": f"Excel block absent; condition/formulation-only fallback row generated from image/caption context. {basis} Experimental numeric assay/readout values were not extracted.",
            }
        )
        apply_group_metadata(out, group, smiles)
        for field in ("metric_type", "original_values", "aggregated_value", "unit", "replicate_type"):
            out[field] = ""
        if out.get("manual_required") == "true":
            out["reason"] = str(out["reason"]) + " Manual review required for fallback group completeness or inferred composition."
        rows.append(out)
    return rows, basis


def column_context(matrix: list[list[str]], row_idx: int, col_idx: int) -> tuple[str, str]:
    above = []
    for r in range(row_idx):
        if col_idx < len(matrix[r]):
            text = matrix[r][col_idx].strip()
            if text and not is_numeric(text):
                above.append(text)
    group = ""
    metric = ""
    for text in above:
        if re.match(r"^Fig\.\s*\d+", text, re.I):
            continue
        low = text.lower()
        if any(term in low for term in GROUP_METRIC_TERMS):
            metric = text
        elif not group:
            group = text
    if above and not group:
        group = above[-1]
    return group, metric


def left_label(row: list[str], col_idx: int) -> str:
    for idx in range(col_idx - 1, -1, -1):
        text = row[idx].strip() if idx < len(row) else ""
        if text and not is_numeric(text):
            return text
    return ""


def row_axis(matrix: list[list[str]], row_idx: int) -> tuple[str, str]:
    if not matrix or row_idx >= len(matrix) or not matrix[row_idx]:
        return "", ""
    first = matrix[row_idx][0].strip()
    if not is_numeric(first):
        return "row_label" if first else "", first
    label = ""
    for r in range(row_idx - 1, -1, -1):
        if matrix[r] and matrix[r][0].strip() and not is_numeric(matrix[r][0]):
            label = matrix[r][0].strip()
            break
    return label, first


def replicate_index(matrix: list[list[str]], row_idx: int, col_idx: int, group: str) -> str:
    if not group:
        return str(col_idx + 1)
    count = 0
    for c in range(col_idx + 1):
        g, _ = column_context(matrix, row_idx, c)
        if g == group:
            count += 1
    return str(count)


def should_skip_numeric(matrix: list[list[str]], row_idx: int, col_idx: int) -> bool:
    if col_idx != 0:
        return False
    if row_idx == 0:
        return False
    header = matrix[0][0].lower() if matrix and matrix[0] else ""
    if any(term in header for term in ["days", "time"]):
        return True
    numeric_after = sum(1 for cell in matrix[row_idx][1:] if is_numeric(cell))
    return numeric_after > 0


def numeric_value_text(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = text.replace(",", "").replace("%", "").strip()
    return text if is_numeric(normalized) else ""


def mean_text(values: list[str]) -> str:
    nums = [float(v.replace(",", "").replace("%", "").strip()) for v in values if numeric_value_text(v)]
    if not nums:
        return ""
    value = sum(nums) / len(nums)
    return f"{value:.6g}"


def concise_metric_type(item_id: str, context: dict[str, object], excel_metric: str = "") -> tuple[str, str]:
    method = str(context.get("Experiment_method", "")).strip()
    unit = metric_for_item(item_id, excel_metric)[1]
    if method:
        if method in {"luminescence", "IVIS", "RNA-seq", "MFI"}:
            metric = {"luminescence": "luminescence", "IVIS": "luminescence_total_flux", "RNA-seq": "RNA_expression", "MFI": "MFI"}[method]
        elif method.startswith("ELISA_IL-12") or method.startswith("ELISA_TNF") or method.startswith("ELISA_IFN"):
            metric = method.replace("ELISA_", "") + "_pg_ml"
            unit = unit or "pg/mL"
        elif method.startswith("flow_cytometry"):
            metric = "flow_cytometry_percent"
            unit = unit or "%"
        elif method.startswith("qPCR"):
            metric = "RNA_expression"
            unit = unit or "fold_change"
        else:
            metric = re.sub(r"[^A-Za-z0-9_]+", "_", method).strip("_")
        return metric, unit
    metric, inferred_unit = metric_for_item(item_id, excel_metric)
    metric = re.sub(r"[^A-Za-z0-9_]+", "_", metric).strip("_")
    return metric, unit or inferred_unit


def formulation_key(value: str) -> str:
    return normalize_name(value).replace("_", "-").replace(" plnp", "").replace(" lnp", "").replace(" fluc", "").replace(" il-12", "")


def matched_value_group(formulation: str, value_groups: dict[str, dict[str, object]]) -> dict[str, object] | None:
    target = formulation_key(formulation)
    if not target:
        return None
    for label, group in value_groups.items():
        key = formulation_key(label)
        if key and (key == target or key in target or target in key):
            return group
    return None


def extract_excel_value_groups(item_id: str, matrix: list[list[str]]) -> dict[str, dict[str, object]]:
    groups: dict[str, dict[str, object]] = {}

    def add(label: str, value: str, metric_hint: str = "") -> None:
        numeric = numeric_value_text(value)
        if not label or not numeric:
            return
        label = formulation_from_labels(item_id, label, "", "")
        if not label or re.match(r"^Fig\.\s*\d+", label, re.I):
            return
        entry = groups.setdefault(label, {"values": [], "metric_hint": metric_hint})
        entry["values"].append(numeric)
        if metric_hint and not entry.get("metric_hint"):
            entry["metric_hint"] = metric_hint

    if item_id == "figure 2b" and matrix:
        header = matrix[0]
        for row in matrix[1:]:
            if not row or not row[0].strip():
                continue
            base = row[0].strip()
            for col_idx, cell in enumerate(row[1:], start=1):
                if col_idx < len(header):
                    label = formulation_from_labels(item_id, "", base, header[col_idx])
                    add(label, cell)
        return groups

    if matrix and matrix[0] and any(term in matrix[0][0].lower() for term in ("day", "time")):
        return groups

    for row_idx, row in enumerate(matrix):
        for col_idx, cell in enumerate(row):
            if should_skip_numeric(matrix, row_idx, col_idx):
                continue
            if not numeric_value_text(cell):
                continue
            group, metric_hint = column_context(matrix, row_idx, col_idx)
            row_label_kind, row_label = row_axis(matrix, row_idx)
            left = left_label(row, col_idx)
            label = group or left
            if not label and row_label_kind == "row_label":
                label = row_label
            if label and any(term in label.lower() for term in GROUP_METRIC_TERMS):
                metric_hint = label
                label = left or group
            add(label, cell, metric_hint)
    return groups


def apply_excel_values(row: dict[str, object], item_id: str, value_group: dict[str, object] | None, block_csv_path: str) -> bool:
    if not value_group:
        return False
    values = [str(v) for v in value_group.get("values", []) if numeric_value_text(str(v))]
    if not values:
        return False
    metric, unit = concise_metric_type(item_id, row, str(value_group.get("metric_hint", "")))
    row["metric_type"] = metric
    row["original_values"] = "|".join(values)
    row["aggregated_value"] = mean_text(values) if len(values) > 1 else values[0]
    row["unit"] = unit
    row["replicate_type"] = "mean" if len(values) == 1 else "individual"
    row["evidence_excel"] = block_csv_path
    row["reason"] = (
        str(row.get("reason", "")).strip()
        + " Experimental assay/readout values were extracted from the mapped Excel/source-data block; aggregated_value is the arithmetic mean of original_values when multiple replicates were present."
    ).strip()
    return True


def base_row(
    paper_folder: Path,
    item_id: str,
    item_row: dict[str, str],
    mapping: dict[str, object],
    caption: str,
) -> dict[str, object]:
    row = {col: "" for col in UNIFIED_COLUMNS}
    row.update(
        {
            "Paper_ID": paper_folder.name,
            "Item_ID": item_id,
            "visual_type": item_row.get("visual_type", "") or item_row.get("item_type", ""),
            "source_image": mapping.get("source_image", ""),
            "source_pdf": mapping.get("source_pdf", ""),
            "source_page": mapping.get("source_page", ""),
            "selected_source_for_paneling": mapping.get("selected_source_for_paneling", "") or mapping.get("source_image", ""),
            "evidence_text": caption or item_row.get("reason", ""),
            "evidence_image": mapping.get("selected_source_for_paneling", "") or mapping.get("source_image", ""),
            "confidence": "medium",
            "manual_required": "false",
        }
    )
    row.update(context_for_item(item_id))
    if item_id.startswith("figure") or row.get("Formulation_Name"):
        row["Aqueous_buffer"] = "10 mM citrate buffer pH 3"
        row["Dialysis_buffer"] = "PBS"
        row["Mixing_method"] = "pipette" if item_id in {"figure 2b", "supplementary figure 47", "supplementary figure 49"} else "microfluidic"
    return row


def add_flag(flags: dict[tuple[str, str, str, str], dict[str, str]], paper_id: str, item_id: str, block_id: str, field: str, issue: str, severity: str, reason: str) -> None:
    key = (item_id, block_id, field, issue)
    flags[key] = {
        "Paper_ID": paper_id,
        "Item_ID": item_id,
        "block_id": block_id,
        "field": field,
        "issue": issue,
        "severity": severity,
        "reason": reason,
    }


def main() -> None:
    paper_folder = find_paper_folder()
    selected = selected_rows(paper_folder)
    mappings = mapping_by_item(paper_folder)
    matches = excel_matches(paper_folder, selected)
    smiles, _manual = smiles_lookup(paper_folder)
    main_md = (paper_folder / "QS_2026" / "QS_2026.md").read_text(encoding="utf-8", errors="replace")
    supp_md = (paper_folder / "41565_2025_2102_MOESM1_ESM" / "41565_2025_2102_MOESM1_ESM.md").read_text(encoding="utf-8", errors="replace")

    records: list[dict[str, object]] = []
    flags: dict[tuple[str, str, str, str], dict[str, str]] = {}

    for item_id, item_row in selected.items():
        caption = caption_for_item(item_id, main_md, supp_md)
        mapping = mappings.get(item_id, {})
        item_matches = matches.get(item_id, [])
        item_rows = 0

        for match in item_matches:
            rel = (match.get("block_csv_path") or "").strip()
            block_path = paper_folder / rel
            if not rel or not block_path.exists():
                add_flag(flags, paper_folder.name, item_id, match.get("block_id", ""), "block_csv_path", "missing Excel block", "high", f"Mapped block does not exist: {rel}")
                continue
            matrix = read_csv_matrix(block_path)
            labels = excel_context_labels(matrix)
            value_groups = extract_excel_value_groups(item_id, matrix)
            formulations = distinct_formulations(item_id, matrix) or [formulation_from_labels(item_id, " ".join(labels), "", "")]
            for formulation in [f for f in formulations if f]:
                out = base_row(paper_folder, item_id, item_row, mapping, caption)
                out.update(
                    {
                        "source_type": "excel_block_context",
                        "excel_file": match.get("excel_file", ""),
                        "excel_sheet": match.get("excel_sheet", ""),
                        "block_id": match.get("block_id", ""),
                        "block_csv_path": rel,
                        "condition_1_name": "excel_context_labels" if labels else "",
                        "condition_1_value": "; ".join(labels),
                        "condition_2_name": "formulation_or_treatment_group",
                        "condition_2_value": formulation,
                        "evidence_excel": rel,
                        "confidence": "medium" if labels else "low",
                        "reason": "Excel block was used for identity, labels, headers, group/formulation context, provenance, and experimental value extraction when a reliable group-to-value mapping was present. Figure-image digitization was not used.",
                    }
                )
                fill_formulation(out, formulation, smiles)
                apply_excel_values(out, item_id, matched_value_group(formulation, value_groups), rel)
                out["Cargo"] = infer_cargo(str(out.get("Formulation_Name", "")), str(out.get("Cargo", "")))
                form_low = str(out.get("Formulation_Name", "")).lower()
                if "il-12" in form_low:
                    out["Cargo_type"] = "IL-12"
                elif "fluc" in form_low:
                    out["Cargo_type"] = "FLuc"

                manual_reasons = []
                if not out.get("evidence_image"):
                    manual_reasons.append("missing figure-image evidence path")
                    add_flag(flags, paper_folder.name, item_id, match.get("block_id", ""), "evidence_image", "missing figure evidence", "medium", "No source image path was available in total_figure_mapping.json.")
                if manual_reasons:
                    out["manual_required"] = "true"
                    out["reason"] = str(out["reason"]) + " Manual review: " + "; ".join(manual_reasons) + "."
                force_blank_output_smiles(out)
                records.append(out)
                item_rows += 1

        if item_rows == 0:
            fallback_rows, fallback_basis = fallback_rows_for_item(paper_folder, item_id, item_row, mapping, caption, smiles)
            if fallback_rows:
                for row in fallback_rows:
                    force_blank_output_smiles(row)
                records.extend(fallback_rows)
                item_rows += len(fallback_rows)
                if any(row.get("manual_required") == "true" for row in fallback_rows):
                    add_flag(flags, paper_folder.name, item_id, "", "fallback_group_labels", "manual fallback review", "medium", f"Fallback groups generated without full direct caption support: {fallback_basis}")
                if not any(row.get("evidence_image") for row in fallback_rows):
                    add_flag(flags, paper_folder.name, item_id, "", "evidence_image", "missing figure evidence", "medium", "No source image path was available in total_figure_mapping.json.")
            else:
                out = base_row(paper_folder, item_id, item_row, mapping, caption)
                out.update(
                    {
                        "source_type": "manual_review_placeholder",
                        "manual_required": "true",
                        "confidence": "low",
                        "reason": "Selected item has no locally mapped Excel context/value block and no supported caption/image fallback group labels; condition/formulation extraction and any Excel-backed value extraction need manual review.",
                    }
                )
                force_blank_output_smiles(out)
                records.append(out)
                add_flag(flags, paper_folder.name, item_id, "", "row", "manual extraction required", "high", out["reason"])
                if not out.get("evidence_image"):
                    add_flag(flags, paper_folder.name, item_id, "", "evidence_image", "missing figure evidence", "medium", "No source image path was available in total_figure_mapping.json.")

    for output_name in ["unified_extraction.csv", "unified_extraction.json", "unified_extraction_review_flags.csv"]:
        backup(paper_folder / output_name)

    write_csv(paper_folder / "unified_extraction.csv", records, UNIFIED_COLUMNS)
    flag_rows = list(flags.values())
    write_csv(paper_folder / "unified_extraction_review_flags.csv", flag_rows, FLAG_COLUMNS)
    with (paper_folder / "unified_extraction.json").open("w", encoding="utf-8") as fh:
        json.dump(
            {
                "created_by": "agent_workspace/tools/build_unified_extraction_qs2026.py",
                "created_at": utc_now(),
                "records": records,
                "source_summary": {
                    "paper_folder": str(paper_folder),
                    "selected_items": len(selected),
                    "items_with_excel_mapping": sum(1 for item in selected if matches.get(item)),
                    "record_count": len(records),
                    "review_flag_count": len(flag_rows),
                    "inputs": [
                        "fig_table_lnpdb_classified.csv",
                        "total_figure_mapping.json",
                        "excel_mapping.json",
                        "excel_block_inventory.csv",
                        "smiles_resolved.csv",
                        "QS_2026/QS_2026.md",
                        "41565_2025_2102_MOESM1_ESM/41565_2025_2102_MOESM1_ESM.md",
                    ],
                },
            },
            fh,
            ensure_ascii=False,
            indent=2,
        )
    print(json.dumps({"records": len(records), "review_flags": len(flag_rows), "selected_items": len(selected)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
