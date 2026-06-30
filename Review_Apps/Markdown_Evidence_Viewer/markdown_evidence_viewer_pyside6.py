#!/usr/bin/env python
"""PySide6 desktop viewer for LNPDB-like rows and grouped source evidence."""

from __future__ import annotations

import argparse
import csv
import html
import re
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPoint, Qt, Signal
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


REQUIRED_FILES = [
    "unified_extraction_lnpdb_like.csv",
    "unified_extraction_source_evidence.csv",
    "unified_extraction_figure_evidence_map.csv",
]

SCIENTIFIC_COLUMNS = [
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
]
SCIENTIFIC_COLUMN_SET = set(SCIENTIFIC_COLUMNS)


@dataclass
class LoadedTables:
    lnpdb_like: pd.DataFrame
    source_evidence: pd.DataFrame
    figure_evidence_map: pd.DataFrame
    sentence_index: pd.DataFrame | None
    final: pd.DataFrame | None
    unified: pd.DataFrame | None


def read_csv_keep_blank(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig", keep_default_na=False, dtype=str)


def load_tables(paper_folder: Path) -> LoadedTables:
    missing = [paper_folder / name for name in REQUIRED_FILES if not (paper_folder / name).exists()]
    if missing:
        detail = "\n".join(str(path) for path in missing)
        raise FileNotFoundError(f"Required input file(s) missing:\n{detail}")

    final_path = paper_folder / "unified_extraction_final.csv"
    unified_path = paper_folder / "unified_extraction.csv"
    sentence_index_path = paper_folder / "markdown_sentence_index" / "markdown_sentence_index_all.csv"
    return LoadedTables(
        lnpdb_like=read_csv_keep_blank(paper_folder / "unified_extraction_lnpdb_like.csv"),
        source_evidence=read_csv_keep_blank(paper_folder / "unified_extraction_source_evidence.csv"),
        figure_evidence_map=read_csv_keep_blank(paper_folder / "unified_extraction_figure_evidence_map.csv"),
        sentence_index=read_csv_keep_blank(sentence_index_path) if sentence_index_path.exists() else None,
        final=read_csv_keep_blank(final_path) if final_path.exists() else None,
        unified=read_csv_keep_blank(unified_path) if unified_path.exists() else None,
    )


def split_list_field(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    separator = "|" if "|" in text else ";"
    return [part.strip() for part in text.split(separator) if part.strip()]


def resolve_path(path_text: Any, paper_folder: Path) -> Path | None:
    text = str(path_text or "").strip().strip('"')
    if not text:
        return None
    path = Path(text)
    if path.is_absolute():
        return path
    return paper_folder / path


def list_markdown_files(paper_folder: Path) -> list[Path]:
    skip_dirs = {
        ".git",
        "__pycache__",
        "Exp_Excel_Blocks",
        "Final_Panel_Splitting",
        "Panel_Splitting",
    }
    files: list[Path] = []
    for path in paper_folder.rglob("*.md"):
        if any(part in skip_dirs or part.startswith(".") for part in path.parts):
            continue
        files.append(path)
    return files


def strip_markdown_marks(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[[^\]]+\]\([^)]+\)", lambda m: m.group(0).split("]")[0].lstrip("["), text)
    text = re.sub(r"[`*_#>\-|]+", " ", text)
    return text


def normalize_text_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", strip_markdown_marks(text)).strip().casefold()


def read_text_fallback(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp949", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def context_slice(text: str, start: int, end: int, context_chars: int) -> str:
    left = max(0, start - context_chars)
    right = min(len(text), end + context_chars)
    return text[left:right]


def paragraph_chunks(text: str) -> list[tuple[int, int, str]]:
    chunks: list[tuple[int, int, str]] = []
    for match in re.finditer(r"(?s)(?:^|\n\s*\n)(.*?)(?=\n\s*\n|$)", text):
        chunk = match.group(1).strip()
        if chunk:
            chunks.append((match.start(1), match.end(1), chunk))
    return chunks


def find_markdown_context(
    evidence_text: str,
    markdown_files: list[Path],
    context_chars: int = 600,
) -> tuple[Path | None, str, str]:
    needle = str(evidence_text or "").strip()
    if not needle:
        return None, "", "No evidence text to search."

    needle_norm = normalize_text_for_match(needle)
    best: tuple[float, Path | None, str, str] = (0.0, None, "", "No markdown match found.")

    for md_path in markdown_files:
        try:
            text = read_text_fallback(md_path)
        except OSError:
            continue

        exact_pos = text.find(needle)
        if exact_pos >= 0:
            return md_path, context_slice(text, exact_pos, exact_pos + len(needle), context_chars), "exact"

        lower_pos = text.casefold().find(needle.casefold())
        if lower_pos >= 0:
            return md_path, context_slice(text, lower_pos, lower_pos + len(needle), context_chars), "case-insensitive"

        normalized = normalize_text_for_match(text)
        norm_pos = normalized.find(needle_norm)
        if norm_pos >= 0:
            # Normalized offsets do not map cleanly to original text; use the whole nearest-sized window.
            return md_path, text[: min(len(text), context_chars * 2)], "normalized-whitespace"

        for start, end, chunk in paragraph_chunks(text):
            chunk_norm = normalize_text_for_match(chunk)
            if not chunk_norm:
                continue
            score = SequenceMatcher(None, needle_norm, chunk_norm[: max(len(needle_norm) * 2, 200)]).ratio()
            if score > best[0]:
                best = (score, md_path, context_slice(text, start, end, context_chars), f"fuzzy score={score:.2f}")

    if best[0] >= 0.55:
        return best[1], best[2], best[3]
    return None, "", "No markdown match found."


def highlight_context_html(context: str, evidence_text: str) -> str:
    safe_context = html.escape(context or "")
    needle = str(evidence_text or "").strip()
    if not safe_context:
        return "<i>No markdown context found.</i>"
    if not needle:
        return f"<pre>{safe_context}</pre>"

    pattern = re.escape(html.escape(needle))
    highlighted = re.sub(
        pattern,
        lambda m: f'<span style="background-color:#fff59d;">{m.group(0)}</span>',
        safe_context,
        flags=re.IGNORECASE,
    )
    return f"<pre style='white-space:pre-wrap;'>{highlighted}</pre>"


class PandasTableModel(QAbstractTableModel):
    data_changed = Signal()

    def __init__(self, df: pd.DataFrame | None = None) -> None:
        super().__init__()
        self._df = df if df is not None else pd.DataFrame()

    def set_dataframe(self, df: pd.DataFrame) -> None:
        self.beginResetModel()
        self._df = df.copy()
        self.endResetModel()
        self.data_changed.emit()

    def dataframe(self) -> pd.DataFrame:
        return self._df

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._df)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._df.columns)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        if role in (Qt.DisplayRole, Qt.EditRole):
            return str(self._df.iat[index.row(), index.column()])
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return str(self._df.columns[section])
        return str(section + 1)


