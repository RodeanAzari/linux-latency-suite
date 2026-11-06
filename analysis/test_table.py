"""Synthetic checks for analysis/table.py.

Run from the repo root: python3 analysis/test_table.py
"""
import os
import sys
import tempfile

sys.path.insert(0, "analysis")
import table  # noqa: E402

COLS = "config_id,config,run,load,test,p50,p99,p99.9\n"
tmp = tempfile.mkdtemp()
csv = os.path.join(tmp, "summary.csv")
rows = COLS
# baseline: three runs, one outlier, so median (2.0) != mean (4.0)
for r, v in ((1, 1.0), (2, 2.0), (3, 9.0)):
    rows += f"0,baseline,{r},idle,sched_latency,{v},{v * 2},{v * 3}\n"
    rows += f"0,baseline,{r},idle,syscall_getppid,0.1{r},0.2,0.3\n"   # us -> shown in ns
rows += "8,spot-nomitigations,1,idle,sched_latency,5,6,7\n"            # spot row, one run
open(csv, "w").write(rows)

t = table.tables(csv)
lines = t.split("\n")
base = next(l for l in lines if l.startswith("| `baseline` |"))
assert "| 3 | 2 / 4 / 6 |" in base, base                  # median, not mean (4 / 8 / 12)
assert "| 120 / 200 / 300 |" in base, base               # getppid us -> ns, median of .11 .12 .13
assert base.count("| – ") == 3, base                     # 3 classes with no data
assert "| *`spot-nomitigations`* | 1 | 5 / 6 / 7 |" in t   # spot italic
assert "| `rt` | 0 |" in t                                # config with no runs is shown, not dropped
assert t.count("| `baseline` |") == 2                     # idle and loaded tables (loaded: 0 runs)
assert "| `baseline` | 0 |" in t
assert table.fmt(123.4) == "123" and table.fmt(4.534) == "4.53" and table.fmt(float("nan")) == "–"

# splice: replaces exactly the block, twice in a row gives the same file
md = os.path.join(tmp, "README.md")
open(md, "w").write(f"# x\n\n{table.BEGIN}\nold\n{table.END}\n\ntail\n")
table.splice(md, "NEW")
once = open(md).read()
table.splice(md, "NEW")
assert once == open(md).read() == f"# x\n\n{table.BEGIN}\nNEW\n{table.END}\n\ntail\n", once
for bad in ("no markers\n", f"{table.BEGIN}\n{table.END}\n{table.BEGIN}\n{table.END}\n"):
    open(md, "w").write(bad)
    try:
        table.splice(md, "x")
        raise AssertionError("splice accepted " + repr(bad))
    except SystemExit:
        pass
print("all checks passed")
