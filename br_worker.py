# br_worker.py
"""
Fast BR log parser (v3).

Design:
  - Workers jump straight to each "(REQUESTQ)" / "(RECEIVE_REPLYQ)" marker using
    C-level find/regex (no per-line Python loop). A block ends at the next line
    that starts with a timestamp.
  - Workers return small dicts of (raw timestamp text, ts_val, br_name, byte
    offsets), already sorted. No JSON text or datetime objects cross process
    boundaries.
  - Search runs against ONE lowercased copy of the file via
    buf.find(term, start, end), so nothing is copied per execution. Each worker
    lowercases its own slice straight into a shared-memory block, so building
    it is parallel and nothing is copied back to the parent.
  - Tables are read from disk by offset when a row is expanded (ensure_tables).
  - "timestamp" (datetime) is created only when something reads it.
  - All indexes (br_name_index, sorted times) are built in the worker thread,
    so the GUI thread only stores references.
  - UTF-16 logs are converted once to a temporary UTF-8 copy, and everything
    (parsing, byte offsets, table reads) works on that copy.
  - Timestamps may be bare ("2026-10-22 00:00:00.531") or bracketed
    ("[2026-10-22 00:00:00.531]"), and the call ID may follow any queue name
    (ELTR(…), ASSY(…), FORM_A(…)).
"""
import atexit
import json
import os
import re
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import shared_memory
from datetime import datetime
from operator import itemgetter

_by_ts = itemgetter("ts_val")

from PySide6.QtCore import QThread, Signal

PARALLEL_THRESHOLD = 20 * 1024 * 1024
MAX_WORKERS = 8

_MARK_RE = re.compile(rb"\((REQUESTQ|RECEIVE_REPLYQ)\)")
# Call ID: the "(…)" right before " : {" on the marker line, whatever queue
# name precedes it (ELTR, ASSY, FORM_A, …). Searched from after the marker.
_ID_RE = re.compile(rb"\(([^()\n]*)\)\s*:\s*\{")
# Older layout: ID after ELTR/ASSY, brace somewhere later on the line
_UUID_RE = re.compile(rb"(?:ELTR\w*|ASSY\w*)\(([^)\n]*)\)")
_ACTID_RE = re.compile(rb'"actID"\s*:\s*"([^"]*)"')
_NEXT_REC_RE = re.compile(rb"\n\[?\d{4}-\d\d-\d\d \d\d:\d\d:\d\d")
_WS = b" \t\r\n"
_BOM = b"\xef\xbb\xbf"
_LOWER = bytes.maketrans(b"ABCDEFGHIJKLMNOPQRSTUVWXYZ", b"abcdefghijklmnopqrstuvwxyz")


# ============================================================
# Timestamps
# ============================================================
def _ts_text(data, ls):
    """Bytes of 'YYYY-MM-DD HH:MM:SS[.fff…]' at the start of a line (optionally
    inside '[…]'), or None."""
    if data[ls:ls + 3] == _BOM:
        ls += 3
    if data[ls:ls + 1] == b"[":
        ls += 1
    head = data[ls:ls + 26]
    if len(head) < 19 or head[4:5] != b"-" or head[13:14] != b":":
        return None
    end = 19
    if head[19:20] == b".":
        end = 20
        while end < len(head) and 48 <= head[end] <= 57:
            end += 1
    return head[:end]


def parse_ts(raw: bytes):
    """Timestamp bytes -> naive datetime, or None."""
    s = raw.decode("ascii", "ignore")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass
    try:                                    # older Pythons: odd fraction lengths
        base, _, frac = s.partition(".")
        dt = datetime.fromisoformat(base)
        return dt.replace(microsecond=int((frac + "000000")[:6])) if frac else dt
    except ValueError:
        return None


class Execution(dict):
    """A dict whose 'timestamp' (datetime) is built on first access."""
    __slots__ = ()

    def __missing__(self, key):
        if key == "timestamp":
            ts = parse_ts(self["ts_raw"]) or datetime(1970, 1, 1)
            self["timestamp"] = ts
            return ts
        raise KeyError(key)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default


# ============================================================
# Encoding (UTF-16 logs are converted to a temporary UTF-8 copy)
# ============================================================
_TEMP_FILES = set()


