# app.py
import sys
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QListWidget,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QMainWindow,
    QFileDialog
)
from PySide6.QtGui import QAction  

from parser import load_log_file

LOG_FILE_PATH = "VARIABLE_TRACE_0126.log"  # 여기에 로그 파일 경로

class LogViewer(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("EIF 로그 뷰어")
        self.resize(1200, 800)

        # 중앙 위젯
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 왼쪽: 로그 리스트
        self.log_list = QListWidget()

        # 오른쪽: placeholder
        self.right_panel = QLabel("Right Panel\n(Coming Soon)")
        self.right_panel.setStyleSheet("background-color: #2b2b2b; padding: 10px; color: white;")

        # 레이아웃
        layout = QHBoxLayout()
        layout.addWidget(self.log_list, 4)
        layout.addWidget(self.right_panel, 1)
        central_widget.setLayout(layout)

        # 메뉴
        self.create_menu()

    def create_menu(self):
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("File")

        open_action = QAction("Open Log...", self)
        open_action.triggered.connect(self.open_log_file)
        file_menu.addAction(open_action)

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    def open_log_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Log File", "", "Log Files (*.log);;All Files (*)")
        if file_path:
            self.load_logs(file_path)

    def load_logs(self, path):
        self.log_list.clear()
        try:
            logs = load_log_file(path)
        except FileNotFoundError:
            self.log_list.addItem("❌ 로그 파일을 찾을 수 없습니다.")
            return

        if not logs:
            self.log_list.addItem("⚠️ 로그 파일이 비어 있습니다.")
            return

        for log in logs:
            self.log_list.addItem(log.raw)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LogViewer()
    window.show()
    sys.exit(app.exec())