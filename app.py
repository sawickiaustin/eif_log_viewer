#app.py
import sys
import re
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QWidget, QListWidget, QListWidgetItem,
    QHBoxLayout, QLabel, QVBoxLayout, QMainWindow,
    QFileDialog, QLineEdit, QPushButton, QCheckBox,
    QTabWidget, QTreeWidget, QTreeWidgetItem
)
from PySide6.QtGui import QAction
from PySide6.QtCore import QDateTime, Qt

from parser import load_log_file
from period_dialog import PeriodDialog
from br_tab import BRTab
from db_manager import DBManager
from PySide6.QtCore import QTimer

class LogViewer(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("EIF 로그 뷰어")
        self.resize(1200, 800)

        self.KNOWN_EQUIPMENTS = ["MIX", "COT", "ROL", "RWD", "TRS"]

        # Separate storage
        self.variable_logs = []
        self.br_logs = []
        self.sequences = {}

        self.period_start = QDateTime.currentDateTime().addSecs(-3600)
        self.period_end = QDateTime.currentDateTime()

        central = QWidget()
        self.setCentralWidget(central)

        # -------------------
        # Search + Period
        # -------------------
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("검색어 입력")
        self.search_input.textChanged.connect(self.search_logs)

        self.period_button = QPushButton()
        self.update_period_button()
        self.period_button.clicked.connect(self.open_period_dialog)

        self.system_layout = QHBoxLayout()
        self.system_checkboxes = {}

        top = QVBoxLayout()

        row = QHBoxLayout()
        row.addWidget(QLabel("검색"))
        row.addWidget(self.search_input)
        row.addWidget(QLabel("기간"))
        row.addWidget(self.period_button)

        top.addLayout(row)
        top.addLayout(self.system_layout)

        # -------------------
        # Variable Log List
        # -------------------
        self.log_list = QListWidget()
        self.log_list.itemDoubleClicked.connect(self.jump_to_log)
        self.pending_br_jump_ts = None

        # -------------------
        # BR Tab (log viewer)
        # -------------------
        self.br_tab = BRTab(self)
        self.pending_br_highlight = None

        # -------------------
        # LEFT SIDE TABS (Log sources)
        # -------------------
        self.left_tabs = QTabWidget()
        self.left_tabs.addTab(self.log_list, "Variable Logs")
        self.left_tabs.addTab(self.br_tab, "BR Logs")

        # Detect tab switch
        self.left_tabs.currentChanged.connect(self.on_left_tab_changed)

        # -------------------
        # RIGHT SIDE TABS (Analysis)
        # -------------------
        self.right_tabs = QTabWidget()

        self.item_list = QListWidget()
        self.item_list.itemClicked.connect(self.on_item_double_clicked)
        self.right_tabs.addTab(self.item_list, "Item별")

        self.seq_tree = QTreeWidget()
        self.seq_tree.setHeaderLabel("Sequences")
        self.seq_tree.itemClicked.connect(self.on_sequence_clicked)
        self.right_tabs.addTab(self.seq_tree, "Sequence")

        self.pending_variable_jump = None

        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._execute_search)

        self.search_input.textChanged.disconnect()
        self.search_input.textChanged.connect(self.schedule_search)

        # -------------------
        # Layout
        # -------------------
        body = QHBoxLayout()
        body.addWidget(self.left_tabs, 4)
        body.addWidget(self.right_tabs, 2)

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addLayout(body)

        central.setLayout(layout)

        self.db = DBManager()

        self.create_menu()

    # -------------------
    # Menu
    # -------------------
    def create_menu(self):
        bar = self.menuBar()
        file_menu = bar.addMenu("File")

        open_var_action = QAction("Open Variable Log...", self)
        open_var_action.triggered.connect(self.open_variable_log)
        file_menu.addAction(open_var_action)

        open_br_action = QAction("Open BR Log...", self)
        open_br_action.triggered.connect(self.open_br_log)
        file_menu.addAction(open_br_action)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)


    def load_br_log(self, path):
        logs = load_log_file(path)
        self.br_logs = logs

        # send to BR tab
        self.br_tab.load_full_logs(logs)

        print(f"Loaded BR log: {len(logs)} lines")
    # -------------------
    # File Loading
    # -------------------
    def open_variable_log(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Variable Log", "", "Log Files (*.log)"
        )
        if path:
            self.load_variable_log(path)

    def open_br_log(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open BR Log", "", "Log Files (*.log)"
        )
        if path:
            self.load_br_log(path)

    def load_variable_log(self, path):
        self.variable_logs = load_log_file(path)

        dynamic_items = {}
        eqp_set = set()

        logs_with_ts = []  # 🔥 (ts_val, log)

        # -----------------------------
        # 🔥 SINGLE PASS (parse + cache everything)
        # -----------------------------
        for idx, log in enumerate(self.variable_logs):
            raw = log.raw

            log.original_index = idx
            log.raw_lower = raw.casefold()

            # -------------------------
            # timestamp (FAST manual parse)
            # -------------------------
            try:
                ts = datetime(
                    int(raw[0:4]), int(raw[5:7]), int(raw[8:10]),
                    int(raw[11:13]), int(raw[14:16]), int(raw[17:19])
                )
            except:
                ts = None

            log.ts = ts
            ts_val = ts.timestamp() if ts else 0

            # -------------------------
            # system
            # -------------------------
            log.system = None
            parts = raw.split("[")
            for p in parts:
                if "." in p and "]" in p:
                    log.system = p.split("]")[0].split(".")[-1]
                    break

            # -------------------------
            # equipment (faster than next())
            # -------------------------
            eqp = None
            for eq in self.KNOWN_EQUIPMENTS:
                if eq in raw:
                    eqp = eq
                    break

            log.equipment = eqp
            if eqp:
                eqp_set.add(eqp)

            # -------------------------
            # dynamic items
            # -------------------------
            item_code = self.extract_item_code(raw)
            if item_code:
                base, suffix = self.split_item_code(item_code)
                if suffix:
                    dynamic_items.setdefault(base, set()).add(suffix)

            # 🔥 store tuple for fast sort later
            logs_with_ts.append((ts_val, log))

        # -----------------------------
        # 🔥 SORT once using timestamp (FAST)
        # -----------------------------
        logs_with_ts.sort(key=lambda x: x[0])

        # -----------------------------
        # 🔥 UNPACK (aligned lists)
        # -----------------------------
        self.variable_timestamps = [ts for ts, _ in logs_with_ts]
        self.variable_logs = [log for _, log in logs_with_ts]

        # -----------------------------
        # equipment result
        # -----------------------------
        if len(eqp_set) > 1:
            print("⚠ Multiple equipments detected:", eqp_set)

        self.current_equipment = next(iter(eqp_set), None)

        # -----------------------------
        # DB rebuild
        # -----------------------------
        self.db.rebuild_for_equipment(
            self.current_equipment,
            dynamic_items
        )

        # -----------------------------
        # Continue normal flow
        # -----------------------------
        self.display_logs(self.variable_logs)
        self.update_period_from_logs()
        self.build_system_checkboxes()
        self.build_sequences()
        self.populate_sequence_tree()
        self.build_item_list()

    # -------------------
    # Timestamp + System
    # -------------------
    def extract_timestamp(self, raw):
        try:
            return datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
        except:
            return None

    def extract_system(self, raw):
        try:
            parts = raw.split("[")
            for p in parts:
                if "." in p and "]" in p:
                    return p.split("]")[0].split(".")[-1]
        except:
            pass
        return None

    # -------------------
    # Period Handling
    # -------------------
    def update_period_from_logs(self):
        times = [log.ts for log in self.variable_logs if log.ts]

        if not times:
            return

        self.period_start = QDateTime(min(times))
        self.period_end = QDateTime(max(times))
        self.update_period_button()

    def update_period_button(self):
        self.period_button.setText(
            f"{self.period_start.toString('yyyy-MM-dd HH:mm')} ~ "
            f"{self.period_end.toString('yyyy-MM-dd HH:mm')}"
        )

    def open_period_dialog(self):
        dlg = PeriodDialog(self.period_start, self.period_end, self)
        if dlg.exec():
            self.period_start, self.period_end = dlg.get_period()
            self.update_period_button()
            self.search_logs()

    # -------------------
    # System Checkboxes
    # -------------------
    def build_system_checkboxes(self):
        while self.system_layout.count():
            w = self.system_layout.takeAt(0).widget()
            if w:
                w.deleteLater()

        self.system_checkboxes.clear()

        systems = {
            self.extract_system(l.raw)
            for l in self.variable_logs
            if self.extract_system(l.raw)
        }

        for s in sorted(systems):
            cb = QCheckBox(s)
            cb.setChecked(True)
            cb.stateChanged.connect(self.search_logs)
            self.system_layout.addWidget(cb)
            self.system_checkboxes[s] = cb

    # -------------------
    # Display Logs
    # -------------------
    def display_logs(self, logs):
        self.log_list.setUpdatesEnabled(False)
        self.log_list.clear()

        if not logs:
            self.log_list.addItem("⚠️ 결과 없음")
            self.log_list.setUpdatesEnabled(True)
            #self.br_tab.show_expected_brs([])
            return

        for log in logs:
            item = QListWidgetItem(log.raw)
            original_idx = getattr(log, "original_index", None)
            item.setData(Qt.UserRole, original_idx)
            self.log_list.addItem(item)

        self.log_list.setUpdatesEnabled(True)
        self.br_tab.clear_highlight()

        # Centralized BR refresh
        #self.refresh_br_for_visible_logs(logs)

        # -------------------
        # Search
        # -------------------
    

    def search_logs(self):
        import bisect
        keyword = self.search_input.text().strip()
        keyword_lower = keyword.casefold()

        start = self.period_start.toPython()
        end = self.period_end.toPython()

        active = {
            s for s, c in self.system_checkboxes.items()
            if c.isChecked()
        }

        if not active:
            self.display_logs([])
            return

        # ------------------------------------
        # FAST TIME FILTER (🔥 binary search)
        # ------------------------------------
        start_ts = start.timestamp()
        end_ts = end.timestamp()

        left = bisect.bisect_left(self.variable_timestamps, start_ts)
        right = bisect.bisect_right(self.variable_timestamps, end_ts)

        subset = self.variable_logs[left:right]

        # ------------------------------------
        # Filter subset only (FAST)
        # ------------------------------------
        result = []

        for log in subset:

            if log.system not in active:
                continue

            if keyword_lower:
                if keyword_lower not in log.raw_lower:
                    continue

            result.append(log)

        self.display_logs(result)

        # ------------------------------------
        # BR filtering (OPTIMIZED)
        # ------------------------------------
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

    # -------------------
    # Sequence Logic
    # -------------------
    def parse_item_signal(self, raw):
        try:
            block = raw.split("[")[-1].split("]")[0]
            item, signal = block.split(":")
            return item, signal
        except:
            return None, None

    def parse_value(self, raw):
        if ": ON" in raw:
            return "ON"
        if ": OFF" in raw:
            return "OFF"
        return None

    def build_sequences(self):
        self.sequences.clear()
        active = {}

        for log in self.variable_logs:

            ts = log.ts
            if not ts:
                continue

            item, signal = self.parse_item_signal(log.raw)
            val = self.parse_value(log.raw)

            if not item or not signal or not val:
                continue

            if signal == "I_B_TRIGGER_REPORT" and val == "ON":
                active[item] = ts

            elif signal == "O_B_TRIGGER_REPORT_CONF" and val == "OFF":
                if item in active:
                    st = active.pop(item)
                    self.sequences.setdefault(item, []).append((st, ts))

    def populate_sequence_tree(self):
        self.seq_tree.clear()

        # ✅ alphabetical sort by item_code
        for item_code, seqs in sorted(self.sequences.items(), key=lambda x: x[0]):

            item_name = self.db.get_item_name(item_code)
            display_text = item_name if item_name else item_code

            parent = QTreeWidgetItem([display_text])
            parent.setData(0, Qt.UserRole, item_code)
            self.seq_tree.addTopLevelItem(parent)

            for st, et in seqs:
                child = QTreeWidgetItem(
                    [st.strftime("%Y-%m-%d %H:%M:%S")]
                )

                child.setData(0, Qt.UserRole, (st, et))
                parent.addChild(child)

    def on_sequence_clicked(self, item):
        parent = item.parent()
        if not parent:
            return

        item_code = parent.data(0, Qt.UserRole)
        time_range = item.data(0, Qt.UserRole)
        if not time_range:
            return

        st, et = time_range
        if not st or not et:
            return

        # ---------------------------------
        # 0️⃣ Clear current search
        # ---------------------------------
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)

        self.update_period_from_logs()

        st_ts = int(st.timestamp())
        et_ts = int(et.timestamp())

        # ---------------------------------
        # 1️⃣ FAST variable log filtering (🔥 binary search)
        # ---------------------------------
        import bisect

        left = bisect.bisect_left(self.variable_timestamps, st_ts)
        right = bisect.bisect_right(self.variable_timestamps, et_ts)

        subset = []

        for log in self.variable_logs[left:right]:
            parsed_item, _ = self.parse_item_signal(log.raw)

            if parsed_item == item_code:
                subset.append(log)

        self.display_logs(subset)

        # ---------------------------------
        # 2️⃣ Reset BR view to FULL list
        # ---------------------------------
        if self.br_tab.br_calls:
            self.br_tab.show_all_brs()

        # ---------------------------------
        # Stop if no BR file loaded
        # ---------------------------------
        if not self.br_tab.br_calls:
            return

        expected_brs = set(self.db.get_brs_for_item(item_code))

        # ---------------------------------
        # 3️⃣ Highlight expected BRs in range
        # ---------------------------------
        if expected_brs:

            executions_to_highlight = [
                e for e in self.br_tab.br_calls
                if e["br_name"] in expected_brs
                and st_ts <= int(e["timestamp"].timestamp()) <= et_ts
            ]

            if executions_to_highlight:
                if self.left_tabs.currentWidget() == self.br_tab:
                    self.br_tab.highlight_br_executions(executions_to_highlight)
                else:
                    self.pending_br_highlight = executions_to_highlight
                return

        # ---------------------------------
        # 4️⃣ No BR found → prepare jump
        # ---------------------------------
        if self.left_tabs.currentWidget() == self.br_tab:
            self.jump_br_view_to_timestamp(st_ts)
            self.br_tab.clear_highlight()
        else:
            self.pending_br_jump_ts = st_ts
            self.pending_br_highlight = None

    # -------------------
    # Build Item List
    # -------------------
    def build_item_list(self):
        self.item_list.clear()

        items = set()

        for log in self.variable_logs:
            item_code, _ = self.parse_item_signal(log.raw)
            if item_code:
                items.add(item_code)

        # ✅ alphabetical sort
        for item_code in sorted(items):

            item_name = self.db.get_item_name(item_code)
            display_text = item_name if item_name else item_code

            list_item = QListWidgetItem(display_text)
            list_item.setData(Qt.UserRole, item_code)

            self.item_list.addItem(list_item)


    def filter_brs_for_sequence(self, item_code, start_time, end_time, buffer_sec=0):
        if not self.br_logs:
            return None  # No BR file loaded

        expected_brs = self.db.get_brs_for_item(item_code)

        if not expected_brs:
            return []

        start = start_time.timestamp() - buffer_sec
        end = end_time.timestamp() + buffer_sec

        matched = []

        for log in self.br_logs:
            ts = log.ts
            if not ts:
                continue

            ts_val = ts.timestamp()

            if not (start <= ts_val <= end):
                continue

            for br in expected_brs:
                if br in log.raw:
                    matched.append(log.raw)
                    break

        return matched

    # -------------------
    # Jump to Original Position
    # -------------------
    def jump_to_log(self, item):

        if not self.variable_logs:
            return

        idx = item.data(Qt.UserRole)
        if idx is None:
            return

        # ----------------------------
        # Reset search
        # ----------------------------
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)

        self.update_period_from_logs()

        self.display_logs(self.variable_logs)

        target = self.log_list.item(idx)
        if not target:
            return

        self.log_list.scrollToItem(target, QListWidget.PositionAtCenter)
        self.log_list.setCurrentItem(target)

        # ----------------------------
        # Reset BR tree to FULL list
        # ----------------------------
        if self.br_tab.br_calls:
            self.br_tab.show_all_brs()

        # ----------------------------
        # Save timestamp for BR jump
        # ----------------------------
        log = self.variable_logs[idx]
        ts = log.ts


        if ts:
            self.pending_br_jump_ts = ts.timestamp()


    # -------------------
    # Item Double Click
    # -------------------
    def on_item_double_clicked(self, item_widget):
        data = item_widget.data(Qt.UserRole)

        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)

        self.update_period_from_logs()
        # -----------------------
        # BR tab active
        # -----------------------
        if self.left_tabs.currentWidget() == self.br_tab:
            if not self.br_tab.br_calls:
                return

            filtered = [
                e for e in self.br_tab.br_calls
                if e["br_name"] == data
            ]

            self.br_tab.populate_tree_from_executions(filtered)
            return

        # -----------------------
        # Variable tab active
        # -----------------------
        item_code = data
        if not item_code:
            return

        filtered = []

        for log in self.variable_logs:
            parsed_code, _ = self.parse_item_signal(log.raw)
            if parsed_code == item_code:
                filtered.append(log)

        self.display_logs(filtered)
        self.reset_br_view()

        
    def refresh_br_for_visible_logs(self, visible_logs):

        if not self.br_tab.full_br_logs:
            # No BR file loaded → only show expected if available
            item_codes = {
                self.parse_item_signal(log.raw)[0]
                for log in visible_logs
                if self.parse_item_signal(log.raw)[0]
            }

            expected_brs = set()
            for item_code in item_codes:
                expected_brs.update(self.db.get_brs_for_item(item_code))

            self.br_tab.show_expected_brs(expected_brs)
            return

        # ----------------------------
        # 1️ Get time range
        # ----------------------------
        timestamps = []

        for log in visible_logs:
            ts = log.ts
            if ts:
                timestamps.append(ts)

        if not timestamps:
            self.br_tab.display_logs([])
            return

        st = min(timestamps)
        et = max(timestamps)

        buffer_sec = 3
        start_ts = st.timestamp() - buffer_sec
        end_ts = et.timestamp() + buffer_sec

        # ----------------------------
        # 2️ Collect ALL BR logs in time range
        # ----------------------------
        matched = []

        for br_name, logs_for_br in self.br_tab.full_br_index.items():

            for ts, log in logs_for_br:
                ts_val = ts.timestamp()

                if start_ts <= ts_val <= end_ts:
                    matched.append((ts, log))

        # ----------------------------
        # 3️ Sort by timestamp
        # ----------------------------
        matched.sort(key=lambda x: x[0])
        sorted_logs = [log for ts, log in matched]

        if sorted_logs:
            self.br_tab.display_logs(sorted_logs)
            return

        # ----------------------------
        # 4️ If no BR was called, show expected
        # ----------------------------
        item_codes = {
            self.parse_item_signal(log.raw)[0]
            for log in visible_logs
            if self.parse_item_signal(log.raw)[0]
        }

        expected_brs = set()
        for item_code in item_codes:
            expected_brs.update(self.db.get_brs_for_item(item_code))

        self.br_tab.show_expected_brs(expected_brs)


    def reset_br_view(self):
        if self.br_tab.full_br_logs:
            self.br_tab.show_all_brs()

    def build_br_list(self):
        self.item_list.clear()

        if not self.br_tab.br_calls:
            return

        br_names = {execution["br_name"] for execution in self.br_tab.br_calls}

        for br in sorted(br_names):
            item = QListWidgetItem(br)
            item.setData(Qt.UserRole, br)
            self.item_list.addItem(item)

    def on_left_tab_changed(self, index):
        tab_text = self.left_tabs.tabText(index)

        # -----------------------
        # BR TAB OPENED
        # -----------------------
        if tab_text == "BR Logs":
            self.build_br_list()

            if self.pending_br_highlight:
                self.br_tab.highlight_br_executions(self.pending_br_highlight)
                self.pending_br_highlight = None

            elif self.pending_br_jump_ts:
                self.jump_br_view_to_timestamp(self.pending_br_jump_ts)
                self.pending_br_jump_ts = None

        # -----------------------
        # VARIABLE TAB OPENED
        # -----------------------
        else:

            self.build_item_list()

            if self.pending_variable_jump:
                self.jump_variable_view_to_timestamp(self.pending_variable_jump)
                self.pending_variable_jump = None

    def jump_br_view_to_timestamp(self, ts):
        tree = self.br_tab.tree

        closest_item = None
        closest_diff = float("inf")

        for i in range(tree.topLevelItemCount()):

            item = tree.topLevelItem(i)
            execution = item.data(0, Qt.UserRole)

            if not execution:
                continue

            br_ts = execution["timestamp"].timestamp()
            diff = abs(br_ts - ts)

            if diff < closest_diff:
                closest_diff = diff
                closest_item = item

        if closest_item:
            tree.scrollToItem(closest_item, QTreeWidget.PositionAtCenter)
            tree.setCurrentItem(closest_item)

    def jump_variable_view_to_timestamp(self, ts):

        target_ts = int(ts.timestamp())

        closest_item = None
        closest_diff = float("inf")

        for i in range(self.log_list.count()):

            item = self.log_list.item(i)
            idx = item.data(Qt.UserRole)

            if idx is None:
                continue

            log = self.variable_logs[idx]

            log_ts = log.ts
            if not log_ts:
                continue

            log_sec = int(log_ts.timestamp())

            diff = abs(log_sec - target_ts)

            if diff < closest_diff:
                closest_diff = diff
                closest_item = item

        if closest_item:
            self.left_tabs.setCurrentWidget(self.log_list)
            self.log_list.scrollToItem(closest_item, QListWidget.PositionAtCenter)
            self.log_list.setCurrentItem(closest_item)


    def schedule_search(self):
        self.search_timer.start(250)  # wait 250ms after typing

    def _execute_search(self):
        self.search_logs()

    def extract_equipment_from_raw(self, raw):
        """
        Detect equipment by checking known equipment codes inside raw string.
        Example:
        [D1EROL101.RollMapElm] → ROL
        """
        raw_upper = raw.upper()

        for eqp in self.KNOWN_EQUIPMENTS:
            if eqp in raw_upper:
                return eqp

        return None

    def extract_item_code(self, raw):
        """
        Extract:
        [G2_1_CARR_ID_RPT_01:I_B_TRIGGER_REPORT] → G2_1_CARR_ID_RPT_01
        """
        try:
            return raw.split("[")[-1].split("]")[0].split(":")[0]
        except:
            return None


    def split_item_code(self, item_code):
        """
        G2_1_CARR_ID_RPT_01 → (G2_1_CARR_ID_RPT, 01)
        """
        match = re.match(r"(.+?)_(\d+)$", item_code)
        if match:
            return match.group(1), match.group(2)
        return item_code, None


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = LogViewer()
    w.show()
    sys.exit(app.exec())