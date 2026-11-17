# db_manager.py
"""
Item metadata (display names, categories and expected BRs) now lives in
item_data.json, not in this file. Edit the JSON and reload the variable log;
no code change or rebuild is needed.

Where the file is looked for, in order:
  1. EIF_ITEM_DATA environment variable (full path), if set
  2. next to the program (the .exe when built with PyInstaller, else this .py)
  3. the current working directory
  4. a copy bundled inside the .exe (PyInstaller --add-data), read-only

File layout:
  {
    "COMMON":    { "EQP": { "<ITEM_CODE>": {"name": "...", "brs": ["BR_..."]}, ... },
                   "ROLLMAP": {...}, "RMS": {...}, "ROS": {...} },
    "EQUIPMENT": { "MIX": { "EQP": {...}, "ROLLMAP": {...}, "RMS": {...} }, ... }
  }
COMMON applies to every equipment; an EQUIPMENT entry replaces the COMMON
entry with the same item code for that equipment. Keys starting with "_"
are ignored (use them for notes).

FORM equipment (Degas Loader etc.) reports handshakes with named bits instead
of B_TRIGGER_REPORT items, so it has its own "FORM" section, keyed by trigger:
  "FORM": {
    "SETTINGS": {"ack_ok": ["10"]},          ACK word values that mean OK
    "COMMON":   {"triggers": {...}},          triggers every FORM equipment has
    "DEGASLOADER": {
      "match": ["DEGASLOADER"],               text found in the log's element name
      "triggers": {
        "TRAY_INFO:I_B_TRAY_BCR_READ_REQ": {  CATEGORY:VARIABLE of the request
          "name":    "Tray BCR Read Request",
          "confirm": "TRAY_INFO:O_B_TRAY_BCR_READ_REQ_CONFIRM",   optional
          "ack":     "TRAY_INFO:O_W_TRAY_BCR_READ_REQ_CONFIRM_ACK", optional
          "group":   "TRAY",                  Sequence tab folder (default: CATEGORY)
          "brs":     ["BR_SET_DEGAS_LD_TRAY_ARRIVED", ...]
        },
        "DEGAS_STATUS:I_W_EQP_STATUS": {"type": "word", ...}   every value change
      }
    }
  }
A bit trigger becomes one sequence per handshake: request ON -> confirm ON ->
request OFF -> confirm OFF. It is shown in red when the ACK word was not OK,
the confirm never came, or a new request started before the last one ended.
"""
import json
import os
import sqlite3
import sys

DATA_FILENAME = "item_data.json"
CATEGORIES = ("EQP", "ROLLMAP", "RMS", "ROS")


class ItemDataError(Exception):
    """item_data.json is missing or can't be used. The message says why."""


def _program_dir():
    if getattr(sys, "frozen", False):                   # PyInstaller .exe
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def find_data_file():
    """Path of the item data file to use, or None if there isn't one."""
    env = os.environ.get("EIF_ITEM_DATA")
    candidates = [env] if env else []
    candidates += [
        os.path.join(_program_dir(), DATA_FILENAME),
        os.path.join(os.getcwd(), DATA_FILENAME),
    ]
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        candidates.append(os.path.join(bundled, DATA_FILENAME))
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    return None


