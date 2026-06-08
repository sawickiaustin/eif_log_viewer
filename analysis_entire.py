# analysis_entire.py
import sys
import re
from datetime import datetime, timedelta

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
    QRadioButton, QPushButton, QFileDialog, QLabel, QSplitter,
    QListView, QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem,
    QLineEdit, QFrame, QMessageBox, QStackedWidget
)
from PySide6.QtGui import QAction, QColor
from PySide6.QtCore import Qt, QModelIndex, QDateTime, QTimer, Slot

from model import LogListModel
from br_tab import BRTab
from db_manager import DBManager
from worker import VariableLogWorker
from period_dialog import PeriodDialog


# =========================================================
# LogListModel with highlight support
# =========================================================
class HighlightLogListModel(LogListModel):
    """LogListModel에 하이라이트 기능 추가."""

    HIGHLIGHT_BG   = QColor("#1a6b9a")
    HIGHLIGHT_TEXT = QColor("#ffffff")

    def __init__(self):
        super().__init__()
        self._highlighted_codes: set[str] = set()

    def set_highlight(self, item_codes: set[str]):
        self._highlighted_codes = item_codes
        if self.logs:
            self.dataChanged.emit(
                self.index(0), self.index(len(self.logs) - 1)
            )

    def clear_highlight(self):
        self.set_highlight(set())

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self.logs):
            return None

        log = self.logs[index.row()]

        if role == Qt.DisplayRole:
            return log.raw

        if role == Qt.UserRole:
            return log.original_index

        if self._highlighted_codes:
            item_code = self._extract_item_code(log.raw)
            is_match = item_code in self._highlighted_codes

            if role == Qt.BackgroundRole and is_match:
                return self.HIGHLIGHT_BG

            if role == Qt.ForegroundRole and is_match:
                return self.HIGHLIGHT_TEXT

        return None

    @staticmethod
    def _extract_item_code(raw: str) -> str | None:
        try:
            block = raw.split("[")[-1].split("]")[0]
            return block.split(":")[0]
        except Exception:
            return None


