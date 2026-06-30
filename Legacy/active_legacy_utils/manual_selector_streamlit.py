from __future__ import annotations

import argparse
from datetime import datetime
from io import StringIO
from pathlib import Path

import pandas as pd
import streamlit as st

from Legacy.active_legacy_utils.ft_id_utils import normalize_ft_item_id


CSV_NAME = "fig_table_lnpdb_classified.csv"
REVIEWED_COPY_NAME = "fig_table_lnpdb_classified_manual_reviewed.csv"
ROW_ID_COL = "__row_id__"
MANUAL_REVIEW_MARKER_FILENAME = ".manual_select_review_done"
EMPTY_VALUES = {"", "nan", "none", "null", "[]", "{}"}
INCLUDE_MANUAL_VALUES = {"yes", "y", "1", "true", "maybe"}
EXCLUDE_MANUAL_VALUES = {"no", "n", "0", "false"}
EXCEL_MATCH_COLUMNS = [
    "excel_item_id",
    "matched_blocks",
    "matched_block_ids",
    "matched_block_csv",
    "matched_sheet",
    "matched_sheet_file",
    "excel_block_id",
    "excel_block_file",
    "excel_sheet",
]
SEARCH_COLUMNS = ["item_id", "base_id", "reason", "visual_type", "excel_item_id", "matched_blocks"]
PREVIEW_COLUMNS = ["item_id", "manual_select", "need_for_lnpdb", "visual_type", "priority", "excel_item_id", "matched_blocks"]


def parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--paper-folder", default=".")
    args, _ = parser.parse_known_args()
    return args


def is_meaningful_value(value: object) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() not in EMPTY_VALUES


def row_has_excel_match(row: pd.Series, excel_cols: list[str]) -> bool:
    return any(is_meaningful_value(row.get(col, "")) for col in excel_cols)


def normalize_manual_select(value: object) -> str:
    text = str(value).strip().lower()
    if text in EMPTY_VALUES:
        return ""
    if text in INCLUDE_MANUAL_VALUES:
        return "yes"
    if text in EXCLUDE_MANUAL_VALUES:
        return "no"
    return ""


def initial_select_for_row(row: pd.Series) -> bool:
    manual = normalize_manual_select(row.get("manual_select", ""))
    if manual == "yes":
        return True
    if manual == "no":
        return False
    return str(row.get("need_for_lnpdb", "")).strip().lower() in {"yes", "maybe"}


def load_classified_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, dtype=str).fillna("")
    if "manual_select" not in df.columns:
        df["manual_select"] = ""
    df[ROW_ID_COL] = range(len(df))
    return df


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    buffer = StringIO()
    df.drop(columns=[ROW_ID_COL], errors="ignore").to_csv(buffer, index=False, encoding="utf-8-sig")
    return buffer.getvalue().encode("utf-8-sig")


def build_selector_view_df(df: pd.DataFrame) -> pd.DataFrame:
    selector_df = pd.DataFrame(
        {
            ROW_ID_COL: df[ROW_ID_COL].astype(int).tolist(),
            "item_id": df["item_id"].astype(str).tolist() if "item_id" in df.columns else [""] * len(df),
            "base_id": df["base_id"].astype(str).tolist() if "base_id" in df.columns else [""] * len(df),
        }
    )
    selector_df["select"] = df.apply(initial_select_for_row, axis=1).astype(bool).tolist()
    return selector_df


def get_unique_options(df: pd.DataFrame, column: str) -> list[str]:
    if column not in df.columns:
        return []
    return sorted({str(v).strip() for v in df[column].fillna("").tolist() if str(v).strip()})


def apply_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    visible = df.copy()
    for column in ["need_for_lnpdb", "priority", "visual_type", "item_type", "is_supplementary", "confidence"]:
        selected = filters.get(column, [])
        if selected and column in visible.columns:
            visible = visible[visible[column].astype(str).str.strip().isin(selected)]
    excel_cols = [col for col in EXCEL_MATCH_COLUMNS if col in visible.columns]
    excel_match = visible.apply(row_has_excel_match, axis=1, excel_cols=excel_cols) if excel_cols else pd.Series(False, index=visible.index)
    excel_status = filters.get("excel_status", "all")
    if excel_status == "Excel matched only":
        visible = visible[excel_match]
    elif excel_status == "Excel missing only":
        visible = visible[~excel_match]
    search = str(filters.get("search", "")).strip().lower()
    if search:
        existing_cols = [col for col in SEARCH_COLUMNS if col in visible.columns]
        if existing_cols:
            haystack = visible[existing_cols].astype(str).agg(" ".join, axis=1).str.lower()
            normalized = visible[existing_cols].astype(str).apply(lambda col: col.map(normalize_ft_item_id)).agg(" ".join, axis=1)
            visible = visible[(haystack + " " + normalized).str.contains(search, regex=False, na=False)]
    return visible