def _pairs_no_dupes(where):
    """object_pairs_hook that records duplicate keys (json would silently keep the last)."""
    def hook(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                where.append(k)
            out[k] = v
        return out
    return hook


def _clean_items(items, where, problems):
    if not isinstance(items, dict):
        raise ItemDataError(f"{where} must be an object of items, got {type(items).__name__}")
    out = {}
    for code, d in items.items():
        if code.startswith("_"):
            continue
        if not isinstance(d, dict):
            raise ItemDataError(f'{where}/{code} must look like {{"name": "...", "brs": [...]}}')
        name = d.get("name") or code
        brs = d.get("brs", [])
        if isinstance(brs, str):
            brs = [brs]
        if not isinstance(brs, list):
            raise ItemDataError(f'{where}/{code}: "brs" must be a list of BR names')
        out[code] = {"name": str(name), "brs": [str(b).strip() for b in brs if str(b).strip()]}
    return out


def _check_key(key, where):
    if not isinstance(key, str) or key.count(":") != 1 or not all(key.split(":")):
        raise ItemDataError(f'{where}: "{key}" must be written as CATEGORY:VARIABLE, '
                            f'e.g. "TRAY_INFO:I_B_TRAY_BCR_READ_REQ"')


def _clean_triggers(triggers, where):
    if not isinstance(triggers, dict):
        raise ItemDataError(f'{where}/triggers must be an object of triggers')
    out = {}
    for key, t in triggers.items():
        if key.startswith("_"):
            continue
        _check_key(key, f"{where}/triggers")
        if not isinstance(t, dict):
            raise ItemDataError(f'{where}/triggers/{key} must look like {{"name": "...", "brs": [...]}}')
        cat, var = key.split(":")
        kind = t.get("type") or ("word" if "_W_" in var[:4] else "bit")
        if kind not in ("bit", "word"):
            raise ItemDataError(f'{where}/triggers/{key}: "type" must be "bit" or "word"')
        brs = t.get("brs", [])
        if isinstance(brs, str):
            brs = [brs]
        if not isinstance(brs, list):
            raise ItemDataError(f'{where}/triggers/{key}: "brs" must be a list of BR names')
        item = {
            "name": str(t.get("name") or var),
            "type": kind,
            "group": str(t.get("group") or cat),
            "brs": [str(b).strip() for b in brs if str(b).strip()],
        }
        for field in ("confirm", "ack"):
            if t.get(field):
                _check_key(t[field], f"{where}/triggers/{key}/{field}")
                item[field] = t[field]
        if "ack_ok" in t:
            item["ack_ok"] = [str(v) for v in t["ack_ok"]]
        out[key] = item
    return out


def _clean_form(form):
    """FORM section -> {"settings": {...}, "common": {key: trigger}, "equipment": {eqp: {...}}}"""
    if not form:
        return {"settings": {"ack_ok": ["10"]}, "common": {}, "equipment": {}}
    if not isinstance(form, dict):
        raise ItemDataError("FORM must be an object")
    settings = form.get("SETTINGS") or {}
    out = {
        "settings": {"ack_ok": [str(v) for v in settings.get("ack_ok", ["10"])]},
        "common": _clean_triggers((form.get("COMMON") or {}).get("triggers", {}), "FORM/COMMON"),
        "equipment": {},
    }
    for eqp, cfg in form.items():
        if eqp.startswith("_") or eqp in ("SETTINGS", "COMMON"):
            continue
        if not isinstance(cfg, dict):
            raise ItemDataError(f"FORM/{eqp} must be an object with match and triggers")
        match = cfg.get("match") or [eqp]
        if isinstance(match, str):
            match = [match]
        out["equipment"][eqp] = {
            "match": [str(m).upper() for m in match if str(m).strip()],
            "triggers": _clean_triggers(cfg.get("triggers", {}), f"FORM/{eqp}"),
        }
    return out


def load_item_data(path=None):
    """
    Read and check the item data file.
    Returns (common, equipment, form, warnings). Raises ItemDataError on a bad file.
    """
    path = path or find_data_file()
    if path is None:
        raise ItemDataError(
            f"{DATA_FILENAME} was not found. Put it next to the program "
            f"({_program_dir()}) or set EIF_ITEM_DATA to its full path."
        )

    dupes = []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            doc = json.load(f, object_pairs_hook=_pairs_no_dupes(dupes))
    except json.JSONDecodeError as e:
        raise ItemDataError(f"{path}\nline {e.lineno}, column {e.colno}: {e.msg}") from None
    except OSError as e:
        raise ItemDataError(f"Can't read {path}: {e}") from None

    if not isinstance(doc, dict):
        raise ItemDataError(f"{path}: the top level must be an object with COMMON and EQUIPMENT")

    problems = []
    common = {}
    for cat, items in (doc.get("COMMON") or {}).items():
        if not cat.startswith("_"):
            common[cat] = _clean_items(items, f"COMMON/{cat}", problems)

    equipment = {}
    for eqp, cats in (doc.get("EQUIPMENT") or {}).items():
        if eqp.startswith("_"):
            continue
        if not isinstance(cats, dict):
            raise ItemDataError(f"EQUIPMENT/{eqp} must be an object of categories")
        equipment[eqp] = {
            cat: _clean_items(items, f"EQUIPMENT/{eqp}/{cat}", problems)
            for cat, items in cats.items() if not cat.startswith("_")
        }

    form = _clean_form(doc.get("FORM"))

    warnings = []
    if dupes:
        warnings.append("Duplicate item codes (the last one is used): " + ", ".join(sorted(set(dupes))))
    unknown = sorted({c for c in common} | {c for e in equipment.values() for c in e}) 
    unknown = [c for c in unknown if c not in CATEGORIES]
    if unknown:
        warnings.append("Unknown categories (shown as written): " + ", ".join(unknown))
    return common, equipment, form, warnings


# ------------------------------------------------------------
# Loaded data. Re-read automatically when the file changes.
# ------------------------------------------------------------
COMMON_DATA = {}
EQP_DATA = {}
FORM_DATA = {"settings": {"ack_ok": ["10"]}, "common": {}, "equipment": {}}
DATA_PATH = None
LOAD_ERROR = None          # message of the last failed load, or None
LOAD_WARNINGS = []
_loaded_stamp = None
_known_bases = None


def reload_if_changed(force=False):
    """
    Re-read item_data.json if it changed since the last load.
    On a bad file the previous good data is kept and LOAD_ERROR says why.
    Returns True if new data was loaded.
    """
    global COMMON_DATA, EQP_DATA, FORM_DATA, DATA_PATH, LOAD_ERROR, LOAD_WARNINGS, _loaded_stamp, _known_bases
    path = find_data_file()
    try:
        stamp = (path, os.path.getmtime(path), os.path.getsize(path)) if path else None
    except OSError:
        stamp = None
    if not force and stamp is not None and stamp == _loaded_stamp:
        return False
    try:
        common, equipment, form, warnings = load_item_data(path)
    except ItemDataError as e:
        LOAD_ERROR = str(e)
        return False
    COMMON_DATA, EQP_DATA, FORM_DATA, DATA_PATH = common, equipment, form, path
    LOAD_ERROR, LOAD_WARNINGS = None, warnings
    _loaded_stamp, _known_bases = stamp, None
    return True


def known_bases():
    """Every item code defined anywhere in the file (for suffix splitting)."""
    global _known_bases
    if _known_bases is None:
        bases = set()
        for items in COMMON_DATA.values():
            bases.update(items)
        for cats in EQP_DATA.values():
            for items in cats.values():
                bases.update(items)
        _known_bases = bases
    return _known_bases


FORM_PREFIX = "FORM:"


def form_triggers(eqp):
    """All triggers for one FORM equipment: FORM COMMON, then that equipment's own (which win)."""
    triggers = dict(FORM_DATA["common"])
    triggers.update(FORM_DATA["equipment"].get(eqp, {}).get("triggers", {}))
    return triggers


def form_worker_config():
    """
    Plain dict handed to VariableLogWorker:
      {"ack_ok": [...], "equipment": {eqp: {"match": [...], "triggers": {...}}}}
    """
    return {
        "ack_ok": list(FORM_DATA["settings"]["ack_ok"]),
        "equipment": {
            eqp: {"match": list(cfg["match"]), "triggers": form_triggers(eqp)}
            for eqp, cfg in FORM_DATA["equipment"].items()
        },
    }


reload_if_changed(force=True)


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

    def get_item_code(self, item_code):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT item_code
            FROM items
            WHERE item_code = ?
        """, (item_code,))
        row = cursor.fetchone()
        return row["item_code"] if row else None

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
    def rebuild_for_equipment(self, eqp, dynamic_items=None, item_categories=None):
        """
        Build DB using:
        - COMMON_DATA (default EQP)
        - EQP_DATA (EQP / ROLLMAP split)
        - dynamic suffix expansion (_01, _02, etc.)
        - item_categories from actual log data (overrides hardcoded categories)
        """

        # Pick up edits to item_data.json without restarting the app
        reload_if_changed()

        self.clear_all()
        merged = {}

        # FORM equipment: the items are its triggers ("CATEGORY:VARIABLE"),
        # not the ELEC/ASSY item tables
        is_form = isinstance(eqp, str) and eqp.startswith(FORM_PREFIX)
        if is_form:
            for key, t in form_triggers(eqp[len(FORM_PREFIX):]).items():
                merged[key] = {"name": t["name"], "brs": list(t["brs"]), "category": t["group"]}

        # 1️⃣ Load COMMON (default EQP)
        for category, items in ({} if is_form else COMMON_DATA).items():
            for item_code, data in items.items():
                merged[item_code] = {
                    "name": data["name"],
                    "brs": list(data["brs"]),
                    "category": category
                }

        # 2️⃣ Apply Equipment Override
        eqp_data = {} if is_form else EQP_DATA.get(eqp, {})
        is_new_format = (
            isinstance(eqp_data, dict) and
            any(k in eqp_data for k in ("EQP", "ROLLMAP", "RMS"))
        )

        if is_new_format:
            for category, items in eqp_data.items():
                for item_code, data in items.items():
                    merged[item_code] = {
                        "name": data["name"],
                        "brs": list(data["brs"]),
                        "category": category
                    }
        else:
            for item_code, data in eqp_data.items():
                merged[item_code] = {
                    "name": data["name"],
                    "brs": list(data["brs"]),
                    "category": "EQP"
                }

        # 3️⃣ Expand dynamic suffix items
        if dynamic_items:
            expanded = {}
            for item_code, data in merged.items():
                expanded[item_code] = data
                if item_code in dynamic_items:
                    for suffix in dynamic_items[item_code]:
                        new_code = f"{item_code}_{suffix}"
                        expanded[new_code] = {
                            "name": f"{data['name']} {suffix}",
                            "brs": list(data["brs"]),
                            "category": data["category"]
                        }
            merged = expanded

        # 🔥 4️⃣ Override categories from actual log data
        if item_categories:
            for item_code, log_category in item_categories.items():
                if item_code in merged:
                    merged[item_code]["category"] = log_category
                else:
                    # Item exists in logs but not in COMMON_DATA or EQP_DATA
                    # Add it with the log-derived category
                    merged[item_code] = {
                        "name": item_code,  # no friendly name available
                        "brs": [],
                        "category": log_category
                    }

        # 5️⃣ Insert into DB
        for item_code, data in merged.items():
            self.insert_item(item_code, data["name"], data["category"])
            for br in data["brs"]:
                self.insert_item_br(item_code, br)

        print(f"✅ DB rebuilt for equipment: {eqp} (from {DATA_PATH})")