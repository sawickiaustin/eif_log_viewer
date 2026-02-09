# app.py
import sys
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QWidget, QListWidget, QHBoxLayout, QLabel,
    QVBoxLayout, QMainWindow, QFileDialog, QLineEdit, QPushButton,
    QDialog, QDateTimeEdit, QCheckBox
)
from PySide6.QtGui import QAction
from PySide6.QtCore import QDateTime

from parser import load_log_file
from period_dialog import PeriodDialog

# -------------------------------
# 메인 윈도우
# -------------------------------
class LogViewer(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("EIF 로그 뷰어")
        self.resize(1200, 800)

        self.all_logs = []

        # 기본값 (로그 로드 시 자동 변경됨)
        self.period_start = QDateTime.currentDateTime().addSecs(-3600)
        self.period_end = QDateTime.currentDateTime()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 검색어
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("검색어 입력")
        self.search_input.textChanged.connect(self.search_logs)

        # 기간 버튼
        self.period_button = QPushButton()
        self.update_period_button()
        self.period_button.clicked.connect(self.open_period_dialog)

        # 검색 버튼
        #self.search_button = QPushButton("검색")
        #self.search_button.clicked.connect(self.search_logs)

        # 시스템 체크박스 영역
        self.system_layout = QHBoxLayout()
        self.system_checkboxes = {}

        # 상단 레이아웃
        top_layout = QVBoxLayout()

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("검색"))
        row1.addWidget(self.search_input)
        row1.addWidget(QLabel("기간"))
        row1.addWidget(self.period_button)
        #row1.addWidget(self.search_button)

        top_layout.addLayout(row1)
        top_layout.addLayout(self.system_layout)

        # 로그 리스트
        self.log_list = QListWidget()

        # 오른쪽 패널
        self.right_panel = QLabel("Right Panel\n(Coming Soon)")
        self.right_panel.setStyleSheet(
            "background-color:#2b2b2b; color:white; padding:10px;"
        )

        body_layout = QHBoxLayout()
        body_layout.addWidget(self.log_list, 4)
        body_layout.addWidget(self.right_panel, 1)

        main_layout = QVBoxLayout()
        main_layout.addLayout(top_layout)
        main_layout.addLayout(body_layout)

        central_widget.setLayout(main_layout)

        self.create_menu()

    # -------------------------------
    # 메뉴
    # -------------------------------
    def create_menu(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("File")

        open_action = QAction("Open Log...", self)
        open_action.triggered.connect(self.open_log_file)
        file_menu.addAction(open_action)

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    # -------------------------------
    # Timestamp 추출
    # -------------------------------
    def extract_timestamp(self, raw: str):
        try:
            return datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
        except:
            return None

    # -------------------------------
    # 시스템 추출
    # -------------------------------
    def extract_system(self, raw_line: str):
        try:
            parts = raw_line.split("[")
            for p in parts:
                if "." in p and "]" in p:
                    name = p.split("]")[0]
                    if "." in name:
                        return name.split(".")[-1]
        except:
            pass
        return None

    # -------------------------------
    # 로그 기준 기간 설정
    # -------------------------------
    def update_period_from_logs(self):
        times = []

        for log in self.all_logs:
            ts = self.extract_timestamp(log.raw)
            if ts:
                times.append(ts)

        if not times:
            return

        start = min(times)
        end = max(times)

        self.period_start = QDateTime(start)
        self.period_end = QDateTime(end)

        self.update_period_button()

    # -------------------------------
    # 시스템 체크박스 생성
    # -------------------------------
    def build_system_checkboxes(self):
        while self.system_layout.count():
            item = self.system_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.system_checkboxes.clear()

        systems = set()

        for log in self.all_logs:
            s = self.extract_system(log.raw)
            if s:
                systems.add(s)

        for s in sorted(systems):
            cb = QCheckBox(s)
            cb.setChecked(True)
            cb.stateChanged.connect(self.search_logs)
            self.system_layout.addWidget(cb)
            self.system_checkboxes[s] = cb

    # -------------------------------
    # 기간 버튼 표시
    # -------------------------------
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

    # -------------------------------
    # 로그 열기
    # -------------------------------
    def open_log_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Log File", "", "Log Files (*.log);;All Files (*)"
        )
        if file_path:
            self.load_logs(file_path)

    def load_logs(self, path):
        self.all_logs = load_log_file(path)

        self.update_period_from_logs()
        self.build_system_checkboxes()
        self.search_logs()

    # -------------------------------
    # 로그 표시
    # -------------------------------
    def display_logs(self, logs):
        self.log_list.clear()

        if not logs:
            self.log_list.addItem("⚠️ 결과 없음")
            return

        for log in logs:
            self.log_list.addItem(log.raw)

    # -------------------------------
    # 검색/필터
    # -------------------------------
    def search_logs(self):
        keyword = self.search_input.text().lower()
        start = self.period_start.toPython()
        end = self.period_end.toPython()

        active_systems = {
            s for s, cb in self.system_checkboxes.items() if cb.isChecked()
        }

        if not active_systems:
            self.display_logs([])
            return

        result = []

        for log in self.all_logs:
            raw = log.raw

            sysname = self.extract_system(raw)
            if sysname not in active_systems:
                continue

            if keyword and keyword not in raw.lower():
                continue

            ts = self.extract_timestamp(raw)
            if ts and not (start <= ts <= end):
                continue

            result.append(log)

        self.display_logs(result)


# -------------------------------
# 실행
# -------------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LogViewer()
    window.show()
    sys.exit(app.exec())
