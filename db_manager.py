#db_manager.py
import sqlite3

class DBManager:
    def __init__(self, db_path="metadata.db"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()

    # -----------------------------
    # Create Tables
    # -----------------------------
    def create_tables(self):
        cursor = self.conn.cursor()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS items (
            item_code TEXT PRIMARY KEY,
            item_name TEXT
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS item_brs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_code TEXT,
            br_code TEXT,
            FOREIGN KEY(item_code) REFERENCES items(item_code)
        )
        """)

        self.conn.commit()

    # -----------------------------
    # Insert
    # -----------------------------
    def insert_item(self, item_code, item_name):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO items (item_code, item_name)
            VALUES (?, ?)
        """, (item_code, item_name))
        self.conn.commit()

    def insert_item_br(self, item_code, br_code):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO item_brs (item_code, br_code)
            VALUES (?, ?)
        """, (item_code, br_code))
        self.conn.commit()

    # -----------------------------
    # Query
    # -----------------------------
    def get_item_name(self, item_code):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT item_name
            FROM items
            WHERE item_code = ?
        """, (item_code,))
        row = cursor.fetchone()
        return row["item_name"] if row else None

    def get_brs_for_item(self, item_code):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT br_code
            FROM item_brs
            WHERE item_code = ?
        """, (item_code,))
        return [row["br_code"] for row in cursor.fetchall()]


    # -----------------------------
    # Clear All Data
    # -----------------------------
    def clear_all(self):
        cursor = self.conn.cursor()

        cursor.execute("DELETE FROM item_brs")
        cursor.execute("DELETE FROM items")

        # Reset autoincrement (important for clean rebuild)
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='item_brs'")

        self.conn.commit()

def create_db():
    db = DBManager()

    db.clear_all()

    data = [
        ("C2_8_ALARM_SET_RPT_01", "Alarm Set Report", ['BR_EQP_REG_EQPT_ALARM']),
        ("C2_9_ALARM_RESET_RPT_01", "Alarm Reset Report", ['BR_EQP_REG_EQPT_ALARM']),

        ("G2_1_CARR_ID_RPT_01", "UWD Core A 투입 보고",
         ["BR_MHS_EIF_REG_REPORT_LOADED_CSTID",
          "BR_PRD_CHK_INPUT_LOT_RP_L",
          "DA_PRD_SEL_LOT_INFO_BY_EIF",
          "BR_PRD_SEL_LOT_INFO_BY_CSTID"]),

        ("G2_1_CARR_ID_RPT_02", "UWD Core B 투입 보고",
         ["BR_MHS_EIF_REG_REPORT_LOADED_CSTID",
          "BR_PRD_CHK_INPUT_LOT_RP_L",
          "DA_PRD_SEL_LOT_INFO_BY_EIF",
          "BR_PRD_SEL_LOT_INFO_BY_CSTID"]),

        ("G2_1_CARR_ID_RPT_03", "RWD Core A 투입 보고",
         ["BR_MHS_EIF_REG_REPORT_LOADED_CSTID",
          "BR_PRD_CHK_INPUT_LOT_RP_L",
          "DA_PRD_SEL_LOT_INFO_BY_EIF",
          "BR_PRD_SEL_LOT_INFO_BY_CSTID"]),

        ("G2_1_CARR_ID_RPT_04", "RWD Core B 투입 보고",
         ["BR_MHS_EIF_REG_REPORT_LOADED_CSTID",
          "BR_PRD_CHK_INPUT_LOT_RP_L",
          "DA_PRD_SEL_LOT_INFO_BY_EIF",
          "BR_PRD_SEL_LOT_INFO_BY_CSTID"]),

        ("G2_2_CARR_JOB_START_01", "UWD Core A 작업 시작", ['BR_PRD_CHK_INPUT_LOT_RP_L']),
        ("G2_2_CARR_JOB_START_02", "UWD Core B 작업 시작", ['BR_PRD_CHK_INPUT_LOT_RP_L']),

        ("G2_3_CARR_OUT_RPT_01", "UWD Core A 탈착 보고", ['BR_PRD_REG_EQPT_MOUNT_MTRL_ELTR']),
        ("G2_3_CARR_OUT_RPT_02", "UWD Core B 탈착 보고", ['BR_PRD_REG_EQPT_MOUNT_MTRL_ELTR']),
        ("G2_3_CARR_OUT_RPT_03", "RWD Core A 탈착 보고", []),
        ("G2_3_CARR_OUT_RPT_04", "RWD Core B 탈착보고", []),

        ("G2_6_CARR_JOB_END_01", "UWD Core A 작업 완료", []),
        ("G2_6_CARR_JOB_END_02", "UWD Core B 작업 완료", []),

        ("PORT_STAT_CHG_101", "Port #101(UWD) 상태 보고", ['BR_MHS_EIF_REG_EQPT_PORT_TRF_STATE']),
        ("PORT_STAT_CHG_102", "Port #102(RWD) 상태 보고", ['BR_MHS_EIF_REG_EQPT_PORT_TRF_STATE']),

        ("PORT_MTRL_TRANSFER_STAT_REQ_101", "Port #101(UWD) 자재 반송 진행 상태", ['BR_MHS_EIF_REG_EQPT_PORT_TRF_STATE']),
        ("PORT_MTRL_TRANSFER_STAT_REQ_102", "Port #102(RWD) 자재 반송 진행 상태", ['BR_MHS_EIF_REG_EQPT_PORT_TRF_STATE']),

        ("G3_2_LOT_START_RPT", "Lot Start Report", ['BR_PRD_GET_NEW_LOTID_RP_EIF','BR_PRD_REG_START_LOT_RP_EIF']),
        ("G3_3_LOT_END_RPT", "Lot End Report", ['BR_PRD_REG_EQPT_END_LOT_RP']),
    ]

    for item_code, name, brs in data:
        db.insert_item(item_code, name)
        for br in brs:
            db.insert_item_br(item_code, br)

    print("Database recreated successfully.")