def sniff_encoding(path):
    """'utf-16' for UTF-16 files (with or without a BOM), else 'utf-8-sig'."""
    with open(path, "rb") as f:
        head = f.read(4096)
    if head[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16"
    if len(head) >= 64:
        # No BOM: mostly-ASCII UTF-16 has a zero byte in every other position
        if head[1::2].count(0) > len(head) // 4:
            return "utf-16-le"
        if head[0::2].count(0) > len(head) // 4:
            return "utf-16-be"
    return "utf-8-sig"


def looks_like_br_log(path, max_lines=100):
    """True if one of the first lines has a BR marker, in whatever encoding."""
    enc = sniff_encoding(path)
    with open(path, "r", encoding=enc, errors="ignore") as f:
        for i, line in enumerate(f):
            if i >= max_lines:
                break
            if "BIZRULE" in line or "(REQUESTQ)" in line:
                return True
    return False


def prepare_br_file(path):
    """
    Returns (path_to_parse, temp_path). UTF-8 files are parsed in place
    (temp_path is None); UTF-16 files are converted to a UTF-8 temp copy first.
    """
    enc = sniff_encoding(path)
    if enc == "utf-8-sig":
        return path, None

    fd, out = tempfile.mkstemp(prefix="eif_br_", suffix=".log")
    _TEMP_FILES.add(out)
    try:
        with open(path, "r", encoding=enc, errors="replace", newline="") as src, \
             os.fdopen(fd, "w", encoding="utf-8", newline="") as dst:
            while True:
                chunk = src.read(4 << 20)          # 4M characters at a time
                if not chunk:
                    break
                dst.write(chunk)
    except BaseException:
        discard_temp(out)
        raise
    return out, out


def discard_temp(path):
    """Delete a temp copy made by prepare_br_file (no-op for anything else)."""
    if path and path in _TEMP_FILES:
        try:
            os.remove(path)
        except OSError:
            return                                 # still in use; atexit retries
        _TEMP_FILES.discard(path)


@atexit.register
def _cleanup_temp_files():
    for p in list(_TEMP_FILES):
        try:
            os.remove(p)
        except OSError:
            pass
    _TEMP_FILES.clear()


# ============================================================
# Parsing (module level so it pickles for multiprocessing)
# ============================================================
def _is_record_start(line: bytes) -> bool:
    if line[:1] == b"[":
        line = line[1:]
    return (
        len(line) >= 19
        and line[4:5] == b"-" and line[7:8] == b"-" and line[10:11] == b" "
        and line[13:14] == b":" and line[16:17] == b":"
        and line[:4].isdigit()
    )


def _find_chunk_ranges(path, n):
    """Byte ranges whose starts fall on a timestamped line."""
    size = os.path.getsize(path)
    if n <= 1 or size == 0:
        return [(0, size)]
    bounds = [0]
    with open(path, "rb") as f:
        for i in range(1, n):
            pos = size * i // n
            if pos <= bounds[-1]:
                continue
            f.seek(pos)
            f.readline()
            while True:
                line_start = f.tell()
                line = f.readline()
                if not line:
                    line_start = size
                    break
                if _is_record_start(line):
                    break
            if line_start > bounds[-1]:
                bounds.append(line_start)
    if bounds[-1] != size:
        bounds.append(size)
    return [(a, b) for a, b in zip(bounds, bounds[1:]) if b > a]


def _attach_shm(name):
    """Attach to the parent's block without letting this worker's exit unlink it."""
    if sys.version_info >= (3, 13):
        return shared_memory.SharedMemory(name=name, track=False)
    shm = shared_memory.SharedMemory(name=name)
    if os.name == "posix":                 # pre-3.13 POSIX quirk (bpo-39959)
        try:
            from multiprocessing import resource_tracker
            resource_tracker.unregister(shm._name, "shared_memory")
        except Exception:
            pass
    return shm


def _process_br_chunk(path, start, end, shm_name=None):
    """
    Returns (completed, pending, orphans), all with ABSOLUTE file offsets:
      completed  [Execution] sorted by ts_val (built here so the parent doesn't have to)
      pending    {uuid: Execution with rep=None}   reply not in this chunk
      orphans    [(uuid, rep_a, rep_b)]            request in an earlier chunk
    If shm_name is given, the lowercased chunk is also written into that shared
    memory block at [start:end], so the search buffer is built in parallel.
    """
    with open(path, "rb") as f:
        f.seek(start)
        data = f.read(end - start)

    if shm_name is not None:
        shm = _attach_shm(shm_name)
        try:
            shm.buf[start:start + len(data)] = data.translate(_LOWER)
        finally:
            shm.close()

    n = len(data)
    completed, pending, orphans = [], {}, []
    skip_until = 0
    names = {}                                   # dedupe names -> smaller pickle
    find, rfind = data.find, data.rfind
    id_search = _ID_RE.search
    uuid_search = _UUID_RE.search
    next_search = _NEXT_REC_RE.search
    actid_search = _ACTID_RE.search
    fromiso = datetime.fromisoformat
    E = Execution

    for m in _MARK_RE.finditer(data):
        ms = m.start()
        if ms < skip_until:                      # marker text inside a JSON body
            continue

        ls = rfind(b"\n", 0, ms) + 1
        le = find(b"\n", ms)
        if le == -1:
            le = n

        um = id_search(data, m.end(), le)
        if um is not None:
            brace = um.end() - 1
        else:
            um = uuid_search(data, ms, le)
            if um is None:
                continue
            brace = find(b"{", um.end(), le)
            if brace == -1:
                continue

        nx = next_search(data, le)
        be = nx.start() if nx else n
        while be > brace and data[be - 1] in _WS:
            be -= 1
        skip_until = be

        a, b = start + brace, start + be

        if m.group(1) == b"REQUESTQ":
            raw = _ts_text(data, ls)
            if raw is None:
                continue
            try:
                ts_val = fromiso(raw.decode()).timestamp()
            except ValueError:
                dt = parse_ts(raw)
                if dt is None:
                    continue
                ts_val = dt.timestamp()
            am = actid_search(data, brace, be)
            nb = am.group(1) if am else b"UNKNOWN"
            name = names.get(nb)
            if name is None:
                name = names[nb] = nb.decode("utf-8", "ignore")
            pending[um.group(1)] = E(ts_raw=raw, ts_val=ts_val, br_name=name,
                                     req=(a, b), rep=None)
        else:
            ex = pending.pop(um.group(1), None)
            if ex is None:
                orphans.append((um.group(1), a, b))
            else:
                ex["rep"] = (a, b)
                completed.append(ex)

    completed.sort(key=_by_ts)       # sorted here, in parallel, not in the parent
    return completed, pending, orphans


def _merge_chunk_results(results):
    calls, open_requests = [], {}
    for completed, pending, orphans in results:       # file order
        calls.extend(completed)
        for uuid, a, b in orphans:
            ex = open_requests.pop(uuid, None)
            if ex is not None:
                ex["rep"] = (a, b)
                calls.append(ex)
        open_requests.update(pending)
    calls.sort(key=_by_ts)        # concatenated sorted runs: near-linear
    return calls


class SearchBuffer:
    """
    Lowercased copy of the whole file. Exposes .find(sub, start, end), which is
    all execution_matches() needs. Backed by the shared-memory block the
    workers filled, so the parent never copies or lowercases 1 GB+ itself.
    """
    __slots__ = ("find", "_owner", "__weakref__")

    def __init__(self, data=None, shm=None):
        self._owner = shm if shm is not None else data
        if shm is not None:
            mm = getattr(shm, "_mmap", None)      # mmap has .find(sub, start, end)
            if mm is None:                        # very unusual: fall back to a copy
                data = bytes(shm.buf)
                self._owner = data
                shm.close()
                self.find = data.find
            else:
                self.find = mm.find
        else:
            self.find = data.find


def build_search_buffer(path):
    """Single-process path for smaller files."""
    with open(path, "rb") as f:
        return SearchBuffer(data=f.read().translate(_LOWER))


def parse_br_file(path):
    """Returns (executions sorted by time, SearchBuffer)."""
    size = os.path.getsize(path)
    n = min(os.cpu_count() or 1, MAX_WORKERS) if size > PARALLEL_THRESHOLD else 1
    ranges = _find_chunk_ranges(path, n)

    if len(ranges) == 1:
        results = [_process_br_chunk(path, *ranges[0])]
        return _merge_chunk_results(results), build_search_buffer(path)

    shm = shared_memory.SharedMemory(create=True, size=max(size, 1))
    try:
        with ProcessPoolExecutor(max_workers=len(ranges)) as ex:
            futures = [ex.submit(_process_br_chunk, path, a, b, shm.name) for a, b in ranges]
            results = [f.result() for f in futures]
    except BaseException:
        shm.close()
        shm.unlink()
        raise

    # Workers are done with it. Removing the name now means the OS frees the
    # memory automatically once this process drops the mapping (POSIX); on
    # Windows it is freed when the last handle closes anyway.
    try:
        shm.unlink()
    except FileNotFoundError:
        pass
    return _merge_chunk_results(results), SearchBuffer(shm=shm)


def build_indexes(calls):
    """Everything BRTab used to build on the GUI thread."""
    name_index = {}
    for e in calls:
        lst = name_index.get(e["br_name"])
        if lst is None:
            name_index[e["br_name"]] = [e]
        else:
            lst.append(e)
    times = [e["ts_val"] for e in calls]
    return name_index, times


# ============================================================
# Used by BRTab
# ============================================================
def encode_terms(terms):
    """Search terms -> lowercase UTF-8 bytes (matches the search buffer)."""
    return [t.casefold().encode("utf-8") for t in terms if t]


def execution_matches(buf, execution, and_terms, or_terms):
    """and_terms / or_terms must already be encoded with encode_terms()."""
    ra, rb = execution["req"]
    pa, pb = execution["rep"]
    find = buf.find
    for t in and_terms:
        if find(t, ra, rb) == -1 and find(t, pa, pb) == -1:
            return False
    if or_terms:
        for t in or_terms:
            if find(t, ra, rb) != -1 or find(t, pa, pb) != -1:
                return True
        return False
    return True


def _read_span(f, span):
    a, b = span
    f.seek(a)
    text = f.read(b - a).decode("utf-8", "ignore")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text)   # ignores trailing junk
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}


