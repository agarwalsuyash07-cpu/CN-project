#!/usr/bin/env bash
# Evidence 5: full unittest run saved to evidence/e5_tests.txt; the screen shows a
# per-module count and the final verdict.
source "$(dirname "$0")/_common.sh"

main() {
    title "EVIDENCE 5 — unittest suite (python3 -m unittest discover -v)"
    clean_state   # tests use temp dirs and free ports; this just keeps runs comparable
    local status=0
    "$PY" -m unittest discover -v >"$EVID/e5_tests.txt" 2>&1 || status=$?
    "$PY" - "$EVID/e5_tests.txt" <<'EOF'
import re, sys
from collections import Counter

text = open(sys.argv[1], encoding="utf-8").read()
results = re.findall(r"^\w+ \(tests\.(test_\w+)\.[\w.]+\) \.\.\. (\w+)", text, re.M)
total, passed = Counter(), Counter()
for module, verdict in results:
    total[module] += 1
    passed[module] += verdict == "ok"
print("%-28s %6s %6s" % ("MODULE", "TESTS", "OK"))
print("-" * 42)
for module in sorted(total):
    print("%-28s %6d %6d" % (module, total[module], passed[module]))
print("-" * 42)
print("%-28s %6d %6d" % ("total", sum(total.values()), sum(passed.values())))
print()
tail = re.search(r"^(Ran \d+ tests? in [\d.]+s)\s*\n\s*\n(.+)$", text, re.M)
print(tail.group(1) if tail else "(no 'Ran N tests' line - see evidence/e5_tests.txt)")
print(tail.group(2) if tail else "")
EOF
    echo "full output: evidence/e5_tests.txt"
    return "$status"
}

main 2>&1 | tee "$EVID/e5_summary.txt"
