# parser.py
from model import LogLine


def load_log_file(path: str) -> list[LogLine]:
    lines = []

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for i, line in enumerate(f):
            line = line.rstrip()
            if not line:
                continue

            log = LogLine(raw=line)
            log.idx = i  # ⭐ 원래 위치 저장
            lines.append(log)

    return lines
