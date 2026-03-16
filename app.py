#app.py
import sys
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


class LogViewer(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("EIF 로그 뷰어")
        self.resize(1200, 800)

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

        # -------------------
        # BR Tab (log viewer)
        # -------------------
        self.br_tab = BRTab()

        # -------------------
        # LEFT SIDE TABS (Log sources)
        # -------------------
        self.left_tabs = QTabWidget()
        self.left_tabs.addTab(self.log_list, "Variable Logs")
        self.left_tabs.addTab(self.br_tab, "BR Logs")

        # -------------------
        # RIGHT SIDE TABS (Analysis)
        # -------------------
        self.right_tabs = QTabWidget()

        self.item_list = QListWidget()
        self.item_list.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.right_tabs.addTab(self.item_list, "Item별")

        self.seq_tree = QTreeWidget()
        self.seq_tree.setHeaderLabel("Sequences")
        self.seq_tree.itemClicked.connect(self.on_sequence_clicked)
        self.right_tabs.addTab(self.seq_tree, "Sequence")

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

        # Store original index once
        for idx, log in enumerate(self.variable_logs):
            log.original_index = idx

        self.display_logs(self.variable_logs)
        self.update_period_from_logs()
        self.build_system_checkboxes()
        self.build_sequences()
        self.populate_sequence_tree()
        self.build_item_list()

    def load_br_log(self, path):
        self.br_logs = load_log_file(path)
        self.br_tab.load_full_logs(self.br_logs)

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
        times = []

        for log in self.variable_logs:
            ts = self.extract_timestamp(log.raw)
            if ts:
                times.append(ts)

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
            self.br_tab.show_expected_brs([])
            return

        for log in logs:
            item = QListWidgetItem(log.raw)
            original_idx = getattr(log, "original_index", None)
            item.setData(Qt.UserRole, original_idx)
            self.log_list.addItem(item)

        self.log_list.setUpdatesEnabled(True)

        # Centralized BR refresh
        #self.refresh_br_for_visible_logs(logs)

    # -------------------
    # Search
    # -------------------
    def search_logs(self):
        keyword = self.search_input.text().strip().casefold()
        start = self.period_start.toPython()
        end = self.period_end.toPython()

        active = {
            s for s, c in self.system_checkboxes.items() if c.isChecked()
        }

        if not active:
            self.display_logs([])
            return

        result = []

        for log in self.variable_logs:
            raw = log.raw

            if self.extract_system(raw) not in active:
                continue

            if keyword and keyword not in raw.casefold():
                continue

            ts = self.extract_timestamp(raw)
            if ts and not (start <= ts <= end):
                continue

            result.append(log)

        self.display_logs(result)

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

        for idx, log in enumerate(self.variable_logs):
            raw = log.raw
            ts = self.extract_timestamp(raw)
            if not ts:
                continue

            item, signal = self.parse_item_signal(raw)
            val = self.parse_value(raw)

            if not item or not signal or not val:
                continue

            # Trigger ON
            if signal == "I_B_TRIGGER_REPORT" and val == "ON":
                active[item] = ts

            # CONF OFF = sequence end
            elif signal == "O_B_TRIGGER_REPORT_CONF" and val == "OFF":
                if item in active:
                    st = active.pop(item)
                    self.sequences.setdefault(item, []).append((st, ts))

    def populate_sequence_tree(self):
        self.seq_tree.clear()

        for item_code, seqs in self.sequences.items():

            item_name = self.db.get_item_name(item_code)
            display_text = item_name if item_name else item_code

            parent = QTreeWidgetItem([display_text])
            parent.setData(0, Qt.UserRole, item_code)
            self.seq_tree.addTopLevelItem(parent)

            for st, et in seqs:
                child = QTreeWidgetItem(
                    [st.strftime("%Y-%m-%d %H:%M:%S")]
                )

                # Store time range instead of index list
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

        # ----------------------------
        # 1️ Filter VARIABLE logs
        # ----------------------------
        subset = []

        for log in self.variable_logs:
            ts = self.extract_timestamp(log.raw)
            parsed_item, _ = self.parse_item_signal(log.raw)

            if not ts:
                continue

            if parsed_item == item_code and st <= ts <= et:
                subset.append(log)

        self.display_logs(subset)

        # ----------------------------
        # 2️ Filter BR executions
        # ----------------------------
        expected_brs = self.db.get_brs_for_item(item_code)

        if not self.br_tab.full_br_logs:
            self.br_tab.show_expected_brs(expected_brs)
            return

        buffer_sec = 3
        start_ts = st.timestamp() - buffer_sec
        end_ts = et.timestamp() + buffer_sec

        self.br_tab.show_brs_in_timerange(start_ts, end_ts, expected_brs)


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

        for item_code in sorted(items):

            # Get DB name
            item_name = self.db.get_item_name(item_code)
            display_text = item_name if item_name else item_code

            list_item = QListWidgetItem(display_text)

            #  Store real item_code internally
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
            ts = self.extract_timestamp(log.raw)
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

        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)

        self.display_logs(self.variable_logs)

        target = self.log_list.item(idx)
        if target:
            self.log_list.scrollToItem(
                target, QListWidget.PositionAtCenter
            )
            self.log_list.setCurrentItem(target)
        self.br_tab.show_all_brs()


    # -------------------
    # Item Double Click
    # -------------------
    def on_item_double_clicked(self, item_widget):
        item_code = item_widget.data(Qt.UserRole)

        if not item_code:
            return

        filtered = []

        for log in self.variable_logs:
            parsed_code, _ = self.parse_item_signal(log.raw)
            if parsed_code == item_code:
                filtered.append(log)

        self.display_logs(filtered)
        


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
            ts = self.extract_timestamp(log.raw)
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

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = LogViewer()
    w.show()
    sys.exit(app.exec())