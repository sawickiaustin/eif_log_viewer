# worker.py
import re
import json
from datetime import datetime, timedelta
from PySide6.QtCore import QThread, Signal
import bisect
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor


# ============================================================
# HELPER FUNCTIONS (must be at module level for multiprocessing)
# ============================================================

KNOWN_EQUIPMENTS = ["MIX","COT","ROL","RWD","TRS","SLT","NND","LAM","STK","PKG","CESS"]

def _detect_equipment(raw):
    try:
        for part in raw.split("["):
            if "." in part and "]" in part:
                prefix = part.split("]")[0].split(".")[0].upper()
                for eq in KNOWN_EQUIPMENTS:
                    if eq in prefix:
                        return eq
    except Exception:
        pass
    return None

def _extract_item_code(raw):
    try:
        # Only look at the structural part, before the value
        structural = raw.split(" : ")[0] if " : " in raw else raw
        
        parts = structural.split("[")
        result = None
        for part in parts:
            if ":" in part and "]" in part:
                block = part.split("]")[0]
                candidate = block.split(":")[0]
                # Skip system blocks (contain dots like "DNC1_1.IO_DNC")
                if "." not in candidate:
                    result = candidate
        return result
    except Exception:
        pass
    return None

def _parse_item_signal(raw):
    try:
        structural = raw.split(" : ")[0] if " : " in raw else raw
        block = structural.split("[")[-1].split("]")[0]
        item, signal = block.split(":")
        return item, signal
    except:
        return None, None

def _parse_value(raw):
    try:
        if " : " in raw:
            return raw.rsplit(" : ", 1)[1].strip()
    except:
        pass
    return None

