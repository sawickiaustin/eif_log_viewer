#app.py
import os
import sys
import re
from datetime import datetime, timedelta

from PySide6.QtWidgets import (
    QApplication, QWidget, QListWidget, QListWidgetItem,
    QHBoxLayout, QLabel, QVBoxLayout, QMainWindow,
    QFileDialog, QLineEdit, QPushButton,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QListView, QMessageBox,
    QStackedWidget, QDialog, QTextBrowser
)
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtCore import QDateTime, Qt, QAbstractListModel, QModelIndex, Signal

from parser import load_log_file
from period_dialog import PeriodDialog
from br_tab import BRTab
from br_worker import looks_like_br_log
from db_manager import DBManager
from PySide6.QtCore import QTimer
from model import LogListModel
from worker import VariableLogWorker

def resource_path(name):
    """Path to a bundled file, both from source and inside a PyInstaller exe."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


# ============================================================
# One tab = one log session (its own logs, BR calls, DB, workers)
# ============================================================
class LogSession(QWidget):
    titleChanged = Signal(object)          # emits self; LogViewer refreshes the tab text

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window

        self.var_path = None
        self.br_path = None
        self.var_loading = False
        self.br_loading = False
        self._var_worker = None

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
        self.variable_timestamps = []      # search_logs() needs this even in a BR-only tab
        self.item_index = {}
        self.br_logs = []
        self.sequences = {}
        self.item_categories = {} 

        self.period_start = QDateTime.currentDateTime().addSecs(-3600)
        self.period_end = QDateTime.currentDateTime()

        # -------------------
        # Search + Period
        # -------------------
        self.search_and_input = QLineEdit()
        self.search_and_input.setPlaceholderText("Include all (comma-separated)")
        self.search_and_input.returnPressed.connect(self._execute_search)

        self.search_or_input = QLineEdit()
        self.search_or_input.setPlaceholderText("Include any (comma-separated)")
        self.search_or_input.returnPressed.connect(self._execute_search)
        
        self.period_button = QPushButton()
        self.update_period_button()
        self.period_button.clicked.connect(self.open_period_dialog)

        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self._execute_search)

        top = QVBoxLayout()

        row = QHBoxLayout()
        row.addWidget(QLabel("Period"))
        row.addWidget(self.period_button)
        row.addWidget(QLabel("Match-AND"))
        row.addWidget(self.search_and_input)
        row.addWidget(QLabel("Match-OR"))
        row.addWidget(self.search_or_input)
        row.addWidget(self.search_button)

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
        self.right_tabs.addTab(self.item_list, "Item")

        self.seq_tree = QTreeWidget()
        self.seq_tree.setHeaderLabel("Sequences")
        self.seq_tree.itemClicked.connect(self.on_sequence_clicked)
        self.right_tabs.addTab(self.seq_tree, "Sequence")

        self.pending_variable_jump = None

        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._execute_search)

        # -------------------
        # Layout
        # -------------------
        body = QHBoxLayout()
        body.addWidget(self.left_tabs, 4)
        body.addWidget(self.right_tabs, 2)

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addLayout(body)

        layout.setContentsMargins(6, 6, 6, 6)
        self.setLayout(layout)

        # Each session has its own in-memory DB: two tabs can be different equipment
        self.db = DBManager(":memory:")

    # -------------------
    # Session helpers
    # -------------------
    def _status(self, msg, ms=0):
        self.main.statusBar().showMessage(msg, ms)

    def title(self):
        name = os.path.basename(self.var_path or self.br_path or "") or "New session"
        if self.br_path and self.var_path:
            name += "  + BR"
        if self.var_loading or self.br_loading:
            name = "⏳ " + name
        return name

    def tooltip(self):
        parts = []
        if self.var_path:
            parts.append(f"Variable: {self.var_path}")
        if self.br_path:
            parts.append(f"BR: {self.br_path}")
        return "\n".join(parts)

    def on_br_loaded(self):
        """Called by BRTab when its worker finishes."""
        self.br_loading = False
        self.br_logs_loading_finished = True

        # No variable log to take the period from: use the BR file's own range,
        # otherwise the default "last hour" period hides every BR call.
        if not self.var_path and self.br_tab.sorted_exec_times:
            times = self.br_tab.sorted_exec_times
            self.period_start = QDateTime.fromMSecsSinceEpoch(int(times[0] * 1000))
            self.period_end = QDateTime.fromMSecsSinceEpoch(int(times[-1] * 1000)).addSecs(1)
            self.update_period_button()

        if self.current_tab == "BR Logs":
            self.build_br_list()
        self._status(f"Loaded {len(self.br_tab.br_calls):,} BR calls.", 4000)
        self.titleChanged.emit(self)

    def running_workers(self):
        workers = [self._var_worker, getattr(self.br_tab, "_br_worker", None)]
        return [w for w in workers if w is not None and w.isRunning()]

    def shutdown(self):
        """
        Detach still-running workers so their results are dropped when they finish,
        and hand them back so the window can keep them alive until then (a QThread
        destroyed while running crashes the app).
        """
        running = self.running_workers()
        for w in running:
            try:
                w.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
        # Drop the big data now rather than when Python gets around to it
        self.variable_logs = []
        self.variable_timestamps = []
        self.item_index = {}
        self.sequences = {}
        self.br_tab.br_calls = []
        self.br_tab._all_executions = []
        self.br_tab.sorted_executions = []
        self.br_tab.br_name_index = {}
        self.br_tab.search_buf = None
        self.br_tab.release_temp()         # UTF-8 copy of a UTF-16 BR log
        return running

    # -------------------
    # Menu
    # -------------------
    def load_br_log(self, path):
        # Reads the first lines in the file's own encoding (UTF-8 or UTF-16)
        if not looks_like_br_log(path):
            QMessageBox.critical(
                self,
                "Invalid BR Log",
                "The selected file is not a valid BR log.\n"
            )
            return False

        self.br_path = path
        self.br_loading = True
        self.br_logs_loading_finished = False
        self.item_list_built_br = False    # rebuild the BR name list from the new file
        self.titleChanged.emit(self)

        # Pass path to BR tab
        self.br_tab.load_full_logs(path)
        return True

    # -------------------
    # File Loading
    # -------------------
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
        # Only clear variable-side state, so a BR log already in this tab stays loaded
        self.reset_variable_state()
        self.var_path = path
        self.var_loading = True
        self.titleChanged.emit(self)

        # Show loading indicator
        self.log_model.setLogs([])
        self.log_loading_label.show()
        self.log_list.hide()

        # 🔥 Pass filepath, not logs
        self._var_worker = VariableLogWorker(path)
        self._var_worker.finished.connect(self._on_variable_log_ready)
        self._var_worker.start()

    def _on_variable_log_ready(self, sorted_logs, sorted_timestamps, item_index, current_equipment, skipped_count, sequences, item_categories):
        # Hide loading indicator
        self.log_loading_label.hide()
        self.log_list.show()

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
        self.item_categories = item_categories  

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
        self.var_loading = False
        self.titleChanged.emit(self)

        self._status(
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

        and_raw = self.search_and_input.text().strip()
        or_raw  = self.search_or_input.text().strip()

        and_terms = [t.strip().casefold() for t in and_raw.split(",") if t.strip()]
        or_terms  = [t.strip().casefold() for t in or_raw.split(",")  if t.strip()]

        start = self.period_start.toPython()
        end   = self.period_end.toPython()

        start_ts = start.timestamp()
        end_ts   = end.timestamp()

        left  = bisect.bisect_left(self.variable_timestamps, start_ts)
        right = bisect.bisect_right(self.variable_timestamps, end_ts)
        subset = self.variable_logs[left:right]

        result = []
        for log in subset:
            raw_lower = log.raw_lower

            # AND: every term must match
            if and_terms and not all(t in raw_lower for t in and_terms):
                continue

            # OR: at least one term must match (skip check if no OR terms)
            if or_terms and not any(t in raw_lower for t in or_terms):
                continue

            result.append(log)

        self.display_logs(result)

        # BR sync
        if not self.br_tab.br_calls:
            return

        if not and_terms and not or_terms:
            self.br_tab.show_brs_in_timerange(start_ts, end_ts)
            return

        br_results = self.br_tab.search_brs_multi(and_terms, or_terms, start_ts, end_ts)
        if br_results:
            self.br_tab.populate_tree_from_executions(br_results)
        else:
            self.br_tab.clear_tree()

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

            # 🔥 FIX: Use item_categories directly instead of database
            category = self.item_categories.get(item_code, "EQP")

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
                child.setData(0, Qt.UserRole, seq)

                if seq.get("error"):
                    from PySide6.QtGui import QBrush, QColor
                    child.setForeground(0, QBrush(QColor("red")))

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
        self.search_and_input.blockSignals(True)
        self.search_or_input.blockSignals(True)
        self.search_and_input.clear()
        self.search_or_input.clear()
        self.search_and_input.blockSignals(False)
        self.search_or_input.blockSignals(False)

        self.update_period_from_logs()

        st_ts = st.timestamp()
        et_ts = et.timestamp()

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
            core_set = set(seq.get("core_indices", []))

            final_logs = []
            for log in logs_in_range:
                item_c, signal = self.parse_item_signal(log.raw)

                if item_c != item_code:
                    continue

                # Always include this sequence's exact core logs
                if log.original_index in core_set:
                    final_logs.append(log)
                    continue

                # Drop any B/CONF logs that aren't part of THIS sequence
                if "B_TRIGGER_REPORT" in signal:
                    continue

                # Include non-B context (W events, IDs, etc.)
                final_logs.append(log)

            final_logs.sort(key=lambda x: x.ts or datetime.min)
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

            import bisect
            times = self.br_tab.sorted_exec_times
            lo = bisect.bisect_left(times, start)
            hi = bisect.bisect_left(times, end + 1)
            executions_to_highlight = [
                e for e in self.br_tab.br_calls[lo:hi]
                if e["br_name"] in expected_brs
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
        self.search_and_input.blockSignals(True)
        self.search_or_input.blockSignals(True)
        self.search_and_input.clear()
        self.search_or_input.clear()
        self.search_and_input.blockSignals(False)
        self.search_or_input.blockSignals(False)

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

        self.search_and_input.blockSignals(True)
        self.search_or_input.blockSignals(True)
        self.search_and_input.clear()
        self.search_or_input.clear()
        self.search_and_input.blockSignals(False)
        self.search_or_input.blockSignals(False)

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
        self.left_tabs.setCurrentWidget(self.log_container)

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
        from db_manager import COMMON_DATA, EQP_DATA

        # Build known bases set (all keys from static data)
        known_bases = set()
        for cat_items in COMMON_DATA.values():
            known_bases.update(cat_items.keys())
        for eqp_data in EQP_DATA.values():
            if isinstance(eqp_data, dict):
                for cat_items in eqp_data.values():
                    if isinstance(cat_items, dict):
                        known_bases.update(cat_items.keys())

        # Longest matching prefix wins
        parts = item_code.split("_")
        for i in range(len(parts) - 1, 0, -1):
            base = "_".join(parts[:i])
            if base in known_bases:
                suffix = "_".join(parts[i:])
                return base, suffix

        return item_code, None

    def _clear_search_inputs(self):
        self.search_and_input.blockSignals(True)
        self.search_or_input.blockSignals(True)
        self.search_and_input.clear()
        self.search_or_input.clear()
        self.search_and_input.blockSignals(False)
        self.search_or_input.blockSignals(False)

    def reset_variable_state(self):
        """Clear everything that came from the variable log. The BR log stays loaded."""
        self.variable_logs = []
        self.variable_timestamps = []
        self.sequences = {}
        self.item_categories = {}
        self.items = set()
        self.item_index = {}
        self.variable_logs_loading_finished = False

        # Reset cache flags
        self.item_list_built = False
        self.item_list_built_variable = False
        self.sequence_tree_built = False

        # Pending jumps/highlights were worked out from the old variable log
        self.pending_br_jump_ts = None
        self.pending_br_highlight = None
        self.pending_variable_jump = None

        # Clear UI elements
        self.log_model.setLogs([])
        self.seq_tree.clear()
        if self.current_tab == "Variable Logs":
            self.item_list.clear()        # on the BR tab this list shows BR names: keep it

        self._clear_search_inputs()

        # The item → BR mapping comes from the variable log's equipment
        self.db.clear_all()

        # Search was cleared, so show every BR call again (if a BR log is loaded)
        self.br_tab.clear_highlight()
        if self.br_tab.br_calls:
            self.br_tab.show_all_brs()

    def reset_br_state(self):
        """Clear everything that came from the BR log."""
        self.br_logs = []
        self.br_names = []
        self.br_logs_loading_finished = False
        self.br_list_built = False
        self.item_list_built_br = False
        self.item_list_mode = None

        self.br_tab.clear_tree()
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

    def reset_all_state(self):
        """Clear both the variable log and the BR log."""
        self.reset_br_state()
        self.reset_variable_state()
        self.item_list.clear()

        # Reset period to default
        self.period_start = QDateTime.currentDateTime().addSecs(-3600)
        self.period_end = QDateTime.currentDateTime()
        self.update_period_button()


# ============================================================
# Main window: one tab per log session
# ============================================================
class LogViewer(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("EIF Log Viewer")
        self.resize(1200, 800)
        self.setWindowIcon(QIcon(resource_path("icon.ico")))

        # Sessions
        self.sessions = QTabWidget()
        self.sessions.setTabsClosable(True)
        self.sessions.setMovable(True)
        self.sessions.setDocumentMode(True)
        self.sessions.tabCloseRequested.connect(self.close_session)
        self.sessions.currentChanged.connect(self._on_session_changed)

        # Shown when no sessions are open
        placeholder = QLabel(
            "No logs open.\n\n"
            "File → Open Variable Log…   (Ctrl+O)\n"
            "File → Open Variable + BR Log…   (Ctrl+Shift+O)\n"
            "File → Open BR Log…   (Ctrl+Shift+B)"
        )
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet("QLabel { color: #888; font-size: 14px; }")

        self.stack = QStackedWidget()
        self.stack.addWidget(placeholder)
        self.stack.addWidget(self.sessions)
        self.setCentralWidget(self.stack)

        # Workers from closed tabs that are still parsing. They are kept
        # referenced until they finish; destroying a running QThread crashes.
        self._retired_workers = []
        self._reaper = QTimer(self)
        self._reaper.timeout.connect(self._reap_workers)
        self._reaper.start(1000)

        self.create_menu()
        self.statusBar().showMessage("Ready")

    # -------------------
    # Menu
    # -------------------
    def create_menu(self):
        bar = self.menuBar()
        file_menu = bar.addMenu("File")

        open_var_action = QAction("Open Variable Log…", self)
        open_var_action.setShortcut(QKeySequence("Ctrl+O"))
        open_var_action.triggered.connect(self.open_variable_log)
        file_menu.addAction(open_var_action)

        open_br_action = QAction("Open BR Log…", self)
        open_br_action.setShortcut(QKeySequence("Ctrl+B"))
        open_br_action.triggered.connect(self.open_br_log)
        file_menu.addAction(open_br_action)

        open_pair_action = QAction("Open Variable + BR Log…", self)
        open_pair_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        open_pair_action.triggered.connect(self.open_variable_and_br_log)
        file_menu.addAction(open_pair_action)

        file_menu.addSeparator()

        self.add_var_action = QAction("Add Variable Log to Current Tab…", self)
        self.add_var_action.setShortcut(QKeySequence("Ctrl+Shift+V"))
        self.add_var_action.triggered.connect(self.add_variable_log_to_current)
        file_menu.addAction(self.add_var_action)

        self.add_br_action = QAction("Add BR Log to Current Tab…", self)
        self.add_br_action.setShortcut(QKeySequence("Ctrl+Shift+B"))
        self.add_br_action.triggered.connect(self.add_br_log_to_current)
        file_menu.addAction(self.add_br_action)

        file_menu.addSeparator()

        self.close_tab_action = QAction("Close Tab", self)
        self.close_tab_action.setShortcut(QKeySequence("Ctrl+W"))
        self.close_tab_action.triggered.connect(
            lambda: self.close_session(self.sessions.currentIndex())
        )
        file_menu.addAction(self.close_tab_action)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        help_menu = bar.addMenu("Help")
        about_action = QAction("About Log Types…", self)
        about_action.triggered.connect(self.show_help_dialog)
        help_menu.addAction(about_action)

        self._update_actions()

    # -------------------
    # Sessions
    # -------------------
    def current_session(self):
        w = self.sessions.currentWidget()
        return w if isinstance(w, LogSession) else None

    def new_session(self):
        session = LogSession(self)
        session.titleChanged.connect(self._refresh_tab)
        index = self.sessions.addTab(session, session.title())
        self.sessions.setCurrentIndex(index)
        self.stack.setCurrentWidget(self.sessions)
        self._update_actions()
        return session

    def _refresh_tab(self, session):
        index = self.sessions.indexOf(session)
        if index < 0:
            return
        self.sessions.setTabText(index, session.title())
        self.sessions.setTabToolTip(index, session.tooltip())
        if session is self.current_session():
            self._update_window_title()

    def _on_session_changed(self, index):
        self._update_window_title()
        self._update_actions()

    def _update_window_title(self):
        session = self.current_session()
        if session is None:
            self.setWindowTitle("EIF Log Viewer")
        else:
            self.setWindowTitle(f"EIF Log Viewer — {session.title().lstrip('⏳ ')}")

    def _update_actions(self):
        has_session = self.current_session() is not None
        if hasattr(self, "add_br_action"):
            self.add_var_action.setEnabled(has_session)
            self.add_br_action.setEnabled(has_session)
            self.close_tab_action.setEnabled(has_session)

    def close_session(self, index):
        session = self.sessions.widget(index)
        if not isinstance(session, LogSession):
            return
        self._retired_workers.extend(session.shutdown())
        self.sessions.removeTab(index)
        session.deleteLater()
        if self.sessions.count() == 0:
            self.stack.setCurrentIndex(0)
            self.statusBar().showMessage("Ready")
        self._update_window_title()
        self._update_actions()

    def _reap_workers(self):
        if self._retired_workers:
            self._retired_workers = [w for w in self._retired_workers if w.isRunning()]

    def closeEvent(self, event):
        running = list(self._retired_workers)
        for i in range(self.sessions.count()):
            running.extend(self.sessions.widget(i).shutdown())
        running = [w for w in running if w.isRunning()]
        if running:
            # Parsing can't be interrupted mid-way; let it finish so Qt doesn't
            # abort on a running QThread at exit.
            self.statusBar().showMessage("Waiting for files still being parsed…")
            QApplication.processEvents()
            for w in running:
                w.wait()
        event.accept()

    # -------------------
    # File menu actions (each opens a new tab)
    # -------------------
    def open_variable_log(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Variable Log", "", "Log Files (*.log)"
        )
        if path:
            self.new_session().load_variable_log(path)

    def open_variable_and_br_log(self):
        var_path, _ = QFileDialog.getOpenFileName(
            self, "Select Variable Log", "", "Log Files (*.log)"
        )
        if not var_path:
            return

        br_path, _ = QFileDialog.getOpenFileName(
            self, "Select BR Log", os.path.dirname(var_path), "Log Files (*.log)"
        )
        if not br_path:
            return

        session = self.new_session()
        session.load_variable_log(var_path)
        session.load_br_log(br_path)

    def open_br_log(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open BR Log", "", "Log Files (*.log)"
        )
        if not path:
            return

        session = self.new_session()
        session.left_tabs.setCurrentWidget(session.br_tab)   # nothing to show on the Variable tab
        if not session.load_br_log(path):
            # Not a valid BR log: don't leave an empty tab behind
            self.close_session(self.sessions.indexOf(session))

    def add_variable_log_to_current(self):
        session = self.current_session()
        if session is None:
            return
        if session.var_loading:
            # Replacing the worker while it runs would destroy a running QThread
            QMessageBox.information(self, "Variable Log", "This tab is still loading its variable log.")
            return

        start_dir = os.path.dirname(session.br_path or session.var_path or "")
        path, _ = QFileDialog.getOpenFileName(
            self, "Add Variable Log", start_dir, "Log Files (*.log)"
        )
        if path:
            session.load_variable_log(path)
            session.left_tabs.setCurrentWidget(session.log_container)   # show the loading indicator

    def add_br_log_to_current(self):
        session = self.current_session()
        if session is None:
            return
        if session.br_loading:
            QMessageBox.information(self, "BR Log", "This tab is still loading its BR log.")
            return

        start_dir = os.path.dirname(session.var_path or session.br_path or "")
        path, _ = QFileDialog.getOpenFileName(
            self, "Add BR Log", start_dir, "Log Files (*.log)"
        )
        if path:
            session.load_br_log(path)

    # -------------------
    # Help
    # -------------------
    def show_help_dialog(self):
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QPushButton

        dlg = QDialog(self)
        dlg.setWindowTitle("Help — Log Types")
        dlg.resize(600, 500)

        text = QTextBrowser()
        text.setOpenExternalLinks(False)
        text.setHtml("""
    <h2>Variable Log</h2>
    <p>A <b>Variable Log</b> records the real-time state changes of equipment items (variables)
    during production. Each line contains a timestamp, a system identifier, an item code,
    a signal name, and the new value.</p>
    <p><b>Variable Trace Log Path Example</b></p>
    <p>D:\\Logs\\A1EROL101\\ezControl\\System\\VARIABLE_TRACE\\VARIABLE_TRACE_0115.log</p>
    <p><b>Example Log Line:</b></p>
    <pre>2024-01-15 08:32:11 [A1EROL101.Elm][ITEM_A:I_B_TRIGGER_REPORT] : ON</pre>

    <hr>

    <h2>BR Log (Business Rule Log)</h2>
    <p>A <b>BR Log</b> records calls to Business Rules (BR) — the logic layer that processes
    equipment events and makes decisions. Each entry captures the full request (input tables)
    and reply (output tables) of a BR execution.</p>
    <p><b>BR Log Path Example</b></p>
    <p>D:\\Logs\\A1EROL101\\ezControl\\A1EROL101_0115.log</p>
    <p><b>Example Log Line:</b></p>
    <pre>
    2024-01-15 08:32:11 [Info] [A1EROL101] (REQUESTQ) PROC_TYPE/LGES_PRD_MES/MES_EIF/ELTR
    (abc125323-21b1-426e-8b28-57c080b1cf93) : {
      "actID": "BR_PRD_REG_EQPT_WIPQTY",
      "refDS": "{\"IN_EQP\":[{\"SRCTYPE\":\"EQ\",\"IFMODE\":\"ON\",\"EQPTID\":\"A1EROL101\",\"USERID\":\"EIF\"}]}",
      "inDTName": "IN_EQP",
      "outDTName": "",
      "TXN_ID": "20240115000000123123123123"
    }

    2024-01-15 08:32:13 [Info] [A1EROL101] (RECEIVE_REPLYQ) REPLY/PROC_TYPE/LGES_PRD_MES/MES_EIF/ELTR
    (abc125323-21b1-426e-8b28-57c080b1cf93) : {
      "actID":"BR_PRD_REG_EQPT_WIPQTY","schema":{}}</pre>

    <hr>

    <h2>Using them together</h2>
    <p>Load a Variable Log and BR Log together via <b>File → Open Variable + BR Log</b>.<br>
    To look at a BR log by itself, use <b>File → Open BR Log</b>.<br>
    To pair files in a tab that is already open, use <b>File → Add Variable Log to Current Tab</b>
    or <b>File → Add BR Log to Current Tab</b>.<br>
    Each file you open gets its own tab, so several sessions can be open side by side.<br>
    Clicking a sequence in the Sequence tab will automatically highlight the corresponding
    BR calls that fired during that time window.</p>
    """)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)

        main_layout = QVBoxLayout(dlg)
        main_layout.addWidget(text)
        main_layout.addWidget(close_btn)

        dlg.exec()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()

    app = QApplication(sys.argv)
    w = LogViewer()
    w.show()
    sys.exit(app.exec())