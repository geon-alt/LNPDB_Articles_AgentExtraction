from __future__ import annotations

import csv
import re
import shutil
from datetime import datetime
from pathlib import Path

try:
    from rdkit import Chem
except Exception:  # pragma: no cover - validation environment may differ
    Chem = None


PAPER_FOLDER = Path(r"F:\내 드라이브\EXTRACT-TEST\QS_2026")

OUTPUTS = {
    "inventory": PAPER_FOLDER / "compound_inventory_standardized.csv",
    "resolved": PAPER_FOLDER / "smiles_resolved.csv",
    "qc": PAPER_FOLDER / "smiles_resolution_qc.csv",
}

TEXT_SOURCES = [
    PAPER_FOLDER / "QS_2026" / "QS_2026.md",
    PAPER_FOLDER
    / "41565_2025_2102_MOESM1_ESM"
    / "41565_2025_2102_MOESM1_ESM.md",
]


CURATED_SMILES = {
    "cholesterol": "C[C@H](CCCC(C)C)[C@H]1CC[C@H]2[C@@H]3CC=C4C[C@@H](O)CC[C@]4(C)[C@H]3CC[C@]12C",
    "1,2-dioleoyl-sn-glycero-3-phosphoethanolamine": "CCCCCCCC/C=C\\CCCCCCCC(=O)OC[C@H](COP(=O)(O)OCCN)OC(=O)CCCCCCC/C=C\\CCCCCCCC",
    "DOPE": "CCCCCCCC/C=C\\CCCCCCCC(=O)OC[C@H](COP(=O)(O)OCCN)OC(=O)CCCCCCC/C=C\\CCCCCCCC",
    "1,2-distearoyl-sn-glycero-3-phosphocholine": "CCCCCCCCCCCCCCCCCC(=O)OC[C@H](COP(=O)([O-])OCC[N+](C)(C)C)OC(=O)CCCCCCCCCCCCCCCCC",
    "DSPC": "CCCCCCCCCCCCCCCCCC(=O)OC[C@H](COP(=O)([O-])OCC[N+](C)(C)C)OC(=O)CCCCCCCCCCCCCCCCC",
    "indoximod": "CN1C=C(C[C@H](N)C(=O)O)c2ccccc21",
    "1-methyl-D-tryptophan": "CN1C=C(C[C@H](N)C(=O)O)c2ccccc21",
    "2-hydroxyethyl disulfide": "OCCSSCCO",
    "2,2'-disulfanediylbis(ethan-1-ol)": "OCCSSCCO",
    "hexane-1,6-diol": "OCCCCCCO",
    "1,6-hexanediol": "OCCCCCCO",
    "epoxydecane": "CCCCCCCCC1CO1",
    "epoxydodecane": "CCCCCCCCCCC1CO1",
    "epoxytetradecane": "CCCCCCCCCCCCC1CO1",
    "4-nitrophenyl carbonochloridate": "O=C(Cl)Oc1ccc([N+](=O)[O-])cc1",
    "triethylamine": "CCN(CC)CC",
    "methanol": "CO",
    "ethanol": "CCO",
    "THF": "C1CCOC1",
    "ethyl acetate": "CCOC(C)=O",
    "hexane": "CCCCCC",
}

DISABLED_STRUCTURE_IMAGE_REASON = "Structure-image-based SMILES extraction is disabled; no exact text/reference SMILES was available."


BASE_COMPOUNDS = [
    {
        "Name": "indoximod",
        "alias": "1-methyl-D-tryptophan; IDO inhibitor; AA",
        "compound_class": "small_molecule_drug",
    },
    {
        "Name": "1-methyl-D-tryptophan",
        "alias": "indoximod",
        "compound_class": "small_molecule_drug",
    },
    {
        "Name": "cholesterol",
        "alias": "",
        "compound_class": "helper_lipid",
    },
    {
        "Name": "DOPE",
        "alias": "1,2-dioleoyl-sn-glycero-3-phosphoethanolamine",
        "compound_class": "helper_lipid",
    },
    {
        "Name": "1,2-dioleoyl-sn-glycero-3-phosphoethanolamine",
        "alias": "DOPE",
        "compound_class": "helper_lipid",
    },
    {
        "Name": "DMG-PEG 2000",
        "alias": "DMG-PEG; 1,2-dimyristoyl-rac-glycero-3-methoxypolyethylene glycol-2000",
        "compound_class": "peg_lipid_polymer",
    },
    {
        "Name": "DMG-PEG",
        "alias": "DMG-PEG 2000; 1,2-dimyristoyl-rac-glycero-3-methoxypolyethylene glycol-2000",
        "compound_class": "peg_lipid_polymer",
    },
    {
        "Name": "DLin-MC3-DMA",
        "alias": "MC3",
        "compound_class": "ionizable_lipid",
    },
    {
        "Name": "MC3",
        "alias": "DLin-MC3-DMA",
        "compound_class": "ionizable_lipid",
    },
    {
        "Name": "DSPC",
        "alias": "1,2-distearoyl-sn-glycero-3-phosphocholine",
        "compound_class": "helper_lipid",
    },
    {
        "Name": "1,2-distearoyl-sn-glycero-3-phosphocholine",
        "alias": "DSPC",
        "compound_class": "helper_lipid",
    },
    {
        "Name": "IL-12 mRNA",
        "alias": "interleukin-12 mRNA",
        "compound_class": "rna_cargo",
    },
    {
        "Name": "FLuc mRNA",
        "alias": "firefly luciferase mRNA",
        "compound_class": "rna_cargo",
    },
    {
        "Name": "m1ψ-modified FLuc mRNA",
        "alias": "1-methylpseudouridine-modified firefly luciferase mRNA",
        "compound_class": "rna_cargo",
    },
]