def _process_variable_chunk(filepath, start_line, end_line):
    """Process a chunk of the variable log file."""
    from model import LogLine
    
    logs = []
    item_index = {}
    sequences = {}
    item_categories = {}  # Track categories during parsing
    eqp_set = set()
    skipped_count = 0
    
    # Sequence building state
    active = {}
    b_intervals = {}
    w_timestamps = {}
    ack_events = {} 
    buffer_sec = 1
    
    KNOWN_EQUIPMENTS = ["MIX","COT","ROL","RWD","TRS","SLT","NND","LAM","CESS","PKG"]
    
    with open(filepath, "r", encoding="utf-8-sig", errors="ignore") as f:
        for idx, raw in enumerate(f):
            if idx < start_line:
                continue
            if idx >= end_line:
                break
            
            raw = raw.rstrip()
            if not raw:
                continue
            
            # Validation
            if len(raw) < 19:
                skipped_count += 1
                continue
            
            ts_str = raw[:19]
            if not (ts_str[4] == '-' and ts_str[7] == '-' and ts_str[10] == ' ' and ts_str[13] == ':' and ts_str[16] == ':'):
                skipped_count += 1
                continue
            
            if "[" not in raw or "]" not in raw:
                skipped_count += 1
                continue
            
            # Create log
            log = LogLine(raw=raw)
            log.original_index = idx
            log.raw_lower = raw.casefold()
            
            # Parse timestamp
            try:
                ts = datetime(
                    int(raw[0:4]), int(raw[5:7]), int(raw[8:10]),
                    int(raw[11:13]), int(raw[14:16]), int(raw[17:19])
                )
                ts_val = ts.timestamp()
            except:
                ts = None
                ts_val = 0
            
            log.ts = ts
            
            # System
            log.system = None
            log.category = "EQP"  # default

            parts = raw.split("[")
            for p in parts:
                if "." in p and "]" in p:
                    system_block = p.split("]")[0]
                    log.system = system_block.split(".")[-1]
        
                    # Infer category from system block
                    system_upper = system_block.upper()
                    if "RMS" in system_upper:
                        log.category = "RMS"
                    elif "ROLLMAP" in system_upper:
                        log.category = "ROLLMAP"
                    else:
                        log.category = "EQP"
                    break
            
            # Parse equipment
            eqp = _detect_equipment(raw)
            log.equipment = eqp
            if eqp:
                eqp_set.add(eqp)
            
            # Item code
            item_code = _extract_item_code(raw)
            log.item_code = item_code
            if item_code:
                item_index.setdefault(item_code, []).append(log)
                if item_code not in item_categories:
                    item_categories[item_code] = log.category
            
            logs.append(log)
            
            # Sequence building
            if not ts:
                    continue

            item, signal = _parse_item_signal(raw)
            val = _parse_value(raw)

            if not item or not signal:
                continue

            if "W_TRIGGER_REPORT_ACK" in signal and val == "11":
                ack_events.setdefault(item, []).append(ts.timestamp())

            # W_TRIGGER_REPORT
            if "W_TRIGGER" in signal:
                ts_val_float = ts.timestamp()
                lo = ts_val_float - buffer_sec
                hi = ts_val_float + buffer_sec

                intervals = b_intervals.get(item, [])
                idx_bisect = bisect.bisect_left(intervals, (lo,))

                inside_b = False
                for iv_start, iv_end in intervals[max(0, idx_bisect - 1): idx_bisect + 2]:
                    if iv_start <= hi and iv_end >= lo:
                        inside_b = True
                        break

                if inside_b:
                    continue

                seen_w = w_timestamps.setdefault(item, set())
                if ts in seen_w:
                    continue
                seen_w.add(ts)

                sequences.setdefault(item, []).append({
                    "start": ts,
                    "end": ts,
                    "type": "W"
                })
                continue

            # B_TRIGGER_REPORT - Step 1: B ON
            if ("B_TRIGGER_REPORT_CONF" not in signal
                    and "B_TRIGGER_REPORT" in signal
                    and val == "ON"):
                active[item] = {
                    "start": ts,
                    "conf_on": False,
                    "b_off": False,
                    "logs": [log]
                }
                continue

            if item not in active:
                continue

            seq = active[item]

            # Step 2: CONF ON
            if "B_TRIGGER_REPORT_CONF" in signal and val == "ON":
                seq["conf_on"] = True
                seq["logs"].append(log)
                continue

            # Step 3: B OFF
            if ("B_TRIGGER_REPORT_CONF" not in signal
                    and "B_TRIGGER_REPORT" in signal
                    and val == "OFF"):
                seq["b_off"] = True
                seq["logs"].append(log)
                continue

            # Step 4: CONF OFF → sequence complete
            if "B_TRIGGER_REPORT_CONF" in signal and val == "OFF":
                if seq["conf_on"] and seq["b_off"]:
                    seq["logs"].append(log)
                    new_start = seq["start"] - timedelta(seconds=buffer_sec)
                    new_end = ts + timedelta(seconds=buffer_sec)

                    existing = sequences.setdefault(item, [])

                    # Evict W events inside this B window. Only the tail can qualify:
                    # entries are appended in log order, and anything older than
                    # new_start was already handled by the previous B. Scanning just the
                    # tail keeps this O(1) per sequence instead of O(len(existing)).
                    k = len(existing)
                    while k > 0 and existing[k - 1]["start"] >= new_start:
                        k -= 1
                    if k < len(existing):
                        existing[k:] = [
                            s for s in existing[k:]
                            if not (
                                s["type"] == "W"
                                and new_start <= s["start"] <= new_end
                            )
                        ]

                    win_lo = seq["start"].timestamp()
                    win_hi = ts.timestamp()
                    acks = ack_events.get(item, [])
                    lo_i = bisect.bisect_left(acks, win_lo)
                    hi_i = bisect.bisect_right(acks, win_hi)
                    has_ack_error = hi_i > lo_i

                    existing.append({
                        "start": seq["start"],
                        "end": ts,
                        "type": "B",
                        "core_indices": [l.original_index for l in seq["logs"]],
                        "error": has_ack_error
                    })

                    # Register interval for future W overlap checks
                    interval = (seq["start"].timestamp(), ts.timestamp())
                    item_intervals = b_intervals.setdefault(item, [])
                    bisect.insort(item_intervals, interval)

                active.pop(item, None)
    
    current_eqp = next(iter(eqp_set), None)
    return (logs, item_index, sequences, item_categories, current_eqp, skipped_count)

