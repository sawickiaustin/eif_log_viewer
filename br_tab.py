# br_tab.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QHBoxLayout, QPushButton, QLabel
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush
from datetime import datetime
import json
import re

PAGE_SIZE = 200

class BRTab(QWidget):
   

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)

        # Pagination controls
        nav_layout = QHBoxLayout()
        self.prev_btn = QPushButton("← Previous")
        self.next_btn = QPushButton("Next →")
        self.page_label = QLabel("Page 1 of 1")
        
        self.prev_btn.clicked.connect(self._prev_page)
        self.next_btn.clicked.connect(self._next_page)
        
        nav_layout.addWidget(self.prev_btn)
        nav_layout.addStretch()
        nav_layout.addWidget(self.page_label)
        nav_layout.addStretch()
        nav_layout.addWidget(self.next_btn)
        
        layout.addLayout(nav_layout)

        # Tree
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Business Rules"])
        self.tree.itemExpanded.connect(self.on_item_expanded)
        self.tree.itemClicked.connect(self.on_br_clicked)
        layout.addWidget(self.tree)

        # Pagination state
        self._current_page = 0
        self._all_executions = []

        # Full dataset (never overwritten)
        self.full_br_logs = []
        self.full_br_index = {}

        # Currently displayed subset
        self.br_calls = []
        self.br_index = {}
        self.txn_map = {}
        self.br_name_index = {}
        self.execution_item_map = {}
        self.sorted_exec_times = []
        self.sorted_executions = []

        self.execution_by_second = {}
        self.highlighted_item = None
        self.last_displayed_ids = None

    def _prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._render_page()

    def _next_page(self):
        max_page = (len(self._all_executions) - 1) // PAGE_SIZE
        if self._current_page < max_page:
            self._current_page += 1
            self._render_page()

    def _render_page(self):
        """Render only the current page of executions."""
        start = self._current_page * PAGE_SIZE
        end = start + PAGE_SIZE
        chunk = self._all_executions[start:end]
    
        total = len(self._all_executions)
        max_page = (total - 1) // PAGE_SIZE if total > 0 else 0
    
        # Update nav controls
        self.prev_btn.setEnabled(self._current_page > 0)
        self.next_btn.setEnabled(self._current_page < max_page)
        self.page_label.setText(
            f"Page {self._current_page + 1} of {max_page + 1}  "
            f"(showing {start + 1}–{min(end, total)} of {total:,})"
        )

        # Render chunk
        self.tree.setUpdatesEnabled(False)
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        self.execution_item_map.clear()

        items = []
        for execution in chunk:  # ← ADD reversed() HERE
            ts = execution["timestamp"]
            root_text = f"{ts.strftime('%H:%M:%S.%f')[:-3]}  {execution['br_name']}"
        
            root_item = QTreeWidgetItem([root_text])
            root_item.setData(0, Qt.UserRole, execution)
            self.execution_item_map[id(execution)] = root_item
            root_item.addChild(QTreeWidgetItem(["Loading..."]))
            items.append(root_item)

        self.tree.addTopLevelItems(items)
        self.tree.setSortingEnabled(True)
        self.tree.setUpdatesEnabled(True)

    def load_full_logs(self, filepath):
        self.full_br_logs = []
        self.full_br_index = {}
        self.br_calls = []
        self.br_name_index.clear()
        self.tree.clear()
        QTreeWidgetItem(self.tree, ["⏳ Parsing BR log…"])

        from worker import BRLogWorker
        self._br_worker = BRLogWorker(filepath)
        self._br_worker.finished.connect(self._on_br_calls_ready)
        self._br_worker.start()

    def _on_br_calls_ready(self, br_calls, full_br_index):  # ← Added full_br_index parameter
        self.br_calls = br_calls
        self.full_br_index = full_br_index  # ← Receive from worker
        self.br_name_index.clear()

        for execution in br_calls:
            ts_val = execution.get("ts_val")
            if ts_val is None:
                continue
            self.sorted_exec_times.append(ts_val)
            self.sorted_executions.append(execution)
            self.br_name_index.setdefault(execution["br_name"], []).append(execution)

        self.build_execution_index()
        self.populate_tree_from_executions(self.br_calls)

        main = self.window()
        if hasattr(main, "item_list_mode") and main.current_tab == "BR Logs":
            main.build_br_list()
        main.br_logs_loading_finished = True

    def build_execution_index(self):
        self.execution_by_second.clear()
        for execution in self.br_calls:
            sec = int(execution["ts_val"])
            self.execution_by_second.setdefault(sec, []).append(execution)

    def build_full_index(self, logs):
        self.full_br_index.clear()
        for log in logs:
            raw = log.raw
            if "BIZRULE" in raw:
                ts = self.extract_timestamp(raw)
                name = raw.split("BIZRULE]")[-1].strip()
                self.full_br_index.setdefault(name, []).append((ts, log))

    def display_logs(self, logs):
        self.br_calls.clear()
        self.br_index.clear()
        self.build_br_calls(logs)
        self.populate_tree_from_executions(self.br_calls)

    def show_all_brs(self):
        if not self.br_calls:
            self.tree.clear()
            QTreeWidgetItem(self.tree, ["⚠ No BR log loaded"])
            return
        self.populate_tree_from_executions(self.br_calls)

    def build_br_calls(self, logs):
        # This method is still here for display_logs compatibility
        # but is rarely used now that we have the worker
        self.br_calls = []
        self.br_name_index.clear()
        pending = {}
        uuid_re = re.compile(r"(?:ELTR\w*|ASSY\w*)\((.*?)\)")
        log_count = len(logs)
        i = 0

        while i < log_count:
            raw = logs[i].raw

            if "(REQUESTQ)" in raw:
                ts = self.extract_timestamp(raw)
                match = uuid_re.search(raw)
                if not match:
                    i += 1
                    continue

                uuid = match.group(1)
                block_lines = ["{"]
                i += 1

                while i < log_count:
                    line = logs[i].raw.strip()
                    block_lines.append(line)
                    if line == "}":
                        break
                    i += 1

                try:
                    request_json = json.loads("\n".join(block_lines))
                except Exception:
                    pending[uuid] = {"timestamp": ts, "br_name": "UNKNOWN", "tables": {}}
                    i += 1
                    continue

                br_name = request_json.get("actID", "UNKNOWN")
                tables = {}
                ref_json = request_json.get("refDS")

                if ref_json:
                    try:
                        ref_data = json.loads(ref_json)
                        for table_name, rows in ref_data.items():
                            tables[table_name] = [
                                {k: "" if v is None else str(v) for k, v in row.items()}
                                for row in rows
                            ]
                    except Exception:
                        pass

                pending[uuid] = {"timestamp": ts, "br_name": br_name, "tables": tables}

            elif "(RECEIVE_REPLYQ)" in raw:
                match = uuid_re.search(raw)
                if not match:
                    i += 1
                    continue

                uuid = match.group(1)
                execution = pending.get(uuid)
                if not execution:
                    i += 1
                    continue

                json_start = raw.find("{")
                if json_start == -1:
                    i += 1
                    continue

                try:
                    reply_json = json.loads(raw[json_start:])
                except Exception:
                    i += 1
                    continue

                pending.pop(uuid, None)

                for key, value in reply_json.items():
                    if not key.startswith("OUT_"):
                        continue
                    execution["tables"][key] = [
                        {k: "" if v is None else str(v) for k, v in row.items()}
                        for row in value
                    ]

                execution["search_blob"] = (
                    execution["br_name"] + " " + json.dumps(execution["tables"])
                ).casefold()

                self.br_calls.append(execution)
                self.br_name_index.setdefault(execution["br_name"], []).append(execution)

            i += 1

    def populate_tree_from_executions(self, executions):
        """Main entry point — store executions and render first page."""
        ids = [id(e) for e in executions]
        if ids == self.last_displayed_ids:
            return
        self.last_displayed_ids = ids

        self._all_executions = executions
        self._current_page = 0
        self._render_page()

    def on_item_expanded(self, item):
        execution = item.data(0, Qt.UserRole)
        if not execution or item.childCount() > 1:
            return

        item.takeChildren()
        tables = execution["tables"]

        for table_name, rows in tables.items():
            table_item = QTreeWidgetItem([table_name])
            item.addChild(table_item)
            for row in rows:
                for col, val in row.items():
                    table_item.addChild(QTreeWidgetItem([f"{col}: {val}"]))

    def show_expected_brs(self, expected_brs):
        self.tree.clear()
        for br in sorted(expected_brs):
            QTreeWidgetItem(self.tree, [f"{br} (Expected – Not Found)"])

    def extract_timestamp(self, raw):
        try:
            ts_str = raw.split(" ")[0] + " " + raw.split(" ")[1]
            return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")
        except Exception:
            return datetime.min

    def show_brs_in_timerange(self, start_ts, end_ts, expected_brs=None):
        if not self.br_calls:
            self.tree.clear()
            return

        filtered = [
            e for e in self.br_calls
            if start_ts <= e["ts_val"] <= end_ts
            and (not expected_brs or e["br_name"] in expected_brs)
        ]

        if filtered:
            self.populate_tree_from_executions(filtered)
        elif expected_brs:
            self.show_expected_brs(expected_brs)

    def search_brs(self, keyword, start_ts=None, end_ts=None):
        if not keyword:
            return None

        keyword = keyword.casefold()
        results = []

        if start_ts and end_ts:
            # Fixed: iterate dict items, not range
            for sec, executions in self.execution_by_second.items():
                if not (start_ts <= sec <= end_ts):
                    continue
                for execution in executions:
                    if keyword in execution.get("search_blob", ""):
                        results.append(execution)
                        if len(results) >= 500:  # cap results
                            return results
        else:
            for execution in self.br_calls:
                if keyword in execution.get("search_blob", ""):
                    results.append(execution)
                    if len(results) >= 500:
                        return results

        return results

    def highlight_br_executions(self, executions):
        if not executions:
            return

        # Find which page contains the first target
        try:
            idx = self._all_executions.index(executions[0])
            target_page = idx // PAGE_SIZE
        except (ValueError, IndexError):
            target_page = self._current_page

        if target_page != self._current_page:
            self._current_page = target_page
            self._render_page()

        self.clear_highlight()
        self.highlighted_item = []

        for e in executions:
            item = self.execution_item_map.get(id(e))
            if item:
                item.setBackground(0, QBrush(Qt.yellow))
                self.highlighted_item.append(item)

        if self.highlighted_item:
            self.tree.scrollToItem(self.highlighted_item[0], QTreeWidget.PositionAtCenter)

    def clear_highlight(self):
        if not self.highlighted_item:
            return

        items = self.highlighted_item if isinstance(self.highlighted_item, list) else [self.highlighted_item]
        for item in items:
            try:
                item.setBackground(0, QBrush())  # reset to default
            except RuntimeError:
                pass

        self.highlighted_item = None

    def on_br_clicked(self, item, column):
        exec_data = item.data(0, Qt.UserRole)
        if not exec_data:
            return

        ts = exec_data.get("timestamp")
        if not ts:
            return

        main_window = self.window()
        if hasattr(main_window, "pending_variable_jump"):
            main_window.pending_variable_jump = ts

    def jump_to_execution(self, execution):
        """Navigate to the page containing this execution and scroll to it."""
        target_ts = execution.get("ts_val")
        target_br = execution.get("br_name")
    
        if target_ts is None or target_br is None:
            return
    
        # Binary search for the timestamp
        import bisect
        idx = bisect.bisect_left(self.sorted_exec_times, target_ts)
    
        # Scan nearby for matching br_name (handles duplicate timestamps)
        target_idx = None
        for i in range(max(0, idx - 10), min(len(self.sorted_executions), idx + 10)):
            e = self.sorted_executions[i]
            if e.get("ts_val") == target_ts and e.get("br_name") == target_br:
                target_idx = i
                break
    
        if target_idx is None:
            return
    
        # Map from sorted_executions back to _all_executions
        # (they should be the same if both came from br_calls)
        target_execution = self.sorted_executions[target_idx]
    
        try:
            page_idx = self._all_executions.index(target_execution)
            target_page = page_idx // PAGE_SIZE
        except ValueError:
            # Fallback: scan _all_executions
            for i, e in enumerate(self._all_executions):
                if e.get("ts_val") == target_ts and e.get("br_name") == target_br:
                    target_page = i // PAGE_SIZE
                    target_execution = e
                    break
            else:
                return
    
        if target_page != self._current_page:
            self._current_page = target_page
            self._render_page()
    
        item = self.execution_item_map.get(id(target_execution))
        if item:
            self.tree.scrollToItem(item, QTreeWidget.PositionAtCenter)
            self.tree.setCurrentItem(item)