def write_review_outputs(paper_folder: Path, df: pd.DataFrame) -> tuple[Path, Path]:
    csv_path = paper_folder / CSV_NAME
    reviewed_path = paper_folder / REVIEWED_COPY_NAME
    backup_path = csv_path.with_suffix(csv_path.suffix + f".bak_manual_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    if csv_path.exists():
        csv_path.replace(backup_path)
    df.drop(columns=[ROW_ID_COL], errors="ignore").to_csv(csv_path, index=False, encoding="utf-8-sig")
    df.drop(columns=[ROW_ID_COL], errors="ignore").to_csv(reviewed_path, index=False, encoding="utf-8-sig")
    marker = paper_folder / MANUAL_REVIEW_MARKER_FILENAME
    marker.write_text(f"manual review completed at {datetime.now().isoformat()}\n", encoding="utf-8")
    return csv_path, marker


def main() -> None:
    args = parse_cli_args()
    paper_folder = Path(args.paper_folder).resolve()
    csv_path = paper_folder / CSV_NAME
    st.set_page_config(page_title="LNPDB manual figure/table selector", layout="wide")
    st.title("LNPDB manual figure/table selector")
    st.caption(str(paper_folder))
    if not csv_path.exists():
        st.error(f"Missing {csv_path}")
        return
    df = load_classified_csv(csv_path)
    if "selector_view_df" not in st.session_state:
        st.session_state["selector_view_df"] = build_selector_view_df(df)
    filters = {
        "need_for_lnpdb": st.sidebar.multiselect("need_for_lnpdb", get_unique_options(df, "need_for_lnpdb")),
        "priority": st.sidebar.multiselect("priority", get_unique_options(df, "priority")),
        "visual_type": st.sidebar.multiselect("visual_type", get_unique_options(df, "visual_type")),
        "item_type": st.sidebar.multiselect("item_type", get_unique_options(df, "item_type")),
        "is_supplementary": st.sidebar.multiselect("is_supplementary", get_unique_options(df, "is_supplementary")),
        "confidence": st.sidebar.multiselect("confidence", get_unique_options(df, "confidence")),
        "excel_status": st.sidebar.selectbox("Excel status", ["all", "Excel matched only", "Excel missing only"]),
        "search": st.sidebar.text_input("Search"),
    }
    visible = apply_filters(df, filters)
    st.write(f"Visible rows: {len(visible)} / {len(df)}")
    selector = st.session_state["selector_view_df"]
    visible_ids = visible[ROW_ID_COL].astype(int).tolist()
    edit_df = selector[selector[ROW_ID_COL].astype(int).isin(visible_ids)][[ROW_ID_COL, "item_id", "select"]].copy()
    edited = st.data_editor(edit_df, hide_index=True, use_container_width=True, column_config={"select": st.column_config.CheckboxColumn("select")})
    updated = selector.set_index(ROW_ID_COL)
    for _, row in edited.iterrows():
        updated.at[int(row[ROW_ID_COL]), "select"] = bool(row["select"])
    st.session_state["selector_view_df"] = updated.reset_index()
    selected_ids = set(st.session_state["selector_view_df"].loc[st.session_state["selector_view_df"]["select"], ROW_ID_COL].astype(int))
    output_df = df.copy()
    output_df["manual_select"] = output_df[ROW_ID_COL].astype(int).map(lambda rid: "yes" if rid in selected_ids else "no")
    preview_cols = [col for col in PREVIEW_COLUMNS if col in output_df.columns]
    st.dataframe(output_df[preview_cols], use_container_width=True)
    st.download_button("Download reviewed CSV", dataframe_to_csv_bytes(output_df), file_name=REVIEWED_COPY_NAME)
    if st.button("Write reviewed CSV and marker"):
        csv_out, marker = write_review_outputs(paper_folder, output_df)
        st.success(f"Wrote {csv_out} and {marker}")


if __name__ == "__main__":
    main()

