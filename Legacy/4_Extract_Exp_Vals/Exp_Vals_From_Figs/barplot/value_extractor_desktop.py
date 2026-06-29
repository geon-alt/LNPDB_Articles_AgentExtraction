from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from PySide6 import QtCore, QtGui, QtWidgets

    PYSIDE6_AVAILABLE = True
    PYSIDE6_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - environment dependent
    QtCore = None
    QtGui = None
    QtWidgets = None
    PYSIDE6_AVAILABLE = False
    PYSIDE6_IMPORT_ERROR = str(exc)

try:
    import cv2
except Exception:  # pragma: no cover - optional runtime dependency check
    cv2 = None

try:
    import value_extractor_core as core
except Exception:
    CURRENT_DIR = Path(__file__).resolve().parent
    if str(CURRENT_DIR) not in sys.path:
        sys.path.insert(0, str(CURRENT_DIR))
    import value_extractor_core as core


WINDOWS: list[Any] = []


if PYSIDE6_AVAILABLE:

    class DataFrameTableModel(QtCore.QAbstractTableModel):
        def __init__(self, dataframe: pd.DataFrame | None = None, parent=None):
            super().__init__(parent)
            self._df = dataframe.copy() if dataframe is not None else pd.DataFrame()

        def dataframe(self) -> pd.DataFrame:
            return self._df.copy()

        def set_dataframe(self, dataframe: pd.DataFrame) -> None:
            self.beginResetModel()
            self._df = dataframe.copy().reset_index(drop=True)
            self.endResetModel()

        def rowCount(self, parent=QtCore.QModelIndex()):
            return 0 if parent.isValid() else len(self._df)

        def columnCount(self, parent=QtCore.QModelIndex()):
            return 0 if parent.isValid() else len(self._df.columns)

        def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
            if role != QtCore.Qt.DisplayRole:
                return None
            if orientation == QtCore.Qt.Horizontal:
                if 0 <= section < len(self._df.columns):
                    return str(self._df.columns[section])
            return str(section)

        def data(self, index, role=QtCore.Qt.DisplayRole):
            if not index.isValid():
                return None
            value = self._df.iat[index.row(), index.column()]
            col_name = self._df.columns[index.column()]
            if role == QtCore.Qt.CheckStateRole and col_name == "selected":
                return QtCore.Qt.Checked if core.is_true(value) else QtCore.Qt.Unchecked
            if role in (QtCore.Qt.DisplayRole, QtCore.Qt.EditRole):
                if pd.isna(value):
                    return ""
                return str(value)
            return None

        def flags(self, index):
            if not index.isValid():
                return QtCore.Qt.ItemIsEnabled
            flags = QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsEditable
            if self._df.columns[index.column()] == "selected":
                flags |= QtCore.Qt.ItemIsUserCheckable
            return flags

        def setData(self, index, value, role=QtCore.Qt.EditRole):
            if not index.isValid():
                return False
            row = index.row()
            col = self._df.columns[index.column()]
            if role == QtCore.Qt.CheckStateRole and col == "selected":
                self._df.at[row, col] = value == QtCore.Qt.Checked
            elif role == QtCore.Qt.EditRole:
                self._df.at[row, col] = self._coerce_value(col, value)
            else:
                return False
            self.dataChanged.emit(index, index, [role])
            return True

        @staticmethod
        def _coerce_value(column: str, value: Any):
            text = str(value).strip()
            if text == "":
                return pd.NA
            if column in {"Pixel", "Value", "x_pixel", "y_pixel"}:
                numeric = pd.to_numeric(pd.Series([text]), errors="coerce").iloc[0]
                return pd.NA if pd.isna(numeric) else numeric
            if column == "selected":
                return text.lower() in {"true", "1", "yes", "y"}
            return text


    class PixelNudgeTableView(QtWidgets.QTableView):
        commandRequested = QtCore.Signal(str)
        focusEntered = QtCore.Signal()

        def focusInEvent(self, event):
            self.focusEntered.emit()
            return super().focusInEvent(event)

        def keyPressEvent(self, event):
            if self.state() == QtWidgets.QAbstractItemView.EditingState:
                return super().keyPressEvent(event)
            key_map = {
                QtCore.Qt.Key_Left: "left",
                QtCore.Qt.Key_Right: "right",
                QtCore.Qt.Key_Up: "up",
                QtCore.Qt.Key_Down: "down",
                QtCore.Qt.Key_A: "left",
                QtCore.Qt.Key_D: "right",
                QtCore.Qt.Key_Q: "row_up",
                QtCore.Qt.Key_E: "row_down",
                QtCore.Qt.Key_W: "up",
                QtCore.Qt.Key_S: "down",
                QtCore.Qt.Key_Space: "apply",
            }
            command = key_map.get(event.key())
            if command is not None and self.currentIndex().isValid():
                self.commandRequested.emit(command)
                event.accept()
                return
            return super().keyPressEvent(event)


    class ImageView(QtWidgets.QGraphicsView):
        imageClicked = QtCore.Signal(int, int)

        def __init__(self, parent=None):
            super().__init__(parent)
            self._scene = QtWidgets.QGraphicsScene(self)
            self._pixmap_item = None
            self._overlay_items: list[QtWidgets.QGraphicsItem] = []
            self._zoom = 1.0
            self.show_extracted_labels = False
            self.show_last_click_label = False
            self.setFocusPolicy(QtCore.Qt.NoFocus)
            self.setScene(self._scene)
            self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
            self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
            self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
            self.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)

        def set_image_cv(self, image_cv) -> None:
            self._scene.clear()
            self._pixmap_item = None
            self._overlay_items = []
            self.resetTransform()
            self._zoom = 1.0
            if image_cv is None:
                return
            if cv2 is None:
                raise RuntimeError("OpenCV(cv2)가 필요합니다.")
            rgb = cv2.cvtColor(image_cv, cv2.COLOR_BGR2RGB)
            h, w, channels = rgb.shape
            bytes_per_line = channels * w
            qimage = QtGui.QImage(rgb.data, w, h, bytes_per_line, QtGui.QImage.Format_RGB888).copy()
            pixmap = QtGui.QPixmap.fromImage(qimage)
            self._pixmap_item = self._scene.addPixmap(pixmap)
            self._scene.setSceneRect(QtCore.QRectF(0, 0, w, h))
            self.fitInView(self._scene.sceneRect(), QtCore.Qt.KeepAspectRatio)

        def recenter_image(self) -> None:
            if self._pixmap_item is None:
                return
            self.resetTransform()
            self._zoom = 1.0
            self.fitInView(self._scene.sceneRect(), QtCore.Qt.KeepAspectRatio)

        def current_pixmap(self) -> QtGui.QPixmap | None:
            if self._pixmap_item is None:
                return None
            pixmap = self._pixmap_item.pixmap()
            if pixmap.isNull():
                return None
            return QtGui.QPixmap(pixmap)

        def clear_overlays(self) -> None:
            for item in list(self._overlay_items):
                if item.scene() is self._scene:
                    self._scene.removeItem(item)
            self._overlay_items = []

        def _track_overlay(self, item):
            item.setZValue(10)
            self._overlay_items.append(item)
            return item

        def _qcolor(self, color, alpha=None):
            qcolor = QtGui.QColor(color)
            if alpha is not None:
                qcolor.setAlpha(int(alpha))
            return qcolor

        def add_line(self, x1, y1, x2, y2, color, width=1.5, style=QtCore.Qt.SolidLine):
            pen = QtGui.QPen(self._qcolor(color))
            pen.setWidthF(float(width))
            pen.setStyle(style)
            return self._track_overlay(self._scene.addLine(float(x1), float(y1), float(x2), float(y2), pen))

        def add_marker(self, x, y, color="#00a85a", radius=5.0, width=2.0, cross=True, alpha=None, brush_alpha=0):
            x = float(x)
            y = float(y)
            radius = float(radius)
            qcolor = self._qcolor(color, alpha)
            pen = QtGui.QPen(qcolor)
            pen.setWidthF(float(width))
            if brush_alpha and brush_alpha > 0:
                fill_color = QtGui.QColor(qcolor)
                fill_color.setAlpha(int(brush_alpha))
                brush = QtGui.QBrush(fill_color)
            else:
                brush = QtGui.QBrush(QtCore.Qt.NoBrush)
            ellipse = self._track_overlay(self._scene.addEllipse(x - radius, y - radius, radius * 2, radius * 2, pen, brush))
            if cross:
                self.add_line(x - radius * 1.5, y, x + radius * 1.5, y, qcolor, width)
                self.add_line(x, y - radius * 1.5, x, y + radius * 1.5, qcolor, width)
            return ellipse

        def add_text(self, x, y, text, color="#222222", point_size=8):
            if text is None or str(text).strip() == "":
                return None
            item = QtWidgets.QGraphicsTextItem(str(text))
            item.setDefaultTextColor(QtGui.QColor(color))
            font = QtGui.QFont()
            font.setPointSize(int(point_size))
            item.setFont(font)
            item.setPos(float(x), float(y))
            item.setZValue(11)
            self._scene.addItem(item)
            self._overlay_items.append(item)
            return item

        def update_overlays(self, state: core.AppState, current_calib_row=None, current_extracted_row=None) -> None:
            self.clear_overlays()
            if self._pixmap_item is None or state is None or state.image_cv is None:
                return

            rect = self._scene.sceneRect()
            width = rect.width()
            height = rect.height()

            axis_x = core.to_float_or_none(getattr(state, "y_axis_x", None))
            baseline_y = core.to_float_or_none(getattr(state, "baseline_y", None))
            y_max_pixel = core.to_float_or_none(getattr(state, "y_max_pixel", None))
            if axis_x is not None:
                self.add_line(axis_x, 0, axis_x, height, "#d62828", 2.0)
                self.add_text(axis_x + 4, 4, f"axis x={axis_x:g}", "#d62828", 8)
            if baseline_y is not None:
                self.add_line(0, baseline_y, width, baseline_y, "#e85d04", 2.2)
                self.add_text(6, baseline_y + 2, f"baseline y={baseline_y:g}", "#e85d04", 8)
            if y_max_pixel is not None:
                self.add_line(0, y_max_pixel, width, y_max_pixel, "#f48c06", 1.8, QtCore.Qt.DashLine)
                self.add_text(6, y_max_pixel + 2, f"y_max_pixel={y_max_pixel:g}", "#f48c06", 8)

            calibration_df = core.ensure_calibration_columns(getattr(state, "df_calibration", None))
            is_horizontal = "Horizontal" in str(getattr(state, "orientation", ""))
            for row_idx, row in calibration_df.iterrows():
                pixel = core.to_float_or_none(row.get("Pixel"))
                if pixel is None:
                    continue
                kind = str(row.get("kind", core.CALIBRATION_KIND_Y_TICK)).strip()
                selected = core.is_true(row.get("selected")) or row_idx == current_calib_row
                if kind == core.CALIBRATION_KIND_Y_AXIS:
                    color = "#b5179e" if not selected else "#7b2cbf"
                    line_width = 1.2 if not selected else 2.6
                    self.add_line(pixel, 0, pixel, height, color, line_width, QtCore.Qt.DashDotLine)
                    self.add_text(pixel + 4, 36 if selected else 22, "y_axis", color, 8 if not selected else 9)
                elif kind == core.CALIBRATION_KIND_BASELINE:
                    color = "#e85d04" if not selected else "#dc2f02"
                    line_width = 1.4 if not selected else 2.8
                    self.add_line(0, pixel, width, pixel, color, line_width, QtCore.Qt.DashDotLine)
                    self.add_text(8, pixel + 4, "baseline", color, 8 if not selected else 9)
                elif kind == core.CALIBRATION_KIND_Y_MAX:
                    color = "#f48c06" if not selected else "#f77f00"
                    line_width = 1.4 if not selected else 2.8
                    self.add_line(0, pixel, width, pixel, color, line_width, QtCore.Qt.DashDotLine)
                    self.add_text(8, pixel + 4, "y_max", color, 8 if not selected else 9)
                else:
                    color = "#0057d8" if not selected else "#003b95"
                    line_width = 1.4 if not selected else 3.2
                    value = row.get("Value")
                    label = "" if pd.isna(value) else str(value)
                    if is_horizontal:
                        self.add_line(pixel, 0, pixel, height, color, line_width, QtCore.Qt.DashLine)
                        self.add_text(pixel + 4, 14 if not selected else 28, label, color, 8 if not selected else 9)
                    else:
                        self.add_line(0, pixel, width, pixel, color, line_width, QtCore.Qt.DashLine)
                        self.add_text(8, pixel - 16 if selected else pixel + 2, label, color, 8 if not selected else 9)

            extracted_df = core.ensure_extracted_columns(getattr(state, "df_extracted", None))
            for row_idx, row in extracted_df.iterrows():
                x_pixel = core.to_float_or_none(row.get("x_pixel"))
                y_pixel = core.to_float_or_none(row.get("y_pixel"))
                if x_pixel is None or y_pixel is None:
                    continue
                selected = core.is_true(row.get("selected")) or row_idx == current_extracted_row
                color = "#198754" if not selected else "#00bcd4"
                radius = 3.0 if not selected else 5.0
                line_width = 1.0 if not selected else 1.4
                alpha = 85 if not selected else 125
                brush_alpha = 18 if not selected else 28
                self.add_marker(
                    x_pixel,
                    y_pixel,
                    color=color,
                    radius=radius,
                    width=line_width,
                    cross=True,
                    alpha=alpha,
                    brush_alpha=brush_alpha,
                )
                if self.show_extracted_labels:
                    label_parts = []
                    for key in ("X_Label", "Group", "Value"):
                        value = row.get(key)
                        if value is not None and not pd.isna(value) and str(value).strip():
                            label_parts.append(str(value).strip())
                    if label_parts:
                        self.add_text(x_pixel + 8, y_pixel + 4, " / ".join(label_parts[:3]), color, 8 if not selected else 9)

            click_x = core.to_float_or_none(getattr(state, "last_click_x", None))
            click_y = core.to_float_or_none(getattr(state, "last_click_y", None))
            if click_x is not None and click_y is not None:
                self.add_marker(
                    click_x,
                    click_y,
                    color="#c218ff",
                    radius=6.0,
                    width=1.1,
                    cross=True,
                    alpha=110,
                    brush_alpha=0,
                )
                if self.show_last_click_label:
                    self.add_text(click_x + 10, click_y - 18, f"click ({int(click_x)}, {int(click_y)})", "#c218ff", 9)

        def wheelEvent(self, event):
            if self._pixmap_item is None:
                return super().wheelEvent(event)
            factor = 1.25 if event.angleDelta().y() > 0 else 0.8
            self._zoom *= factor
            self.scale(factor, factor)

        def mousePressEvent(self, event):
            if event.button() == QtCore.Qt.LeftButton and self._pixmap_item is not None:
                scene_pos = self.mapToScene(event.position().toPoint())
                rect = self._scene.sceneRect()
                if rect.contains(scene_pos):
                    self.imageClicked.emit(int(round(scene_pos.x())), int(round(scene_pos.y())))
            super().mousePressEvent(event)


    class GeminiWorker(QtCore.QThread):
        finishedWithState = QtCore.Signal(object)
        failed = QtCore.Signal(str)
        message = QtCore.Signal(str)

        def __init__(self, mode: str, state: core.AppState, parent=None):
            super().__init__(parent)
            self.mode = mode
            self.state = state

        def run(self):
            try:
                if self.mode == "first_pass":
                    result = core.run_first_pass_analysis(self.state)
                elif self.mode == "autonomous":
                    result = core.run_autonomous_extraction(self.state, status_callback=self.message.emit)
                else:
                    raise ValueError(f"Unknown worker mode: {self.mode}")
                self.finishedWithState.emit(result)
            except Exception as exc:
                self.failed.emit(core.traceback_to_string(exc))


    class MainWindow(QtWidgets.QMainWindow):
        def __init__(self, state: core.AppState | None = None):
            super().__init__()
            self.state = state or core.AppState()
            self.worker: GeminiWorker | None = None
            self.last_click: tuple[int, int] | None = None
            self.active_pixel_table: str | None = None
            self.figure_boss_window = None
            self._updating_ui = False
            self.setWindowTitle("LNPDB Plot Extractor Desktop")
            self.resize(1500, 900)
            self._build_ui()
            self._refresh_all()

        def _build_ui(self):
            self._build_menu()
            central = QtWidgets.QWidget()
            self.setCentralWidget(central)
            root_layout = QtWidgets.QVBoxLayout(central)

            top_bar = QtWidgets.QHBoxLayout()
            self.open_btn = QtWidgets.QPushButton("이미지 열기")
            self.recenter_btn = QtWidgets.QPushButton("이미지 중앙/맞춤")
            self.new_window_btn = QtWidgets.QPushButton("새 창 열기")
            self.save_csv_btn = QtWidgets.QPushButton("CSV 저장")
            self.status_label = QtWidgets.QLabel("Ready")
            self.status_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            top_bar.addWidget(self.open_btn)
            top_bar.addWidget(self.recenter_btn)
            top_bar.addWidget(self.new_window_btn)
            top_bar.addWidget(self.save_csv_btn)
            top_bar.addWidget(self.status_label, 1)
            root_layout.addLayout(top_bar)

            splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
            root_layout.addWidget(splitter, 1)

            left_panel = QtWidgets.QWidget()
            left_layout = QtWidgets.QVBoxLayout(left_panel)
            splitter.addWidget(left_panel)

            form = QtWidgets.QFormLayout()
            self.figure_name_edit = QtWidgets.QLineEdit()
            self.orientation_combo = QtWidgets.QComboBox()
            self.orientation_combo.addItems(["Vertical (세로형)", "Horizontal (가로형)"])
            self.log_scale_check = QtWidgets.QCheckBox("Log scale")
            self.x_labels_edit = QtWidgets.QPlainTextEdit()
            self.x_labels_edit.setPlaceholderText("comma-separated labels")
            self.x_labels_edit.setMaximumHeight(90)
            self.groups_edit = QtWidgets.QPlainTextEdit()
            self.groups_edit.setPlaceholderText("comma-separated groups")
            self.groups_edit.setMaximumHeight(90)
            form.addRow("figure_name", self.figure_name_edit)
            form.addRow("orientation", self.orientation_combo)
            form.addRow("", self.log_scale_check)
            form.addRow("x_labels_input", self.x_labels_edit)
            form.addRow("groups_input", self.groups_edit)
            left_layout.addLayout(form)

            self.first_pass_btn = QtWidgets.QPushButton("Gemini 1차 자동 분석")
            self.autonomous_btn = QtWidgets.QPushButton("Gemini 2차 정밀 자율 추출")
            self.generate_labels_btn = QtWidgets.QPushButton("라벨 표 자동 생성")
            self.apply_click_btn = QtWidgets.QPushButton("클릭 좌표를 선택 행에 적용")
            self.insert_row_btn = QtWidgets.QPushButton("선택 행 아래 삽입")
            self.delete_row_btn = QtWidgets.QPushButton("선택 행 삭제")
            for button in [
                self.first_pass_btn,
                self.autonomous_btn,
                self.generate_labels_btn,
                self.apply_click_btn,
                self.insert_row_btn,
                self.delete_row_btn,
            ]:
                left_layout.addWidget(button)
            help_label = QtWidgets.QLabel(
                "Calibration row: Space=apply last click, Q/E=prev/next row, W/S or ↑/↓=move y, A/D or ←/→=move x for y_axis\n"
                "Extracted row: Space=apply last click, Q/E=prev/next row, WASD/arrows=nudge point"
            )
            help_label.setWordWrap(True)
            help_label.setStyleSheet("color: #555;")
            left_layout.addWidget(help_label)
            left_layout.addStretch(1)

            self.image_view = ImageView()
            splitter.addWidget(self.image_view)

            right_panel = QtWidgets.QWidget()
            right_layout = QtWidgets.QVBoxLayout(right_panel)
            splitter.addWidget(right_panel)

            right_layout.addWidget(QtWidgets.QLabel("Calibration table"))
            self.calibration_table = PixelNudgeTableView()
            self.calibration_model = DataFrameTableModel(core.create_default_calibration_dataframe())
            self.calibration_table.setModel(self.calibration_model)
            self.calibration_table.horizontalHeader().setStretchLastSection(True)
            right_layout.addWidget(self.calibration_table, 1)

            calib_buttons = QtWidgets.QHBoxLayout()
            self.insert_calib_btn = QtWidgets.QPushButton("캘리브레이션 행 삽입")
            self.delete_calib_btn = QtWidgets.QPushButton("캘리브레이션 행 삭제")
            calib_buttons.addWidget(self.insert_calib_btn)
            calib_buttons.addWidget(self.delete_calib_btn)
            right_layout.addLayout(calib_buttons)

            right_layout.addWidget(QtWidgets.QLabel("Extracted value table"))
            self.extracted_table = PixelNudgeTableView()
            self.extracted_model = DataFrameTableModel(core.create_empty_extracted_dataframe())
            self.extracted_table.setModel(self.extracted_model)
            self.extracted_table.horizontalHeader().setStretchLastSection(True)
            right_layout.addWidget(self.extracted_table, 2)

            splitter.setSizes([320, 760, 560])

            self.open_btn.clicked.connect(self.open_image)
            self.recenter_btn.clicked.connect(self.recenter_image)
            self.new_window_btn.clicked.connect(self.new_window)
            self.save_csv_btn.clicked.connect(self.save_csv)
            self.first_pass_btn.clicked.connect(lambda: self.start_worker("first_pass"))
            self.autonomous_btn.clicked.connect(lambda: self.start_worker("autonomous"))
            self.generate_labels_btn.clicked.connect(self.generate_label_table)
            self.apply_click_btn.clicked.connect(self.apply_last_click)
            self.insert_row_btn.clicked.connect(self.insert_extracted_row)
            self.delete_row_btn.clicked.connect(self.delete_extracted_row)
            self.insert_calib_btn.clicked.connect(self.insert_calibration_row)
            self.delete_calib_btn.clicked.connect(self.delete_calibration_row)
            self.image_view.imageClicked.connect(self.record_click)
            self.orientation_combo.currentTextChanged.connect(lambda *_: self.refresh_overlay(commit=True))
            self.log_scale_check.stateChanged.connect(lambda *_: self.refresh_overlay(commit=True))
            self.calibration_model.dataChanged.connect(lambda *_: self.on_calibration_model_changed())
            self.extracted_model.dataChanged.connect(lambda *_: self.on_extracted_model_changed())
            self.calibration_table.selectionModel().selectionChanged.connect(
                lambda *_: self.on_pixel_table_activated("calibration")
            )
            self.extracted_table.selectionModel().selectionChanged.connect(
                lambda *_: self.on_pixel_table_activated("extracted")
            )
            self.calibration_table.clicked.connect(lambda *_: self.on_pixel_table_activated("calibration"))
            self.extracted_table.clicked.connect(lambda *_: self.on_pixel_table_activated("extracted"))
            self.calibration_table.focusEntered.connect(lambda: self.on_pixel_table_activated("calibration"))
            self.extracted_table.focusEntered.connect(lambda: self.on_pixel_table_activated("extracted"))
            self.calibration_table.commandRequested.connect(self.handle_calibration_table_command)
            self.extracted_table.commandRequested.connect(self.handle_extracted_table_command)

        def _build_menu(self) -> None:
            help_menu = self.menuBar().addMenu("Help")
            self.figure_boss_action = QtGui.QAction("Figure Boss", self)
            self.figure_boss_action.setShortcut(QtGui.QKeySequence("Ctrl+Shift+B"))
            self.figure_boss_action.setStatusTip("Launch the hidden Figure Boss Battle mini-game")
            self.figure_boss_action.triggered.connect(self.launch_figure_boss_easter_egg)
            help_menu.addAction(self.figure_boss_action)

        def _commit_widgets_to_state(self) -> None:
            self.state.figure_name = self.figure_name_edit.text().strip()
            self.state.orientation = self.orientation_combo.currentText()
            self.state.is_log_scale = self.log_scale_check.isChecked()
            self.state.x_labels_input = self.x_labels_edit.toPlainText()
            self.state.groups_input = self.groups_edit.toPlainText()
            self.state.df_calibration = core.ensure_calibration_columns(self.calibration_model.dataframe())
            self.state.df_extracted = core.ensure_extracted_columns(self.extracted_model.dataframe())
            core.apply_axis_control_rows_to_state(self.state)

        def _refresh_widgets_from_state(self) -> None:
            self.figure_name_edit.setText(self.state.figure_name)
            idx = self.orientation_combo.findText(self.state.orientation)
            if idx >= 0:
                self.orientation_combo.setCurrentIndex(idx)
            self.log_scale_check.setChecked(bool(self.state.is_log_scale))
            self.x_labels_edit.setPlainText(self.state.x_labels_input)
            self.groups_edit.setPlainText(self.state.groups_input)

        def _refresh_all(self) -> None:
            self._updating_ui = True
            try:
                self._refresh_widgets_from_state()
                self.calibration_model.set_dataframe(core.ensure_calibration_columns(self.state.df_calibration))
                self.extracted_model.set_dataframe(core.ensure_extracted_columns(self.state.df_extracted))
                self.image_view.set_image_cv(self.state.image_cv)
                self._resize_tables()
            finally:
                self._updating_ui = False
            self.refresh_overlay(commit=False)

        def _resize_tables(self) -> None:
            self.calibration_table.resizeColumnsToContents()
            self.extracted_table.resizeColumnsToContents()

        def refresh_overlay(self, commit: bool = True) -> None:
            if getattr(self, "_updating_ui", False):
                return
            if commit:
                self._commit_widgets_to_state()
            self.image_view.update_overlays(
                self.state,
                current_calib_row=self.current_calibration_row(),
                current_extracted_row=self.current_extracted_row(),
            )

        def on_pixel_table_activated(self, table_name: str) -> None:
            self.active_pixel_table = table_name
            self.refresh_overlay(commit=True)

        def focus_active_pixel_table(self) -> None:
            if self.active_pixel_table == "calibration" and self.current_calibration_row() is not None:
                self.calibration_table.setFocus(QtCore.Qt.OtherFocusReason)
            elif self.active_pixel_table == "extracted" and self.current_extracted_row() is not None:
                self.extracted_table.setFocus(QtCore.Qt.OtherFocusReason)

        def on_calibration_model_changed(self) -> None:
            if getattr(self, "_updating_ui", False):
                return
            selected_row = self.current_calibration_row()
            self._commit_widgets_to_state()
            self.state.df_extracted = core.recalculate_values(
                self.state.df_extracted,
                self.state.df_calibration,
                self.state.orientation,
                self.state.is_log_scale,
            )
            self._updating_ui = True
            try:
                self.extracted_model.set_dataframe(self.state.df_extracted)
            finally:
                self._updating_ui = False
            if selected_row is not None:
                self.calibration_table.selectRow(selected_row)
            self.refresh_overlay(commit=False)

        def on_extracted_model_changed(self) -> None:
            if getattr(self, "_updating_ui", False):
                return
            self._commit_widgets_to_state()
            self.refresh_overlay(commit=False)

        def _set_calibration_pixel(self, row: int, pixel: int | float | None) -> None:
            self._commit_widgets_to_state()
            df = core.ensure_calibration_columns(self.state.df_calibration)
            if row is None or row < 0 or row >= len(df):
                return
            df.at[row, "Pixel"] = pd.NA if pixel is None else int(round(float(pixel)))
            self.state.df_calibration = df
            core.apply_axis_control_rows_to_state(self.state)
            self.state.df_extracted = core.recalculate_values(
                self.state.df_extracted,
                self.state.df_calibration,
                self.state.orientation,
                self.state.is_log_scale,
            )
            self._updating_ui = True
            try:
                self.calibration_model.set_dataframe(self.state.df_calibration)
                self.extracted_model.set_dataframe(self.state.df_extracted)
            finally:
                self._updating_ui = False
            self.calibration_table.selectRow(row)
            self.refresh_overlay(commit=False)

        def _calibration_kind_for_row(self, row: int) -> str:
            df = core.ensure_calibration_columns(self.calibration_model.dataframe())
            if row is None or row < 0 or row >= len(df):
                return ""
            return str(df.at[row, "kind"]).strip() or core.CALIBRATION_KIND_Y_TICK

        def handle_calibration_table_command(self, command: str) -> None:
            row = self.current_calibration_row()
            if row is None:
                return
            if command == "row_up":
                self.select_relative_table_row(self.calibration_table, -1)
                self.status_label.setText(f"Calibration row selected: {self.current_calibration_row()}")
                return
            if command == "row_down":
                self.select_relative_table_row(self.calibration_table, 1)
                self.status_label.setText(f"Calibration row selected: {self.current_calibration_row()}")
                return
            if command == "apply":
                self.apply_last_click_to_calibration_row(row)
                return

            df = core.ensure_calibration_columns(self.calibration_model.dataframe())
            if row < 0 or row >= len(df):
                return
            kind = self._calibration_kind_for_row(row)
            current_pixel = core.to_float_or_none(df.at[row, "Pixel"])
            if current_pixel is None:
                current_pixel = 0
            delta = 0
            if kind == core.CALIBRATION_KIND_Y_AXIS:
                if command == "left":
                    delta = -1
                elif command == "right":
                    delta = 1
            elif kind in {core.CALIBRATION_KIND_Y_TICK, core.CALIBRATION_KIND_BASELINE, core.CALIBRATION_KIND_Y_MAX}:
                if command == "up":
                    delta = -1
                elif command == "down":
                    delta = 1
            if delta == 0:
                return
            self._set_calibration_pixel(row, current_pixel + delta)
            self.status_label.setText(f"Calibration {kind} row {row}: Pixel={int(round(current_pixel + delta))}")

        def apply_last_click_to_calibration_row(self, row: int) -> None:
            if self.last_click is None:
                self.status_label.setText("No click position available")
                return
            kind = self._calibration_kind_for_row(row)
            x, y = self.last_click
            pixel = x if kind == core.CALIBRATION_KIND_Y_AXIS else y
            self._set_calibration_pixel(row, pixel)
            self.status_label.setText(f"Applied last click to calibration {kind} row {row}: Pixel={pixel}")

        def select_relative_table_row(self, table: QtWidgets.QTableView, delta: int) -> None:
            model = table.model()
            if model is None or model.rowCount() <= 0:
                return
            index = table.currentIndex()
            current_row = index.row() if index.isValid() else 0
            next_row = max(0, min(model.rowCount() - 1, current_row + int(delta)))
            table.selectRow(next_row)
            table.setCurrentIndex(model.index(next_row, max(0, index.column() if index.isValid() else 0)))
            self.refresh_overlay(commit=True)

        def _set_extracted_point(self, row: int, x_pixel=None, y_pixel=None) -> None:
            self._commit_widgets_to_state()
            df = core.ensure_extracted_columns(self.state.df_extracted)
            if row is None or row < 0 or row >= len(df):
                return
            if x_pixel is not None:
                df.at[row, "x_pixel"] = int(round(float(x_pixel)))
            if y_pixel is not None:
                df.at[row, "y_pixel"] = int(round(float(y_pixel)))
            x_val = core.to_float_or_none(df.at[row, "x_pixel"])
            y_val = core.to_float_or_none(df.at[row, "y_pixel"])
            if x_val is not None and y_val is not None:
                value_pixel = x_val if "Horizontal" in str(self.state.orientation) else y_val
                df.at[row, "Value"] = core.calculate_custom_value(value_pixel, self.state.df_calibration, self.state.is_log_scale)
            self.state.df_extracted = df
            self._updating_ui = True
            try:
                self.extracted_model.set_dataframe(df)
            finally:
                self._updating_ui = False
            self.extracted_table.selectRow(row)
            self.refresh_overlay(commit=False)

        def handle_extracted_table_command(self, command: str) -> None:
            row = self.current_extracted_row()
            if row is None:
                return
            if command == "row_up":
                self.select_relative_table_row(self.extracted_table, -1)
                self.status_label.setText(f"Extracted row selected: {self.current_extracted_row()}")
                return
            if command == "row_down":
                self.select_relative_table_row(self.extracted_table, 1)
                self.status_label.setText(f"Extracted row selected: {self.current_extracted_row()}")
                return
            if command == "apply":
                self.apply_last_click()
                return
            df = core.ensure_extracted_columns(self.extracted_model.dataframe())
            if row < 0 or row >= len(df):
                return
            x_pixel = core.to_float_or_none(df.at[row, "x_pixel"])
            y_pixel = core.to_float_or_none(df.at[row, "y_pixel"])
            if x_pixel is None:
                x_pixel = core.to_float_or_none(getattr(self.state, "last_click_x", None)) or 0
            if y_pixel is None:
                y_pixel = core.to_float_or_none(getattr(self.state, "last_click_y", None)) or 0
            if command == "left":
                x_pixel -= 1
            elif command == "right":
                x_pixel += 1
            elif command == "up":
                y_pixel -= 1
            elif command == "down":
                y_pixel += 1
            else:
                return
            self._set_extracted_point(row, x_pixel=x_pixel, y_pixel=y_pixel)
            self.status_label.setText(f"Extracted row {row}: x={int(round(x_pixel))}, y={int(round(y_pixel))}")

        def keyPressEvent(self, event):
            if self._should_ignore_global_pixel_key():
                return super().keyPressEvent(event)
            key_map = {
                QtCore.Qt.Key_Left: "left",
                QtCore.Qt.Key_Right: "right",
                QtCore.Qt.Key_Up: "up",
                QtCore.Qt.Key_Down: "down",
                QtCore.Qt.Key_A: "left",
                QtCore.Qt.Key_D: "right",
                QtCore.Qt.Key_Q: "row_up",
                QtCore.Qt.Key_E: "row_down",
                QtCore.Qt.Key_W: "up",
                QtCore.Qt.Key_S: "down",
                QtCore.Qt.Key_Space: "apply",
            }
            command = key_map.get(event.key())
            if command is None:
                return super().keyPressEvent(event)
            if self.dispatch_active_pixel_command(command):
                event.accept()
                return
            return super().keyPressEvent(event)

        def _should_ignore_global_pixel_key(self) -> bool:
            focus_widget = QtWidgets.QApplication.focusWidget()
            if focus_widget is None:
                return False
            editable_widgets = (
                QtWidgets.QLineEdit,
                QtWidgets.QTextEdit,
                QtWidgets.QPlainTextEdit,
                QtWidgets.QSpinBox,
                QtWidgets.QDoubleSpinBox,
                QtWidgets.QComboBox,
            )
            if isinstance(focus_widget, editable_widgets):
                return True
            if self.calibration_table.state() == QtWidgets.QAbstractItemView.EditingState:
                return True
            if self.extracted_table.state() == QtWidgets.QAbstractItemView.EditingState:
                return True
            return False

        def dispatch_active_pixel_command(self, command: str) -> bool:
            if self.active_pixel_table == "calibration" and self.current_calibration_row() is not None:
                self.handle_calibration_table_command(command)
                return True
            if self.active_pixel_table == "extracted" and self.current_extracted_row() is not None:
                self.handle_extracted_table_command(command)
                return True
            return False

        def _set_busy(self, busy: bool) -> None:
            for widget in [
                self.open_btn,
                self.recenter_btn,
                self.first_pass_btn,
                self.autonomous_btn,
                self.generate_labels_btn,
                self.save_csv_btn,
                self.apply_click_btn,
            ]:
                widget.setEnabled(not busy)

        def open_image(self) -> None:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Open image",
                "",
                "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp);;All files (*.*)",
            )
            if not path:
                return
            try:
                self.state = core.state_from_image_path(path)
                self.status_label.setText(f"Opened: {path}")
                self._refresh_all()
            except Exception as exc:
                self.show_error("이미지 열기 실패", core.traceback_to_string(exc))

        def recenter_image(self) -> None:
            self.image_view.recenter_image()
            self.refresh_overlay(commit=True)
            self.status_label.setText("Image view recentered")

        def new_window(self) -> None:
            window = MainWindow()
            WINDOWS.append(window)
            window.show()

        def get_current_figure_pixmap_if_available(self):
            return self.image_view.current_pixmap()

        def launch_figure_boss_easter_egg(self) -> None:
            try:
                from figure_boss_easter_egg import FigureBossGameWindow

                pixmap = self.get_current_figure_pixmap_if_available()
                self.figure_boss_window = FigureBossGameWindow(parent=self, figure_pixmap=pixmap)
                self.figure_boss_window.show()
                self.figure_boss_window.raise_()
                self.figure_boss_window.activateWindow()
                self.status_label.setText("Figure Boss Battle launched")
            except Exception as exc:
                self.show_error("Figure Boss 실행 실패", core.traceback_to_string(exc))

        def save_csv(self) -> None:
            self._commit_widgets_to_state()
            default_name = f"LNPDB_{self.state.figure_name or 'extracted'}.csv"
            if self.state.image_path:
                default_dir = str(Path(self.state.image_path).parent / default_name)
            else:
                default_dir = default_name
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save CSV", default_dir, "CSV (*.csv)")
            if not path:
                return
            try:
                core.save_extracted_csv(self.state.df_extracted, path)
                self.status_label.setText(f"Saved: {path}")
            except Exception as exc:
                self.show_error("CSV 저장 실패", core.traceback_to_string(exc))

        def start_worker(self, mode: str) -> None:
            self._commit_widgets_to_state()
            if self.state.image_cv is None:
                self.show_error("이미지 없음", "이미지를 먼저 여세요.")
                return
            self._set_busy(True)
            self.status_label.setText("Gemini 작업 실행 중...")
            worker_state = self._copy_state_for_worker()
            self.worker = GeminiWorker(mode, worker_state, self)
            self.worker.message.connect(self.status_label.setText)
            self.worker.finishedWithState.connect(self.worker_finished)
            self.worker.failed.connect(self.worker_failed)
            self.worker.start()

        def _copy_state_for_worker(self) -> core.AppState:
            return core.AppState(
                image_path=self.state.image_path,
                image_cv=self.state.image_cv.copy() if self.state.image_cv is not None else None,
                image_pil=self.state.image_pil.copy() if self.state.image_pil is not None else None,
                uploaded_file_hash=self.state.uploaded_file_hash,
                figure_name=self.state.figure_name,
                x_labels_input=self.state.x_labels_input,
                groups_input=self.state.groups_input,
                orientation=self.state.orientation,
                is_log_scale=self.state.is_log_scale,
                plot_type=self.state.plot_type,
                baseline_y=self.state.baseline_y,
                y_max_pixel=self.state.y_max_pixel,
                y_axis_x=self.state.y_axis_x,
                last_click_x=self.state.last_click_x,
                last_click_y=self.state.last_click_y,
                df_calibration=self.state.df_calibration.copy(),
                df_extracted=self.state.df_extracted.copy(),
            )

        def worker_finished(self, state: core.AppState) -> None:
            self.state = state
            core.sync_axis_control_rows_from_state(self.state)
            self._refresh_all()
            self._set_busy(False)
            self.status_label.setText("Gemini 작업 완료")
            self.worker = None

        def worker_failed(self, message: str) -> None:
            self._set_busy(False)
            self.worker = None
            self.show_error("Gemini 작업 실패", message)

        def generate_label_table(self) -> None:
            self._commit_widgets_to_state()
            self.state.df_extracted = core.generate_label_table(
                self.state.figure_name,
                self.state.x_labels_input,
                self.state.groups_input,
                plot_type=self.state.plot_type or "Manual",
            )
            self.extracted_model.set_dataframe(self.state.df_extracted)
            self._resize_tables()
            self.refresh_overlay(commit=False)
            self.status_label.setText(f"Generated {len(self.state.df_extracted)} rows")

        def record_click(self, x: int, y: int) -> None:
            self.last_click = (x, y)
            self.state.last_click_x = x
            self.state.last_click_y = y
            if self.active_pixel_table is None:
                if self.current_calibration_row() is not None:
                    self.active_pixel_table = "calibration"
                elif self.current_extracted_row() is not None:
                    self.active_pixel_table = "extracted"
            target = self.active_pixel_table or "none"
            self.status_label.setText(f"Clicked image coordinate: x={x}, y={y} | active target: {target}")
            self.refresh_overlay(commit=True)
            self.focus_active_pixel_table()

        def current_extracted_row(self) -> int | None:
            index = self.extracted_table.currentIndex()
            return index.row() if index.isValid() else None

        def current_calibration_row(self) -> int | None:
            index = self.calibration_table.currentIndex()
            return index.row() if index.isValid() else None

        def apply_last_click(self) -> None:
            if self.last_click is None:
                self.show_error("클릭 좌표 없음", "이미지를 먼저 클릭하세요.")
                return
            row = self.current_extracted_row()
            if row is None:
                self.show_error("선택 행 없음", "extracted value table에서 행을 선택하세요.")
                return
            self._commit_widgets_to_state()
            try:
                x, y = self.last_click
                df, value = core.apply_click_to_row(
                    self.state.df_extracted,
                    row,
                    x,
                    y,
                    self.state.df_calibration,
                    self.state.orientation,
                    self.state.is_log_scale,
                )
                self.state.df_extracted = df
                self.extracted_model.set_dataframe(df)
                self.extracted_table.selectRow(row)
                self.refresh_overlay(commit=False)
                self.status_label.setText(f"Applied click to row {row}: Value={value}")
            except Exception as exc:
                self.show_error("클릭 적용 실패", core.traceback_to_string(exc))

        def insert_extracted_row(self) -> None:
            self._commit_widgets_to_state()
            row = self.current_extracted_row()
            new_row = {
                "selected": False,
                "figure_name": self.state.figure_name,
                "X_Label": None,
                "Group": "N/A",
                "Value": None,
                "Type": self.state.plot_type or "Manual",
                "x_pixel": None,
                "y_pixel": None,
            }
            self.state.df_extracted = core.ensure_extracted_columns(core.insert_row_below(self.state.df_extracted, row, new_row))
            self.extracted_model.set_dataframe(self.state.df_extracted)
            if row is not None:
                self.extracted_table.selectRow(row + 1)
            self.refresh_overlay(commit=False)

        def delete_extracted_row(self) -> None:
            self._commit_widgets_to_state()
            row = self.current_extracted_row()
            if row is None:
                return
            self.state.df_extracted = core.ensure_extracted_columns(core.delete_rows(self.state.df_extracted, [row]))
            self.extracted_model.set_dataframe(self.state.df_extracted)
            self.refresh_overlay(commit=False)

        def insert_calibration_row(self) -> None:
            self._commit_widgets_to_state()
            row = self.current_calibration_row()
            new_row = {"selected": False, "kind": core.CALIBRATION_KIND_Y_TICK, "Pixel": None, "Value": None}
            self.state.df_calibration = core.ensure_calibration_columns(core.insert_row_below(self.state.df_calibration, row, new_row))
            self.calibration_model.set_dataframe(self.state.df_calibration)
            if row is not None:
                self.calibration_table.selectRow(row + 1)
            self.refresh_overlay(commit=False)

        def delete_calibration_row(self) -> None:
            self._commit_widgets_to_state()
            row = self.current_calibration_row()
            if row is None:
                return
            self.state.df_calibration = core.ensure_calibration_columns(core.delete_rows(self.state.df_calibration, [row]))
            self.calibration_model.set_dataframe(self.state.df_calibration)
            self.refresh_overlay(commit=False)

        def show_error(self, title: str, message: str) -> None:
            self.status_label.setText(title)
            QtWidgets.QMessageBox.critical(self, title, message)


def main() -> None:
    if not PYSIDE6_AVAILABLE:
        raise RuntimeError(f"PySide6가 필요합니다. 설치: pip install PySide6\nImport error: {PYSIDE6_IMPORT_ERROR}")
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    WINDOWS.append(window)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()


# Example:
# python value_extractor_desktop.py