def ensure_tables(execution, path):
    """Parse a call's tables from disk the first time its row is expanded."""
    tables = execution.get("tables")
    if tables is not None:
        return tables

    tables = {}

    def norm(rows):
        return [
            {k: "" if v is None else str(v) for k, v in row.items()}
            for row in rows if isinstance(row, dict)
        ]

    try:
        with open(path, "rb") as f:
            req = _read_span(f, execution["req"])
            rep = _read_span(f, execution["rep"])
    except OSError:
        req, rep = {}, {}

    ref = req.get("refDS")
    if ref:
        try:
            ref_data = json.loads(ref) if isinstance(ref, str) else ref
            for name, rows in ref_data.items():
                if isinstance(rows, list):
                    tables[name] = norm(rows)
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass

    # Output tables: OUT_* (ELTR style), OUTDATA (FORM_A style), plus any name
    # the request listed in outDTName
    out_names = {n.strip() for n in str(req.get("outDTName") or "").split(",") if n.strip()}
    for key, value in rep.items():
        if (key.startswith("OUT") or key in out_names) and isinstance(value, list):
            tables[key] = norm(value)

    execution["tables"] = tables
    return tables


# ============================================================
# Qt worker
# ============================================================
class BRLogWorker(QThread):
    # (executions, {"path", "temp_path", "source_path", "search_buf", "name_index", "times"})
    #   path        file the byte offsets refer to (a UTF-8 temp copy for UTF-16 logs)
    #   temp_path   that temp copy, or None; delete it with discard_temp() when done
    finished = Signal(list, object)

    def __init__(self, filepath):
        super().__init__()
        self.filepath = filepath

    def run(self):
        parse_path, temp_path = prepare_br_file(self.filepath)
        calls, buf = parse_br_file(parse_path)
        name_index, times = build_indexes(calls)
        self.finished.emit(calls, {
            "path": parse_path,
            "temp_path": temp_path,
            "source_path": self.filepath,
            "search_buf": buf,
            "name_index": name_index,
            "times": times,
        })