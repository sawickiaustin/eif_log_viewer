# parser.py
from model import LogLine


def load_log_file(path: str) -> list[LogLine]:
    lines = []

    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        # Note: utf-8-sig automatically removes BOM if present
        for i, line in enumerate(f):
            line = line.rstrip()
            if not line:
                continue

            log = LogLine(raw=line)
            log.idx = i  # ⭐ 원래 위치 저장
            lines.append(log)

    return lines
