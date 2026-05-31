import sys
import re
from datetime import datetime, timedelta

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
    QRadioButton, QPushButton, QFileDialog, QLabel, QSplitter,
    QListView, QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem,
    QLineEdit, QFrame, QMessageBox
)
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt, QModelIndex, QDateTime, QTimer, Slot

from model import LogListModel
from br_tab import BRTab
from db_manager import DBManager
from worker import VariableLogWorker
from period_dialog import PeriodDialog


class AnalysisPage(QWidget):

    KNOWN_EQUIPMENTS = ["MIX", "COT", "ROL", "RWD", "TRS", "NND"]

    def __init__(self, parent=None):
        super().__init__(parent)

        # ── 상태 ──────────────────────────────────────────
        self.variable_logs = []
        self.variable_timestamps = []
        self.br_logs = []
        self.sequences = {}
        self.item_categories = {}
        self.items = set()
        self.item_index = {}
        self.br_names = []

        self.variable_logs_loading_finished = False
        self.br_logs_loading_finished = False
        self.br_list_built = False
        self.item_list_built_variable = False
        self.item_list_built_br = False
        self.sequence_tree_built = False
        self.item_list_mode = None

        self.pending_br_jump_ts = None
        self.pending_br_highlight = None
        self.pending_variable_jump = None

        self.period_start = QDateTime.currentDateTime().addSecs(-3600)
        self.period_end = QDateTime.currentDateTime()

        self.db = DBManager()

        # BR 탭은 UI에 표시하지 않지만 로직상 필요하므로 숨겨진 위젯으로 유지
        self.br_tab = BRTab(self)
        self.br_tab.hide()

        self._build_ui()
        self._wire_signals()

    # =========================================================
    # UI 구성
    # =========================================================
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # ── 상단: 분석 유형 라디오 + File 버튼 ───────────
        header = QHBoxLayout()

        header.addWidget(QLabel("분석 유형"))

        self.radio_var = QRadioButton("Variable Trace")
        self.radio_br  = QRadioButton("Variable Trace + Biz Rule Log")
        self.radio_var.setChecked(True)
        header.addWidget(self.radio_var)
        header.addWidget(self.radio_br)
        header.addStretch()

        self.file_btn = QPushButton("File")
        header.addWidget(self.file_btn)

        layout.addLayout(header)

        # ── 구분선 ────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        # ── 본문: 스플리터 (왼쪽 로그뷰 / 오른쪽 패널) ──
        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setHandleWidth(6)

        # 왼쪽: 로그 리스트뷰 + 로딩 레이블
        log_container = QWidget()
        lc_layout = QVBoxLayout(log_container)
        lc_layout.setContentsMargins(0, 0, 0, 0)

        self.log_loading_label = QLabel("⏳ Loading variable log...")
        self.log_loading_label.setAlignment(Qt.AlignCenter)
        self.log_loading_label.setStyleSheet(
            "QLabel { font-size: 14px; color: #666; padding: 20px; }"
        )
        self.log_loading_label.hide()

        self.log_list = QListView()
        self.log_list.setUniformItemSizes(True)
        self.log_model = LogListModel()
        self.log_list.setModel(self.log_model)
        self.log_list.doubleClicked.connect(self._jump_to_log)

        lc_layout.addWidget(self.log_loading_label)
        lc_layout.addWidget(self.log_list)

        splitter.addWidget(log_container)

        # 오른쪽: Item/Sequence 라디오 + 검색 + 리스트/트리
        right = QWidget()
        rlay = QVBoxLayout(right)

        kind_row = QHBoxLayout()
        self.k_item = QRadioButton("Item")
        self.k_seq  = QRadioButton("Sequence")
        self.k_item.setChecked(True)
        kind_row.addWidget(self.k_item)
        kind_row.addWidget(self.k_seq)
        kind_row.addStretch()
        rlay.addLayout(kind_row)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("검색"))
        self.search_input = QLineEdit()
        search_row.addWidget(self.search_input)
        rlay.addLayout(search_row)

        self.item_list = QListWidget()
        self.item_list.itemClicked.connect(self._on_item_clicked)

        self.seq_tree = QTreeWidget()
        self.seq_tree.setHeaderLabel("Sequences")
        self.seq_tree.itemClicked.connect(self._on_sequence_clicked)
        self.seq_tree.hide()

        rlay.addWidget(self.item_list)
        rlay.addWidget(self.seq_tree)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)

    def _wire_signals(self):
        self.file_btn.clicked.connect(self._on_file_clicked)

        self.k_item.toggled.connect(lambda checked: self.item_list.setVisible(checked))
        self.k_seq.toggled.connect(lambda checked: self.seq_tree.setVisible(checked))

        # 검색 디바운스
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._execute_search)
        self.search_input.textChanged.connect(lambda: self.search_timer.start(250))

    # =========================================================
    # 파일 열기 — 라디오 선택에 따라 분기
    # =========================================================
    def _on_file_clicked(self):
        if self.radio_br.isChecked():
            self._open_variable_and_br_log()
        else:
            self._open_variable_log()

    def _open_variable_log(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Variable Log 선택", "", "Log Files (*.log);;All Files (*)"
        )
        if path:
            self._load_variable_log(path)

    def _open_variable_and_br_log(self):
        var_path, _ = QFileDialog.getOpenFileName(
            self, "Variable Log 선택", "", "Log Files (*.log)"
        )
        if not var_path:
            return
        br_path, _ = QFileDialog.getOpenFileName(
            self, "BR Log 선택", "", "Log Files (*.log)"
        )
        if not br_path:
            return
        self._load_variable_log(var_path)
        self._load_br_log(br_path)

    def _load_variable_log(self, path):
        self._reset_all_state()
        self.log_model.setLogs([])
        self.log_loading_label.show()
        self.log_list.hide()

        self._var_worker = VariableLogWorker(path)
        self._var_worker.finished.connect(self._on_variable_log_ready)
        self._var_worker.start()

    def _load_br_log(self, path):
        valid = False
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
            for i, line in enumerate(f):
                if i >= 100:
                    break
                if "BIZRULE" in line or "(REQUESTQ)" in line:
                    valid = True
                    break
        if not valid:
            QMessageBox.critical(self, "Invalid BR Log", "선택한 파일이 유효한 BR 로그가 아닙니다.")
            return
        self.br_tab.load_full_logs(path)

    # =========================================================
    # 워커 콜백
    # =========================================================
    def _on_variable_log_ready(
        self, sorted_logs, sorted_timestamps, item_index,
        current_equipment, skipped_count, sequences, item_categories
    ):
        self.log_loading_label.hide()
        self.log_list.show()

        total = len(sorted_logs) + skipped_count
        if total > 0 and (skipped_count / total) > 0.2:
            QMessageBox.warning(
                self, "Invalid Lines Detected",
                f"유효하지 않은 줄 {skipped_count:,}개 건너뜀 ({skipped_count * 100 // total}%).\n"
                "Variable 로그 파일이 맞는지 확인하세요."
            )

        self.variable_logs       = sorted_logs
        self.variable_timestamps = sorted_timestamps
        self.item_index          = item_index
        self.current_equipment   = current_equipment
        self.sequences           = sequences
        self.item_categories     = item_categories

        dynamic_items = {}
        for item_code in item_index:
            base, suffix = self._split_item_code(item_code)
            if suffix:
                dynamic_items.setdefault(base, set()).add(suffix)

        self.db.rebuild_for_equipment(current_equipment, dynamic_items, item_categories)

        self._display_logs(self.variable_logs)
        self._update_period_from_logs()
        self._populate_sequence_tree()
        self._build_item_list()
        self.variable_logs_loading_finished = True

        mw = self.window()
        if hasattr(mw, "statusBar"):
            mw.statusBar().showMessage(f"Loaded {len(self.variable_logs):,} lines.", 4000)

    # =========================================================
    # 기간
    # =========================================================
    def _update_period_from_logs(self):
        times = [log.ts for log in self.variable_logs if log.ts]
        if not times:
            return
        self.period_start = QDateTime(min(times))
        self.period_end   = QDateTime(max(times))

    # =========================================================
    # 검색 (오른쪽 패널 검색창 기준)
    # =========================================================
    def _execute_search(self):
        import bisect
        keyword       = self.search_input.text().strip()
        keyword_lower = keyword.casefold()

        start_ts = self.period_start.toPython().timestamp()
        end_ts   = self.period_end.toPython().timestamp()

        left  = bisect.bisect_left(self.variable_timestamps, start_ts)
        right = bisect.bisect_right(self.variable_timestamps, end_ts)
        subset = self.variable_logs[left:right]

        result = [
            log for log in subset
            if not keyword_lower or keyword_lower in log.raw_lower
        ]
        self._display_logs(result)

        if not self.br_tab.br_calls:
            return
        if not keyword:
            self.br_tab.show_brs_in_timerange(start_ts, end_ts)
            return
        br_results = self.br_tab.search_brs(keyword_lower, start_ts, end_ts)
        if br_results:
            self.br_tab.populate_tree_from_executions(br_results)
        else:
            self.br_tab.tree.clear()

    # =========================================================
    # 로그 표시
    # =========================================================
    def _display_logs(self, logs):
        self.log_model.setLogs(logs or [])
        self.br_tab.clear_highlight()

    # =========================================================
    # 시퀀스 트리
    # =========================================================
    def _populate_sequence_tree(self, force=False):
        if self.sequence_tree_built and not force:
            return

        self.seq_tree.setUpdatesEnabled(False)
        self.seq_tree.clear()

        group_nodes = {}
        for item_code, seqs in sorted(self.sequences.items()):
            category = self.item_categories.get(item_code, "EQP")
            if category not in group_nodes:
                group_nodes[category] = QTreeWidgetItem([category])
                self.seq_tree.addTopLevelItem(group_nodes[category])

            item_name    = self.db.get_item_name(item_code)
            display_text = item_name if item_name else item_code

            parent = QTreeWidgetItem([display_text])
            parent.setData(0, Qt.UserRole, item_code)
            group_nodes[category].addChild(parent)

            for seq in sorted(seqs, key=lambda x: x["start"]):
                label = f"[{seq['type']}] {seq['start'].strftime('%Y-%m-%d %H:%M:%S')}"
                child = QTreeWidgetItem([label])
                child.setData(0, Qt.UserRole, seq)
                if seq.get("error"):
                    from PySide6.QtGui import QBrush, QColor
                    child.setForeground(0, QBrush(QColor("red")))
                parent.addChild(child)

        self.seq_tree.setUpdatesEnabled(True)
        self.sequence_tree_built = True

    # =========================================================
    # 아이템 리스트
    # =========================================================
    def _build_item_list(self, force=False):
        self.item_list.setUpdatesEnabled(False)
        self.item_list.clear()

        if not self.item_list_built_variable or force:
            self.items = sorted(self.item_index.keys())

        groups = {}
        for item_code in self.items:
            category = self.db.get_item_category(item_code)
            groups.setdefault(category, []).append(item_code)

        for category in ["EQP", "ROLLMAP", "RMS"]:
            if not groups.get(category):
                continue
            header_item = QListWidgetItem(f"[{category}]")
            header_item.setFlags(Qt.NoItemFlags)
            self.item_list.addItem(header_item)

            for item_code in groups[category]:
                item_name    = self.db.get_item_name(item_code)
                display_text = item_name if item_name else item_code
                list_item    = QListWidgetItem(display_text)
                list_item.setData(Qt.UserRole, item_code)
                self.item_list.addItem(list_item)

        self.item_list.setUpdatesEnabled(True)
        self.item_list_built_variable = True

    # =========================================================
    # 클릭 이벤트
    # =========================================================
    def _on_item_clicked(self, item_widget):
        item_code = item_widget.data(Qt.UserRole)
        if not item_code:
            return

        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)

        filtered = self.item_index.get(item_code, [])
        self._display_logs(filtered)

    def _on_sequence_clicked(self, item):
        import bisect
        parent = item.parent()
        if not parent:
            return

        item_code = parent.data(0, Qt.UserRole)
        seq = item.data(0, Qt.UserRole)
        if not isinstance(seq, dict):
            return

        st = seq["start"]
        et = seq["end"]

        if seq["type"] == "B":
            buffer_sec = 1
            st = seq["start"] - timedelta(seconds=buffer_sec)
            et = seq["end"]   + timedelta(seconds=buffer_sec)

        if not st or not et:
            return

        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)

        st_ts = st.timestamp()
        et_ts = et.timestamp()

        left  = bisect.bisect_left(self.variable_timestamps, st_ts)
        right = bisect.bisect_right(self.variable_timestamps, et_ts)
        logs_in_range = self.variable_logs[left:right]

        if seq["type"] == "B":
            core_set  = set(seq.get("core_indices", []))
            final_logs = []
            for log in logs_in_range:
                item_c, signal = self._parse_item_signal(log.raw)
                if item_c != item_code:
                    continue
                if log.original_index in core_set:
                    final_logs.append(log)
                    continue
                if "B_TRIGGER_REPORT" in (signal or ""):
                    continue
                final_logs.append(log)
            final_logs.sort(key=lambda x: x.ts or datetime.min)
            self._display_logs(final_logs)
        else:
            subset = [
                log for log in logs_in_range
                if self._parse_item_signal(log.raw)[0] == item_code
            ]
            self._display_logs(subset)

        # BR 연동 (BR 탭이 숨겨져 있어도 내부 데이터는 동기화)
        if not self.br_tab.br_calls:
            return
        self.br_tab.show_all_brs()
        expected_brs = set(self.db.get_brs_for_item(item_code))
        if expected_brs:
            buffer_sec = 1
            executions_to_highlight = [
                e for e in self.br_tab.br_calls
                if e["br_name"] in expected_brs
                and (st_ts - buffer_sec) <= int(e["timestamp"].timestamp()) <= (et_ts + buffer_sec)
            ]
            if executions_to_highlight:
                self.pending_br_highlight = executions_to_highlight

    # =========================================================
    # 더블클릭 → 원래 위치로 점프
    # =========================================================
    def _jump_to_log(self, index):
        if not index.isValid():
            return
        idx = index.data(Qt.UserRole)
        if idx is None:
            return

        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)

        if self.log_model.logs != self.variable_logs:
            self._display_logs(self.variable_logs)

        model_index = self.log_model.index(idx)
        if not model_index.isValid():
            return

        def do_scroll():
            self.log_list.scrollTo(model_index, QListView.PositionAtCenter)
            self.log_list.setCurrentIndex(model_index)

        QTimer.singleShot(0, do_scroll)

    # =========================================================
    # 전체 상태 초기화
    # =========================================================
    def _reset_all_state(self):
        self.variable_logs       = []
        self.variable_timestamps = []
        self.br_logs             = []
        self.sequences           = {}
        self.item_categories     = {}
        self.items               = set()
        self.item_index          = {}
        self.br_names            = []

        self.variable_logs_loading_finished = False
        self.br_logs_loading_finished       = False
        self.br_list_built                  = False
        self.item_list_built_variable       = False
        self.item_list_built_br             = False
        self.item_list_mode                 = None
        self.sequence_tree_built            = False

        self.pending_br_jump_ts    = None
        self.pending_br_highlight  = None
        self.pending_variable_jump = None

        self.log_model.setLogs([])
        self.item_list.clear()
        self.seq_tree.clear()

        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)

        self.period_start = QDateTime.currentDateTime().addSecs(-3600)
        self.period_end   = QDateTime.currentDateTime()

        self.br_tab.tree.clear()
        self.br_tab.br_calls            = []
        self.br_tab.br_name_index       = {}
        self.br_tab.execution_item_map  = {}
        self.br_tab.sorted_exec_times   = []
        self.br_tab.sorted_executions   = []
        self.br_tab.execution_by_second = {}
        self.br_tab.highlighted_item    = None
        self.br_tab.last_displayed_ids  = None
        self.br_tab._all_executions     = []
        self.br_tab._current_page       = 0
        self.br_tab.page_label.setText("Page 1 of 1")

        self.db.clear_all()

    # =========================================================
    # 파싱 헬퍼
    # =========================================================
    def _parse_item_signal(self, raw):
        try:
            block = raw.split("[")[-1].split("]")[0]
            item, signal = block.split(":")
            return item, signal
        except Exception:
            return None, None

    def _split_item_code(self, item_code):
        match = re.match(r"(.+?)_(\d+)$", item_code)
        if match:
            return match.group(1), match.group(2)
        return item_code, None


