# parser.py
from model import LogLine


def load_log_file(path: str) -> list[LogLine]:
    lines = []

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.rstrip()
            if not line:
                continue
            lines.append(LogLine(raw=line))

    return lines