# =========================================================
# AnalysisPage
# =========================================================
class AnalysisPage(QWidget):

    KNOWN_EQUIPMENTS = ["MIX", "COT", "ROL", "RWD", "TRS", "NND"]

    def __init__(self, parent=None):
        super().__init__(parent)

        # ── 상태 ──────────────────────────────────────────
        self.variable_logs = []
        self.variable_timestamps = []
        self.sequences = {}
        self.item_categories = {}
        self.items = set()
        self.item_index = {}

        self.variable_logs_loading_finished = False
        self.br_logs_loading_finished = False
        self.item_list_built_variable = False
        self.sequence_tree_built = False

        self.pending_br_jump_ts = None
        self.pending_br_highlight = None

        self.period_start = QDateTime.currentDateTime().addSecs(-3600)
        self.period_end   = QDateTime.currentDateTime()

        self.db = DBManager()

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

        self.file_btn = QPushButton("File")
        self.file_btn.setFixedWidth(60)
        header.addWidget(self.file_btn)
        header.addStretch()
        layout.addLayout(header)

        # ── 구분선 ────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        # ── 본문: 메인 스플리터 (좌/우) ───────────────────
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setHandleWidth(6)

        # ── 왼쪽: QStackedWidget으로 모드 전환 ────────────
        #   stack[0] = Variable 전용 (로그뷰만)
        #   stack[1] = Variable+BR (상하 스플리터)
        self.left_stack = QStackedWidget()

        # 공유 모델
        self.log_model = HighlightLogListModel()

        # Variable 패널 빌더 — 헤더 없이 QListView만 사용
        def _make_var_panel():
            w = QWidget()
            lay = QVBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)

            loading = QLabel("⏳ Loading variable log...")
            loading.setAlignment(Qt.AlignCenter)
            loading.setStyleSheet("QLabel { font-size: 14px; color: #666; padding: 20px; }")
            loading.hide()

            view = QListView()
            view.setUniformItemSizes(True)
            view.setModel(self.log_model)
            view.setFrameShape(QFrame.NoFrame)
            view.doubleClicked.connect(self._jump_to_log)

            lay.addWidget(loading)
            lay.addWidget(view)
            return w, loading, view

        # stack[0]: Variable 전용
        var_only, self.log_loading_label_var, self.log_list_var = _make_var_panel()
        self.left_stack.addWidget(var_only)          # index 0

        # stack[1]: Variable + BR (상하 스플리터)
        self.v_splitter = QSplitter(Qt.Vertical)
        self.v_splitter.setHandleWidth(6)

        var_panel, self.log_loading_label_br, self.log_list_br = _make_var_panel()

        self.br_tab = BRTab(self)
        # 페이지네이션 버튼 불필요 — 숨김
        self.br_tab.prev_btn.hide()
        self.br_tab.next_btn.hide()
        self.br_tab.page_label.hide()
        self.br_tab.tree.setHeaderHidden(True)
        self.br_tab.tree.setFrameShape(QFrame.NoFrame)

        self.v_splitter.addWidget(var_panel)
        self.v_splitter.addWidget(self.br_tab)
        self.v_splitter.setStretchFactor(0, 1)
        self.v_splitter.setStretchFactor(1, 1)
        self.left_stack.addWidget(self.v_splitter)   # index 1

        self.main_splitter.addWidget(self.left_stack)

        # ── 오른쪽: Item/Sequence 패널 ────────────────────
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

        self.main_splitter.addWidget(right)
        self.main_splitter.setStretchFactor(0, 3)
        self.main_splitter.setStretchFactor(1, 1)

        layout.addWidget(self.main_splitter)

        # 초기 모드: Variable 전용
        self.left_stack.setCurrentIndex(0)

    def _wire_signals(self):
        self.file_btn.clicked.connect(self._on_file_clicked)

        # 라디오 전환 → 레이아웃 모드 전환
        self.radio_var.toggled.connect(self._on_mode_changed)

        self.k_item.toggled.connect(lambda checked: self.item_list.setVisible(checked))
        self.k_seq.toggled.connect(lambda checked: self.seq_tree.setVisible(checked))

        # 검색 디바운스
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._execute_search)
        self.search_input.textChanged.connect(lambda: self.search_timer.start(250))

    # =========================================================
    # 모드 전환
    # =========================================================
    def _on_mode_changed(self):
        if self.radio_var.isChecked():
            self.left_stack.setCurrentIndex(0)   # Variable 전용
        else:
            self.left_stack.setCurrentIndex(1)   # Variable + BR

    # =========================================================
    # 파일 열기
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
        self.log_loading_label_var.show()
        self.log_list_var.hide()
        self.log_loading_label_br.show()
        self.log_list_br.hide()

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
        self.br_logs_loading_finished = True

    # =========================================================
    # 워커 콜백
    # =========================================================
    def _on_variable_log_ready(
        self, sorted_logs, sorted_timestamps, item_index,
        current_equipment, skipped_count, sequences, item_categories
    ):
        self.log_loading_label_var.hide()
        self.log_list_var.show()
        self.log_loading_label_br.hide()
        self.log_list_br.show()

        total = len(sorted_logs) + skipped_count
        if total > 0 and (skipped_count / total) > 0.2:
            QMessageBox.warning(
                self, "Invalid Lines Detected",
                f"유효하지 않은 줄 {skipped_count:,}개 건너뜀 "
                f"({skipped_count * 100 // total}%).\n"
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
    # 검색
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
        self.log_model.clear_highlight()

    # =========================================================
    # 하이라이팅
    # =========================================================
    def _highlight_variable_by_item(self, item_code: str):
        """Variable 로그에서 해당 item_code 줄만 색상 강조."""
        self.log_model.set_highlight({item_code})

    def _highlight_br_by_item(self, item_code: str):
        """DB에서 연관 BR을 찾아 BR 탭에서 강조."""
        if not self.br_tab.br_calls:
            return
        expected_brs = set(self.db.get_brs_for_item(item_code))
        if not expected_brs:
            return
        executions = [
            e for e in self.br_tab.br_calls
            if e["br_name"] in expected_brs
        ]
        if executions:
            self.br_tab.highlight_br_executions(executions)

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
                    from PySide6.QtGui import QBrush
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
    # Item 클릭 → 전체 로그 유지 + 해당 item 하이라이팅
    # =========================================================
    def _on_item_clicked(self, item_widget):
        item_code = item_widget.data(Qt.UserRole)
        if not item_code:
            return

        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)

        # 전체 로그 표시 (필터링 없음)
        self.log_model.setLogs(self.variable_logs)

        # Variable 로그 하이라이팅
        self._highlight_variable_by_item(item_code)

        # BR 로그 하이라이팅
        self._highlight_br_by_item(item_code)

        # 첫 번째 해당 줄로 스크롤
        self._scroll_to_first_match(item_code)

    def _scroll_to_first_match(self, item_code: str):
        """해당 item_code의 첫 번째 줄로 스크롤."""
        logs = self.log_model.logs
        for i, log in enumerate(logs):
            code = HighlightLogListModel._extract_item_code(log.raw)
            if code == item_code:
                model_index = self.log_model.index(i)
                active_view = (
                    self.log_list_br
                    if self.left_stack.currentIndex() == 1
                    else self.log_list_var
                )
                def do_scroll(idx=model_index, view=active_view):
                    view.scrollTo(idx, QListView.PositionAtCenter)
                    view.setCurrentIndex(idx)
                QTimer.singleShot(0, do_scroll)
                break

    # =========================================================
    # Sequence 클릭
    # =========================================================
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
            st = seq["start"] - timedelta(seconds=1)
            et = seq["end"]   + timedelta(seconds=1)

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
            core_set   = set(seq.get("core_indices", []))
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

        # BR 하이라이팅
        if not self.br_tab.br_calls:
            return
        self.br_tab.show_all_brs()
        expected_brs = set(self.db.get_brs_for_item(item_code))
        if expected_brs:
            executions = [
                e for e in self.br_tab.br_calls
                if e["br_name"] in expected_brs
                and (st_ts - 1) <= int(e["timestamp"].timestamp()) <= (et_ts + 1)
            ]
            if executions:
                self.br_tab.highlight_br_executions(executions)

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
            self.log_model.setLogs(self.variable_logs)
            self.log_model.clear_highlight()

        model_index = self.log_model.index(idx)
        if not model_index.isValid():
            return

        active_view = (
            self.log_list_br
            if self.left_stack.currentIndex() == 1
            else self.log_list_var
        )

        def do_scroll():
            active_view.scrollTo(model_index, QListView.PositionAtCenter)
            active_view.setCurrentIndex(model_index)

        QTimer.singleShot(0, do_scroll)

    # =========================================================
    # 전체 상태 초기화
    # =========================================================
    def _reset_all_state(self):
        self.variable_logs               = []
        self.variable_timestamps         = []
        self.sequences                   = {}
        self.item_categories             = {}
        self.items                       = set()
        self.item_index                  = {}

        self.variable_logs_loading_finished = False
        self.br_logs_loading_finished       = False
        self.item_list_built_variable       = False
        self.sequence_tree_built            = False

        self.pending_br_jump_ts    = None
        self.pending_br_highlight  = None

        self.log_model.setLogs([])
        self.log_model.clear_highlight()
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
        # Ctrl+T 단축키만 유지 (메뉴바 File 항목 제거)
        new_tab_action = QAction("새 분석 탭", self)
        new_tab_action.setShortcut("Ctrl+T")
        new_tab_action.triggered.connect(lambda: self._add_page())
        self.addAction(new_tab_action)

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