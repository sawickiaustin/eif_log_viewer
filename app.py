#app.py
import sys
import re
from datetime import datetime, timedelta

from PySide6.QtWidgets import (
    QApplication, QWidget, QListWidget, QListWidgetItem,
    QHBoxLayout, QLabel, QVBoxLayout, QMainWindow,
    QFileDialog, QLineEdit, QPushButton,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QListView,QMessageBox
)
from PySide6.QtGui import QAction
from PySide6.QtCore import QDateTime, Qt, QAbstractListModel, QModelIndex

from parser import load_log_file
from period_dialog import PeriodDialog
from br_tab import BRTab
from db_manager import DBManager
from PySide6.QtCore import QTimer
from model import LogListModel
from worker import VariableLogWorker

class LogViewer(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("EIF 로그 뷰어")
        self.resize(1200, 800)

        self.KNOWN_EQUIPMENTS = ["MIX", "COT", "ROL", "RWD", "TRS"]

        self.variable_logs_loading_finished = False
        self.br_logs_loading_finished = False

        self.br_list_built = False
        self.item_list_built = False
        self.item_list_mode = None 
        self.item_list_built_variable = False
        self.item_list_built_br = False

        self.br_names = []
        self.items = set()

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

        top = QVBoxLayout()

        row = QHBoxLayout()
        row.addWidget(QLabel("검색"))
        row.addWidget(self.search_input)
        row.addWidget(QLabel("기간"))
        row.addWidget(self.period_button)

        top.addLayout(row)

        # -------------------
        # Variable Log List
        # -------------------
        # Create a container widget for the log list + loading overlay
        self.log_container = QWidget()
        log_container_layout = QVBoxLayout(self.log_container)
        log_container_layout.setContentsMargins(0, 0, 0, 0)

        self.log_list = QListView()
        self.log_list.doubleClicked.connect(self.jump_to_log)
        self.pending_br_jump_ts = None
        self.log_list.setUniformItemSizes(True)

        self.log_model = LogListModel()
        self.log_list.setModel(self.log_model)

        # Loading label (initially hidden)
        self.log_loading_label = QLabel("⏳ Loading variable log...")
        self.log_loading_label.setAlignment(Qt.AlignCenter)
        self.log_loading_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                color: #666;
                padding: 20px;
            }
        """)
        self.log_loading_label.hide()

        log_container_layout.addWidget(self.log_loading_label)
        log_container_layout.addWidget(self.log_list)

        # -------------------
        # BR Tab (log viewer)
        # -------------------
        self.br_tab = BRTab(self)
        self.pending_br_highlight = None

        # -------------------
        # LEFT SIDE TABS (Log sources)
        # -------------------
        self.left_tabs = QTabWidget()
        self.left_tabs.addTab(self.log_container, "Variable Logs")  # ← changed from self.log_list
        self.left_tabs.addTab(self.br_tab, "BR Logs")

        # Detect tab switch
        self.left_tabs.currentChanged.connect(self.on_left_tab_changed)

        self.current_tab = 'Variable Logs'

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
        self.statusBar().showMessage("Ready")

    # -------------------
    # Menu
    # -------------------
    def open_variable_and_br_log(self):
        # -------------------------
        # Select Variable file
        # -------------------------
        var_path, _ = QFileDialog.getOpenFileName(
            self, "Select Variable Log", "", "Log Files (*.log)"
        )

        if not var_path:
            return

        # -------------------------
        # Select BR file
        # -------------------------
        br_path, _ = QFileDialog.getOpenFileName(
            self, "Select BR Log", "", "Log Files (*.log)"
        )

        if not br_path:
            return

        # -------------------------
        # Load BOTH (important order)
        # -------------------------
        self.load_variable_log(var_path)
        self.load_br_log(br_path)

    def create_menu(self):
        bar = self.menuBar()
        file_menu = bar.addMenu("File")

        # 1️⃣ Variable only
        open_var_action = QAction("Add Variable Log...", self)
        open_var_action.triggered.connect(self.open_variable_log)
        file_menu.addAction(open_var_action)

        # 2️⃣ Variable + BR together
        open_pair_action = QAction("Add Variable + BR Log...", self)
        open_pair_action.triggered.connect(self.open_variable_and_br_log)
        file_menu.addAction(open_pair_action)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)


    def load_br_log(self, path):
        logs = load_log_file(path)

        # 🔥 VALIDATION (must contain BIZRULE or REQUESTQ)
        valid = False

        for log in logs[:100]:
            raw = log.raw
            if "BIZRULE" in raw or "(REQUESTQ)" in raw:
                valid = True
                break

        if not valid:
            QMessageBox.critical(
                self,
                "Invalid BR Log",
                "The selected file is not a valid BR log.\n"
            )
            return

        self.br_logs = logs

        # 🔥 reset cache flag
        self.br_list_built = False
        self.item_list_built_br = False

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

    def is_valid_log_line(self, raw):
        if len(raw) < 19:
            return False

        # Check timestamp
        try:
            datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
        except:
            return False

        # Must contain structured block
        if "[" not in raw or "]" not in raw:
            return False

        return True

    def load_variable_log(self, path):
        self.reset_all_state()

        raw_logs = load_log_file(path)

        # Reset flags
        self.item_list_built = False
        self.sequence_tree_built = False
        self.item_list_built_variable = False
        self.item_index = {}

        # Show loading indicator
        self.log_model.setLogs([])
        self.log_loading_label.show()  # ← Show loading label
        self.log_list.hide()           # ← Hide the li

        # Spin up worker
        self._var_worker = VariableLogWorker(raw_logs)
        self._var_worker.finished.connect(self._on_variable_log_ready)
        self._var_worker.start()

    def _on_variable_log_ready(self, sorted_logs, sorted_timestamps, item_index, current_equipment, skipped_count, sequences, item_categories):
        # Hide loading indicator
        self.log_loading_label.hide()  # ← Hide loading label
        self.log_list.show()           # ← Show the list

        # Alert if >20% of lines were invalid
        total_lines = len(sorted_logs) + skipped_count
        if total_lines > 0 and (skipped_count / total_lines) > 0.2:
            QMessageBox.warning(
                self,
                "Invalid Lines Detected",
                f"Skipped {skipped_count:,} invalid lines ({skipped_count*100//total_lines}% of file).\n"
                "This may not be a valid Variable log file."
            )

        self.variable_logs = sorted_logs
        self.variable_timestamps = sorted_timestamps
        self.item_index = item_index
        self.current_equipment = current_equipment
        self.sequences = sequences

        # Dynamic suffix items for DB
        dynamic_items = {}
        for item_code in item_index:
            base, suffix = self.split_item_code(item_code)
            if suffix:
                dynamic_items.setdefault(base, set()).add(suffix)

        self.db.rebuild_for_equipment(current_equipment, dynamic_items, item_categories)

        self.display_logs(self.variable_logs)
        self.update_period_from_logs()
        self.populate_sequence_tree()

        if self.current_tab == "Variable Logs":
            self.build_item_list()

        self.variable_logs_loading_finished = True

        self.statusBar().showMessage(
            f"Loaded {len(self.variable_logs):,} variable log lines.", 4000
        )

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
    # Display Logs
    # -------------------
    def display_logs(self, logs):
        if not logs:
            self.log_model.setLogs([])
            return

        self.log_model.setLogs(logs)
        self.br_tab.clear_highlight()
    

    def search_logs(self):
        import bisect
        keyword = self.search_input.text().strip()
        keyword_lower = keyword.casefold()

        start = self.period_start.toPython()
        end = self.period_end.toPython()

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
        try:
            if " : " in raw:
                return raw.rsplit(" : ", 1)[1].strip()
        except:
            pass

        return None

    def merge_overlapping_sequences(self):
        for item, seqs in self.sequences.items():

            # 🔥 only merge B sequences
            b_seqs = [s for s in seqs if s["type"] == "B"]
            other_seqs = [s for s in seqs if s["type"] != "B"]

            if not b_seqs:
                continue

            # sort by start time
            b_seqs.sort(key=lambda x: x["start"])

            merged = []
            current = b_seqs[0]

            for nxt in b_seqs[1:]:

                # 🔥 overlap or touching
                if nxt["start"] <= current["end"]:
                    current["end"] = max(current["end"], nxt["end"])
                else:
                    merged.append(current)
                    current = nxt

            merged.append(current)

            # 🔥 rebuild list (keep W untouched)
            self.sequences[item] = merged + other_seqs

    def build_sequences(self):
        self.sequences = {}

        active = {}
        # item -> {
        #   "start": datetime,
        #   "conf_on": bool,
        #   "b_off": bool
        # }

        # O(log n) lookup structures
        b_intervals = {}   # item -> sorted list of (start_ts, end_ts) for B sequences
        w_timestamps = {}  # item -> set of datetime for W deduplication

        buffer_sec = 1
        import bisect

        for log in self.variable_logs:

            ts = log.ts
            if not ts:
                continue

            item, signal = self.parse_item_signal(log.raw)
            val = self.parse_value(log.raw)

            if not item or not signal:
                continue

            # =====================================================
            # TYPE W: W_TRIGGER_REPORT (instant)
            # =====================================================
            if "W_TRIGGER_REPORT" in signal:

                ts_val = ts.timestamp()
                lo = ts_val - buffer_sec
                hi = ts_val + buffer_sec

                # O(log n) overlap check against known B intervals
                intervals = b_intervals.get(item, [])
                idx = bisect.bisect_left(intervals, (lo,))

                inside_b = False
                for iv_start, iv_end in intervals[max(0, idx - 1): idx + 2]:
                    if iv_start <= hi and iv_end >= lo:
                        inside_b = True
                        break

                if inside_b:
                    continue

                # O(1) duplicate check
                seen_w = w_timestamps.setdefault(item, set())
                if ts in seen_w:
                    continue
                seen_w.add(ts)

                self.sequences.setdefault(item, []).append({
                    "start": ts,
                    "end": ts,
                    "type": "W"
                })
                continue

            # =====================================================
            # TYPE B: B_TRIGGER_REPORT (strict 4-step sequence)
            # =====================================================

            # Step 1: B ON (not CONF)
            if ("B_TRIGGER_REPORT_CONF" not in signal
                    and "B_TRIGGER_REPORT" in signal
                    and val == "ON"):

                active[item] = {
                    "start": ts,
                    "conf_on": False,
                    "b_off": False
                }
                continue

            if item not in active:
                continue

            seq = active[item]

            # Step 2: CONF ON
            if "B_TRIGGER_REPORT_CONF" in signal and val == "ON":
                seq["conf_on"] = True
                continue

            # Step 3: B OFF
            if ("B_TRIGGER_REPORT_CONF" not in signal
                    and "B_TRIGGER_REPORT" in signal
                    and val == "OFF"):
                seq["b_off"] = True
                continue

            # Step 4: CONF OFF → sequence complete
            if "B_TRIGGER_REPORT_CONF" in signal and val == "OFF":

                if seq["conf_on"] and seq["b_off"]:

                    new_start = seq["start"] - timedelta(seconds=buffer_sec)
                    new_end   = ts           + timedelta(seconds=buffer_sec)

                    existing = self.sequences.setdefault(item, [])

                    # Evict any W events that fall inside this B window
                    existing[:] = [
                        s for s in existing
                        if not (
                            s["type"] == "W"
                            and new_start <= s["start"] <= new_end
                        )
                    ]

                    existing.append({
                        "start": seq["start"],
                        "end":   ts,
                        "type":  "B"
                    })

                    # Register interval for future O(log n) W overlap checks
                    interval = (seq["start"].timestamp(), ts.timestamp())
                    item_intervals = b_intervals.setdefault(item, [])
                    bisect.insort(item_intervals, interval)

                active.pop(item, None)

    def populate_sequence_tree(self, force=False):
        if hasattr(self, "sequence_tree_built") and self.sequence_tree_built and not force:
            return

        self.seq_tree.setUpdatesEnabled(False)
        self.seq_tree.clear()

        group_nodes = {}

        for item_code, seqs in sorted(self.sequences.items()):

            category = self.db.get_item_category(item_code)

            if category not in group_nodes:
                group_nodes[category] = QTreeWidgetItem([category])
                self.seq_tree.addTopLevelItem(group_nodes[category])

            parent_group = group_nodes[category]

            item_name = self.db.get_item_name(item_code)
            display_text = item_name if item_name else item_code

            parent = QTreeWidgetItem([display_text])
            parent.setData(0, Qt.UserRole, item_code)
            parent_group.addChild(parent)

            # sort by start
            sorted_seqs = sorted(seqs, key=lambda x: x["start"])

            for seq in sorted_seqs:
                st = seq["start"]

                label = f"[{seq['type']}] {st.strftime('%Y-%m-%d %H:%M:%S')}"

                child = QTreeWidgetItem([label])

                # 🔥 ALWAYS store dict (critical fix)
                child.setData(0, Qt.UserRole, seq)

                parent.addChild(child)

        self.seq_tree.setUpdatesEnabled(True)
        self.sequence_tree_built = True

    from datetime import datetime

    def to_datetime_safe(self, value):
        if isinstance(value, datetime):
            return value

        if isinstance(value, str):
            try:
                return datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S")
            except:
                return None

        return None

    def on_sequence_clicked(self, item):
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
            et = seq["end"] + timedelta(seconds=buffer_sec)

        if not st or not et:
            return

        # ---------------------------------
        # Clear search
        # ---------------------------------
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)

        self.update_period_from_logs()

        st_ts = int(st.timestamp())
        et_ts = int(et.timestamp())

        # ---------------------------------
        # FAST slice by time
        # ---------------------------------
        import bisect

        left = bisect.bisect_left(self.variable_timestamps, st_ts)
        right = bisect.bisect_right(self.variable_timestamps, et_ts)

        logs_in_range = self.variable_logs[left:right]

        # =====================================================
        # 🔴 B SEQUENCE HANDLING
        # =====================================================
        if seq["type"] == "B":

            main_sequence = []
            step = 0

            for log in logs_in_range:
                item, signal = self.parse_item_signal(log.raw)
                val = self.parse_value(log.raw)

                if item != item_code:
                    continue

                # STEP 1: B ON
                if step == 0:
                    if "B_TRIGGER_REPORT" in signal and "CONF" not in signal and val == "ON":
                        main_sequence.append(log)
                        step = 1
                    continue

                # STEP 2: CONF ON
                elif step == 1:
                    if "B_TRIGGER_REPORT_CONF" in signal and val == "ON":
                        main_sequence.append(log)
                        step = 2
                    continue

                # STEP 3: B OFF
                elif step == 2:
                    if "B_TRIGGER_REPORT" in signal and "CONF" not in signal and val == "OFF":
                        main_sequence.append(log)
                        step = 3
                    continue

                # STEP 4: CONF OFF
                elif step == 3:
                    if "B_TRIGGER_REPORT_CONF" in signal and val == "OFF":
                        main_sequence.append(log)
                        break  # done

            # ---------------------------------
            # Collect ALL other valid logs
            # ---------------------------------
            main_set = {log.original_index for log in main_sequence}

            final_logs = []

            for log in logs_in_range:
                item, signal = self.parse_item_signal(log.raw)

                if item != item_code:
                    continue

                # ✅ Always include the main sequence logs
                if log.original_index in main_set:
                    final_logs.append(log)
                    continue

                # ❌ Skip ANY extra B/CONF logs (outliers)
                if "B_TRIGGER_REPORT" in signal:
                    continue

                # ✅ Include everything else (W, IDs, etc.)
                final_logs.append(log)

            # ---------------------------------
            # Sort final logs by timestamp
            # ---------------------------------
            final_logs.sort(key=lambda x: x.ts or 0)

            self.display_logs(final_logs)

        # =====================================================
        # 🟢 W SEQUENCE
        # =====================================================
        else:
            subset = [
                log for log in logs_in_range
                if self.parse_item_signal(log.raw)[0] == item_code
            ]
            self.display_logs(subset)

        # ---------------------------------
        # BR handling (unchanged)
        # ---------------------------------
        if not self.br_tab.br_calls:
            return

        self.br_tab.show_all_brs()

        expected_brs = set(self.db.get_brs_for_item(item_code))

        if expected_brs:
            buffer_sec = 1
            start = st_ts - buffer_sec
            end = et_ts + buffer_sec

            executions_to_highlight = [
                e for e in self.br_tab.br_calls
                if e["br_name"] in expected_brs
                and start <= int(e["timestamp"].timestamp()) <= end
            ]

            if executions_to_highlight:
                if self.left_tabs.currentWidget() == self.br_tab:
                    self.br_tab.highlight_br_executions(executions_to_highlight)
                else:
                    self.pending_br_highlight = executions_to_highlight
                return

        if self.left_tabs.currentWidget() == self.br_tab:
            self.jump_br_view_to_timestamp(st_ts)
            self.br_tab.clear_highlight()
        else:
            self.pending_br_jump_ts = st_ts
            self.pending_br_highlight = None

    # -------------------
    # Build Item List
    # -------------------
    def build_item_list(self, force=False):
        self.item_list.setUpdatesEnabled(False)
        self.item_list.clear()

        # 🔥 Use index keys directly (fast)
        if not self.item_list_built_variable or force:
            self.items = sorted(self.item_index.keys())

        groups = {"EQP": [], "ROLLMAP": []}

        for item_code in self.items:
            category = self.db.get_item_category(item_code)
            groups.setdefault(category, []).append(item_code)

        # ----------------------------
        # 🔥 BUILD UI
        # ----------------------------
        for category in ["EQP", "ROLLMAP", "RMS"]:
            if not groups.get(category):
                continue

            # Header (non-clickable)
            header = QListWidgetItem(f"[{category}]")
            header.setFlags(Qt.NoItemFlags)
            self.item_list.addItem(header)

            for item_code in groups[category]:
                item_name = self.db.get_item_name(item_code)
                display_text = item_name if item_name else item_code

                list_item = QListWidgetItem(display_text)
                list_item.setData(Qt.UserRole, item_code)
                self.item_list.addItem(list_item)

        self.item_list.setUpdatesEnabled(True)

        self.item_list_built_variable = True


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
    def jump_to_log(self, index):
        if not index.isValid():
            return

        idx = index.data(Qt.UserRole)
        if idx is None:
            return

        # ----------------------------
        # Reset search (no re-trigger)
        # ----------------------------
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)

        self.update_period_from_logs()

        # ----------------------------
        # Ensure full log view
        # ----------------------------
        if self.log_model.logs != self.variable_logs:
            self.display_logs(self.variable_logs)

        # ----------------------------
        # Get model index
        # ----------------------------
        model_index = self.log_model.index(idx)
        if not model_index.isValid():
            return

        view = self.log_list

        # ----------------------------
        # 🔥 CORRECT CENTER SCROLL (Qt-native)
        # ----------------------------
        from PySide6.QtCore import QTimer

        def do_scroll():
            view.scrollTo(model_index, QListView.PositionAtCenter)
            view.setCurrentIndex(model_index)

        QTimer.singleShot(0, do_scroll)

        # ----------------------------
        # Reset BR view
        # ----------------------------
        if self.br_tab.br_calls:
            self.br_tab.show_all_brs()
            self.pending_br_highlight = None

        # ----------------------------
        # Save timestamp for BR sync
        # ----------------------------
        log = self.variable_logs[idx]
        if log.ts:
            self.pending_br_jump_ts = log.ts.timestamp()

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

            filtered = self.br_tab.br_name_index.get(data, [])

            self.br_tab.populate_tree_from_executions(filtered)
            self.reset_variable_view()
            return

        # -----------------------
        # Variable tab active
        # -----------------------
        item_code = data
        if not item_code:
            return

        # O(1) lookup instead of scanning all logs
        filtered = self.item_index.get(item_code, [])

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

    def reset_variable_view(self):
        if self.variable_logs:
            self.display_logs(self.variable_logs)

    def build_br_list(self, force=False):
        self.item_list.setUpdatesEnabled(False)   # 🔥 prevent UI redraw lag
        self.item_list.clear()

        if not self.br_tab.br_calls:
            self.item_list.setUpdatesEnabled(True)
            return

        if not self.item_list_built_br:
            self.br_names = sorted({execution["br_name"] for execution in self.br_tab.br_calls})

        for br in self.br_names:
            item = QListWidgetItem(br)
            item.setData(Qt.UserRole, br)
            self.item_list.addItem(item)

        self.item_list.setUpdatesEnabled(True)    # 🔥 re-enable UI updates

        self.item_list_built_br = True

    def on_left_tab_changed(self, index):
        self.current_tab = self.left_tabs.tabText(index)
        # -----------------------
        # BR TAB
        # -----------------------
        if self.br_logs_loading_finished == True and self.current_tab == "BR Logs":
            self.build_br_list()   

            if self.pending_br_highlight:
                self.br_tab.highlight_br_executions(self.pending_br_highlight)
                self.pending_br_highlight = None

            elif self.pending_br_jump_ts is not None:
                self.jump_br_view_to_timestamp(self.pending_br_jump_ts)
                self.pending_br_jump_ts = None

        # -----------------------
        # VARIABLE TAB
        # -----------------------
        elif self.variable_logs_loading_finished == True and self.current_tab == "Variable Logs":
            self.build_item_list()   # ✅ NO force (uses cache)

            if self.pending_variable_jump:
                self.jump_variable_view_to_timestamp(self.pending_variable_jump)
                self.pending_variable_jump = None
        else:
            self.item_list.clear()

    

    def jump_br_view_to_timestamp(self, ts):
        if not hasattr(self.br_tab, "sorted_exec_times"):
            return

        times = self.br_tab.sorted_exec_times
        executions = self.br_tab.sorted_executions

        if not times:
            return

        import bisect
        idx = bisect.bisect_left(times, ts)

        candidates = []
        if idx < len(times):
            candidates.append(idx)
        if idx > 0:
            candidates.append(idx - 1)

        best = None
        best_diff = float("inf")

        for i in candidates:
            diff = abs(times[i] - ts)
            if diff < best_diff:
                best_diff = diff
                best = executions[i]

        if best:
            self.br_tab.jump_to_execution(best)

    def jump_variable_view_to_timestamp(self, ts):
        if not self.variable_logs:
            return

        target_ts = int(ts.timestamp())

        closest_idx = None
        closest_diff = float("inf")

        # ----------------------------
        # Find closest log index
        # ----------------------------
        for i, log in enumerate(self.variable_logs):

            log_ts = log.ts
            if not log_ts:
                continue

            log_sec = int(log_ts.timestamp())
            diff = abs(log_sec - target_ts)

            if diff < closest_diff:
                closest_diff = diff
                closest_idx = i

        if closest_idx is None:
            return

        model_index = self.log_model.index(closest_idx)
        if not model_index.isValid():
            return

        view = self.log_list

        # ----------------------------
        # Switch to correct tab first
        # ----------------------------
        self.left_tabs.setCurrentWidget(self.log_list)

        # ----------------------------
        # 🔥 CORRECT CENTER SCROLL
        # ----------------------------
        from PySide6.QtCore import QTimer

        def do_scroll():
            view.scrollTo(model_index, QListView.PositionAtCenter)
            view.setCurrentIndex(model_index)

        QTimer.singleShot(0, do_scroll)


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
        Extract correct item code from log line.

        Example:
        [YNPARA_LOG:ParaUseYN_Log] → YNPARA_LOG
        [C1_4_DATE_TIME_SET_REQ:O_B_TRIGGER_DATE_TIME] → C1_4_DATE_TIME_SET_REQ
        """
        try:
            parts = raw.split("[")

            # We want the block that contains ":" (item:signal)
            for part in parts:
                if ":" in part and "]" in part:
                    block = part.split("]")[0]
                    return block.split(":")[0]

        except:
            pass

        return None


    def split_item_code(self, item_code):
        """
        G2_1_CARR_ID_RPT_01 → (G2_1_CARR_ID_RPT, 01)
        """
        match = re.match(r"(.+?)_(\d+)$", item_code)
        if match:
            return match.group(1), match.group(2)
        return item_code, None

    def reset_all_state(self):
        # Reset data structures
        self.variable_logs = []
        self.variable_timestamps = []
        self.br_logs = []
        self.sequences = {}
        self.items = set()
        self.item_index = {}
        self.br_names = []
        self.variable_logs_loading_finished = False
        self.br_logs_loading_finished = False
    
        # Reset cache flags
        self.br_list_built = False
        self.item_list_built = False
        self.item_list_built_variable = False
        self.item_list_built_br = False
        self.item_list_mode = None
        self.sequence_tree_built = False
    
        # Reset pending actions
        self.pending_br_jump_ts = None
        self.pending_br_highlight = None
        self.pending_variable_jump = None
    
        # Clear UI elements
        self.log_model.setLogs([])
        self.item_list.clear()
        self.seq_tree.clear()
    
        # Clear search
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)
    
        # Reset period to default
        self.period_start = QDateTime.currentDateTime().addSecs(-3600)
        self.period_end = QDateTime.currentDateTime()
        self.update_period_button()
    
        # Clear BR tab
        self.br_tab.tree.clear()
        self.br_tab.br_calls = []
        self.br_tab.br_name_index = {}
        self.br_tab.execution_item_map = {}
        self.br_tab.sorted_exec_times = []
        self.br_tab.sorted_executions = []
        self.br_tab.execution_by_second = {}
        self.br_tab.highlighted_item = None
        self.br_tab.last_displayed_ids = None
        self.br_tab._all_executions = []
        self.br_tab._current_page = 0
        self.br_tab.page_label.setText("Page 1 of 1")
    
        # Clear database
        self.db.clear_all()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = LogViewer()
    w.show()
    sys.exit(app.exec())