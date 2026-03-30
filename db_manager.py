# db_manager.py
import sqlite3


# ============================================================
# 🔹 GLOBAL DATA (COMMON + EQUIPMENT OVERRIDES)
# ============================================================

COMMON_DATA = {
    "ADDITEM": {"name": "ADDITEM", "brs": []},

    "C1_1_EQP_COMM_CHK": {"name": "EQP Communication Check", "brs": []},
    "C1_2_HOST_COMM_CHK": {"name": "Host Communication Check", "brs": []},
    "C1_3_COMM_STAT_CHG_RPT": {"name": "Communication State Change Report", "brs": []},

    "C1_4_DATE_TIME_SET_REQ": {
        "name": "Date and Time Set Request",
        "brs": ["BR_EQP_GET_SYSTEM_TIME"]
    },

    "C2_1_EQP_STAT_CHG_RPT": {
        "name": "EQP State Change Report",
        "brs": ["BR_EQP_REG_EIOSTATE"]
    },

    "C2_3_HOST_ALARM_MSG_SEND": {"name": "Host Alarm Message Send", "brs": []},
    "C2_4_EQP_OP_MODE_CHG_RPT": {"name": "EQP Operation Mode Change Report", "brs": []},
    "C2_5_PROCESS_STAT_CHG_RPT": {"name": "Process State Change Report", "brs": []},
    "C2_6_REMOTE_COMM_SND": {"name": "Remote Command Send", "brs": []},

    "C2_8_ALARM_SET_RPT": {
        "name": "Alarm Set Report",
        "brs": ["BR_EQP_REG_EQPT_ALARM"]
    },

    "C2_9_ALARM_RESET_RPT": {
        "name": "Alarm Reset Report",
        "brs": ["BR_EQP_REG_EQPT_ALARM"]
    },

    "G1_1_MTRL_MONITOR_DATA": {
        "name": "Material Monitoring Data Report",
        "brs": [
            "BR_PRD_CHK_INPUT_LOT_CT_WITH_MSG",
            "BR_PRD_REG_USE_MLOT",
            "BR_PRD_CHK_INPUT_LOT_CT"
        ]
    },

    "G1_2_MTRL_ID_REQ": {"name": "Material ID Confirm Request", "brs": []},

    "G1_3_MTRL_STATE_CHG": {"name": "Material State Change", "brs": []},

    "G1_4_MTRL_OUT_RPT": {"name": "Material Output Report", "brs": []},
    "G1_6_MTRL_JOB_START_RPT": {"name": "Material Job Start Report", "brs": []},
    "G1_7_MTRL_JOB_END_RPT": {"name": "Material Job End Report", "brs": []},

    "G2_1_CARR_ID_RPT": {"name": "Carrier ID Report", "brs": []},
    "G2_2_CARR_IN_RPT": {"name": "Carrier In Report", "brs": []},
    "G2_3_CARR_OUT_RPT": {"name": "Carrier Out Report", "brs": []},

    "G3_2_LOT_START_RPT": {"name": "Lot Start Report", "brs": []},
    "G3_3_LOT_END_RPT": {"name": "Lot End Report", "brs": []},

    "G3_7_DFT_DATA_RPT": {
        "name": "Defect Data Report",
        "brs": ["BR_PRD_REG_EQPT_DFCT_CLCT_L"]
    },

    "G6_1_EQP_PART_IN_RPT": {
        "name": "UBM Parts Input Report",
        "brs": ["BR_EQP_REG_MOUNT_UBM_L"]
    },

    "G6_2_EQP_PART_OUT_RPT": {
        "name": "UBM Parts Output Report",
        "brs": ["BR_EQP_REG_UNMOUNT_UBM_L"]
    },

    "T1_1_PORT_STAT_CHG": {
        "name": "Port State Change Report",
        "brs": [
            "BR_MHS_EIF_REG_EQPT_PORt_TRF_STATE",
            "BR_MHS_EIF_REG_EQPT_PORT_ACCESS_MODE"
        ]
    },

    "T1_4_PORT_MTRL_TRANSFER_STAT_REQ": {
        "name": "Port Material Transfer State Request",
        "brs": ["BR_MHS_EIF_GET_EQPT_PORT_TRF_CMD"]
    },
}