REAGENTS = [
    "2-hydroxyethyl disulfide",
    "2,2'-disulfanediylbis(ethan-1-ol)",
    "hexane-1,6-diol",
    "1,6-hexanediol",
    "epoxydecane",
    "epoxydodecane",
    "epoxytetradecane",
    "4-nitrophenyl carbonochloridate",
    "triethylamine",
    "methanol",
    "ethanol",
    "THF",
    "ethyl acetate",
    "hexane",
]


def canonical_smiles(smiles: str) -> tuple[str, str]:
    if not smiles:
        return "", ""
    if Chem is None:
        return smiles, "rdkit_unavailable_not_canonicalized"
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return "", "invalid_curated_smiles"
    return Chem.MolToSmiles(mol, isomericSmiles=True), ""


def read_sources() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in TEXT_SOURCES:
        if not path.exists():
            continue
        rel = path.relative_to(PAPER_FOLDER).as_posix()
        for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            text = re.sub(r"\s+", " ", line).strip()
            if text:
                rows.append({"source_path": rel, "line": str(line_no), "text": text})
    return rows


def find_evidence(name: str, sources: list[dict[str, str]]) -> dict[str, str]:
    variants = {name, name.replace("G0-", "GO-"), name.replace("GO-", "G0-")}
    if name == "DOPE":
        variants.add("1,2-dioleoyl")
    if name == "DMG-PEG 2000":
        variants.add("DMG-PEG")
    if name == "DLin-MC3-DMA":
        variants.add("MC3")
    if name == "indoximod":
        variants.add("1-methyl-D-tryptophan")
    for row in sources:
        hay = row["text"]
        if any(v and v in hay for v in variants):
            return {
                "source_path": row["source_path"],
                "source_line": row["line"],
                "evidence_text": hay[:700],
            }
    return {"source_path": "", "source_line": "", "evidence_text": ""}


def build_pil_rows() -> list[dict[str, str]]:
    rows = []
    heads = ["P2A", "T3A", "G0", "110", "306", "L2A", "DAB"]
    tails = ["C10", "C12", "C14"]
    for head in heads:
        for tail in tails:
            rows.append(
                {
                    "Name": f"{head}-SS-AA-{tail}",
                    "alias": f"{head}-SS-AA prodrug head with {tail} epoxide-derived alkyl tails",
                    "compound_class": "novel_prodrug_ionizable_lipid",
                }
            )
    for name in ["G0-6C-AA-C12", "Nitro-SS-Nitro", "Nitro-SS-AA", "4-Nitro-SS-AA"]:
        rows.append({"Name": name, "alias": "", "compound_class": "synthetic_intermediate_or_control"})
    for head in heads:
        rows.append(
            {
                "Name": f"{head}-SS-AA",
                "alias": f"{head} prodrug amine head",
                "compound_class": "prodrug_amine_head_intermediate",
            }
        )
    for name in ["Nitro-6C-Nitro", "Nitro-6C-AA", "G0-6C-AA"]:
        rows.append({"Name": name, "alias": "", "compound_class": "synthetic_intermediate_or_control"})
    return rows


def build_formulation_rows() -> list[dict[str, str]]:
    names = [
        ("G0-SS-AA-C12 IL-12 pLNP", "lead pLNP formulation with IL-12 mRNA"),
        ("G0-SS-AA-C12 FLuc pLNP", "pLNP formulation with FLuc mRNA"),
        ("G0-6C-AA-C12 IL-12 LNP", "non-cleavable control LNP with IL-12 mRNA"),
        ("G0-6C-AA-C12 LNP", "non-cleavable control LNP"),
        ("MC3 LNP", "DLin-MC3-DMA control LNP"),
    ]
    return [
        {"Name": name, "alias": alias, "compound_class": "lnp_formulation_mixture"}
        for name, alias in names
    ]


