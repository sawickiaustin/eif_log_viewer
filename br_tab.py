# br_tab.py
import bisect

from PySide6.QtWidgets import QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QHBoxLayout, QPushButton, QLabel
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor

from br_worker import BRLogWorker, encode_terms, execution_matches, ensure_tables, discard_temp

PAGE_SIZE = 200


class BRTab(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session = parent         # the LogSession this tab belongs to

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

        # File the byte offsets refer to + lowercase search buffer (set when
        # parsing finishes). For UTF-16 logs br_path is a UTF-8 temp copy.
        self.br_path = None
        self._temp_path = None
        self.search_buf = None

        # Kept for compatibility with app.py
        self.full_br_logs = []
        self.full_br_index = {}

        self.br_calls = []                 # all executions, sorted by ts_val
        self.br_name_index = {}
        self.execution_item_map = {}
        self.sorted_exec_times = []        # parallel to br_calls
        self.sorted_executions = []        # same list object as br_calls
        self.execution_by_second = {}      # unused, kept for app.reset_all_state
        self.highlighted_item = None
        self.last_displayed_ids = None

    def clear_tree(self):
        """
        Clear the tree AND forget what was displayed. Clearing only the widget
        left stale rows in execution_item_map and made the next show_all_brs()
        skip re-rendering, leaving the tab blank.
        """
        self.tree.clear()
        self.execution_item_map.clear()
        self.highlighted_item = None
        self.last_displayed_ids = None
        self._all_executions = []
        self._current_page = 0

    # ------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------
    def _prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._render_page()

    def _next_page(self):
        if not self._all_executions:
            return
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

        self.prev_btn.setEnabled(self._current_page > 0)
        self.next_btn.setEnabled(total > 0 and self._current_page < max_page)
        self.page_label.setText(
            f"Page {self._current_page + 1} of {max_page + 1}  "
            f"(showing {start + 1}–{min(end, total)} of {total:,})"
            if total > 0 else "No results"
        )

        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        self.highlighted_item = None
        self.execution_item_map.clear()

        items = []
        for execution in chunk:            # already in time order
            ts = execution["timestamp"]
            root_item = QTreeWidgetItem([f"{ts.strftime('%H:%M:%S.%f')[:-3]}  {execution['br_name']}"])
            root_item.setData(0, Qt.UserRole, execution)

            if execution["br_name"] == "BR_SYS_REG_BIZRULE_EXCEPTION":
                root_item.setBackground(0, QBrush(QColor("red")))
                root_item.setForeground(0, QBrush(QColor("white")))

            self.execution_item_map[id(execution)] = root_item
            root_item.addChild(QTreeWidgetItem(["Loading..."]))
            items.append(root_item)

        # Fixed: these used to run inside the loop, re-adding the list every iteration
        self.tree.addTopLevelItems(items)
        self.tree.setUpdatesEnabled(True)

    # ------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------
    def release_temp(self):
        """Delete the UTF-8 temp copy of a UTF-16 log, if this tab made one."""
        discard_temp(self._temp_path)
        self._temp_path = None

    def load_full_logs(self, filepath):
        # Release the previous file's buffer before parsing the next one
        self.search_buf = None
        self.br_path = None
        self.release_temp()
        self.br_calls = []
        self.br_name_index = {}
        self.sorted_exec_times = []
        self.sorted_executions = []
        self.clear_tree()
        QTreeWidgetItem(self.tree, ["⏳ Parsing BR log…"])

        self._br_worker = BRLogWorker(filepath)
        self._br_worker.finished.connect(self._on_br_calls_ready)
        self._br_worker.start()

    def _on_br_calls_ready(self, br_calls, meta):
        # Indexes were built in the worker thread; just store references.
        self.br_calls = br_calls
        self.br_path = meta["path"]
        self._temp_path = meta.get("temp_path")
        self.search_buf = meta["search_buf"]
        self.br_name_index = meta["name_index"]
        self.sorted_exec_times = meta["times"]
        self.sorted_executions = br_calls

        self.last_displayed_ids = None
        self.populate_tree_from_executions(self.br_calls)

        if hasattr(self._session, "on_br_loaded"):
            self._session.on_br_loaded()

    def show_all_brs(self):
        if not self.br_calls:
            self.clear_tree()
            QTreeWidgetItem(self.tree, ["⚠ No BR log loaded"])
            return
        self.populate_tree_from_executions(self.br_calls)

    def populate_tree_from_executions(self, executions):
        """Store executions and render the first page."""
        # O(1) check instead of building an id() list of every execution
        key = (id(executions), len(executions))
        if executions is self._all_executions and key == self.last_displayed_ids:
            return
        self.last_displayed_ids = key

        self._all_executions = executions
        self._current_page = 0
        self._render_page()

    def on_item_expanded(self, item):
        execution = item.data(0, Qt.UserRole)
        if not execution or item.childCount() > 1:
            return

        item.takeChildren()
        tables = ensure_tables(execution, self.br_path)

        for table_name, rows in tables.items():
            table_item = QTreeWidgetItem([table_name])
            item.addChild(table_item)
            for row in rows:
                for col, val in row.items():
                    table_item.addChild(QTreeWidgetItem([f"{col}: {val}"]))

    def show_expected_brs(self, expected_brs):
        self.clear_tree()
        for br in sorted(expected_brs):
            QTreeWidgetItem(self.tree, [f"{br} (Expected – Not Found)"])

    # ------------------------------------------------------------
    # Time-range + search (bisect on sorted times instead of full scans)
    # ------------------------------------------------------------
    def _time_slice(self, start_ts=None, end_ts=None):
        if start_ts is None or end_ts is None:
            return self.br_calls
        lo = bisect.bisect_left(self.sorted_exec_times, start_ts)
        hi = bisect.bisect_right(self.sorted_exec_times, end_ts)
        return self.br_calls[lo:hi]

    def show_brs_in_timerange(self, start_ts, end_ts, expected_brs=None):
        if not self.br_calls:
            self.clear_tree()
            return

        filtered = [
            e for e in self._time_slice(start_ts, end_ts)
            if not expected_brs or e["br_name"] in expected_brs
        ]

        if filtered:
            self.populate_tree_from_executions(filtered)
        elif expected_brs:
            self.show_expected_brs(expected_brs)

    def search_brs(self, keyword, start_ts=None, end_ts=None):
        if not keyword or self.search_buf is None:
            return None
        terms = encode_terms([keyword])
        buf = self.search_buf
        results = []
        for execution in self._time_slice(start_ts, end_ts):
            if execution_matches(buf, execution, terms, ()):
                results.append(execution)
                if len(results) >= 500:
                    break
        return results

    def search_brs_multi(self, and_terms, or_terms, start_ts, end_ts):
        if self.search_buf is None:
            return []
        and_b = encode_terms(and_terms)
        or_b = encode_terms(or_terms)
        buf = self.search_buf
        return [
            e for e in self._time_slice(start_ts, end_ts)
            if execution_matches(buf, e, and_b, or_b)
        ]

    # ------------------------------------------------------------
    # Highlight / navigation
    # ------------------------------------------------------------
    def highlight_br_executions(self, executions):
        if not executions:
            return

        idx = self._position(executions[0])
        target_page = idx // PAGE_SIZE if idx is not None else self._current_page

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
                item.setBackground(0, QBrush())
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

        if hasattr(self._session, "pending_variable_jump"):
            self._session.pending_variable_jump = ts

    def _position(self, execution):
        """Index of execution in the displayed list (bisect when it is br_calls)."""
        if self._all_executions is self.br_calls:
            ts = execution.get("ts_val")
            if ts is None:
                return None
            i = bisect.bisect_left(self.sorted_exec_times, ts)
            n = len(self.br_calls)
            while i < n and self.sorted_exec_times[i] == ts:
                if self.br_calls[i] is execution:
                    return i
                i += 1
            return None
        for i, e in enumerate(self._all_executions):
            if e is execution:
                return i
        return None

    def jump_to_execution(self, execution):
        """Navigate to the page containing this execution and scroll to it."""
        idx = self._position(execution)
        if idx is None:
            return
        target_page = idx // PAGE_SIZE

        if target_page != self._current_page:
            self._current_page = target_page
            self._render_page()

        item = self.execution_item_map.get(id(execution))
        if item:
            self.tree.scrollToItem(item, QTreeWidget.PositionAtCenter)
            self.tree.setCurrentItem(item)