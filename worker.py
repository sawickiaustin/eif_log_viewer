# worker.py
import re
import json
from datetime import datetime, timedelta
from PySide6.QtCore import QThread, Signal
import bisect


# ============================================================
# Variable Log Worker (with integrated sequence building)
# ============================================================
class VariableLogWorker(QThread):
    finished = Signal(list, list, dict, object, int, dict)
    # emits: (sorted_logs, sorted_timestamps, item_index, current_equipment, skipped_count, sequences)

    KNOWN_EQUIPMENTS = ["MIX", "COT", "ROL", "RWD", "TRS"]

    def __init__(self, logs):
        super().__init__()
        self.logs = logs

    def run(self):
        logs_with_ts = []
        item_index = {}
        eqp_set = set()
        skipped_count = 0

        # Sequence building state (same as build_sequences)
        sequences = {}
        active = {}
        b_intervals = {}
        w_timestamps = {}
        buffer_sec = 1

        for idx, log in enumerate(self.logs):
            raw = log.raw

            # ============================================
            # VALIDATION - Skip invalid lines
            # ============================================
            if len(raw) < 19:
                skipped_count += 1
                continue

            try:
                datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                skipped_count += 1
                continue

            if "[" not in raw or "]" not in raw:
                skipped_count += 1
                continue

            # ============================================
            # Process valid line
            # ============================================
            log.original_index = idx
            log.raw_lower = raw.casefold()

            # Timestamp
            try:
                ts = datetime(
                    int(raw[0:4]), int(raw[5:7]), int(raw[8:10]),
                    int(raw[11:13]), int(raw[14:16]), int(raw[17:19])
                )
            except Exception:
                ts = None

            log.ts = ts
            ts_val = ts.timestamp() if ts else 0

            # System
            log.system = None
            parts = raw.split("[")
            for p in parts:
                if "." in p and "]" in p:
                    log.system = p.split("]")[0].split(".")[-1]
                    break

            # Equipment
            eqp = None
            for eq in self.KNOWN_EQUIPMENTS:
                if eq in raw:
                    eqp = eq
                    break
            log.equipment = eqp
            if eqp:
                eqp_set.add(eqp)

            # Item code
            item_code = self._extract_item_code(raw)
            log.item_code = item_code
            if item_code:
                item_index.setdefault(item_code, []).append(log)

            logs_with_ts.append((ts_val, log))

            # ============================================
            # BUILD SEQUENCES (inline during same pass)
            # ============================================
            if not ts:
                continue

            item, signal = self._parse_item_signal(raw)
            val = self._parse_value(raw)

            if not item or not signal:
                continue

            # W_TRIGGER_REPORT
            if "W_TRIGGER_REPORT" in signal:
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
                    "b_off": False
                }
                continue

            if item not in active:
                continue

            seq = active[item]

            # Step 2: CONF ON
            if "B_TRIGGER_REPORT_CONF" in signal and val == "ON":
                seq["conf_on"] = True
                continue

            # Step 3: B OFF
            if ("B_TRIGGER_REPORT_CONF" not in signal
                    and "B_TRIGGER_REPORT" in signal
                    and val == "OFF"):
                seq["b_off"] = True
                continue

            # Step 4: CONF OFF → sequence complete
            if "B_TRIGGER_REPORT_CONF" in signal and val == "OFF":
                if seq["conf_on"] and seq["b_off"]:
                    new_start = seq["start"] - timedelta(seconds=buffer_sec)
                    new_end = ts + timedelta(seconds=buffer_sec)

                    existing = sequences.setdefault(item, [])

                    # Evict W events inside this B window
                    existing[:] = [
                        s for s in existing
                        if not (
                            s["type"] == "W"
                            and new_start <= s["start"] <= new_end
                        )
                    ]

                    existing.append({
                        "start": seq["start"],
                        "end": ts,
                        "type": "B"
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

        self.finished.emit(sorted_logs, sorted_timestamps, item_index, current_equipment, skipped_count, sequences)

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
# BR Log Worker (unchanged)
# ============================================================
class BRLogWorker(QThread):
    finished = Signal(list)

    def __init__(self, logs):
        super().__init__()
        self.logs = logs

    def run(self):
        # Split logs into chunks (e.g., 4 chunks for 4 cores)
        import multiprocessing
        num_workers = max(1, multiprocessing.cpu_count() - 1)
        chunk_size = len(self.logs) // num_workers
        
        if chunk_size < 10000:  # Don't bother for small files
            br_calls = self._build_br_calls(self.logs)
        else:
            from concurrent.futures import ThreadPoolExecutor
            chunks = [
                self.logs[i:i + chunk_size]
                for i in range(0, len(self.logs), chunk_size)
            ]
            
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                results = list(executor.map(self._build_br_calls, chunks))
            
            # Merge results
            br_calls = []
            for chunk_result in results:
                br_calls.extend(chunk_result)
        
        self.finished.emit(br_calls)

    def _extract_timestamp(self, raw):
        try:
            ts_str = raw.split(" ")[0] + " " + raw.split(" ")[1]
            return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")
        except Exception:
            return datetime.min

    def _build_br_calls(self, logs):
        br_calls = []
        pending = {}
        uuid_re = re.compile(r"(?:ELTR\w*|ASSY\w*)\((.*?)\)")
    
        i = 0
        log_count = len(logs)
    
        # Pre-compile patterns for faster matching
        requestq_check = "(REQUESTQ)"
        replyq_check = "(RECEIVE_REPLYQ)"
    
        while i < log_count:
            raw = logs[i].raw
        
            # Fast prefix check before regex
            if requestq_check in raw:
                ts = self._extract_timestamp(raw)
                match = uuid_re.search(raw)
                if not match:
                    i += 1
                    continue

                uuid = match.group(1)
                i += 1
            
                # Collect JSON block with minimal allocations
                block_start = i
                brace_count = 1  # We know first line is "{"
            
                while i < log_count and brace_count > 0:
                    line = logs[i].raw
                    # Count braces without strip() allocation
                    brace_count += line.count('{') - line.count('}')
                    i += 1
            
                # Build JSON string once
                json_lines = ["{"]
                for j in range(block_start, i):
                    json_lines.append(logs[j].raw.strip())
            
                try:
                    request_json = json.loads("".join(json_lines))
                except json.JSONDecodeError as e:
                    pending[uuid] = {
                        "timestamp": ts,
                        "ts_val": ts.timestamp(),
                        "br_name": "UNKNOWN",
                        "tables": {}
                    }
                    continue

                br_name = request_json.get("actID", "UNKNOWN")
                tables = {}
                ref_json = request_json.get("refDS")

                if ref_json:
                    try:
                        ref_data = json.loads(ref_json)
                        # Process tables in one pass
                        for table_name, rows in ref_data.items():
                            tables[table_name] = [
                                {k: "" if v is None else str(v) for k, v in row.items()}
                                for row in rows
                            ]
                    except json.JSONDecodeError:
                        pass

                pending[uuid] = {
                    "timestamp": ts,
                    "ts_val": ts.timestamp(),
                    "br_name": br_name,
                    "tables": tables
                }

            elif replyq_check in raw:
                match = uuid_re.search(raw)
                if not match:
                    i += 1
                    continue

                uuid = match.group(1)
                execution = pending.get(uuid)
                if not execution:
                    i += 1
                    continue

                # Find JSON start without allocating substring
                json_start = raw.find("{")
                if json_start == -1:
                    i += 1
                    continue

                try:
                    reply_json = json.loads(raw[json_start:])
                except json.JSONDecodeError:
                    i += 1
                    continue

                pending.pop(uuid, None)

                # Process OUT_ tables
                for key, value in reply_json.items():
                    if key.startswith("OUT_"):
                        execution["tables"][key] = [
                            {k: "" if v is None else str(v) for k, v in row.items()}
                            for row in value
                        ]

                # Build search blob once
                execution["search_blob"] = (
                    execution["br_name"] + " " + json.dumps(execution["tables"])
                ).casefold()

                br_calls.append(execution)
                i += 1
            else:
                i += 1

        return br_calls