"""
def _process_br_chunk(filepath, start_line, end_line):
    ""Process a chunk of BR log file.""
    br_calls = []
    full_br_index = {}
    pending = {}
    
    uuid_re = re.compile(r"(?:ELTR\w*|ASSY\w*)\((.*?)\)")
    requestq_check = "(REQUESTQ)"
    replyq_check = "(RECEIVE_REPLYQ)"
    bizrule_check = "BIZRULE"
    
    json_buffer = []
    in_json_block = False
    brace_count = 0
    current_uuid = None
    current_ts = None
    
    with open(filepath, "r", encoding="utf-8-sig", errors="ignore") as f:
        for idx, line in enumerate(f):
            if idx < start_line:
                continue
            if idx >= end_line:
                break
            
            line = line.rstrip()
            if not line:
                continue
            
            # Build index
            if bizrule_check in line:
                space_idx = line.find(" ", 20)
                if space_idx != -1:
                    ts_str = line[:space_idx]
                    try:
                        ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")
                    except:
                        ts = datetime.min
                else:
                    ts = datetime.min
                
                bizrule_idx = line.find("BIZRULE]")
                if bizrule_idx != -1:
                    name = line[bizrule_idx+8:].strip()
                    full_br_index.setdefault(name, []).append((ts, line))
            
            # JSON block collection
            if in_json_block:
                json_buffer.append(line.strip())
                brace_count += line.count('{') - line.count('}')
                
                if brace_count == 0:
                    in_json_block = False
                    
                    try:
                        request_json = json.loads("".join(json_buffer))
                    except json.JSONDecodeError:
                        pending[current_uuid] = {
                            "timestamp": current_ts,
                            "ts_val": current_ts.timestamp(),
                            "br_name": "UNKNOWN",
                            "tables": {}
                        }
                        json_buffer = []
                        continue
                    
                    br_name = request_json.get("actID", "UNKNOWN")
                    tables = {}
                    ref_json = request_json.get("refDS")
                    
                    if ref_json:
                        try:
                            ref_data = json.loads(ref_json)
                            for table_name, rows in ref_data.items():
                                tables[table_name] = [
                                    {k: "" if v is None else str(v) for k, v in row.items()}
                                    for row in rows
                                ]
                        except json.JSONDecodeError:
                            pass
                    
                    pending[current_uuid] = {
                        "timestamp": current_ts,
                        "ts_val": current_ts.timestamp(),
                        "br_name": br_name,
                        "tables": tables
                    }
                    
                    json_buffer = []
                continue
            
            # REQUESTQ check
            if requestq_check in line:
                try:
                    ts_str = line[:23]
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")
                except:
                    ts = datetime.min
                
                match = uuid_re.search(line)
                if match:
                    current_uuid = match.group(1)
                    current_ts = ts
                    in_json_block = True
                    brace_count = 1
                    json_buffer = ["{"]
                continue
            
            # RECEIVE_REPLYQ check
            if replyq_check in line:
                match = uuid_re.search(line)
                if not match:
                    continue
                
                uuid = match.group(1)
                execution = pending.get(uuid)
                if not execution:
                    continue
                
                json_start = line.find("{")
                if json_start == -1:
                    continue
                
                try:
                    reply_json = json.loads(line[json_start:])
                except json.JSONDecodeError:
                    continue
                
                pending.pop(uuid, None)
                
                for key, value in reply_json.items():
                    if key.startswith("OUT_"):
                        execution["tables"][key] = [
                            {k: "" if v is None else str(v) for k, v in row.items()}
                            for row in value
                        ]
                
                execution["search_blob"] = (
                    execution["br_name"] + " " + json.dumps(execution["tables"])
                ).casefold()
                
                br_calls.append(execution)
    
    return (br_calls, full_br_index)

"""
# ============================================================
# FORM equipment: handshake sequences from configured triggers
# ============================================================
# "[CATEGORY:VARIABLE] (Type) : value" - the first match is the real one,
# values that contain brackets come after it
_FORM_CV_RE = re.compile(r"\[([A-Za-z0-9_]+):([A-Za-z0-9_]+)\]\s*\(\w+\)\s*:\s?(.*)$")
# "<date> <time> [Level] [ELEMENT]" - the element name identifies the equipment
_FORM_ELEMENT_RE = re.compile(r"^﻿?\S+ \S+ \[\w+\] \[([^\]]+)\]")