EQP_DATA = {

    "MIX": {
        "G3_1_LOT_INFO_REQ": {
            "name": "Lot Information Request",
            "brs": [
                "BR_PRD_GET_NEW_LOTID_MX",
                "BR_PRD_GET_NEW_LOTID_PM",
                "BR_PRD_GET_NEW_LOTID_BS",
                "BR_PRD_GET_NEW_LOTID_CMC",
                "BR_PRD_GET_NEW_LOTID_INSULT_MX",
                "BR_PRD_GET_LOT_INFO_DEFAULT_FOR_RMS",
                "BR_PRD_GET_WORKORDER"
            ]
        },
        "G3_2_LOT_START_RPT": {
            "name": "Lot Start Report",
            "brs": [
                "BR_PRD_REG_START_LOT_MX",
                "BR_PRD_REG_START_LOT_PM",
                "BR_PRD_REG_START_LOT_BS",
                "BR_PRD_REG_START_LOT_CMC",
                "BR_PRD_REG_START_LOT_INSULT_MX"
            ]
        },
        "G3_3_LOT_END_RPT": {
            "name": "Lot End Report",
            "brs": [
                "BR_PRD_REG_EQPT_END_LOT_MX",
                "BR_PRD_REG_EQPT_END_LOT_PM",
                "BR_PRD_REG_EQPT_END_LOT_BS",
                "BR_PRD_REG_EQPT_END_LOT_CMC",
                "BR_PRD_REG_EQPT_END_LOT_INSULT_MX",
                "BR_PRD_REG_EQPT_MTRL_INPUT_QTY_MX"
            ]
        },
        "G3_6_WIP_DATA_RPT": {
            "name": "WIP Data Report",
            "brs": [
                "BR_PRD_REG_EQPT_WIPQTY",
                "BR_MAT_REG_MIXER_TANK_MTRL_WEIGHT"
            ]
        },
        "S1_1_RAW_MTRL_LIST_REQ": {
            "name": "Raw Material List Request",
            "brs": ["BR_MAT_GET_MATERIAL_TANK"]
        },
        "S1_3_RAW_MTRL_INPUT_COMPLETE_RPT": {
            "name": "Raw Material Input Complete Report",
            "brs": ["BR_MAT_REG_HOPPER_MTRL_INPUT_END_DRB"]
        },
        "S1_6_RAW_MTRL_VALIDATION_READY": {
            "name": "Raw Material Validation Ready",
            "brs": ["BR_MAT_REG_HOPPER_MTRL_DETECT_MODE_DRB"]
        },
        "S2_1_BATCH_OUTPUT_RPT": {
            "name": "Batch Output Report",
            "brs": ["BR_PRD_CHK_CONFIRM_LOT_ELTR"]
        },
        "S2_2_BATCH_INPUT_RPT": {
            "name": "Batch Input Report",
            "brs": ["BR_PRD_CHK_INPUT_LOT_MX"]
        }
    },

    "COT": {
        "C2_5_PROCESS_STAT_CHG_RPT": {
            "name": "Processing State Change Report",
            "brs": ["BR_QCA_REG_EQPT_DATA_CLCT"]
        },
        "G1_1_MTRL_MONITOR_DATA": {
            "name": "Material Monitoring Data Report",
            "brs": [
                "BR_PRD_CHK_INPUT_LOT_CT_WITH_MSG",
                "BR_PRD_REG_USE_MLOT",
                "BR_PRD_CHK_INPUT_LOT_CT"
            ]
        },
        "G1_2_MTRL_ID_REQ": {
            "name": "Material ID Confirm Request",
            "brs": [
                "BR_MHS_EIF_REG_REPORT_LOADED_CSTID",
                "BR_PRD_CHK_INPUT_LOT_CT_WITH_MSG",
                "BR_PRD_CHK_INPUT_LOT_CT"
            ]
        },
        "G1_4_MTRL_OUT_RPT": {
            "name": "Material Output Report",
            "brs": ["BR_PRD_REG_USE_MLOT"]
        },
        "G1_6_MTRL_JOB_START_RPT": {
            "name": "Material Job Start Report",
            "brs": ["BR_PRD_REG_USE_MLOT"]
        },
        "G2_1_CARR_ID_RPT": {
            "name": "Carrier ID Report",
            "brs": [
                "BR_MHS_EIF_REG_REPORT_LOADED_CSTID",
                "BR_PRD_CHK_UNLOADER_CSTID_L",
                "BR_PRD_REG_EQPT_SCAN_RSLT"
            ]
        },
        "G3_1_LOT_INFO_REQ": {
            "name": "Lot Information Request",
            "brs": [
                "BR_PRD_GET_NEW_PROD_LOTID_CT_EIF",
                "BR_PRD_GET_WORKORDER",
                "BR_PRD_GET_LOT_INFO_DEFAULT_FOR_RMS"
            ]
        },
        "G3_6_WIP_DATA_RPT": {
            "name": "WIP Data Report",
            "brs": [
                "BR_PRD_REG_EQPT_WIPQTY_CT",
                "BR_QCA_REG_EQPT_DATA_CLCT"
            ]
        },
        "S3_1_WORK_START_RPT": {
            "name": "Work Start Report",
            "brs": [
                "BR_PRD_REG_START_PROD_LOT_CT_EIF",
                "BR_PRD_GET_FIRSTOUTLOT",
                "BR_EQP_REG_MOUNT_UBM_L"
            ]
        },
        "S3_2_CUTTING_RPT": {
            "name": "Cutting Report",
            "brs": [
                "BR_QCA_REG_EQPT_DATA_CLCT",
                "BR_PRD_REG_EQPT_DFCT_CLCT_L",
                "BR_PRD_REG_END_PROD_LOT_UBM_L",
                "BR_PRD_REG_EQPT_END_OUT_LOT_CT",
                "BR_PRD_REG_BATCH_INFO_CT",
                "BR_PRD_REG_START_OUT_LOT_CT_EIF",
                "BR_PRD_REG_EQPT_END_PROD_LOT_CT",
                "BR_PRD_REG_EQPT_END_OUT_LOT_TOPBACK_CT_EIF",
                "BR_PRD_REG_CSTID_REMAPPING"
            ]
        },
        "S7_4_SPECIFC_PROC_RPT": {
            "name": "Specific Processing Report",
            "brs": ["BR_PRD_REG_EQPT_DFCT_WEB_BREAK_CLCT"]
        }
    },

    "ROL": {
        "G2_1_CARR_ID_RPT": {
            "name": "Carrier ID Report",
            "brs": [
                "BR_MHS_EIF_REG_REPORT_LOADED_CSTID",
                "BR_PRD_CHK_INPUT_LOT_RP_L",
                "DA_PRD_SEL_LOT_INFO_BY_EIF",
                "BR_PRD_SEL_LOT_INFO_BY_CSTID"
            ]
        },
        "G2_2_CARR_JOB_START": {
            "name": "Carrier Job Start Report",
            "brs": ["BR_PRD_CHK_INPUT_LOT_RP_L"]
        },
        "G2_3_CARR_OUT_RPT": {
            "name": "Carrier Out Report",
            "brs": ["BR_PRD_REG_EQPT_MOUNT_MTRL_ELTR"]
        },
        "G2_6_CARR_JOB_END": {
            "name": "Carrier Job End Report",
            "brs": []
        },
        "G3_2_LOT_START_RPT": {
            "name": "Lot Start Report",
            "brs": [
                "BR_PRD_GET_NEW_LOTID_RP_EIF",
                "BR_PRD_REG_START_LOT_RP_EIF"
            ]
        },
        "G3_3_LOT_END_RPT": {
            "name": "Lot End Report",
            "brs": ["BR_PRD_REG_EQPT_END_LOT_RP"]
        }
    }
}


