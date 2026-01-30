# app.py
import sys
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QWidget, QListWidget, QHBoxLayout, QLabel,
    QVBoxLayout, QMainWindow, QFileDialog, QLineEdit, QPushButton,
    QGridLayout, QDialog, QDateTimeEdit
)
from PySide6.QtGui import QAction
from PySide6.QtCore import QDateTime

from parser import load_log_file


# -------------------------------
# 기간 선택 다이얼로그
# -------------------------------
class PeriodDialog(QDialog):
    def __init__(self, start: QDateTime, end: QDateTime, parent=None):
        super().__init__(parent)
        self.setWindowTitle("기간 선택")
        self.resize(520, 300)

        self.start_edit = QDateTimeEdit(start)
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")

        self.end_edit = QDateTimeEdit(end)
        self.end_edit.setCalendarPopup(True)
        self.end_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")

        layout = QVBoxLayout()

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("시작"))
        row1.addWidget(self.start_edit)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("끝"))
        row2.addWidget(self.end_edit)

        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)

        layout.addLayout(row1)
        layout.addLayout(row2)
        layout.addStretch()
        layout.addWidget(ok_btn)

        self.setLayout(layout)

    def get_period(self):
        return self.start_edit.dateTime(), self.end_edit.dateTime()


# -------------------------------
# 메인 윈도우
# -------------------------------
class LogViewer(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("EIF 로그 뷰어")
        self.resize(1200, 800)

        self.all_logs = []

        # 기본 기간 (최근 1시간)
        self.period_start = QDateTime.currentDateTime().addSecs(-3600)
        self.period_end = QDateTime.currentDateTime()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 검색어
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("검색어 입력")

        # 기간 버튼
        self.period_button = QPushButton()
        self.update_period_button()
        self.period_button.clicked.connect(self.open_period_dialog)

        # 검색 버튼 (하나만)
        self.search_button = QPushButton("검색")
        self.search_button.clicked.connect(self.search_logs)

        # 상단 레이아웃
        top_layout = QGridLayout()
        top_layout.addWidget(QLabel("검색"), 0, 0)
        top_layout.addWidget(self.search_input, 0, 1)
        top_layout.addWidget(QLabel("기간"), 0, 2)
        top_layout.addWidget(self.period_button, 0, 3)
        top_layout.addWidget(self.search_button, 0, 4)

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
    # 기간 버튼 표시 업데이트
    # -------------------------------
    def update_period_button(self):
        self.period_button.setText(
            f"{self.period_start.toString('yyyy-MM-dd HH:mm')}  ~  "
            f"{self.period_end.toString('yyyy-MM-dd HH:mm')}"
        )

    # -------------------------------
    # 기간 다이얼로그 열기
    # -------------------------------
    def open_period_dialog(self):
        dlg = PeriodDialog(self.period_start, self.period_end, self)
        if dlg.exec():
            self.period_start, self.period_end = dlg.get_period()
            self.update_period_button()

    # -------------------------------
    # 로그 파일 열기
    # -------------------------------
    def open_log_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Log File", "", "Log Files (*.log);;All Files (*)"
        )
        if file_path:
            self.load_logs(file_path)

    # -------------------------------
    # 로그 로딩
    # -------------------------------
    def load_logs(self, path):
        try:
            self.all_logs = load_log_file(path)
        except FileNotFoundError:
            self.log_list.clear()
            self.log_list.addItem("❌ 로그 파일을 찾을 수 없습니다.")
            return

        self.display_logs(self.all_logs)

    def display_logs(self, logs):
        self.log_list.clear()
        if not logs:
            self.log_list.addItem("⚠️ 결과 없음")
            return

        for log in logs:
            self.log_list.addItem(log.raw)

    # -------------------------------
    # 검색 (기간 + 키워드)
    # -------------------------------
    def search_logs(self):
        keyword = self.search_input.text().lower()
        start = self.period_start.toPython()
        end = self.period_end.toPython()

        result = []
        for log in self.all_logs:
            if keyword and keyword not in log.raw.lower():
                continue

            try:
                ts = datetime.strptime(log.raw[:19], "%Y-%m-%d %H:%M:%S")
                if not (start <= ts <= end):
                    continue
            except Exception:
                continue

            result.append(log)

        self.display_logs(result)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LogViewer()
    window.show()
    sys.exit(app.exec())
