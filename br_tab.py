# br_tab.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem
from PySide6.QtCore import Qt
from datetime import datetime


class BRTab(QWidget):
    def __init__(self):
        super().__init__()

        layout = QVBoxLayout(self)


        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Business Rules"])
        self.tree.itemExpanded.connect(self.on_item_expanded)

        layout.addWidget(self.tree)

        # Full dataset (never overwritten)
        self.full_br_logs = []
        self.full_br_index = {}

        # Currently displayed subset
        self.br_calls = []
        self.br_index = {}
        self.txn_map = {}
    # ============================================================
    # 1️ Load FULL BR file (called once when BR file is opened)
    # ============================================================
    def load_full_logs(self, logs):
        self.full_br_logs = logs
        self.build_full_index(logs)

        # Parse once
        self.build_br_calls(logs)

        # Show everything
        self.populate_tree_from_executions(self.br_calls)

    # ============================================================
    # 2️ Build master index (fast lookup)
    # ============================================================
    def build_full_index(self, logs):
        self.full_br_index.clear()

        for log in logs:
            raw = log.raw

            if "BIZRULE" in raw:
                ts = self.extract_timestamp(raw)
                name = raw.split("BIZRULE]")[-1].strip()

                if name not in self.full_br_index:
                    self.full_br_index[name] = []

                self.full_br_index[name].append((ts, log))

    # ============================================================
    # 3️ Display subset (never touches full dataset)
    # ============================================================
    def display_logs(self, logs):
        self.br_calls.clear()
        self.br_index.clear()

        self.build_br_calls(logs)
        self.populate_tree_lazy()

    def show_all_brs(self):
        """
        Display every BR execution from the loaded BR log file.
        """
        if not self.full_br_logs:
            self.tree.clear()
            QTreeWidgetItem(self.tree, ["⚠ No BR log loaded"])
            return

        # Display the full dataset
        self.display_logs(self.full_br_logs)

    # ============================================================
    # 4️ Build call groups for display
    # ============================================================
    def build_br_calls(self, logs):

        self.br_calls = []

        current_execution = None
        current_table = None
        headers = []

        for log in logs:
            raw = log.raw.strip()

            # ----------------------------
            # Detect BIZRULE start
            # ----------------------------
            if "[BIZRULE]" in raw:

                ts = self.extract_timestamp(raw)
                br_name = raw.split("[BIZRULE]")[-1].strip()

                # Peek next table type later
                new_execution = {
                    "timestamp": ts,
                    "br_name": br_name,
                    "tables": {}
                }

                # Temporarily store but don't append yet
                current_execution = new_execution
                current_table = None
                headers = []

                self.br_calls.append(current_execution)

            # ----------------------------
            # Detect table
            # ----------------------------
            elif raw.startswith("Table Name"):

                parts = raw.split(":")
                if len(parts) >= 2:

                    table_name = parts[1].split("-")[0].strip()
                    current_table = table_name
                    headers = []

                    # If this is an OUT_ table and previous execution exists
                    if table_name.startswith("OUT_") and len(self.br_calls) >= 2:

                        prev = self.br_calls[-2]

                        # Same BR name → merge reply
                        if prev["br_name"] == current_execution["br_name"]:
                            prev["tables"][table_name] = []
                            current_execution = prev

                            # remove the duplicate execution we just created
                            self.br_calls.pop()

                    if current_execution:
                        current_execution["tables"][table_name] = []

            # ----------------------------
            # Detect header row
            # ----------------------------
            elif raw.startswith("[") and "]" in raw and current_table:

                headers = [h.strip("[]") for h in raw.split() if h.startswith("[")]

            # ----------------------------
            # Detect data row
            # ----------------------------
            elif raw.startswith("(") and current_table and headers:

                values = [v.strip("[]") for v in raw.split() if v.startswith("[")]

                row_dict = dict(zip(headers, values))

                current_execution["tables"][current_table].append(row_dict)

    # ============================================================
    # 5️ Lazy tree population
    # ============================================================
    def populate_tree_lazy(self):
        self.tree.clear()

        for execution in self.br_calls:

            root_text = f"{execution['timestamp'].strftime('%H:%M:%S.%f')[:-3]}  {execution['br_name']}"
            root_item = QTreeWidgetItem([root_text])
            self.tree.addTopLevelItem(root_item)

            for table_name, rows in execution["tables"].items():

                table_item = QTreeWidgetItem([table_name])
                root_item.addChild(table_item)

                for row in rows:
                    for col, val in row.items():
                        col_item = QTreeWidgetItem([f"{col}: {val}"])
                        table_item.addChild(col_item)

    def on_item_expanded(self, item):
        br_name = item.data(0, Qt.UserRole)

        if not br_name:
            return

        # Prevent duplicate expansion
        if item.childCount() > 0:
            return

        calls = self.br_index.get(br_name, [])

        for call in calls:
            call_item = QTreeWidgetItem(
                [f"Call @ {call['timestamp'].strftime('%H:%M:%S.%f')[:-3]}"]
            )

            for log in call["logs"]:
                log_item = QTreeWidgetItem([log.raw])
                call_item.addChild(log_item)

            item.addChild(call_item)

    # ============================================================
    # 6️ Show expected BRs only
    # ============================================================
    def show_expected_brs(self, expected_brs):
        self.tree.clear()

        for br in sorted(expected_brs):
            QTreeWidgetItem(self.tree, [f"{br} (Expected – Not Found)"])

    # ============================================================
    # 7️ Utility: extract timestamp
    # ============================================================
    def extract_timestamp(self, raw):
        try:
            ts_str = raw.split(" ")[0] + " " + raw.split(" ")[1]
            return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")
        except Exception:
            return datetime.min


    def populate_tree_from_executions(self, executions):
        self.tree.clear()
        for execution in executions:

            root_text = f"{execution['timestamp'].strftime('%H:%M:%S.%f')[:-3]}  {execution['br_name']}"
            root_item = QTreeWidgetItem([root_text])
            self.tree.addTopLevelItem(root_item)

            for table_name, rows in execution["tables"].items():

                table_item = QTreeWidgetItem([table_name])
                root_item.addChild(table_item)

                for row in rows:
                    for col, val in row.items():
                        col_item = QTreeWidgetItem([f"{col}: {val}"])
                        table_item.addChild(col_item)

    def show_brs_in_timerange(self, start_ts, end_ts, expected_brs=None):

        if not self.br_calls:
            self.tree.clear()
            return

        filtered = []

        for execution in self.br_calls:
            ts = execution["timestamp"].timestamp()

            if start_ts <= ts <= end_ts:

                # If DB has BRs saved → only show those
                if expected_brs and len(expected_brs) > 0:
                    if execution["br_name"] in expected_brs:
                        filtered.append(execution)

                # If DB has no BRs → show everything in range
                else:
                    filtered.append(execution)

        if filtered:
            self.populate_tree_from_executions(filtered)
            return

        # If DB expected BRs but none occurred
        if expected_brs:
            self.show_expected_brs(expected_brs)