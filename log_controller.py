# log_controller.py
"""
로그 데이터 흐름 전담 컨트롤러.
- 파일 열기 / 워커 실행 / 콜백 처리
- 검색 (키워드 + 기간 필터)
- 로그 표시 / 점프
- 전체 상태 초기화
"""
import re
from datetime import datetime

from PySide6.QtWidgets import QFileDialog, QListView, QMessageBox
from PySide6.QtCore import QDateTime, QTimer

from worker import VariableLogWorker
from db_manager import DBManager


class LogController:
    def __init__(self, page):
        """
        page : AnalysisPage 인스턴스.
        위젯 접근은 모두 self.page.xxx 를 통해서만 합니다.
        """
        self.page = page
        self.db: DBManager = page.db

        # ── 데이터 ──────────────────────────────────────
        self.variable_logs        = []
        self.variable_timestamps  = []
        self.sequences            = {}
        self.item_categories      = {}
        self.item_index           = {}
        self.current_equipment    = None

        self.variable_logs_loading_finished = False
        self.sequence_tree_built            = False
        self.item_list_built_variable       = False

        self.period_start = QDateTime.currentDateTime().addSecs(-3600)
        self.period_end   = QDateTime.currentDateTime()

        # 검색 디바운스 타이머
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self.execute_search)

    # =========================================================
    # 파일 열기
    # =========================================================
    def open_variable_log(self):
        path, _ = QFileDialog.getOpenFileName(
            self.page, "Variable Log 선택", "", "Log Files (*.log);;All Files (*)"
        )
        if path:
            self.load_variable_log(path)

    def open_variable_and_br_log(self):
        var_path, _ = QFileDialog.getOpenFileName(
            self.page, "Variable Log 선택", "", "Log Files (*.log)"
        )
        if not var_path:
            return
        br_path, _ = QFileDialog.getOpenFileName(
            self.page, "BR Log 선택", "", "Log Files (*.log)"
        )
        if not br_path:
            return
        self.load_variable_log(var_path)
        self.page.br_tab.load_full_logs(br_path) if self._validate_br_log(br_path) else None

    def _validate_br_log(self, path) -> bool:
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
            for i, line in enumerate(f):
                if i >= 100:
                    break
                if "BIZRULE" in line or "(REQUESTQ)" in line:
                    return True
        QMessageBox.critical(self.page, "Invalid BR Log", "선택한 파일이 유효한 BR 로그가 아닙니다.")
        return False

    def load_variable_log(self, path):
        self.reset_all_state()

        self.page.log_model.setLogs([])
        self.page.log_loading_label.show()
        self.page.log_list.hide()

        self._var_worker = VariableLogWorker(path)
        self._var_worker.finished.connect(self._on_variable_log_ready)
        self._var_worker.start()

    # =========================================================
    # 워커 콜백
    # =========================================================
    def _on_variable_log_ready(
        self, sorted_logs, sorted_timestamps, item_index,
        current_equipment, skipped_count, sequences, item_categories
    ):
        self.page.log_loading_label.hide()
        self.page.log_list.show()

        total = len(sorted_logs) + skipped_count
        if total > 0 and (skipped_count / total) > 0.2:
            QMessageBox.warning(
                self.page, "Invalid Lines Detected",
                f"유효하지 않은 줄 {skipped_count:,}개 건너뜀 ({skipped_count * 100 // total}%).\n"
                "Variable 로그 파일이 맞는지 확인하세요."
            )

        self.variable_logs       = sorted_logs
        self.variable_timestamps = sorted_timestamps
        self.item_index          = item_index
        self.current_equipment   = current_equipment
        self.sequences           = sequences
        self.item_categories     = item_categories

        # DB 재빌드
        dynamic_items = {}
        for item_code in item_index:
            base, suffix = _split_item_code(item_code)
            if suffix:
                dynamic_items.setdefault(base, set()).add(suffix)
        self.db.rebuild_for_equipment(current_equipment, dynamic_items, item_categories)

        self.display_logs(self.variable_logs)
        self.update_period_from_logs()
        self.variable_logs_loading_finished = True

        # SequenceController / ItemController에 알림
        self.page.seq_ctrl.on_logs_loaded()
        self.page.item_ctrl.on_logs_loaded()

        mw = self.page.window()
        if hasattr(mw, "statusBar"):
            mw.statusBar().showMessage(f"Loaded {len(self.variable_logs):,} lines.", 4000)

    # =========================================================
    # 기간
    # =========================================================
    def update_period_from_logs(self):
        times = [log.ts for log in self.variable_logs if log.ts]
        if not times:
            return
        self.period_start = QDateTime(min(times))
        self.period_end   = QDateTime(max(times))

    # =========================================================
    # 검색
    # =========================================================
    def schedule_search(self):
        self._search_timer.start(250)

    def execute_search(self):
        import bisect
        keyword       = self.page.search_input.text().strip()
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
        self.display_logs(result)

        br_tab = self.page.br_tab
        if not br_tab.br_calls:
            return
        if not keyword:
            br_tab.show_brs_in_timerange(start_ts, end_ts)
            return
        br_results = br_tab.search_brs(keyword_lower, start_ts, end_ts)
        if br_results:
            br_tab.populate_tree_from_executions(br_results)
        else:
            br_tab.tree.clear()

    # =========================================================
    # 로그 표시
    # =========================================================
    def display_logs(self, logs):
        self.page.log_model.setLogs(logs or [])
        self.page.br_tab.clear_highlight()

    # =========================================================
    # 더블클릭 → 원래 위치로 점프
    # =========================================================
    def jump_to_log(self, index):
        from PySide6.QtCore import Qt
        if not index.isValid():
            return
        idx = index.data(Qt.UserRole)
        if idx is None:
            return

        self.page.search_input.blockSignals(True)
        self.page.search_input.clear()
        self.page.search_input.blockSignals(False)

        if self.page.log_model.logs != self.variable_logs:
            self.display_logs(self.variable_logs)

        model_index = self.page.log_model.index(idx)
        if not model_index.isValid():
            return

        def do_scroll():
            self.page.log_list.scrollTo(model_index, QListView.PositionAtCenter)
            self.page.log_list.setCurrentIndex(model_index)

        QTimer.singleShot(0, do_scroll)

    # =========================================================
    # 전체 상태 초기화
    # =========================================================
    def reset_all_state(self):
        self.variable_logs                  = []
        self.variable_timestamps            = []
        self.sequences                      = {}
        self.item_categories                = {}
        self.item_index                     = {}
        self.current_equipment              = None
        self.variable_logs_loading_finished = False
        self.sequence_tree_built            = False
        self.item_list_built_variable       = False

        self.period_start = QDateTime.currentDateTime().addSecs(-3600)
        self.period_end   = QDateTime.currentDateTime()

        self.page.log_model.setLogs([])

        self.page.search_input.blockSignals(True)
        self.page.search_input.clear()
        self.page.search_input.blockSignals(False)

        br_tab = self.page.br_tab
        br_tab.tree.clear()
        br_tab.br_calls            = []
        br_tab.br_name_index       = {}
        br_tab.execution_item_map  = {}
        br_tab.sorted_exec_times   = []
        br_tab.sorted_executions   = []
        br_tab.execution_by_second = {}
        br_tab.highlighted_item    = None
        br_tab.last_displayed_ids  = None
        br_tab._all_executions     = []
        br_tab._current_page       = 0
        br_tab.page_label.setText("Page 1 of 1")

        self.db.clear_all()


# ── 모듈 수준 헬퍼 ────────────────────────────────────────────
def _split_item_code(item_code):
    import re
    match = re.match(r"(.+?)_(\d+)$", item_code)
    if match:
        return match.group(1), match.group(2)
    return item_code, None