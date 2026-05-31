# item_controller.py
"""
오른쪽 패널의 아이템 리스트 전담 컨트롤러.
- 아이템 리스트 빌드 (EQP / ROLLMAP / RMS 카테고리별)
- 아이템 클릭 → 해당 item_code 로그 필터링
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem


class ItemController:
    def __init__(self, page):
        self.page = page
        self.items: list = []
        self.item_list_built = False

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
        self.build_item_list()

    # =========================================================
    # 아이템 리스트 빌드
    # =========================================================
    def build_item_list(self, force=False):
        item_list = self.page.item_list
        item_list.setUpdatesEnabled(False)
        item_list.clear()

        if not self.item_list_built or force:
            self.items = sorted(self._lc.item_index.keys())

        groups: dict[str, list] = {}
        for item_code in self.items:
            category = self._db.get_item_category(item_code)
            groups.setdefault(category, []).append(item_code)

        for category in ["EQP", "ROLLMAP", "RMS"]:
            if not groups.get(category):
                continue

            header = QListWidgetItem(f"[{category}]")
            header.setFlags(Qt.NoItemFlags)
            item_list.addItem(header)

            for item_code in groups[category]:
                item_name    = self._db.get_item_name(item_code)
                display_text = item_name if item_name else item_code
                row          = QListWidgetItem(display_text)
                row.setData(Qt.UserRole, item_code)
                item_list.addItem(row)

        item_list.setUpdatesEnabled(True)
        self.item_list_built = True

    # =========================================================
    # 아이템 클릭
    # =========================================================
    def on_item_clicked(self, item_widget):
        item_code = item_widget.data(Qt.UserRole)
        if not item_code:
            return

        self.page.search_input.blockSignals(True)
        self.page.search_input.clear()
        self.page.search_input.blockSignals(False)

        filtered = self._lc.item_index.get(item_code, [])
        self._lc.display_logs(filtered)

    # =========================================================
    # 상태 초기화
    # =========================================================
    def reset(self):
        self.items            = []
        self.item_list_built  = False
        self.page.item_list.clear()