def detect_form_equipment(logs, form_cfg, max_lines=2000):
    """FORM equipment key whose "match" text is in the log's element name, or None."""
    if not form_cfg or not form_cfg.get("equipment"):
        return None
    # Longest match first, so "DEGASLOADER" wins over a shorter "LOADER"
    cands = sorted(
        ((m, eqp) for eqp, cfg in form_cfg["equipment"].items() for m in cfg.get("match", [])),
        key=lambda x: -len(x[0]),
    )
    for log in logs[:max_lines]:
        m = _FORM_ELEMENT_RE.match(log.raw)
        if not m:
            continue
        element = m.group(1).upper()
        for text, eqp in cands:
            if text in element:
                return eqp
    return None


def _precise_ts(log):
    """log.ts only has whole seconds; add the milliseconds from the raw line."""
    ts = log.ts
    raw = log.raw.lstrip("﻿")
    if ts is not None and len(raw) > 23 and raw[19] == "." and raw[20:23].isdigit():
        return ts.replace(microsecond=int(raw[20:23]) * 1000)
    return ts


def build_form_sequences(logs, triggers, ack_ok=("10",)):
    """
    logs must be in time order. Returns {trigger_key: [sequence, ...]}.

    bit trigger:  request ON -> confirm ON -> request OFF -> confirm OFF = one "B" sequence
                  (no confirm configured: request ON -> request OFF)
    word trigger: every logged value change = one "W" sequence
    error (red):  ACK word not in ack_ok, confirm never ON, confirm dropped before the
                  request, or a new request ON before the previous handshake finished
    """
    confirms, acks = {}, {}
    for key, t in triggers.items():
        if t.get("confirm"):
            confirms.setdefault(t["confirm"], []).append(key)
        if t.get("ack"):
            acks.setdefault(t["ack"], []).append(key)

    sequences, active = {}, {}

    def handshake_keys(key):
        t = triggers[key]
        return [k for k in (key, t.get("confirm"), t.get("ack")) if k]

    def close(key, end, error=False):
        a = active.pop(key)
        keys = handshake_keys(key)
        sequences.setdefault(key, []).append({
            "start": a["start"],
            "end": end,
            "type": "B",
            "core_indices": [l.original_index for l in a["logs"]],
            "error": bool(error or a["nak"]),
            "form": True,
            "categories": sorted({k.split(":")[0] for k in keys}),
            "handshake": keys,
        })

    for log in logs:
        if log.ts is None:
            continue
        m = _FORM_CV_RE.search(log.raw)
        if not m:
            continue
        key = f"{m.group(1)}:{m.group(2)}"
        val = m.group(3).strip()

        t = triggers.get(key)
        if t is not None:
            ts = _precise_ts(log)
            if t["type"] == "word":
                sequences.setdefault(key, []).append({
                    "start": ts, "end": ts, "type": "W",
                    "core_indices": [log.original_index], "error": False,
                    "form": True, "categories": [m.group(1)], "handshake": [key],
                })
            elif val == "ON":
                if key in active:                       # last handshake never finished
                    close(key, active[key]["last"], error=True)
                active[key] = {"start": ts, "last": ts, "logs": [log],
                               "conf_on": False, "conf_off": False, "req_off": False, "nak": False}
            elif val == "OFF" and key in active:
                a = active[key]
                a["req_off"] = True
                a["last"] = ts
                a["logs"].append(log)
                if not t.get("confirm"):
                    close(key, ts)
                elif a["conf_off"]:                     # host dropped confirm first (timeout)
                    close(key, ts, error=True)

        for tk in confirms.get(key, ()):
            a = active.get(tk)
            if a is None:
                continue
            ts = _precise_ts(log)
            a["logs"].append(log)
            a["last"] = ts
            if val == "ON":
                a["conf_on"] = True
            elif val == "OFF":
                a["conf_off"] = True
                if a["req_off"]:
                    close(tk, ts, error=not a["conf_on"])

        for tk in acks.get(key, ()):
            a = active.get(tk)
            if a is None:
                continue
            a["logs"].append(log)
            ok = triggers[tk].get("ack_ok", ack_ok)
            if val not in ("", "0") and val not in ok:
                a["nak"] = True

    # Handshakes still open when the file ends: keep them, they are just cut off
    for key in list(active):
        close(key, active[key]["last"])
    return sequences