def backup_existing() -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for path in OUTPUTS.values():
        if path.exists():
            backup = path.with_name(f"{path.name}.bak_05_smiles_structure_resolution_{timestamp}")
            shutil.copy2(path, backup)


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    sources = read_sources()
    backup_existing()

    input_rows = BASE_COMPOUNDS + build_pil_rows() + build_formulation_rows()
    input_rows += [{"Name": name, "alias": "", "compound_class": "reagent_or_solvent"} for name in REAGENTS]

    seen: set[str] = set()
    inventory: list[dict[str, str]] = []
    resolved: list[dict[str, str]] = []
    qc: list[dict[str, str]] = []

    for index, row in enumerate(input_rows, 1):
        name = row["Name"]
        if name in seen:
            continue
        seen.add(name)
        evidence = find_evidence(name, sources)
        source_type = "markdown_text" if evidence["source_path"] else "curated_candidate"
        smiles_raw = CURATED_SMILES.get(name, "")
        smiles, smiles_issue = canonical_smiles(smiles_raw)

        manual_required = "false" if smiles and not smiles_issue else "true"
        reason = ""
        method = ""
        confidence = "high" if smiles and not smiles_issue else "low"
        if smiles:
            method = "api_free_curated_smiles_validated_by_rdkit" if Chem is not None else "api_free_curated_smiles"
            reason = "Resolved from exact local name/alias using an API-free curated common-chemical mapping."
        elif row["compound_class"] == "novel_prodrug_ionizable_lipid":
            reason = DISABLED_STRUCTURE_IMAGE_REASON
            method = "structure_image_smiles_disabled_unresolved"
        elif row["compound_class"] in {"lnp_formulation_mixture", "rna_cargo", "peg_lipid_polymer"}:
            reason = "Entity is a formulation, polymeric PEG lipid, or RNA cargo rather than a single exact small-molecule structure."
            method = "not_single_exact_smiles"
        elif row["Name"] in {"MC3", "DLin-MC3-DMA"}:
            reason = "MC3 is identified locally, but exact stereochemical/structural SMILES was not resolved without external lookup."
            method = "local_text_evidence_unresolved"
        else:
            reason = "No deterministic local SMILES mapping was available."
            method = "local_text_evidence_unresolved"

        if smiles_issue:
            reason = f"{reason} Curated SMILES validation issue: {smiles_issue}."

        compound_id = f"QS2026_CMPD_{index:03d}"
        inv_row = {
            "compound_id": compound_id,
            "Name": name,
            "standardized_name": name.replace("GO-", "G0-"),
            "alias": row.get("alias", ""),
            "IUPAC_name": "",
            "compound_class": row.get("compound_class", ""),
            "source_type": source_type,
            "source_path": evidence["source_path"],
            "source_line": evidence["source_line"],
            "Item_ID": "",
            "source_image": "",
            "evidence_text": evidence["evidence_text"],
            "manual_required": manual_required,
            "reason": reason,
        }
        inventory.append(inv_row)
        resolved.append(
            {
                "compound_id": compound_id,
                "Name": name,
                "standardized_name": inv_row["standardized_name"],
                "alias": inv_row["alias"],
                "SMILES": smiles,
                "resolved_smiles": smiles,
                "resolution_method": method,
                "confidence": confidence,
                "manual_required": manual_required,
                "source_path": evidence["source_path"],
                "source_line": evidence["source_line"],
                "evidence_text": evidence["evidence_text"],
                "reason": reason,
            }
        )
        if manual_required == "true":
            qc.append(
                {
                    "compound_id": compound_id,
                    "Name": name,
                    "issue": "unresolved_smiles",
                    "severity": "manual_review",
                    "manual_required": "true",
                    "source_path": evidence["source_path"],
                    "source_line": evidence["source_line"],
                    "evidence_text": evidence["evidence_text"],
                    "reason": reason,
                }
            )

    qc.append(
        {
            "compound_id": "",
            "Name": "G0/GO OCR normalization",
            "issue": "ambiguous_ocr_variant",
            "severity": "note",
            "manual_required": "false",
            "source_path": "QS_2026/QS_2026.md",
            "source_line": "",
            "evidence_text": "The main markdown contains both G0-SS-AA-C12 and GO-SS-AA-C12 variants; standardized_name normalizes GO- to G0- because the nomenclature definition and supplement use G0.",
            "reason": "Recorded for provenance; no source file was modified.",
        }
    )

    inventory_fields = [
        "compound_id",
        "Name",
        "standardized_name",
        "alias",
        "IUPAC_name",
        "compound_class",
        "source_type",
        "source_path",
        "source_line",
        "Item_ID",
        "source_image",
        "evidence_text",
        "manual_required",
        "reason",
    ]
    resolved_fields = [
        "compound_id",
        "Name",
        "standardized_name",
        "alias",
        "SMILES",
        "resolved_smiles",
        "resolution_method",
        "confidence",
        "manual_required",
        "source_path",
        "source_line",
        "evidence_text",
        "reason",
    ]
    qc_fields = [
        "compound_id",
        "Name",
        "issue",
        "severity",
        "manual_required",
        "source_path",
        "source_line",
        "evidence_text",
        "reason",
    ]

    write_csv(OUTPUTS["inventory"], inventory, inventory_fields)
    write_csv(OUTPUTS["resolved"], resolved, resolved_fields)
    write_csv(OUTPUTS["qc"], qc, qc_fields)

    resolved_count = sum(1 for row in resolved if row["resolved_smiles"])
    print(f"wrote {OUTPUTS['inventory']} rows={len(inventory)}")
    print(f"wrote {OUTPUTS['resolved']} rows={len(resolved)} resolved_smiles={resolved_count}")
    print(f"wrote {OUTPUTS['qc']} rows={len(qc)}")


if __name__ == "__main__":
    main()
