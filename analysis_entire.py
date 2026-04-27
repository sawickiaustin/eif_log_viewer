import sys
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
    QRadioButton, QButtonGroup, QPushButton, QFileDialog, QLabel, QSplitter,
    QListView, QListWidget, QTreeWidget, QLineEdit, QSizePolicy, QFrame
)
from PySide6.QtCore import Qt, QAbstractListModel, QModelIndex, Slot


class SimpleLog:
    def __init__(self, raw, idx=0):
        self.raw = raw.rstrip("\n")
        self.raw_lower = self.raw.casefold()
        self.original_index = idx
        self.ts = self._parse_ts(self.raw)

    def _parse_ts(self, raw):
        try:
            return datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    def __str__(self):
        return self.raw


class LogListModel(QAbstractListModel):
    def __init__(self, logs=None):
        super().__init__()
        self.logs = logs or []

    def data(self, index, role):
        if not index.isValid() or role not in (Qt.DisplayRole,):
            return None
        log = self.logs[index.row()]
        return log.raw

    def rowCount(self, parent=QModelIndex()):
        return len(self.logs)

    def setLogs(self, logs):
        self.beginResetModel()
        self.logs = list(logs)
        self.endResetModel()


class AnalysisPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Header: analysis type radios + file button
        header = QHBoxLayout()
        lbl = QLabel("분석 유형")
        header.addWidget(lbl)

        self.radio_var = QRadioButton("Variable Trace")
        self.radio_br = QRadioButton("Variable Trace + Biz Rule Log")
        self.radio_var.setChecked(True)
        header.addWidget(self.radio_var)
        header.addWidget(self.radio_br)

        # File button next to radios
        self.file_btn = QPushButton("File")
        header.addWidget(self.file_btn)

        header.addStretch()
        layout.addLayout(header)

        # horizontal separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        # Body: splitter left (log view) / right (item/sequence + search)
        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setHandleWidth(8)

        # Left: full log view
        self.log_view = QListView()
        self.log_view.setUniformItemSizes(True)
        self.log_model = LogListModel([])
        self.log_view.setModel(self.log_model)
        splitter.addWidget(self.log_view)

        # Right: Item / Sequence with radio + search + content
        right = QWidget()
        rlay = QVBoxLayout(right)

        # radio head for Item/Sequence
        kind_layout = QHBoxLayout()
        self.k_item = QRadioButton("Item")
        self.k_seq = QRadioButton("Sequence")
        self.k_item.setChecked(True)
        kind_layout.addWidget(self.k_item)
        kind_layout.addWidget(self.k_seq)
        kind_layout.addStretch()
        rlay.addLayout(kind_layout)

        # search
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("검색"))
        self.search_edit = QLineEdit()
        search_layout.addWidget(self.search_edit)
        rlay.addLayout(search_layout)

        # content area: stacked manual choice (we'll keep both widgets visible within tab)
        self.item_list = QListWidget()
        self.seq_tree = QTreeWidget()
        self.seq_tree.setHeaderLabel("Sequences")
        rlay.addWidget(self.item_list)
        rlay.addWidget(self.seq_tree)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)

        # expose for external wiring
        self.splitter = splitter

    def load_logs_from_path(self, path):
        logs = []
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                for i, line in enumerate(fh):
                    logs.append(SimpleLog(line, i))
        except Exception as e:
            print("Failed to load:", e)
        self.log_model.setLogs(logs)
        # populate simple item list (unique item codes heuristic)
        self._populate_items(logs)

    def _populate_items(self, logs):
        self.item_list.clear()
        items = set()
        for l in logs:
            # heuristic: item code inside [ITEM:...]
            try:
                block = l.raw.split("[")[-1].split("]")[0]
                item = block.split(":")[0]
                items.add(item)
            except Exception:
                continue
        for it in sorted(items):
            self.item_list.addItem(it)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Analysis Pages")
        self.resize(1200, 800)
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main = QVBoxLayout(central)

        self.page_tabs = QTabWidget()
        self.page_tabs.setTabsClosable(True)
        self.page_tabs.tabCloseRequested.connect(self._close_tab)
        self.page_tabs.currentChanged.connect(self._on_tab_changed)

        # create first real page
        self._add_page("1")

        # plus tab
        plus = QWidget()
        self.page_tabs.addTab(plus, "+")
        main.addWidget(self.page_tabs)

    def _add_page(self, title=None, switch_to=True):
        idx = self.page_tabs.count()
        # if last tab is plus, insert before it
        plus_idx = self.page_tabs.count() - 1
        if plus_idx >= 0 and self.page_tabs.tabText(plus_idx) == "+":
            insert_at = plus_idx
        else:
            insert_at = self.page_tabs.count()
        page = AnalysisPage(self)
        page_idx = self.page_tabs.insertTab(insert_at, page, title or f"Tab {insert_at+1}")
        # wire file btn
        page.file_btn.clicked.connect(lambda _, p=page: self._on_file_open(p))
        # show only item_list or seq_tree according to radio
        page.k_item.toggled.connect(lambda checked, p=page: p.item_list.setVisible(checked))
        page.k_seq.toggled.connect(lambda checked, p=page: p.seq_tree.setVisible(checked))
        # ensure initial visibility
        page.item_list.setVisible(True)
        page.seq_tree.setVisible(False)
        if switch_to:
            self.page_tabs.setCurrentIndex(page_idx)
        return page_idx

    @Slot(int)
    def _on_tab_changed(self, idx):
        # if user clicked plus tab -> create new and switch
        if idx >= 0 and self.page_tabs.tabText(idx) == "+":
            new_idx = self._add_page(f"{self.page_tabs.count()}")
            self.page_tabs.setCurrentIndex(new_idx)

    def _close_tab(self, idx):
        # prevent closing last real tab if only plus remains
        if self.page_tabs.tabText(idx) == "+":
            return
        self.page_tabs.removeTab(idx)

    def _on_file_open(self, page: AnalysisPage):
        # choose file then load into that page only
        fname, _ = QFileDialog.getOpenFileName(self, "Open Log File", "", "Log Files (*.log);;All Files (*)")
        if not fname:
            return
        page.load_logs_from_path(fname)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.showMaximized()
    sys.exit(app.exec())