# ============================================================
# Variable Log Worker (with integrated sequence building)
# ============================================================
class VariableLogWorker(QThread):
    finished = Signal(list, list, dict, object, int, dict, dict)
    # emits: (sorted_logs, sorted_timestamps, item_index, current_equipment, skipped_count, sequences, item_categories)

    KNOWN_EQUIPMENTS = ["MIX","COT","ROL","RWD","TRS","SLT","NND","LAM","CESS","PKG"]

    def __init__(self, filepath, form_cfg=None):
        super().__init__()
        self.filepath = filepath
        self.form_cfg = form_cfg       # db_manager.form_worker_config(), or None

    def _emit(self, sorted_logs, sorted_timestamps, item_index, current_equipment,
              skipped_count, sequences, item_categories):
        """Add FORM handshake sequences (if this is a FORM equipment log), then emit."""
        form_eqp = detect_form_equipment(sorted_logs, self.form_cfg)
        if form_eqp:
            current_equipment = "FORM:" + form_eqp
            triggers = self.form_cfg["equipment"][form_eqp]["triggers"]
            form_seqs = build_form_sequences(sorted_logs, triggers, self.form_cfg.get("ack_ok", ["10"]))
            for key, seqs in form_seqs.items():
                sequences[key] = seqs
                item_categories[key] = triggers[key]["group"]
        self.finished.emit(
            sorted_logs, sorted_timestamps, item_index, current_equipment,
            skipped_count, sequences, item_categories
        )

    def run(self):
        file_size = os.path.getsize(self.filepath)
        
        # Only parallelize for files > 50MB
        if file_size > 50 * 1024 * 1024:
            self._run_parallel()
        else:
            self._run_single()

    def _run_parallel(self):
        """Multi-core processing for large files."""
        num_workers = multiprocessing.cpu_count()
    
        # STEP 1: Split file into chunks by line count
        chunk_ranges = self._get_file_chunks(num_workers)
    
        # STEP 2: Process chunks in parallel
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = [
                executor.submit(_process_variable_chunk, self.filepath, start, end)
                for start, end in chunk_ranges
            ]
        
            chunk_results = [f.result() for f in futures]
    
        # STEP 3: Merge results
        all_logs = []
        all_item_index = {}
        all_sequences = {}
        all_item_categories = {}
        eqp_set = set()
        total_skipped = 0
    
        for logs, item_idx, seqs, cats, eqp, skipped in chunk_results:
            all_logs.extend(logs)
            total_skipped += skipped
        
            # Merge item index
            for item_code, logs_list in item_idx.items():
                all_item_index.setdefault(item_code, []).extend(logs_list)
        
            # Merge sequences
            for item, seq_list in seqs.items():
                all_sequences.setdefault(item, []).extend(seq_list)
        
            # 🔥 FIX: Merge categories with priority to non-EQP values
            for item_code, category in cats.items():
                if item_code not in all_item_categories:
                    all_item_categories[item_code] = category
                elif all_item_categories[item_code] == "EQP" and category != "EQP":
                    # If we already have EQP but found RMS/ROLLMAP, upgrade it
                    all_item_categories[item_code] = category
        
            if eqp:
                eqp_set.add(eqp)
    
        # STEP 4: Sort merged logs
        all_logs.sort(key=lambda x: x.ts.timestamp() if x.ts else 0)
        sorted_timestamps = [log.ts.timestamp() if log.ts else 0 for log in all_logs]
    
        current_equipment = next(iter(eqp_set), None)
    
        if total_skipped > 0:
            print(f"⚠ Skipped {total_skipped:,} invalid lines during variable log load")
    
        self._emit(
            all_logs, sorted_timestamps, all_item_index, current_equipment,
            total_skipped, all_sequences, all_item_categories
        )

    def _get_file_chunks(self, num_chunks):
        """Split file into roughly equal chunks by line count."""
        with open(self.filepath, "r", encoding="utf-8-sig", errors="ignore") as f:
            total_lines = sum(1 for _ in f)
        
        chunk_size = total_lines // num_chunks
        
        ranges = []
        for i in range(num_chunks):
            start = i * chunk_size
            end = start + chunk_size if i < num_chunks - 1 else total_lines
            ranges.append((start, end))
        
        return ranges

    def _run_single(self):
        """Single-threaded processing."""
        logs_with_ts = []
        item_index = {}
        eqp_set = set()
        skipped_count = 0

        sequences = {}
        active = {}
        b_intervals = {}
        w_timestamps = {}
        ack_events = {}
        buffer_sec = 1
        item_categories = {}

        with open(self.filepath, "r", encoding="utf-8-sig", errors="ignore") as f:
            for idx, raw in enumerate(f):
                raw = raw.rstrip()
                if not raw:
                    continue

                # Validation
                if len(raw) < 19:
                    skipped_count += 1
                    continue

                ts_str = raw[:19]
                if not (ts_str[4] == '-' and ts_str[7] == '-' and ts_str[10] == ' ' and ts_str[13] == ':' and ts_str[16] == ':'):
                    skipped_count += 1
                    continue

                if "[" not in raw or "]" not in raw:
                    skipped_count += 1
                    continue

                from model import LogLine
                log = LogLine(raw=raw)
                log.original_index = idx
                log.raw_lower = raw.casefold()

                # Parse timestamp
                try:
                    ts = datetime(
                        int(raw[0:4]), int(raw[5:7]), int(raw[8:10]),
                        int(raw[11:13]), int(raw[14:16]), int(raw[17:19])
                    )
                    ts_val = ts.timestamp()
                except Exception:
                    ts = None
                    ts_val = 0

                log.ts = ts

                # System
                log.system = None
                log.category = "EQP"  # default

                parts = raw.split("[")
                for p in parts:
                    if "." in p and "]" in p:
                        system_block = p.split("]")[0]
                        log.system = system_block.split(".")[-1]
        
                        # Infer category from system block
                        system_upper = system_block.upper()
                        if "RMS" in system_upper:
                            log.category = "RMS"
                        elif "ROLLMAP" in system_upper:
                            log.category = "ROLLMAP"
                        else:
                            log.category = "EQP"
                        break

                # Equipment
                eqp = _detect_equipment(raw)
                log.equipment = eqp
                if eqp:
                    eqp_set.add(eqp)

                # Item code
                item_code = self._extract_item_code(raw)
                log.item_code = item_code
                if item_code:
                    item_index.setdefault(item_code, []).append(log)
                    if item_code not in item_categories:
                        item_categories[item_code] = log.category

                logs_with_ts.append((ts_val, log))

                # =====================================================
                # SEQUENCE BUILDING (complete implementation)
                # =====================================================
                if not ts:
                    continue

                item, signal = self._parse_item_signal(raw)
                val = self._parse_value(raw)

                if not item or not signal:
                    continue

                if "W_TRIGGER_REPORT_ACK" in signal and val == "11":
                    ack_events.setdefault(item, []).append(ts.timestamp())

                # W_TRIGGER_REPORT
                if "W_TRIGGER" in signal:
                    ts_val_float = ts.timestamp()
                    lo = ts_val_float - buffer_sec
                    hi = ts_val_float + buffer_sec

                    intervals = b_intervals.get(item, [])
                    idx_bisect = bisect.bisect_left(intervals, (lo,))

                    inside_b = False
                    for iv_start, iv_end in intervals[max(0, idx_bisect - 1): idx_bisect + 2]:
                        if iv_start <= hi and iv_end >= lo:
                            inside_b = True
                            break

                    if inside_b:
                        continue

                    seen_w = w_timestamps.setdefault(item, set())
                    if ts in seen_w:
                        continue
                    seen_w.add(ts)

                    sequences.setdefault(item, []).append({
                        "start": ts,
                        "end": ts,
                        "type": "W"
                    })
                    continue

                # B_TRIGGER_REPORT - Step 1: B ON
                if ("B_TRIGGER_REPORT_CONF" not in signal
                        and "B_TRIGGER_REPORT" in signal
                        and val == "ON"):
                    active[item] = {
                        "start": ts,
                        "conf_on": False,
                        "b_off": False,
                        "logs": [log]
                    }
                    continue

                if item not in active:
                    continue

                seq = active[item]

                # Step 2: CONF ON
                if "B_TRIGGER_REPORT_CONF" in signal and val == "ON":
                    seq["conf_on"] = True
                    seq["logs"].append(log)
                    continue

                # Step 3: B OFF
                if ("B_TRIGGER_REPORT_CONF" not in signal
                        and "B_TRIGGER_REPORT" in signal
                        and val == "OFF"):
                    seq["b_off"] = True
                    seq["logs"].append(log)
                    continue

                # Step 4: CONF OFF → sequence complete
                if "B_TRIGGER_REPORT_CONF" in signal and val == "OFF":
                    if seq["conf_on"] and seq["b_off"]:
                        seq["logs"].append(log)
                        new_start = seq["start"] - timedelta(seconds=buffer_sec)
                        new_end = ts + timedelta(seconds=buffer_sec)

                        existing = sequences.setdefault(item, [])

                        # Evict W events inside this B window. Only the tail can qualify:
                        # entries are appended in log order, and anything older than
                        # new_start was already handled by the previous B. Scanning just the
                        # tail keeps this O(1) per sequence instead of O(len(existing)).
                        k = len(existing)
                        while k > 0 and existing[k - 1]["start"] >= new_start:
                            k -= 1
                        if k < len(existing):
                            existing[k:] = [
                                s for s in existing[k:]
                                if not (
                                    s["type"] == "W"
                                    and new_start <= s["start"] <= new_end
                                )
                            ]

                        win_lo = seq["start"].timestamp()
                        win_hi = ts.timestamp()
                        acks = ack_events.get(item, [])
                        lo_i = bisect.bisect_left(acks, win_lo)
                        hi_i = bisect.bisect_right(acks, win_hi)
                        has_ack_error = hi_i > lo_i

                        existing.append({
                            "start": seq["start"],
                            "end": ts,
                            "type": "B",
                            "core_indices": [l.original_index for l in seq["logs"]],
                            "error": has_ack_error
                        })

                        # Register interval for future W overlap checks
                        interval = (seq["start"].timestamp(), ts.timestamp())
                        item_intervals = b_intervals.setdefault(item, [])
                        bisect.insort(item_intervals, interval)

                    active.pop(item, None)

        # Sort logs by timestamp
        logs_with_ts.sort(key=lambda x: x[0])
        sorted_timestamps = [ts for ts, _ in logs_with_ts]
        sorted_logs = [log for _, log in logs_with_ts]
        current_equipment = next(iter(eqp_set), None)

        if skipped_count > 0:
            print(f"⚠ Skipped {skipped_count:,} invalid lines during variable log load")

        # 🔥 Emit with the categories we built during parsing
        self._emit(
            sorted_logs, sorted_timestamps, item_index, current_equipment, 
            skipped_count, sequences, item_categories
        )
    def _extract_item_code(self, raw):
        try:
            parts = raw.split("[")
            for part in parts:
                if ":" in part and "]" in part:
                    block = part.split("]")[0]
                    return block.split(":")[0]
        except Exception:
            pass
        return None
    def _parse_item_signal(self, raw):
        try:
            block = raw.split("[")[-1].split("]")[0]
            item, signal = block.split(":")
            return item, signal
        except:
            return None, None
    def _parse_value(self, raw):
        try:
            if " : " in raw:
                return raw.rsplit(" : ", 1)[1].strip()
        except:
            pass
        return None