class MarkdownEvidenceViewer(QMainWindow):
    def __init__(self, initial_folder: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Markdown Evidence Viewer")
        self.resize(1500, 900)

        self.paper_folder: Path | None = None
        self.tables: LoadedTables | None = None
        self.markdown_files: list[Path] = []
        self.current_evidence_rows: list[dict[str, str]] = []

        self.table_model = PandasTableModel()
        self._build_ui()
        self._build_shortcuts()

        if initial_folder:
            self.folder_edit.setText(str(initial_folder))
            self.load_folder(initial_folder)

    def _build_ui(self) -> None:
        root_splitter = QSplitter(Qt.Horizontal)
        root_splitter.addWidget(self._build_left_panel())
        root_splitter.addWidget(self._build_right_panel())
        root_splitter.setSizes([850, 650])
        self.setCentralWidget(root_splitter)
        self.statusBar().showMessage("Select a paper folder.")

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Select paper folder containing unified_extraction_* CSV files")
        browse_button = QPushButton("Browse")
        reload_button = QPushButton("Reload")
        browse_button.clicked.connect(self.browse_folder)
        reload_button.clicked.connect(self.reload_folder)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(browse_button)
        folder_row.addWidget(reload_button)
        layout.addLayout(folder_row)

        filter_layout = QFormLayout()
        self.item_combo = QComboBox()
        self.method_combo = QComboBox()
        self.model_combo = QComboBox()
        self.target_combo = QComboBox()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search visible LNPDB-like row values")
        for combo in (self.item_combo, self.method_combo, self.model_combo, self.target_combo):
            combo.currentIndexChanged.connect(self.apply_filters)
        self.search_edit.textChanged.connect(self.apply_filters)
        filter_layout.addRow("Item_ID", self.item_combo)
        filter_layout.addRow("Experiment_method", self.method_combo)
        filter_layout.addRow("Model", self.model_combo)
        filter_layout.addRow("Model_target", self.target_combo)
        filter_layout.addRow("Text search", self.search_edit)
        layout.addLayout(filter_layout)

        view_row = QHBoxLayout()
        self.show_admin_checkbox = QCheckBox("Show admin/provenance columns")
        self.show_admin_checkbox.setChecked(False)
        self.show_admin_checkbox.stateChanged.connect(lambda _state: self.apply_filters())
        self.evidence_column_combo = QComboBox()
        self.evidence_column_combo.setMinimumWidth(220)
        show_evidence_button = QPushButton("Show Evidence for Selected Column")
        show_evidence_button.clicked.connect(self.show_evidence_for_selected_column)
        view_row.addWidget(self.show_admin_checkbox)
        view_row.addWidget(QLabel("Evidence column"))
        view_row.addWidget(self.evidence_column_combo)
        view_row.addWidget(show_evidence_button)
        layout.addLayout(view_row)

        self.lnpdb_table = QTableView()
        self.lnpdb_table.setModel(self.table_model)
        self.lnpdb_table.setSelectionBehavior(QTableView.SelectItems)
        self.lnpdb_table.setSelectionMode(QTableView.SingleSelection)
        self.lnpdb_table.setSortingEnabled(False)
        self.lnpdb_table.clicked.connect(self.on_cell_selected)
        self.lnpdb_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lnpdb_table.customContextMenuRequested.connect(self.show_table_context_menu)
        layout.addWidget(self.lnpdb_table, 1)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        self.summary_label = QLabel("No cell selected.")
        self.summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.sentence_index_status = QLabel("Sentence index: not loaded.")
        self.sentence_index_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.sentence_index_status.setWordWrap(True)
        layout.addWidget(self.sentence_index_status)

        copy_row = QHBoxLayout()
        copy_evidence_button = QPushButton("Copy Evidence Text")
        copy_source_button = QPushButton("Copy Source Path")
        copy_cell_button = QPushButton("Copy Cell ID")
        open_index_button = QPushButton("Open Indexed Markdown")
        copy_evidence_button.clicked.connect(self.copy_current_evidence_text)
        copy_source_button.clicked.connect(self.copy_current_source_path)
        copy_cell_button.clicked.connect(self.copy_current_cell_id)
        open_index_button.clicked.connect(self.show_selected_indexed_markdown)
        copy_row.addWidget(copy_evidence_button)
        copy_row.addWidget(copy_source_button)
        copy_row.addWidget(copy_cell_button)
        copy_row.addWidget(open_index_button)
        layout.addLayout(copy_row)

        self.evidence_list = QListWidget()
        self.evidence_list.currentRowChanged.connect(self.on_evidence_selected)
        layout.addWidget(QLabel("Matched evidence"))
        layout.addWidget(self.evidence_list, 1)

        tabs = QTabWidget()
        self.evidence_detail = QTextEdit()
        self.evidence_detail.setReadOnly(True)
        self.markdown_context = QTextBrowser()
        self.markdown_context.setOpenExternalLinks(False)
        self.source_preview = QWidget()
        self.source_preview_layout = QVBoxLayout(self.source_preview)
        self.source_path_label = QLabel("")
        self.source_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.image_label = QLabel("No image preview.")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumHeight(220)
        self.block_preview = QTableWidget()
        self.block_preview.setEditTriggers(QTableWidget.NoEditTriggers)
        self.source_preview_layout.addWidget(self.source_path_label)
        self.source_preview_layout.addWidget(self.image_label, 2)
        self.source_preview_layout.addWidget(self.block_preview, 3)
        tabs.addTab(self.evidence_detail, "Evidence Detail")
        tabs.addTab(self.markdown_context, "Markdown Context")
        tabs.addTab(self.source_preview, "Source Preview")
        layout.addWidget(tabs, 3)
        return panel

    def _build_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.browse_folder)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.reload_folder)

    def browse_folder(self) -> None:
        start_dir = self.folder_edit.text().strip() or str(Path.cwd())
        folder = QFileDialog.getExistingDirectory(self, "Select paper folder", start_dir)
        if folder:
            self.folder_edit.setText(folder)
            self.load_folder(Path(folder))

    def reload_folder(self) -> None:
        text = self.folder_edit.text().strip()
        if not text:
            QMessageBox.information(self, "No folder", "Select a paper folder first.")
            return
        self.load_folder(Path(text))

    def load_folder(self, paper_folder: Path) -> None:
        try:
            self.tables = load_tables(paper_folder)
        except Exception as exc:
            QMessageBox.critical(self, "Unable to load paper folder", str(exc))
            self.statusBar().showMessage("Load failed.")
            return

        self.paper_folder = paper_folder
        self.markdown_files = list_markdown_files(paper_folder)
        self.populate_filters()
        self.populate_evidence_column_selector()
        self.update_sentence_index_status()
        self.apply_filters()
        self.statusBar().showMessage(
            f"Loaded {len(self.tables.lnpdb_like)} rows, "
            f"{len(self.tables.source_evidence)} evidence rows, "
            f"{len(self.tables.figure_evidence_map)} map rows, "
            f"{len(self.markdown_files)} markdown files, "
            f"{0 if self.tables.sentence_index is None else len(self.tables.sentence_index)} indexed sentences."
        )

    def populate_filters(self) -> None:
        if not self.tables:
            return
        df = self.tables.lnpdb_like
        self._fill_combo(self.item_combo, df, "Item_ID")
        self._fill_combo(self.method_combo, df, "Experiment_method")
        self._fill_combo(self.model_combo, df, "Model")
        self._fill_combo(self.target_combo, df, "Model_target")

    def populate_evidence_column_selector(self) -> None:
        self.evidence_column_combo.blockSignals(True)
        self.evidence_column_combo.clear()
        if self.tables:
            columns = [col for col in SCIENTIFIC_COLUMNS if col in self.tables.lnpdb_like.columns]
            self.evidence_column_combo.addItems(columns)
            self.evidence_column_combo.setEnabled(bool(columns))
        else:
            self.evidence_column_combo.setEnabled(False)
        self.evidence_column_combo.blockSignals(False)

    def update_sentence_index_status(self) -> None:
        if not self.tables or self.tables.sentence_index is None:
            self.sentence_index_status.setText("Sentence index: not loaded. Fuzzy markdown search will be fallback only.")
            return
        sentence_index = self.tables.sentence_index
        source_ids = []
        if "source_md_id" in sentence_index.columns:
            source_ids = sorted({str(value).strip() for value in sentence_index["source_md_id"].tolist() if str(value).strip()})
        self.sentence_index_status.setText(
            "<b>Sentence index:</b> loaded | "
            f"<b>indexed sentences:</b> {len(sentence_index)} | "
            f"<b>sources:</b> {html.escape(', '.join(source_ids) if source_ids else '(none)')}"
        )

    def default_visible_columns(self, df: pd.DataFrame) -> list[str]:
        preferred = ["row_id", "Paper_ID", "Item_ID"] + SCIENTIFIC_COLUMNS
        return [col for col in preferred if col in df.columns]

    def visible_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.show_admin_checkbox.isChecked():
            return df
        columns = self.default_visible_columns(df)
        return df.loc[:, columns] if columns else df

    def _fill_combo(self, combo: QComboBox, df: pd.DataFrame, column: str) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("(All)")
        if column in df.columns:
            values = sorted({str(value).strip() for value in df[column].tolist() if str(value).strip()})
            combo.addItems(values)
            combo.setEnabled(True)
        else:
            combo.setEnabled(False)
        combo.blockSignals(False)

    def apply_filters(self) -> None:
        if not self.tables:
            return
        df = self.tables.lnpdb_like.copy()
        for combo, column in (
            (self.item_combo, "Item_ID"),
            (self.method_combo, "Experiment_method"),
            (self.model_combo, "Model"),
            (self.target_combo, "Model_target"),
        ):
            value = combo.currentText()
            if value and value != "(All)" and column in df.columns:
                df = df[df[column].astype(str) == value]

        query = self.search_edit.text().strip().casefold()
        if query and not df.empty:
            mask = df.apply(lambda row: query in " ".join(str(v) for v in row.values).casefold(), axis=1)
            df = df[mask]

        visible_df = self.visible_dataframe(df)
        self.table_model.set_dataframe(visible_df.reset_index(drop=True))
        self.lnpdb_table.resizeColumnsToContents()
        self.statusBar().showMessage(f"Showing {len(visible_df)} LNPDB-like rows and {len(visible_df.columns)} columns.")

    def on_cell_selected(self, index: QModelIndex) -> None:
        if not index.isValid() or not self.tables:
            return
        df = self.table_model.dataframe()
        row = df.iloc[index.row()].to_dict()
        clicked_column = str(df.columns[index.column()])
        column_name = clicked_column if clicked_column in SCIENTIFIC_COLUMN_SET else self.selected_evidence_column()
        row_id = str(row.get("row_id", "")).strip()
        item_id = str(row.get("Item_ID", "")).strip()
        cell_value = str(row.get(clicked_column, "")).strip()
        evidence_cell_value = str(row.get(column_name, "")).strip()

        self.summary_label.setText(
            f"<b>row_id:</b> {html.escape(row_id)}<br>"
            f"<b>Item_ID:</b> {html.escape(item_id)}<br>"
            f"<b>clicked_column:</b> {html.escape(clicked_column)}<br>"
            f"<b>clicked_value:</b> {html.escape(cell_value)}<br>"
            f"<b>evidence_column:</b> {html.escape(column_name)}<br>"
            f"<b>evidence_cell_value:</b> {html.escape(evidence_cell_value)}"
        )

        evidence_rows = self.find_evidence_for_cell(row_id, item_id, column_name)
        if not evidence_rows and clicked_column not in SCIENTIFIC_COLUMN_SET and not column_name:
            self.show_evidence([], "No evidence required for administrative/provenance column.")
        else:
            self.show_evidence(evidence_rows)

    def selected_evidence_column(self) -> str:
        column = self.evidence_column_combo.currentText().strip()
        return column if column in SCIENTIFIC_COLUMN_SET else ""

    def show_evidence_for_selected_column(self) -> None:
        index = self.lnpdb_table.currentIndex()
        if not index.isValid() or not self.tables:
            QMessageBox.information(self, "No row selected", "Select a row in the LNPDB-like table first.")
            return
        df = self.table_model.dataframe()
        row = df.iloc[index.row()].to_dict()
        column_name = self.selected_evidence_column()
        if not column_name:
            QMessageBox.information(self, "No scientific column", "No scientific evidence column is selected.")
            return
        row_id = str(row.get("row_id", "")).strip()
        item_id = str(row.get("Item_ID", "")).strip()
        cell_value = str(row.get(column_name, "")).strip()
        self.summary_label.setText(
            f"<b>row_id:</b> {html.escape(row_id)}<br>"
            f"<b>Item_ID:</b> {html.escape(item_id)}<br>"
            f"<b>evidence_column:</b> {html.escape(column_name)}<br>"
            f"<b>evidence_cell_value:</b> {html.escape(cell_value)}"
        )
        self.show_evidence(self.find_evidence_for_cell(row_id, item_id, column_name))

    def find_evidence_for_cell(self, row_id: str, item_id: str, column_name: str) -> list[dict[str, str]]:
        if not self.tables:
            return []
        fmap = self.tables.figure_evidence_map
        src = self.tables.source_evidence
        if "evidence_id" not in fmap.columns or "evidence_id" not in src.columns:
            return []

        matched_ids: list[str] = []
        for _, map_row in fmap.iterrows():
            if str(map_row.get("Item_ID", "")).strip() != item_id:
                continue
            supported_columns = split_list_field(map_row.get("supported_columns", ""))
            if column_name not in supported_columns:
                continue
            supported_row_ids = split_list_field(map_row.get("supported_row_ids", ""))
            support_scope = str(map_row.get("support_scope", "")).strip()
            row_match = (
                row_id in supported_row_ids
                or support_scope == "item_level_all_rows"
                or (not supported_row_ids and item_id)
            )
            if row_match:
                evidence_id = str(map_row.get("evidence_id", "")).strip()
                if evidence_id:
                    matched_ids.append(evidence_id)

        if not matched_ids:
            return []

        src_by_id = {str(row.get("evidence_id", "")).strip(): row.to_dict() for _, row in src.iterrows()}
        map_by_id = {
            str(row.get("evidence_id", "")).strip(): row.to_dict()
            for _, row in fmap.iterrows()
            if str(row.get("evidence_id", "")).strip() in matched_ids
        }
        rows: list[dict[str, str]] = []
        seen: set[str] = set()
        for evidence_id in matched_ids:
            if evidence_id in seen:
                continue
            seen.add(evidence_id)
            merged = {str(k): str(v) for k, v in src_by_id.get(evidence_id, {}).items()}
            for key, value in map_by_id.get(evidence_id, {}).items():
                if key not in merged or not merged[key]:
                    merged[key] = str(value)
                else:
                    merged[f"map_{key}"] = str(value)
            rows.append(merged)
        return rows

    def show_evidence(self, evidence_rows: list[dict[str, str]], message: str | None = None) -> None:
        self.current_evidence_rows = evidence_rows
        self.evidence_list.clear()
        if message:
            self.evidence_detail.setPlainText(message)
            self.markdown_context.setHtml(f"<i>{html.escape(message)}</i>")
            self.clear_preview()
            return
        if not evidence_rows:
            self.evidence_detail.setPlainText("No figure-level evidence matched this cell.")
            self.markdown_context.setHtml("<i>No evidence text to search.</i>")
            self.clear_preview()
            return

        for row in evidence_rows:
            label = (
                f"{row.get('evidence_id', '')} | "
                f"{row.get('support_scope') or row.get('map_support_scope', '')} | "
                f"{row.get('supported_columns') or row.get('map_supported_columns', '')} | "
                f"{row.get('confidence', '')}"
            )
            item = QListWidgetItem(label)
            self.evidence_list.addItem(item)
        self.evidence_list.setCurrentRow(0)

    def on_evidence_selected(self, row_index: int) -> None:
        if row_index < 0 or row_index >= len(self.current_evidence_rows):
            return
        row = self.current_evidence_rows[row_index]
        self.show_evidence_detail(row)
        self.show_markdown_context(row.get("evidence_text_exact", ""))
        self.preview_source(row)

    def show_evidence_detail(self, row: dict[str, str]) -> None:
        summary = row.get("evidence_summary") or row.get("map_evidence_summary", "")
        sentence_ids = row.get("evidence_sentence_ids") or row.get("map_evidence_sentence_ids", "")
        sentence_texts = row.get("evidence_sentence_texts", "")
        lines = []
        if summary:
            lines.append(f"EVIDENCE SUMMARY\n{summary}")
        if sentence_ids:
            lines.append(f"INDEXED SENTENCE IDS\n{sentence_ids}")
        if sentence_texts:
            lines.append(f"INDEXED SENTENCE TEXTS\n{sentence_texts}")
        fields = [
            "evidence_id",
            "evidence_text_exact",
            "evidence_source_type",
            "source_pdf",
            "source_page",
            "source_image",
            "evidence_excel",
            "excel_file",
            "excel_sheet",
            "block_id",
            "block_csv_path",
            "supported_columns",
            "supported_row_ids",
            "supported_formulation_ids",
            "support_scope",
            "confidence",
            "manual_required",
            "reason",
        ]
        for field in fields:
            value = row.get(field) or row.get(f"map_{field}", "")
            if value:
                lines.append(f"{field}: {value}")
        self.evidence_detail.setPlainText("\n\n".join(lines))

    def show_markdown_context(self, evidence_text: str) -> None:
        current_row = self.current_evidence_rows[self.evidence_list.currentRow()] if self.evidence_list.currentRow() >= 0 and self.current_evidence_rows else {}
        sentence_ids = current_row.get("evidence_sentence_ids") or current_row.get("map_evidence_sentence_ids", "")
        if sentence_ids:
            self.show_sentence_id_context(sentence_ids)
            return
        path, context, mode = find_markdown_context(evidence_text, self.markdown_files)
        title = f"<b>Fallback fuzzy markdown search only</b><br><b>Match:</b> {html.escape(mode)}"
        if path and self.paper_folder:
            try:
                rel = path.relative_to(self.paper_folder)
            except ValueError:
                rel = path
            title += f"<br><b>Markdown:</b> {html.escape(str(rel))}"
        self.markdown_context.setHtml(title + "<hr>" + highlight_context_html(context, evidence_text))

    def sentence_rows_for_ids(self, sentence_ids: str) -> list[dict[str, str]]:
        if not self.tables or self.tables.sentence_index is None or self.tables.sentence_index.empty:
            return []
        wanted = split_list_field(sentence_ids)
        if not wanted:
            return []
        index = {
            str(row.get("global_sentence_id", "")).strip(): row.to_dict()
            for _, row in self.tables.sentence_index.iterrows()
        }
        return [index[sentence_id] for sentence_id in wanted if sentence_id in index]

    def show_sentence_id_context(self, sentence_ids: str) -> None:
        rows = self.sentence_rows_for_ids(sentence_ids)
        if not rows:
            self.markdown_context.setHtml(
                "<b>Indexed sentence lookup</b><hr><i>Sentence IDs were present, but no matching rows were found in markdown_sentence_index_all.csv.</i>"
            )
            return
        grouped: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            grouped.setdefault(str(row.get("source_md_id", "")), []).append(row)
        parts = ["<b>Indexed sentence evidence</b><br><i>Using evidence_sentence_ids; no fuzzy full-sentence matching required.</i>"]
        for source_md_id, group_rows in grouped.items():
            source_rel = group_rows[0].get("source_md_relpath", "")
            parts.append(f"<h3>{html.escape(source_md_id)}</h3>")
            if source_rel:
                parts.append(f"<div><b>Source:</b> {html.escape(str(source_rel))}</div>")
            for row in group_rows:
                sentence_id = html.escape(str(row.get("sentence_id", "")))
                text = html.escape(str(row.get("sentence_text", "")))
                parts.append(f"<p><b>[{sentence_id}]</b> {text}</p>")
        self.markdown_context.setHtml("\n".join(parts))

    def show_selected_indexed_markdown(self) -> None:
        if self.evidence_list.currentRow() < 0 or not self.current_evidence_rows:
            return
        row = self.current_evidence_rows[self.evidence_list.currentRow()]
        sentence_ids = row.get("evidence_sentence_ids") or row.get("map_evidence_sentence_ids", "")
        if not sentence_ids:
            self.markdown_context.setHtml("<i>No evidence_sentence_ids available for this evidence row.</i>")
            return
        rows = self.sentence_rows_for_ids(sentence_ids)
        if not rows or not self.paper_folder:
            self.show_sentence_id_context(sentence_ids)
            return
        first = rows[0]
        source_md_id = str(first.get("source_md_id", ""))
        sentence_id = str(first.get("sentence_id", ""))
        indexed_md = self.paper_folder / "markdown_sentence_index" / f"{source_md_id}.sentences.md"
        if not indexed_md.exists():
            self.show_sentence_id_context(sentence_ids)
            return
        text = read_text_fallback(indexed_md)
        marker = f"[{sentence_id}]"
        pos = text.find(marker)
        context = context_slice(text, pos if pos >= 0 else 0, (pos + len(marker)) if pos >= 0 else 0, 1200)
        safe = html.escape(context)
        safe = safe.replace(html.escape(marker), f'<span style="background-color:#fff59d;">{html.escape(marker)}</span>')
        all_ids_html = "<br>".join(html.escape(sentence_id) for sentence_id in split_list_field(sentence_ids))
        self.markdown_context.setHtml(
            f"<b>Indexed Markdown:</b> {html.escape(str(indexed_md))}<br>"
            f"<b>All evidence_sentence_ids:</b><br>{all_ids_html}<hr>"
            f"<pre style='white-space:pre-wrap;'>{safe}</pre>"
        )

    def preview_source(self, row: dict[str, str]) -> None:
        self.clear_preview()
        if not self.paper_folder:
            return

        source_image = resolve_path(row.get("source_image", ""), self.paper_folder)
        block_csv = resolve_path(row.get("block_csv_path", ""), self.paper_folder)
        source_pdf = resolve_path(row.get("source_pdf", ""), self.paper_folder)
        source_page = row.get("source_page", "") or row.get("pdf_page_index", "")

        path_lines = []
        if source_pdf:
            path_lines.append(f"PDF: {source_pdf}")
            if source_page:
                path_lines.append(f"Page: {source_page}")
        if source_image:
            path_lines.append(f"Image: {source_image}")
        if block_csv:
            path_lines.append(f"Block CSV: {block_csv}")
        self.source_path_label.setText("\n".join(path_lines) if path_lines else "No source path fields.")

        if source_image and source_image.exists():
            self.preview_source_image(source_image)
        elif source_image:
            self.image_label.setText(f"Image not found:\n{source_image}")

        if block_csv and block_csv.exists():
            self.preview_block_csv(block_csv)
        elif block_csv:
            self.block_preview.setRowCount(0)
            self.block_preview.setColumnCount(1)
            self.block_preview.setHorizontalHeaderLabels(["Missing block CSV"])
            self.block_preview.setRowCount(1)
            self.block_preview.setItem(0, 0, QTableWidgetItem(str(block_csv)))

    def preview_source_image(self, path: Path) -> None:
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.image_label.setText(f"Unable to load image:\n{path}")
            return
        scaled = pixmap.scaled(620, 360, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled)
        self.image_label.setToolTip(str(path))

    def preview_block_csv(self, path: Path, max_rows: int = 25, max_cols: int = 12) -> None:
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.reader(fh))
        except UnicodeDecodeError:
            with path.open("r", encoding="cp949", newline="") as fh:
                rows = list(csv.reader(fh))
        except OSError as exc:
            self.block_preview.setRowCount(1)
            self.block_preview.setColumnCount(1)
            self.block_preview.setItem(0, 0, QTableWidgetItem(str(exc)))
            return

        rows = rows[:max_rows]
        col_count = min(max((len(row) for row in rows), default=1), max_cols)
        self.block_preview.setColumnCount(col_count)
        self.block_preview.setRowCount(len(rows))
        for r, csv_row in enumerate(rows):
            for c in range(col_count):
                self.block_preview.setItem(r, c, QTableWidgetItem(csv_row[c] if c < len(csv_row) else ""))
        self.block_preview.resizeColumnsToContents()

    def clear_preview(self) -> None:
        self.source_path_label.setText("")
        self.image_label.clear()
        self.image_label.setText("No image preview.")
        self.block_preview.setRowCount(0)
        self.block_preview.setColumnCount(0)

    def current_selected_table_cell(self) -> tuple[str, str] | None:
        index = self.lnpdb_table.currentIndex()
        if not index.isValid():
            return None
        df = self.table_model.dataframe()
        row = df.iloc[index.row()].to_dict()
        column = str(df.columns[index.column()])
        return str(row.get("row_id", "")), column

    def show_table_context_menu(self, position: QPoint) -> None:
        index = self.lnpdb_table.indexAt(position)
        if not index.isValid():
            return
        menu = QMenu(self)
        copy_cell_action = QAction("Copy cell value", self)
        copy_id_action = QAction("Copy row_id/column_name", self)
        copy_cell_action.triggered.connect(lambda: QGuiApplication.clipboard().setText(str(index.data() or "")))
        copy_id_action.triggered.connect(self.copy_current_cell_id)
        menu.addAction(copy_cell_action)
        menu.addAction(copy_id_action)
        menu.exec(self.lnpdb_table.viewport().mapToGlobal(position))

    def copy_current_evidence_text(self) -> None:
        row = self.current_evidence_rows[self.evidence_list.currentRow()] if self.evidence_list.currentRow() >= 0 and self.current_evidence_rows else {}
        QGuiApplication.clipboard().setText(str(row.get("evidence_text_exact", "")))

    def copy_current_source_path(self) -> None:
        row = self.current_evidence_rows[self.evidence_list.currentRow()] if self.evidence_list.currentRow() >= 0 and self.current_evidence_rows else {}
        values = [row.get(key, "") for key in ("source_pdf", "source_image", "block_csv_path", "evidence_excel")]
        QGuiApplication.clipboard().setText("\n".join(str(value) for value in values if value))

    def copy_current_cell_id(self) -> None:
        cell = self.current_selected_table_cell()
        if not cell:
            return
        row_id, column = cell
        QGuiApplication.clipboard().setText(f"{row_id}\t{column}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PySide6 desktop Markdown evidence viewer.")
    parser.add_argument("--paper-folder", type=Path, default=None, help="Optional paper folder to load at startup.")
    parser.add_argument("--self-check", action="store_true", help="Check imports and optional paper-folder CSV loading, then exit without opening the GUI.")
    return parser.parse_args(argv)