# ============================================================
# 🔹 DB MANAGER
# ============================================================

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
            UNIQUE(item_code, br_code),
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
            INSERT OR IGNORE INTO item_brs (item_code, br_code)
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

        # Reset autoincrement
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='item_brs'")

        self.conn.commit()

    # ============================================================
    # 🔥 CORE: Rebuild DB based on Equipment
    # ============================================================
    def rebuild_for_equipment(self, eqp, dynamic_items=None):
        """
        Build DB using:
        - COMMON_DATA
        - EQP_DATA (override)
        - dynamic suffix expansion (_01, _02, etc.)
        """

        self.clear_all()

        merged = {}

        # -----------------------------
        # 1️⃣ Load COMMON
        # -----------------------------
        for item, data in COMMON_DATA.items():
            merged[item] = {
                "name": data["name"],
                "brs": list(data["brs"])
            }

        # -----------------------------
        # 2️⃣ Apply Equipment Override
        # -----------------------------
        eqp_data = EQP_DATA.get(eqp, {})

        for item, data in eqp_data.items():
            merged[item] = {
                "name": data["name"],
                "brs": list(data["brs"])
            }

        # -----------------------------
        # 3️⃣ Expand dynamic suffix items
        # -----------------------------
        if dynamic_items:
            expanded = {}

            for item_code, data in merged.items():
                # keep original
                expanded[item_code] = data

                # expand if suffix exists
                if item_code in dynamic_items:
                    for suffix in dynamic_items[item_code]:
                        new_code = f"{item_code}_{suffix}"
                        new_name = f"{data['name']} {suffix}"

                        expanded[new_code] = {
                            "name": new_name,
                            "brs": list(data["brs"])
                        }

            merged = expanded

        # -----------------------------
        # 4️⃣ Insert into DB
        # -----------------------------
        for item_code, data in merged.items():
            self.insert_item(item_code, data["name"])

            for br in data["brs"]:
                self.insert_item_br(item_code, br)

        print(f"✅ DB rebuilt for equipment: {eqp}")