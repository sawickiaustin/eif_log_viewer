# br_tab.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem
from PySide6.QtCore import Qt
from datetime import datetime
import json
import re


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

        self.execution_by_second = {}
    # ============================================================
    # 1️ Load FULL BR file (called once when BR file is opened)
    # ============================================================
    def load_full_logs(self, logs):
        self.full_br_logs = logs
        self.build_full_index(logs)

        # Parse once
        self.build_br_calls(logs)
        self.build_execution_index()

        # Show everything
        self.populate_tree_from_executions(self.br_calls)


    def build_execution_index(self):
        self.execution_by_second.clear()

        for execution in self.br_calls:
            sec = int(execution["timestamp"].timestamp())

            if sec not in self.execution_by_second:
                self.execution_by_second[sec] = []

            self.execution_by_second[sec].append(execution)

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
        Uses the already parsed execution list.
        """
        if not self.br_calls:
            self.tree.clear()
            QTreeWidgetItem(self.tree, ["⚠ No BR log loaded"])
            return

        self.populate_tree_from_executions(self.br_calls)

    # ============================================================
    # 4️ Build call groups for display
    # ============================================================
    def build_br_calls(self, logs):

        self.br_calls = []
        pending = {}

        uuid_re = re.compile(r"(?:ELTR|ASSY)\((.*?)\)")

        logs_local = logs
        log_count = len(logs_local)

        i = 0

        while i < log_count:

            raw = logs_local[i].raw

            # ------------------------------------------------
            # REQUESTQ
            # ------------------------------------------------
            if "(REQUESTQ)" in raw:

                ts = self.extract_timestamp(raw)

                match = uuid_re.search(raw)
                if not match:
                    i += 1
                    continue

                uuid = match.group(1)

                block_lines = ["{"]
                i += 1

                # capture JSON block
                while i < log_count:

                    line = logs_local[i].raw.strip()
                    block_lines.append(line)

                    if line == "}":
                        break

                    i += 1

                try:
                    request_json = json.loads("\n".join(block_lines))
                except Exception:
                    pending[uuid] = {
                        "timestamp": ts,
                        "br_name": "UNKNOWN",
                        "tables": {}
                    }
                    i += 1
                    continue

                br_name = request_json.get("actID", "UNKNOWN")

                tables = {}
                ref_json = request_json.get("refDS")

                if ref_json:
                    try:
                        ref_data = json.loads(ref_json)

                        for table_name, rows in ref_data.items():

                            parsed_rows = []

                            for row in rows:
                                parsed_rows.append({
                                    k: "" if v is None else str(v)
                                    for k, v in row.items()
                                })

                            tables[table_name] = parsed_rows

                    except Exception:
                        pass

                pending[uuid] = {
                    "timestamp": ts,
                    "br_name": br_name,
                    "tables": tables
                }

            # ------------------------------------------------
            # RECEIVE_REPLYQ
            # ------------------------------------------------
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

                    rows = []

                    for row in value:
                        rows.append({
                            k: "" if v is None else str(v)
                            for k, v in row.items()
                        })

                    execution["tables"][key] = rows

                self.br_calls.append(execution)

            i += 1

    # ============================================================
    # 5️ Lazy tree population
    # ============================================================
    def populate_tree_from_executions(self, executions):

        self.tree.setUpdatesEnabled(False)
        self.tree.clear()

        for execution in executions:

            root_text = f"{execution['timestamp'].strftime('%H:%M:%S.%f')[:-3]}  {execution['br_name']}"

            root_item = QTreeWidgetItem([root_text])

            # store execution for lazy loading
            root_item.setData(0, Qt.UserRole, execution)

            # dummy child so expand arrow appears
            root_item.addChild(QTreeWidgetItem(["Loading..."]))

            self.tree.addTopLevelItem(root_item)

        self.tree.setUpdatesEnabled(True)

    def on_item_expanded(self, item):
        execution = item.data(0, Qt.UserRole)

        if not execution:
            return

        # if already populated
        if item.childCount() > 1:
            return

        item.takeChildren()

        tables = execution["tables"]

        for table_name, rows in tables.items():

            table_item = QTreeWidgetItem([table_name])
            item.addChild(table_item)

            for row in rows:
                for col, val in row.items():
                    table_item.addChild(QTreeWidgetItem([f"{col}: {val}"]))

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

    def search_brs(self, keyword, start_ts=None, end_ts=None):
        """
        Search BR executions by:
        - BR name
        - table names
        - column names
        - column values
        """

        if not keyword:
            return None

        keyword = keyword.casefold()

        results = []

        for execution in self.br_calls:

            ts_val = execution["timestamp"].timestamp()

            # Apply time range filter
            if start_ts and ts_val < start_ts:
                continue

            if end_ts and ts_val > end_ts:
                continue

            # ----------------------------
            # Search BR name
            # ----------------------------
            if keyword in execution["br_name"].casefold():
                results.append(execution)
                continue

            # ----------------------------
            # Search tables
            # ----------------------------
            tables = execution["tables"]
            found = False

            for table_name, rows in tables.items():

                # table name match
                if keyword in table_name.casefold():
                    found = True
                    break

                for row in rows:
                    for col, val in row.items():

                        if keyword in col.casefold():
                            found = True
                            break

                        if keyword in val.casefold():
                            found = True
                            break

                    if found:
                        break

                if found:
                    break

            if found:
                results.append(execution)

        return results