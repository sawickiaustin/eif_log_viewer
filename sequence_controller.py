# sequence_controller.py
"""
시퀀스 트리 빌드 및 클릭 이벤트 전담 컨트롤러.
- _populate_sequence_tree()
- 시퀀스 클릭 → 로그 필터 + BR 하이라이트
"""
from datetime import datetime, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem


class SequenceController:
    def __init__(self, page):
        self.page = page

    # 편의 프로퍼티
    @property
    def _lc(self):
        return self.page.log_ctrl

    @property
    def _db(self):
        return self.page.db

    # =========================================================
    # logs 로드 완료 시 호출
    # =========================================================
    def on_logs_loaded(self):
        self.populate_sequence_tree()

    # =========================================================
    # 시퀀스 트리 빌드
    # =========================================================
    def populate_sequence_tree(self, force=False):
        if self._lc.sequence_tree_built and not force:
            return

        seq_tree = self.page.seq_tree
        seq_tree.setUpdatesEnabled(False)
        seq_tree.clear()

        group_nodes = {}
        for item_code, seqs in sorted(self._lc.sequences.items()):
            category = self._lc.item_categories.get(item_code, "EQP")

            if category not in group_nodes:
                group_nodes[category] = QTreeWidgetItem([category])
                seq_tree.addTopLevelItem(group_nodes[category])

            item_name    = self._db.get_item_name(item_code)
            display_text = item_name if item_name else item_code

            parent = QTreeWidgetItem([display_text])
            parent.setData(0, Qt.UserRole, item_code)
            group_nodes[category].addChild(parent)

            for seq in sorted(seqs, key=lambda x: x["start"]):
                label = f"[{seq['type']}] {seq['start'].strftime('%Y-%m-%d %H:%M:%S')}"
                child = QTreeWidgetItem([label])
                child.setData(0, Qt.UserRole, seq)
                if seq.get("error"):
                    from PySide6.QtGui import QBrush, QColor
                    child.setForeground(0, QBrush(QColor("red")))
                parent.addChild(child)

        seq_tree.setUpdatesEnabled(True)
        self._lc.sequence_tree_built = True

    # =========================================================
    # 시퀀스 클릭
    # =========================================================
    def on_sequence_clicked(self, item):
        import bisect

        parent = item.parent()
        if not parent:
            return

        item_code = parent.data(0, Qt.UserRole)
        seq       = item.data(0, Qt.UserRole)
        if not isinstance(seq, dict):
            return

        st = seq["start"]
        et = seq["end"]

        if seq["type"] == "B":
            buffer_sec = 1
            st = seq["start"] - timedelta(seconds=buffer_sec)
            et = seq["end"]   + timedelta(seconds=buffer_sec)

        if not st or not et:
            return

        self.page.search_input.blockSignals(True)
        self.page.search_input.clear()
        self.page.search_input.blockSignals(False)

        st_ts = st.timestamp()
        et_ts = et.timestamp()

        left  = bisect.bisect_left(self._lc.variable_timestamps, st_ts)
        right = bisect.bisect_right(self._lc.variable_timestamps, et_ts)
        logs_in_range = self._lc.variable_logs[left:right]

        if seq["type"] == "B":
            core_set   = set(seq.get("core_indices", []))
            final_logs = []
            for log in logs_in_range:
                item_c, signal = _parse_item_signal(log.raw)
                if item_c != item_code:
                    continue
                if log.original_index in core_set:
                    final_logs.append(log)
                    continue
                if "B_TRIGGER_REPORT" in (signal or ""):
                    continue
                final_logs.append(log)
            final_logs.sort(key=lambda x: x.ts or datetime.min)
            self._lc.display_logs(final_logs)
        else:
            subset = [
                log for log in logs_in_range
                if _parse_item_signal(log.raw)[0] == item_code
            ]
            self._lc.display_logs(subset)

        # BR 연동
        br_tab = self.page.br_tab
        if not br_tab.br_calls:
            return

        br_tab.show_all_brs()
        expected_brs = set(self._db.get_brs_for_item(item_code))
        if not expected_brs:
            return

        buffer_sec = 1
        to_highlight = [
            e for e in br_tab.br_calls
            if e["br_name"] in expected_brs
            and (st_ts - buffer_sec) <= int(e["timestamp"].timestamp()) <= (et_ts + buffer_sec)
        ]
        if to_highlight:
            self.page.pending_br_highlight = to_highlight


# ── 모듈 수준 헬퍼 ────────────────────────────────────────────
def _parse_item_signal(raw):
    try:
        block = raw.split("[")[-1].split("]")[0]
        item, signal = block.split(":")
        return item, signal
    except Exception:
        return None, None