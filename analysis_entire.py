# analysis_entire.py
"""
진입점 — MainWindow (탭 관리만 담당).
실제 분석 UI는 analysis_page.AnalysisPage에서 구현.
"""
import sys

from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QTabWidget
from PySide6.QtGui import QAction
from PySide6.QtCore import Slot

from analysis_page import AnalysisPage


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EIF 로그 뷰어")
        self.resize(1400, 900)
        self._build_ui()
        self._create_menu()
        self.statusBar().showMessage("Ready")

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        self.page_tabs = QTabWidget()
        self.page_tabs.setTabsClosable(True)
        self.page_tabs.tabCloseRequested.connect(self._close_tab)
        self.page_tabs.currentChanged.connect(self._on_tab_changed)

        self._add_page("1")

        plus = QWidget()
        self.page_tabs.addTab(plus, "+")

        layout.addWidget(self.page_tabs)

    def _create_menu(self):
        bar       = self.menuBar()
        file_menu = bar.addMenu("File")

        new_tab = QAction("새 분석 탭", self)
        new_tab.setShortcut("Ctrl+T")
        new_tab.triggered.connect(lambda: self._add_page())
        file_menu.addAction(new_tab)

        file_menu.addSeparator()

        exit_act = QAction("Exit", self)
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

    def _add_page(self, title=None, switch_to=True) -> int:
        plus_idx  = self.page_tabs.count() - 1
        insert_at = plus_idx if (
            plus_idx >= 0 and self.page_tabs.tabText(plus_idx) == "+"
        ) else self.page_tabs.count()

        page  = AnalysisPage(self)
        label = title or str(insert_at + 1)
        idx   = self.page_tabs.insertTab(insert_at, page, label)

        if switch_to:
            self.page_tabs.setCurrentIndex(idx)
        return idx

    @Slot(int)
    def _on_tab_changed(self, idx: int):
        if idx >= 0 and self.page_tabs.tabText(idx) == "+":
            new_idx = self._add_page(str(self.page_tabs.count()))
            self.page_tabs.setCurrentIndex(new_idx)

    def _close_tab(self, idx: int):
        if self.page_tabs.tabText(idx) == "+":
            return
        real_count = sum(
            1 for i in range(self.page_tabs.count())
            if self.page_tabs.tabText(i) != "+"
        )
        if real_count <= 1:
            return
        self.page_tabs.removeTab(idx)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w   = MainWindow()
    w.showMaximized()
    sys.exit(app.exec())