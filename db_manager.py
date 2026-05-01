# db_manager.py
import sqlite3


# ============================================================
# 🔹 GLOBAL DATA (COMMON + EQUIPMENT OVERRIDES)
# ============================================================

COMMON_DATA = {
    "EQP": {
        "ADDITEM": {"name": "ADDITEM", "brs": []},
        "BASICINFO": {"name": "BASICINFO", "brs": []},

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

        "T1_0_PORT_STAT_REFRESH_REQ": {
            "name": "Port Status Refresh Request",
            "brs": []
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
        }
    },
    "ROLLMAP": {
        "ALARM_RPT": {
            "name": "Alarm ID Report",
            "brs": []
        },
        "PROC_STAT_CHG_RPT": {
            "name": "Process Status Change Report",
            "brs": []
        },
        "DEF_MARKING_DATA_SEND": {
            "name": "Befor Process Defect Marking Data Send",
            "brs": []
        },
        "DATUM_MARKING_DATA_SEND": {
            "name": "Befor Process Datum Marking Data Send",
            "brs": []
        }
    },
    "RMS": {
        "RMS_CTL_STAT_CHG": {
            "name": "RMS Control State Change",
            "brs": []
        },
        "RCP_PARA_DOWN": {
            "name": "RMS Parameter Download Request",
            "brs": []
        },
        "RCP_PARA_VALID": {
            "name": "RMS Parameter Validation Request",
            "brs": []
        },
        "RCP_PARA_UP": {
            "name": "RMS Parameter Upload Request",
            "brs": []
        },
        "PROD_INFO_REQ": {
            "name": "Product Information Request",
            "brs": ["BR_PRD_GET_WORKORDER"]
        },
        "PARA_SPEC_REQ": {
            "name": "Recipe Parameter Spec Request",
            "brs": []
        },
        "CUR_RCP_PARA_RPT": {
            "name": "Version Data Collect",
            "brs": []
        },
        "SYNC_RCP_PARA_RPT": {
            "name": "SV Para.List Data Report",
            "brs": []
        },
        "REMOTE_COMM_SND": {
            "name": "Remote Command Send",
            "brs": []
        },
    }
}


