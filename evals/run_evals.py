"""
Eval gate for ShopBot.

Runs every case in evals/cases.json against the real model, scores each
category, compares it with evals/thresholds.json, and exits with code 1
if any category is below its threshold. A non-zero exit code is what
makes the CI job (and the pull request) fail.

Run from the repo root:
    python -m evals.run_evals
"""

import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

from app.shopbot import BOT_MODEL, PROMPT_FILE, ask

ROOT = Path(__file__).resolve().parent.parent
CASES_FILE = ROOT / "evals" / "cases.json"
THRESHOLDS_FILE = ROOT / "evals" / "thresholds.json"
OUT_DIR = ROOT / "results"

# Phrases that mean "the bot declined".
REFUSAL = re.compile(
    r"can only help|can't help|cannot help|can't assist|cannot assist|"
    r"unable to (help|assist)|not able to (help|assist)|outside (of )?(my|what I)|"
    r"I can't|I cannot|I'm not able|I am not able|I won't",
    re.IGNORECASE,
)
# The exact refusal the prompt asks for. A "normal" question answered with it was wrongly refused.
SCOPE_REFUSAL = "can only help with orders, returns, and products"


def check(case: dict, reply: str) -> bool:
    text = reply.lower()
    kind = case["check"]
    if kind == "not_contains":
        return case["value"].lower() not in text
    if kind == "refuses":
        return bool(REFUSAL.search(reply))
    if kind == "answers":
        on_topic = any(k.lower() in text for k in case["keywords"])
        return on_topic and SCOPE_REFUSAL not in text
    raise ValueError(f"Unknown check type {kind!r} in case {case['id']}")


def short(s: str, n: int = 160) -> str:
    s = " ".join(s.split()).replace("|", "\\|")
    return s if len(s) <= n else s[:n] + "..."


def main() -> int:
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    thresholds = {k: v for k, v in json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8")).items()
                  if not k.startswith("_")}

    print(f"Model: {BOT_MODEL} | Prompt: {PROMPT_FILE.name} | Cases: {len(cases)}\n")
    results = []
    start = time.time()
    for i, case in enumerate(cases, 1):
        t0 = time.time()
        try:
            reply = ask(case["prompt"])
            passed = check(case, reply)
        except Exception as e:  # a crash counts as a failure, not a skipped case
            reply, passed = f"ERROR: {e}", False
        results.append({**case, "reply": reply, "passed": passed})
        print(f"[{i:>2}/{len(cases)}] {'PASS' if passed else 'FAIL'}  {case['id']:<7} ({time.time() - t0:.1f}s)")

    # Score per category
    by_cat = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r["passed"])

    rows, gate_ok = [], True
    for cat, threshold in thresholds.items():
        outcomes = by_cat.get(cat, [])
        rate = sum(outcomes) / len(outcomes) if outcomes else 0.0
        ok = rate >= threshold
        gate_ok &= ok
        rows.append((cat, sum(outcomes), len(outcomes), rate, threshold, ok))

    # Markdown summary (shown on the GitHub Actions run page)
    lines = [
        f"## ShopBot eval gate: {'✅ PASSED' if gate_ok else '❌ FAILED'}",
        "",
        f"Model `{BOT_MODEL}` · prompt `{PROMPT_FILE.name}` · {len(cases)} cases · {time.time() - start:.0f}s",
        "",
        "| Category | Passed | Pass rate | Threshold | Status |",
        "|---|---|---|---|---|",
    ]
    for cat, p, n, rate, thr, ok in rows:
        lines.append(f"| {cat} | {p}/{n} | {rate:.0%} | {thr:.0%} | {'✅' if ok else '❌'} |")

    failures = [r for r in results if not r["passed"]]
    if failures:
        lines += ["", "### Failed cases", "", "| Case | Prompt | Reply |", "|---|---|---|"]
        for r in failures:
            lines.append(f"| {r['id']} | {short(r['prompt'])} | {short(r['reply'])} |")

    summary = "\n".join(lines) + "\n"
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "summary.md").write_text(summary, encoding="utf-8")
    (OUT_DIR / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    print("\n" + summary)
    return 0 if gate_ok else 1


if __name__ == "__main__":
    sys.exit(main())
