# analysis_page.py
"""
AnalysisPage: UI 뼈대 + 세 컨트롤러 조립.
- UI 구성 / 시그널 연결만 담당
- 실제 로직은 log_ctrl / seq_ctrl / item_ctrl 에 위임
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QRadioButton,
    QPushButton, QLabel, QSplitter, QListView, QListWidget,
    QTreeWidget, QLineEdit, QFrame
)
from PySide6.QtCore import Qt, QDateTime, QTimer

from model import LogListModel
from br_tab import BRTab
from db_manager import DBManager
from log_controller import LogController
from sequence_controller import SequenceController
from item_controller import ItemController


class AnalysisPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        # ── 공유 자원 ──────────────────────────────────────
        self.db     = DBManager()
        self.br_tab = BRTab(self)
        self.br_tab.hide()   # UI에는 표시하지 않음; 내부 데이터 처리용

        self.pending_br_highlight = None

        # ── 컨트롤러 생성 (page 참조를 공유) ──────────────
        self.log_ctrl  = LogController(self)
        self.seq_ctrl  = SequenceController(self)
        self.item_ctrl = ItemController(self)

        # ── UI ────────────────────────────────────────────
        self._build_ui()
        self._wire_signals()

    # =========================================================
    # UI 구성
    # =========================================================
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # ── 상단: 분석 유형 라디오 + File 버튼 ───────────
        header = QHBoxLayout()
        header.addWidget(QLabel("분석 유형"))

        self.radio_var = QRadioButton("Variable Trace")
        self.radio_br  = QRadioButton("Variable Trace + Biz Rule Log")
        self.radio_var.setChecked(True)
        header.addWidget(self.radio_var)
        header.addWidget(self.radio_br)
        header.addStretch()

        self.file_btn = QPushButton("File")
        header.addWidget(self.file_btn)
        layout.addLayout(header)

        # ── 구분선 ────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        # ── 본문: 스플리터 ────────────────────────────────
        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setHandleWidth(6)

        # 왼쪽: 로그 리스트뷰
        log_container = QWidget()
        lc_layout = QVBoxLayout(log_container)
        lc_layout.setContentsMargins(0, 0, 0, 0)

        self.log_loading_label = QLabel("⏳ Loading variable log...")
        self.log_loading_label.setAlignment(Qt.AlignCenter)
        self.log_loading_label.setStyleSheet(
            "QLabel { font-size: 14px; color: #666; padding: 20px; }"
        )
        self.log_loading_label.hide()

        self.log_list  = QListView()
        self.log_list.setUniformItemSizes(True)
        self.log_model = LogListModel()
        self.log_list.setModel(self.log_model)

        lc_layout.addWidget(self.log_loading_label)
        lc_layout.addWidget(self.log_list)
        splitter.addWidget(log_container)

        # 오른쪽: Item/Sequence 패널
        right = QWidget()
        rlay  = QVBoxLayout(right)

        kind_row = QHBoxLayout()
        self.k_item = QRadioButton("Item")
        self.k_seq  = QRadioButton("Sequence")
        self.k_item.setChecked(True)
        kind_row.addWidget(self.k_item)
        kind_row.addWidget(self.k_seq)
        kind_row.addStretch()
        rlay.addLayout(kind_row)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("검색"))
        self.search_input = QLineEdit()
        search_row.addWidget(self.search_input)
        rlay.addLayout(search_row)

        self.item_list = QListWidget()
        self.seq_tree  = QTreeWidget()
        self.seq_tree.setHeaderLabel("Sequences")
        self.seq_tree.hide()

        rlay.addWidget(self.item_list)
        rlay.addWidget(self.seq_tree)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

    # =========================================================
    # 시그널 연결 — 이벤트를 컨트롤러로 위임
    # =========================================================
    def _wire_signals(self):
        # File 버튼
        self.file_btn.clicked.connect(self._on_file_clicked)

        # Item / Sequence 전환
        self.k_item.toggled.connect(lambda checked: self.item_list.setVisible(checked))
        self.k_seq.toggled.connect(lambda checked: self.seq_tree.setVisible(checked))

        # 검색 → LogController
        self.search_input.textChanged.connect(self.log_ctrl.schedule_search)

        # 로그 더블클릭 → LogController
        self.log_list.doubleClicked.connect(self.log_ctrl.jump_to_log)

        # 아이템 클릭 → ItemController
        self.item_list.itemClicked.connect(self.item_ctrl.on_item_clicked)

        # 시퀀스 클릭 → SequenceController
        self.seq_tree.itemClicked.connect(self.seq_ctrl.on_sequence_clicked)

    # =========================================================
    # File 버튼 — 라디오 선택에 따라 분기
    # =========================================================
    def _on_file_clicked(self):
        if self.radio_br.isChecked():
            self.log_ctrl.open_variable_and_br_log()
        else:
            self.log_ctrl.open_variable_log()