def self_check(paper_folder: Path | None = None) -> int:
    print("PySide6 Markdown Evidence Viewer imports OK.")
    if not paper_folder:
        return 0
    tables = load_tables(paper_folder)
    print(f"lnpdb_like_rows={len(tables.lnpdb_like)}")
    print(f"source_evidence_rows={len(tables.source_evidence)}")
    print(f"figure_evidence_map_rows={len(tables.figure_evidence_map)}")
    print(f"markdown_sentence_index_rows={0 if tables.sentence_index is None else len(tables.sentence_index)}")
    if tables.sentence_index is not None and "source_md_id" in tables.sentence_index.columns:
        counts = tables.sentence_index["source_md_id"].value_counts().to_dict()
        print("source_md_id_counts=" + ";".join(f"{key}:{value}" for key, value in counts.items()))
    if tables.lnpdb_like.empty:
        print("warning=lnpdb_like_empty")
        return 0

    row_id = ""
    item_id = ""
    column_name = ""
    matches = 0
    for _, sample_row in tables.lnpdb_like.iterrows():
        sample = sample_row.to_dict()
        row_id = str(sample.get("row_id", "")).strip()
        item_id = str(sample.get("Item_ID", "")).strip()
        for _, map_row in tables.figure_evidence_map.iterrows():
            if str(map_row.get("Item_ID", "")).strip() != item_id:
                continue
            supported_row_ids = split_list_field(map_row.get("supported_row_ids", ""))
            support_scope = str(map_row.get("support_scope", "")).strip()
            row_matches = row_id in supported_row_ids or support_scope == "item_level_all_rows" or (not supported_row_ids and item_id)
            if not row_matches:
                continue
            for candidate in split_list_field(map_row.get("supported_columns", "")):
                if candidate in tables.lnpdb_like.columns and str(sample.get(candidate, "")).strip():
                    column_name = candidate
                    break
            if column_name:
                break
        if column_name:
            break

    if column_name:
        for _, map_row in tables.figure_evidence_map.iterrows():
            if str(map_row.get("Item_ID", "")).strip() != item_id:
                continue
            if column_name not in split_list_field(map_row.get("supported_columns", "")):
                continue
            supported_row_ids = split_list_field(map_row.get("supported_row_ids", ""))
            support_scope = str(map_row.get("support_scope", "")).strip()
            if row_id in supported_row_ids or support_scope == "item_level_all_rows" or (not supported_row_ids and item_id):
                matches += 1
    print(f"sample_cell={row_id}|{item_id}|{column_name}")
    print(f"sample_evidence_matches={matches}")
    sample_sentence_id_matches = 0
    if column_name:
        for _, map_row in tables.figure_evidence_map.iterrows():
            if str(map_row.get("Item_ID", "")).strip() != item_id:
                continue
            if column_name not in split_list_field(map_row.get("supported_columns", "")):
                continue
            supported_row_ids = split_list_field(map_row.get("supported_row_ids", ""))
            support_scope = str(map_row.get("support_scope", "")).strip()
            if row_id in supported_row_ids or support_scope == "item_level_all_rows" or (not supported_row_ids and item_id):
                if split_list_field(map_row.get("evidence_sentence_ids", "")):
                    sample_sentence_id_matches += 1
    print(f"sample_evidence_with_sentence_ids={sample_sentence_id_matches}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.self_check:
        return self_check(args.paper_folder)
    app = QApplication(sys.argv)
    window = MarkdownEvidenceViewer(args.paper_folder)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
