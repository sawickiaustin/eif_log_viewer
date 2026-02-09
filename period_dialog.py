#period_dialog
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QDateTimeEdit, QPushButton
)
from PySide6.QtCore import QDateTime


class PeriodDialog(QDialog):
    def __init__(self, start: QDateTime, end: QDateTime, parent=None):
        super().__init__(parent)
        self.setWindowTitle("기간 선택")
        self.resize(400, 200)

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
        layout.addWidget(ok_btn)

        self.setLayout(layout)

    def get_period(self):
        return self.start_edit.dateTime(), self.end_edit.dateTime()