EQP_DATA = {

    "MIX": {
        "EQP": {
            "C2_5_PROCESS_STAT_CHG_RPT": {
            "name": "Processing State Change Report",
            "brs": [
                "BR_MAT_REG_RINGBLOWER_INFO"
            ]
            },
            "G3_5_APD_RPT": {
                "name": "Actual Processing Data Report",
                "brs": [
                    "BR_QCA_REG_EQPT_DATA_CLCT"
                ]
            },
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
            "S1_2_RAW_MTRL_INPUT_HOPPER_NUM_SEND": {
                "name": "Raw Material Input Hopper Number Send",
                "brs": []
            },
            "S1_3_RAW_MTRL_INPUT_COMPLETE_RPT": {
                "name": "Raw Material Input Complete Report",
                "brs": ["BR_MAT_REG_HOPPER_MTRL_INPUT_END_DRB"]
            },
            "S1_3_RAW_MTRL_INPUT_COMPLETE_RPT": {
                "name": "Raw Material Input Complete Report",
                "brs": ["BR_MAT_REG_HOPPER_MTRL_INPUT_END_DRB"]
            },
            "S1_6_RAW_MTRL_VALIDATION_READY": {
                "name": "Raw Material Validation Ready",
                "brs": ["BR_MAT_REG_HOPPER_MTRL_DETECT_MODE_DRB"]
            },
            "S1_7_RAW_MTRL_VALIDATION_RST_SEND": {
                "name": "Raw Material Validation Result Send (PDA)",
                "brs": []
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
        "ROLLMAP": {
            "BATCH_OUT_DATA_RPT": {
                "name": "Batch Output Report",
                "brs": ["BR_PRD_REG_RM_EIF_CT_SLURRY_MOVE"]
            }   
        },
        "RMS": {}
    },

    "COT": {
        "EQP": {
            "C2_5_PROCESS_STAT_CHG_RPT": {
                "name": "Processing State Change Report",
                "brs": ["BR_QCA_REG_EQPT_DATA_CLCT"]
            },
            "G1_1_MTRL_MONITER_DATA": {
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
            "G3_5_APD_RPT": {
                "name": "Actual Processing Data Report",
                "brs": ["BR_QCA_REG_WIP_DATA_CLCT_EIF"]
            },
            "G1_4_MTRL_OUT_RPT": {
                "name": "Material Output Report",
                "brs": ["BR_PRD_REG_USE_MLOT"]
            },
            "G1_6_MTRL_JOB_START_RPT": {
                "name": "Material Job Start Report",
                "brs": ["BR_PRD_REG_USE_MLOT"]
            },
            "G1_7_MTRL_JOB_END_RPT": {
                "name": "Material Job End Report",
                "brs": []
            },
            "G2_1_CARR_ID_RPT": {
                "name": "Carrier ID Report",
                "brs": [
                    "BR_MHS_EIF_REG_REPORT_LOADED_CSTID",
                    "BR_PRD_CHK_UNLOADER_CSTID_L",
                    "BR_PRD_REG_EQPT_SCAN_RSLT"
                ]
            },
            "G2_3_CARR_OUT_RPT": {
                "name": "Carrier Output Report",
                "brs": []
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
            "S3_4_VERSION_CHG_RPT": {
                "name": "Version Change Report",
                "brs": []
            },
            "S3_5_UNCOATING_STAT_CHG_RPT": {
                "name": "Uncoating State Change Report",
                "brs": []
            },
            "S7_4_SPECIFC_PROC_RPT": {
                "name": "Specific Processing Report",
                "brs": ["BR_PRD_REG_EQPT_DFCT_WEB_BREAK_CLCT"]
            },
            "G6_1_EQP_PART_IN_RPT": {
                "name": "UBM Parts Input Report",
                "brs": ["BR_EQP_REG_MOUNT_UBM_L"]
            }
        },
        "ROLLMAP": {
            "MTRL_MONITORING_DATA_RPT": {
                "name": "Material Monitoring Data Report",
                "brs": [""]
            },
            "PROC_STAT_DATA": {
                "name": "Processing State Change Report",
                "brs": [""]
            },
            "WIP_RPT": {
                "name": "WIP Data Report",
                "brs": [""]
            },
            "CUTTING_RPT": {
                "name": "Cutting Report (Roll-In)",
                "brs": [""]
            },
            "CUTTING_RPT_STATE": {
                "name": "Cutting Report (State)",
                "brs": [""]
            },
            "CUTTING_RPT_OFFSET": {
                "name": "Cutting Report (Position Offset)",
                "brs": [""]
            },
            "PROC_STAT_MAP_DATA_RPT": {
                "name": "Processing State Map Data Report",
                "brs": [""]
            },
            "INSPECTION_STAT_MAP_DATA_RPT": {
                "name": "Inspection State Map Data Report",
                "brs": [""]
            },
            "SECTION_DEF_DATA_RPT": {
                "name": "Section Defect Data Report",
                "brs": [""]
            },
            "SPOT_DEF_DATA_RPT": {
                "name": "Spot Defect Data Report",
                "brs": [""]
            },
            "SECTION_DEF_MARKING_DATA_RPT": {
                "name": "Section Defect Marking Data Report",
                "brs": [""]
            },
            "SPOT_DEF_MARKING_DATA_RPT": {
                "name": "Spot Defect Marking Data Report",
                "brs": [""]
            },
            "DATUM_POINT_MARK_RPT": {
                "name": "Datum Point Marking Data Report",
                "brs": [""]
            },
            "DATUM_POINT_MARKING_UNIT_STAT_CHG_RPT": {
                "name": "Datum Point Marking Unit State Change Report",
                "brs": [""]
            },
        },
        "RMS": {}
    },

    "ROL": {
        "EQP": {
            "G2_1_CARR_ID_RPT": {
                "name": "Carrier ID Report",
                "brs": [
                    "BR_MHS_EIF_REG_REPORT_LOADED_CSTID",
                    "BR_PRD_CHK_INPUT_LOT_RP_L",
                    "DA_PRD_SEL_LOT_INFO_BY_EIF",
                    "BR_PRD_SEL_LOT_INFO_BY_CSTID",
                    "BR_PRD_GET_RM_EIF_INPUT_LOT_SET"
                ]
            },
            "G2_2_CARR_JOB_START": {
                "name": "Carrier Job Start Report",
                "brs": ["BR_PRD_CHK_INPUT_LOT_RP_L","BR_PRD_GET_RM_EIF_OUT_LOTID","BR_PRD_REG_RM_EIF_UW_OUTPUT","BR_PRD_REG_RM_EIF_UW_INPUT"]
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
                "brs": ["BR_PRD_GET_NEW_LOTID_RP_EIF","BR_PRD_REG_START_LOT_RP_EIF","BR_PRD_GET_RM_EIF_OUT_LOTID","BR_PRD_REG_RM_EIF_EQPT_START"]
            },
            "G3_3_LOT_END_RPT": {
                "name": "Lot End Report",
                "brs": ["BR_PRD_REG_EQPT_END_LOT_RP","BR_PRD_GET_RM_EIF_OUT_LOTID","BR_PRD_REG_RM_EIF_EQPT_END"]
            },
            "G3_6_WIP_DATA_RPT": {
                "name": "WIP Data Report",
                "brs": ["BR_PRD_REG_EQPT_WIPQTY","BR_QCA_REG_EQPT_DATA_CLCT","BR_EQP_REG_EQPT_OPER_INFO"]
            }
        },
        "ROLLMAP": {
            "CARR_ID_RPT": {
                "name": "Carrier ID Report",
                "brs": ["BR_PRD_CHK_INPUT_LOT_RP_RM_WITH_OUT_MARK"]
            },
            "CARR_JOB_START": {
                "name": "Carrier Job Start Report",
                "brs": []
            },
            "INSPECT_STAT_MAP_DATA_RPT": {
                "name": "Inspection State Map Data Report",
                "brs": ["BR_PRD_REG_THICK_SCAN_AVG_RM"]
            },
            "SECTION_DEF_DATA_DATA_RPT": {
                "name": "Section Defect Data Report",
                "brs": ["BR_PRD_REG_PET_END_RM"]
            },
            "SPOT_DEF_DATA_RPT": {
                "name": "Spot Defect Data Report",
                "brs": ["BR_PRD_REG_VIS_SURF_NG_RM"]
            },
            "SPOT_DEF_MARKING_DATA_RPT": {
                "name": "Spot Defect Marking Data Report",
                "brs": ["BR_PRD_REG_TAG_SPOT_POSITION_RM"]
            },
            "DEF_MARKING_DATA_SEND": {
                "name": "Defect Marking Data Send",
                "brs": []
            },
            "ELEC_SCRAP_OUT_RPT": {
                "name": "Electrode Scrap Output Report",
                "brs": ["BR_PRD_REG_RM_EIF_SCRAP","BR_PRD_GET_RM_EIF_INPUT_LOT_SET","BR_PRD_REG_RM_EIF_SCRAP_RESULT"]
            },
            "RW_MANUAL_SCRAP_RPT": {
                "name": "RW Maual Scrap End Report",
                "brs": ["BR_PRD_REG_SCRAP_RESULT_RM"]
            },
            "DATUM_MARK_DETECT_RPT": {
                "name": "Datum Point Marking Detection Report",
                "brs": ["BR_PRD_REG_MARKING_DETECT_RM"]
            },
            "DATUM_MARKING_DATA_SEND": {
                "name": "Datum Point Marking Data Send",
                "brs": []
            },
            "RW_CONN_LOSS_RPT": {
                "name": "RW Connection Loss Data Report",
                "brs": ["BR_PRD_REG_RW_CONNECTION_LOSS_RM"]
            },
            "UW_CONN_LOSS_RPT": {
                "name": "UW Connection Loss Data Report",
                "brs": ["BR_PRD_REG_UW_CONNECTION_LOSS_RM"]
            },
            "THICK_DEFECT_DATA_RPT": {
                "name": "Thickness Defect Data Report",
                "brs": ["BR_PRD_REG_THICK_NG_RM"]
            },
            "APP_WEB_BREAK_DATA_RPT": {
                "name": "Appearance Web Break Data Report",
                "brs": ["BR_PRD_REG_WEB_BREAK_NG_RM"]
            },
            "POSITION_OFFSET": {
                "name": "Position Offset",
                "brs": []
            },
            "WIP_RPT": {
                "name": "Wip Report",
                "brs": []
            },
            "EQPT_OP_MODE_CHANGE_RPT": {
                "name": "Equipment Operation Mode Change Report",
                "brs": []
            },
            "CARRIER_ID_RPT": {
                "name": "Carrier ID Report",
                "brs": ["BR_PRD_GET_RM_EIF_INPUT_LOT_SET"]
            },
            "CARR_JOB_START_RPT": {
                "name": "Carrier Job Start Report",
                "brs": ["BR_PRD_GET_RM_EIF_OUT_LOTID","BR_PRD_REG_RM_EIF_UW_OUTPUT","BR_PRD_REG_RM_EIF_UW_INPUT"]
            },
            "LOT_START": {
                "name": "Lot Start Report",
                "brs": ["BR_PRD_GET_RM_EIF_OUT_LOTID","BR_PRD_REG_RM_EIF_EQPT_START"]
            },
            "LOT_END": {
                "name": "Lot End Report",
                "brs": ["BR_PRD_GET_RM_EIF_OUT_LOTID","BR_PRD_REG_RM_EIF_EQPT_START"]
            },
            "INSPECT_STAT_MAP_DATA_RPT": {
                "name": "Inspection State Map Data Report",
                "brs": ["BR_PRD_GET_RM_EIF_OUT_LOTID","BR_PRD_REG_RM_EIF_THICK_SCAN_AVG"]
            },
            "SECTION_DEF_DATA_RPT": {
                "name": "Section Defect Data Report",
                "brs": ["BR_PRD_GET_RM_EIF_OUT_LOTID","BR_PRD_REG_RM_EIF_PET"]
            },
            "SPOT_DEF_DATA_RPT": {
                "name": "Spot Defect Data Report",
                "brs": ["BR_PRD_GET_RM_EIF_OUT_LOTID","BR_PRD_REG_RM_EIF_VIS_SURF_NG"]
            },
            "SECTION_DEFT_MARK_DATA_REPORT": {
                "name": "Section Defect Marking Data Report",
                "brs": ["BR_PRD_GET_RM_EIF_OUT_LOTID","BR_PRD_REG_RM_EIF_TAG_SECTION","BR_PRD_REG_RM_EIF_TAG_SECTION_SINGLE"]
            },
            "SPOT_DEF_MARKING_DATA_RPT": {
                "name": "Spot Defect Marking Data Report",
                "brs": ["BR_PRD_GET_RM_EIF_OUT_LOTID","BR_PRD_REG_RM_EIF_TAG_SPOT"]
            },
            "ELEC_SCRAP_OUT_RPT": {
                "name": "Electrode Scrap Output Report",
                "brs": ["BR_PRD_REG_RM_EIF_SCRAP","BR_PRD_REG_RM_EIF_SCRAP_RESULT"]
            },
            "RW_MANUAL_SCRAP_RPT": {
                "name": "RW Manual Scrap Report",
                "brs": ["BR_PRD_REG_RM_EIF_SCRAP_RW"]
            },
            "TAG_SECT_SCRAP_RPT": {
                "name": "Tag Section Scrap Data Report",
                "brs": ["BR_PRD_GET_RM_EIF_OUT_LOTID","BR_PRD_REG_RM_EIF_SCRAP_SECTION"]
            },
            "DATUM_MARK_DETECT_RPT": {
                "name": "Datum Point Marking Detect Report",
                "brs": ["BR_PRD_GET_RM_EIF_OUT_LOTID","BR_PRD_REG_RM_EIF_MARK_DETECT"]
            },
            "RW_CONN_LOSS_DATA_RPT": {
                "name": "RW Connection Loss Data Report",
                "brs": ["BR_PRD_REG_RM_EIF_RW_CONNECTION_LOSS"]
            },
            "UW_CONN_LOSS_DATA_RPT": {
                "name": "UW Connection Loss Data Report",
                "brs": ["BR_PRD_REG_RM_EIF_UW_CONNECTION_LOSS"]
            },
            "THICK_DEFECT_DATA_RPT": {
                "name": "Thickness Defect Data Report",
                "brs": ["BR_PRD_GET_RM_EIF_OUT_LOTID","BR_PRD_REG_RM_EIF_THICK_NG"]
            },
            "APP_WEB_BREAK_DATA_RPT": {
                "name": "Apperance Web Break Data Report",
                "brs": ["BR_PRD_GET_RM_EIF_OUT_LOTID","BR_PRD_REG_RM_EIF_WEB_BREAK_NG"]
            },
            "HMI_MANUAL_SCRAP_DATA_RPT": {
                "name": "HMI Manual Scrap Data Report",
                "brs": ["BR_PRD_GET_RM_EIF_OUT_LOTID","BR_PRD_REG_RM_EIF_OUTSIDE_SCRAP"]
            }                      
        },
        "RMS": {}
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
            item_name TEXT,
            category TEXT   -- 🔥 NEW
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
    def insert_item(self, item_code, item_name, category):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO items (item_code, item_name, category)
            VALUES (?, ?, ?)
        """, (item_code, item_name, category))
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

    def get_item_category(self, item_code):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT category FROM items WHERE item_code = ?
        """, (item_code,))
        row = cursor.fetchone()
        return row["category"] if row else "EQP"

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
        - COMMON_DATA (default EQP)
        - EQP_DATA (EQP / ROLLMAP split)
        - dynamic suffix expansion (_01, _02, etc.)
        """

        self.clear_all()

        merged = {}

        # -----------------------------
        # 1️⃣ Load COMMON (default EQP)
        # -----------------------------
        for category, items in COMMON_DATA.items():
            for item_code, data in items.items():
                merged[item_code] = {
                    "name": data["name"],
                    "brs": list(data["brs"]),
                    "category": category
                }

        # -----------------------------
        # 2️⃣ Apply Equipment Override
        # -----------------------------
        eqp_data = EQP_DATA.get(eqp, {})

        # ✅ Detect format ONCE
        is_new_format = (
            isinstance(eqp_data, dict) and
            any(k in eqp_data for k in ("EQP", "ROLLMAP", "RMS"))
        )

        if is_new_format:
            # -----------------------------
            # NEW FORMAT (EQP / ROLLMAP)
            # -----------------------------
            for category, items in eqp_data.items():
                for item_code, data in items.items():
                    merged[item_code] = {
                        "name": data["name"],
                        "brs": list(data["brs"]),
                        "category": category
                    }
        else:
            # -----------------------------
            # OLD FORMAT (flat → treat as EQP)
            # -----------------------------
            for item_code, data in eqp_data.items():
                merged[item_code] = {
                    "name": data["name"],
                    "brs": list(data["brs"]),
                    "category": "EQP"
                }

        # -----------------------------
        # 3️⃣ Expand dynamic suffix items
        # -----------------------------
        if dynamic_items:
            expanded = {}

            for item_code, data in merged.items():

                # Keep original
                expanded[item_code] = data

                # Expand suffix (🔥 FIX: keep category)
                if item_code in dynamic_items:
                    for suffix in dynamic_items[item_code]:
                        new_code = f"{item_code}_{suffix}"

                        expanded[new_code] = {
                            "name": f"{data['name']} {suffix}",
                            "brs": list(data["brs"]),
                            "category": data["category"]   # 🔥 CRITICAL FIX
                        }

            merged = expanded

        # -----------------------------
        # 4️⃣ Insert into DB
        # -----------------------------
        for item_code, data in merged.items():
            self.insert_item(item_code, data["name"], data["category"])

            for br in data["brs"]:
                self.insert_item_br(item_code, br)

        print(f"✅ DB rebuilt for equipment: {eqp}")