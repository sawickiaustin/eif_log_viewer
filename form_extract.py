"""
form_extract.py - build the FORM trigger block for item_data.json from EIF C# sources.

Usage (base file first, then the add-on files that override it):
    python form_extract.py --name DEGASUNLOADER --match DEGASUNLOADER \
        CGDegasUnLoader_Base.cs CGDegasUnLoader.cs  >  degasunloader.json

What it reads from the sources:
  - every  __CATEGORY__VARIABLE.OnBooleanChanged / OnShortChanged += Handler  registration
  - the handler body (the add-on's override wins over the base), plus the class's
    own helper methods it calls (e.g. ReportLoadedCarrier), for "BR_..." names
  - O_B_ bits the handler sets to true/value  -> "confirm"
  - ACK words it sets to eConfirm.ACK / ConfirmAck.OK -> "ack"
  - the variable's description text            -> "name"

What it cannot know (add these by hand, or check against a day of logs):
  - alarm triggers (ALM_INFO_xx on the ROS element) - handled outside these classes
  - timer BRs (e.g. the tact-time thread)
  - which bits the deployed build actually uses, if it differs from the source
Error-path BRs (BR_SYS_REG_BIZRULE_EXCEPTION, BR_COM_GET_ERRORMESSAGE) are left out.
"""
import argparse
import json
import re
import sys

ERROR_ONLY = {"BR_SYS_REG_BIZRULE_EXCEPTION", "BR_COM_GET_ERRORMESSAGE"}
SKIP_CONFIRM = ("HOST_ALARM", "REMOTE", "COMM_CHECK", "SYSTEM_TIME")


def strip_comments(src):
    """Remove // and /* */ comments, leaving string literals intact."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c == '"' or (c in "$@" and i + 1 < n and src[i + 1] == '"'):
            verbatim = c == "@"
            j = i + (2 if c in "$@" else 1)
            while j < n:
                if src[j] == "\\" and not verbatim:
                    j += 2
                    continue
                if src[j] == '"':
                    j += 1
                    break
                j += 1
            out.append(src[i:j])
            i = j
        elif src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


# Method declarations start a line; the access modifier is optional (C# default: private)
METHOD_RE = re.compile(
    r"(?m)^[ \t]*(?:(?:private|protected|public|internal|static|virtual|override|new|async|sealed)\s+)*"
    r"(?P<ret>[\w<>\[\],.]+)\s+(?P<name>\w+)\s*\(([^)]*)\)\s*\{")
NOT_METHOD = {"if", "for", "foreach", "while", "switch", "catch", "using", "lock", "return", "else", "new", "throw", "await"}


def methods(src):
    """{method name: body} by brace matching."""
    out = {}
    for m in METHOD_RE.finditer(src):
        if m["ret"] in NOT_METHOD or m["name"] in NOT_METHOD:
            continue
        depth, j = 1, m.end()
        while j < len(src) and depth:
            ch = src[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == '"':
                j += 1
                while j < len(src) and src[j] != '"':
                    j += 2 if src[j] == "\\" else 1
            j += 1
        out[m["name"]] = src[m.end():j - 1]
    return out


VAR = (r'(?:this\.)?(?:__(?P<a>[A-Z0-9_]+?)__(?P<b>[A-Z0-9_]+)'
       r'|(?:this\.)?Variables\["(?P<c>[A-Z0-9_]+):(?P<d>[A-Z0-9_]+)"\])')
REG_RE = re.compile(VAR + r"\.(?P<ev>OnBooleanChanged|OnShortChanged|OnVariableOn)\s*\+=\s*"
                          r"(?:new\s+[\w<>,\s]+?\()?(?P<h>\w+)")
BR_RE = re.compile(r'"((?:BR|DA)_[A-Za-z0-9_]+)"')
CALL_RE = re.compile(r"\b(\w+)\s*\(")
SET_RE = re.compile(r"(?:this\.)?([A-Z0-9_]+?)__(O_[BW]_[A-Z0-9_]+)\s*=\s*([^;]+);")
DEF_RE = re.compile(r'__INTERNAL_VARIABLE_\w+\(\s*"(\w+)"\s*,\s*"(\w+)"(.*?)\);', re.S)
STR_RE = re.compile(r'\$?"((?:[^"\\]|\\.)*)"')


def analyse(files):
    texts = [strip_comments(open(f, encoding="utf-8-sig", errors="replace").read()) for f in files]
    meths, descs = {}, {}
    for t in texts:                      # later files (add-ons) override the base
        meths.update(methods(t))
        for var, cat, rest in DEF_RE.findall(t):
            strs = STR_RE.findall(rest)
            if strs:
                descs[f"{cat}:{var}"] = strs[-1].replace("{EQPTYPE}", "").strip()

    def brs_of(name, seen):
        if name in seen or name not in meths:
            return []
        seen.add(name)
        body = meths[name]
        found = BR_RE.findall(body)
        for callee in CALL_RE.findall(body):
            found += brs_of(callee, seen)
        return found

    rows = {}
    for m in REG_RE.finditer("\n".join(texts)):
        cat, var = (m["a"], m["b"]) if m["a"] else (m["c"], m["d"])
        key = f"{cat}:{var}"
        body = meths.get(m["h"], "")
        brs = [b for b in dict.fromkeys(brs_of(m["h"], set())) if b not in ERROR_ONLY]
        if not brs:
            continue                     # handlers that only log are not triggers
        confirm, ack = [], []
        for c, v, val in SET_RE.findall(body):
            val = val.strip()
            if v.startswith("O_B_") and not v.endswith("_ACK") and val in ("true", "value") and not any(s in v for s in SKIP_CONFIRM):
                confirm.append(f"{c}:{v}")
            if (v.startswith("O_W_") or v.endswith("_ACK")) and ("eConfirm.ACK" in val or "ConfirmAck.OK" in val):
                ack.append(f"{c}:{v}")
        is_word = m["ev"] == "OnShortChanged"
        item = {"name": descs.get(key) or var}
        if is_word:
            item["type"] = "word"
        if confirm and not is_word:
            item["confirm"] = list(dict.fromkeys(confirm))[0]
        if ack and not is_word:
            item["ack"] = list(dict.fromkeys(ack))[0]
        if is_word and var.startswith("I_W_EQP_") and "STATUS" in var:
            item["group"] = "STATUS"
        item["brs"] = brs
        rows[key] = item
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="equipment key, e.g. DEGASUNLOADER")
    ap.add_argument("--match", action="append", help="text in the log element name (default: --name)")
    ap.add_argument("sources", nargs="+", help="base .cs first, then add-on .cs files")
    a = ap.parse_args()
    triggers = analyse(a.sources)
    block = {a.name: {"match": a.match or [a.name], "triggers": triggers}}
    J = lambda x: json.dumps(x, ensure_ascii=False)
    lines = [f'"{a.name}": {{', f'  "match": {J(block[a.name]["match"])},', '  "triggers": {']
    lines.append(",\n".join(f"    {J(k)}: {J(v)}" for k, v in triggers.items()))
    lines += ["  }", "}"]
    print("\n".join(lines))
    print(f"\n{len(triggers)} triggers. Add alarm (ALM_INFO_xx) and timer triggers by hand.", file=sys.stderr)


if __name__ == "__main__":
    main()