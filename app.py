# app.py
import sys
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QWidget, QListWidget, QListWidgetItem,
    QHBoxLayout, QLabel, QVBoxLayout, QMainWindow,
    QFileDialog, QLineEdit, QPushButton, QCheckBox, QTabWidget, QTreeWidget, QTreeWidgetItem
)
from PySide6.QtGui import QAction
from PySide6.QtCore import QDateTime, Qt

from parser import load_log_file
from period_dialog import PeriodDialog


class LogViewer(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("EIF 로그 뷰어")
        self.resize(1200, 800)

        self.all_logs = []
        self.sequences = {}

        self.period_start = QDateTime.currentDateTime().addSecs(-3600)
        self.period_end = QDateTime.currentDateTime()

        central = QWidget()
        self.setCentralWidget(central)

        # 검색
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("검색어 입력")
        self.search_input.textChanged.connect(self.search_logs)

        self.period_button = QPushButton()
        self.update_period_button()
        self.period_button.clicked.connect(self.open_period_dialog)

        #self.search_button = QPushButton("검색")
       # self.search_button.clicked.connect(self.search_logs)

        # 시스템 체크박스
        self.system_layout = QHBoxLayout()
        self.system_checkboxes = {}

        # 상단 UI
        top = QVBoxLayout()

        row = QHBoxLayout()
        row.addWidget(QLabel("검색"))
        row.addWidget(self.search_input)
        row.addWidget(QLabel("기간"))
        row.addWidget(self.period_button)
        #row.addWidget(self.search_button)

        top.addLayout(row)
        top.addLayout(self.system_layout)

        # 로그 리스트
        self.log_list = QListWidget()
        self.log_list.itemDoubleClicked.connect(self.jump_to_log)

        # ✅ 오른쪽 탭 패널
        self.tabs = QTabWidget()

        self.tab_item = QLabel("Item View (Coming Soon)")
        self.tabs.addTab(self.tab_item, "Item별")

        self.seq_tree = QTreeWidget()
        self.seq_tree.setHeaderLabel("Sequences")
        self.seq_tree.itemClicked.connect(self.on_sequence_clicked)

        self.tabs.addTab(self.seq_tree, "Sequence")

        body = QHBoxLayout()
        body.addWidget(self.log_list, 4)
        body.addWidget(self.tabs, 2)

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addLayout(body)

        central.setLayout(layout)

        self.create_menu()



    # -------------------
    # 메뉴
    # -------------------
    def create_menu(self):
        m = self.menuBar().addMenu("File")

        open_action = QAction("Open Log", self)
        open_action.triggered.connect(self.open_log_file)
        m.addAction(open_action)

    # -------------------
    # 파싱
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
    # 기간 자동 설정
    # -------------------
    def update_period_from_logs(self):
        times = []

        for log in self.all_logs:
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
    # 체크박스 생성
    # -------------------
    def build_system_checkboxes(self):
        while self.system_layout.count():
            w = self.system_layout.takeAt(0).widget()
            if w:
                w.deleteLater()

        self.system_checkboxes.clear()

        systems = {
            self.extract_system(l.raw)
            for l in self.all_logs
            if self.extract_system(l.raw)
        }

        for s in sorted(systems):
            cb = QCheckBox(s)
            cb.setChecked(True)
            cb.stateChanged.connect(self.search_logs)
            self.system_layout.addWidget(cb)
            self.system_checkboxes[s] = cb

    # -------------------
    # 로그 열기
    # -------------------
    def open_log_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open", "", "Log (*.log)"
        )
        if path:
            self.load_logs(path)

    def load_logs(self, path):
        self.all_logs = load_log_file(path)

        self.update_period_from_logs()
        self.build_system_checkboxes()
        self.search_logs()

        self.build_sequences()
        self.populate_sequence_tree()

    # -------------------
    # 표시 (빠른 버전)
    # -------------------
    def display_logs(self, logs):
        self.log_list.setUpdatesEnabled(False)
        self.log_list.clear()

        if not logs:
            self.log_list.addItem("⚠️ 결과 없음")
            self.log_list.setUpdatesEnabled(True)
            return

        for log in logs:
            item = QListWidgetItem(log.raw)
            item.setData(Qt.UserRole, log.idx)
            self.log_list.addItem(item)

        self.log_list.setUpdatesEnabled(True)

    # -------------------
    # 검색
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

        for log in self.all_logs:
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
    # Item + Signal 추출
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

    # -------------------
    # 시퀀스 찾기
    # -------------------
    def build_sequences(self, wiggle=3):
        self.sequences.clear()
        active = {}  # 진행 중인 시퀀스: key=item, value=(시작 시간, 시작 idx)

        for idx, log in enumerate(self.all_logs):
            raw = log.raw
            ts = self.extract_timestamp(raw)
            if not ts:
                continue

            item, signal = self.parse_item_signal(raw)
            val = self.parse_value(raw)

            if not item or not signal or not val:
                continue

            # 시퀀스 시작
            if signal == "I_B_TRIGGER_REPORT" and val == "ON":
                active[item] = (ts, idx)

            # 시퀀스 종료
            elif signal == "O_B_TRIGGER_REPORT_CONF" and val == "OFF":
                if item in active:
                    st, si = active.pop(item)

                    # 여유 적용: 시작/끝 주변 wiggle 범위
                    start_idx = max(0, si - wiggle)
                    end_idx = min(len(self.all_logs) - 1, idx + wiggle)

                    # 시퀀스 안 로그 수집: item 일치하는 것만 포함
                    seq_logs = []
                    for i in range(start_idx, end_idx + 1):
                        log_item, _ = self.parse_item_signal(self.all_logs[i].raw)
                        if log_item == item:
                            seq_logs.append(i)

                    # 시퀀스 저장
                    if seq_logs:
                        self.sequences.setdefault(item, []).append(
                            (st, ts, seq_logs)
                        )
    # -------------------
    # Tree 채우기
    # -------------------
    def populate_sequence_tree(self):
        self.seq_tree.clear()

        for item, seqs in self.sequences.items():
            parent = QTreeWidgetItem([item])
            self.seq_tree.addTopLevelItem(parent)

            for st, et, log_idxs in seqs:
                child = QTreeWidgetItem([st.strftime("%Y-%m-%d %H:%M:%S")])
                child.setData(0, 1, log_idxs)
                parent.addChild(child)


    # -------------------
    # 클릭 시 표시
    # -------------------
    def on_sequence_clicked(self, item):
        log_idxs = item.data(0, 1)
        if not log_idxs:
            return

        subset = [self.all_logs[i] for i in log_idxs]
        self.display_logs(subset)

    # -------------------
    # 점프
    # -------------------
    def jump_to_log(self, item):
        if self.all_logs != self.log_list:
            idx = item.data(Qt.UserRole)

            if idx is None:
                return

            self.search_input.blockSignals(True)
            self.search_input.clear()
            self.search_input.blockSignals(False)
            self.display_logs(self.all_logs)

            target = self.log_list.item(idx)
            self.log_list.scrollToItem(target, QListWidget.PositionAtCenter )
            self.log_list.setCurrentItem(target)

# -------------------
# 실행
# -------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = LogViewer()
    w.show()
    sys.exit(app.exec())

