# model.py
from dataclasses import dataclass
from PySide6.QtCore import QDateTime, Qt, QAbstractListModel, QModelIndex

@dataclass
class LogLine:
    raw: str

class LogListModel(QAbstractListModel):
    def __init__(self, logs=None):
        super().__init__()
        self.logs = logs or []

    def rowCount(self, parent=QModelIndex()):
        return len(self.logs)

    def data(self, index, role):
        if not index.isValid():
            return None

        log = self.logs[index.row()]

        if role == Qt.DisplayRole:
            return log.raw

        if role == Qt.UserRole:
            return log.original_index

        return None

    def setLogs(self, logs):
        self.beginResetModel()
        self.logs = logs
        self.endResetModel()