# ============================================================
# BR Log Worker
# ============================================================
"""
class BRLogWorker(QThread):
    finished = Signal(list, dict)

    def __init__(self, filepath):
        super().__init__()
        self.filepath = filepath

    def run(self):
        file_size = os.path.getsize(self.filepath)
        
        # Parallelize for files > 20MB
        if file_size > 20 * 1024 * 1024:
            self._run_parallel()
        else:
            self._run_single()

    def _run_parallel(self):
        ""Multi-core BR processing.""
        num_workers = multiprocessing.cpu_count()
        
        # STEP 1: Split file into chunks
        chunk_ranges = self._get_file_chunks(num_workers)
        
        # STEP 2: Process chunks in parallel
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = [
                executor.submit(_process_br_chunk, self.filepath, start, end)
                for start, end in chunk_ranges
            ]
            
            chunk_results = [f.result() for f in futures]
        
        # STEP 3: Merge results
        all_br_calls = []
        full_br_index = {}
        
        for br_calls, br_index in chunk_results:
            all_br_calls.extend(br_calls)
            
            # Merge index
            for name, entries in br_index.items():
                full_br_index.setdefault(name, []).extend(entries)
        
        self.finished.emit(all_br_calls, full_br_index)

    def _get_file_chunks(self, num_chunks):
        ""Split file into chunks.""
        with open(self.filepath, "r", encoding="utf-8-sig", errors="ignore") as f:
            total_lines = sum(1 for _ in f)
        
        chunk_size = total_lines // num_chunks
        ranges = []
        
        for i in range(num_chunks):
            start = i * chunk_size
            end = start + chunk_size if i < num_chunks - 1 else total_lines
            ranges.append((start, end))
        
        return ranges

    def _run_single(self):
        ""Single-threaded processing.""
        br_calls = []
        full_br_index = {}
        pending = {}
        
        uuid_re = re.compile(r"(?:ELTR\w*|ASSY\w*)\((.*?)\)")
        requestq_check = "(REQUESTQ)"
        replyq_check = "(RECEIVE_REPLYQ)"
        bizrule_check = "BIZRULE"
        
        json_buffer = []
        in_json_block = False
        brace_count = 0
        current_uuid = None
        current_ts = None

        with open(self.filepath, "r", encoding="utf-8-sig", errors="ignore") as f:
            for line in f:
                line = line.rstrip()
                if not line:
                    continue
                
                # Build index
                if bizrule_check in line:
                    space_idx = line.find(" ", 20)
                    if space_idx != -1:
                        ts_str = line[:space_idx]
                        try:
                            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")
                        except:
                            ts = datetime.min
                    else:
                        ts = datetime.min
                    
                    bizrule_idx = line.find("BIZRULE]")
                    if bizrule_idx != -1:
                        name = line[bizrule_idx+8:].strip()
                        full_br_index.setdefault(name, []).append((ts, line))
                
                # JSON block collection
                if in_json_block:
                    json_buffer.append(line.strip())
                    brace_count += line.count('{') - line.count('}')
                    
                    if brace_count == 0:
                        in_json_block = False
                        
                        try:
                            request_json = json.loads("".join(json_buffer))
                        except json.JSONDecodeError:
                            pending[current_uuid] = {
                                "timestamp": current_ts,
                                "ts_val": current_ts.timestamp(),
                                "br_name": "UNKNOWN",
                                "tables": {}
                            }
                            json_buffer = []
                            continue
                        
                        br_name = request_json.get("actID", "UNKNOWN")
                        tables = {}
                        ref_json = request_json.get("refDS")
                        
                        if ref_json:
                            try:
                                ref_data = json.loads(ref_json)
                                for table_name, rows in ref_data.items():
                                    tables[table_name] = [
                                        {k: "" if v is None else str(v) for k, v in row.items()}
                                        for row in rows
                                    ]
                            except json.JSONDecodeError:
                                pass
                        
                        pending[current_uuid] = {
                            "timestamp": current_ts,
                            "ts_val": current_ts.timestamp(),
                            "br_name": br_name,
                            "tables": tables
                        }
                        
                        json_buffer = []
                    continue
                
                # REQUESTQ check
                if requestq_check in line:
                    try:
                        ts_str = line[:23]
                        ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")
                    except:
                        ts = datetime.min
                    
                    match = uuid_re.search(line)
                    if match:
                        current_uuid = match.group(1)
                        current_ts = ts
                        in_json_block = True
                        brace_count = 1
                        json_buffer = ["{"]
                    continue
                
                # RECEIVE_REPLYQ check
                if replyq_check in line:
                    match = uuid_re.search(line)
                    if not match:
                        continue
                    
                    uuid = match.group(1)
                    execution = pending.get(uuid)
                    if not execution:
                        continue
                    
                    json_start = line.find("{")
                    if json_start == -1:
                        continue
                    
                    try:
                        reply_json = json.loads(line[json_start:])
                    except json.JSONDecodeError:
                        continue
                    
                    pending.pop(uuid, None)
                    
                    for key, value in reply_json.items():
                        if key.startswith("OUT_"):
                            execution["tables"][key] = [
                                {k: "" if v is None else str(v) for k, v in row.items()}
                                for row in value
                            ]
                    
                    execution["search_blob"] = (
                        execution["br_name"] + " " + json.dumps(execution["tables"])
                    ).casefold()
                    
                    br_calls.append(execution)
        
        self.finished.emit(br_calls, full_br_index)
"""