# =========================================================
# MainWindow — 탭 관리만 담당
# =========================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EIF 로그 뷰어")
        self.resize(1400, 900)
        self._build_ui()
        self._create_menu()
        self.statusBar().showMessage("Ready")

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        self.page_tabs = QTabWidget()
        self.page_tabs.setTabsClosable(True)
        self.page_tabs.tabCloseRequested.connect(self._close_tab)
        self.page_tabs.currentChanged.connect(self._on_tab_changed)

        self._add_page("1")

        plus = QWidget()
        self.page_tabs.addTab(plus, "+")

        layout.addWidget(self.page_tabs)

    def _create_menu(self):
        bar = self.menuBar()
        file_menu = bar.addMenu("File")

        new_tab_action = QAction("새 분석 탭", self)
        new_tab_action.setShortcut("Ctrl+T")
        new_tab_action.triggered.connect(lambda: self._add_page())
        file_menu.addAction(new_tab_action)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    def _add_page(self, title=None, switch_to=True):
        plus_idx  = self.page_tabs.count() - 1
        insert_at = plus_idx if (
            plus_idx >= 0 and self.page_tabs.tabText(plus_idx) == "+"
        ) else self.page_tabs.count()

        page  = AnalysisPage(self)
        label = title or f"{insert_at + 1}"
        idx   = self.page_tabs.insertTab(insert_at, page, label)

        if switch_to:
            self.page_tabs.setCurrentIndex(idx)
        return idx

    @Slot(int)
    def _on_tab_changed(self, idx):
        if idx >= 0 and self.page_tabs.tabText(idx) == "+":
            new_idx = self._add_page(f"{self.page_tabs.count()}")
            self.page_tabs.setCurrentIndex(new_idx)

    def _close_tab(self, idx):
        if self.page_tabs.tabText(idx) == "+":
            return
        real_count = sum(
            1 for i in range(self.page_tabs.count())
            if self.page_tabs.tabText(i) != "+"
        )
        if real_count <= 1:
            return
        self.page_tabs.removeTab(idx)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.showMaximized()
    sys.exit(app.exec())