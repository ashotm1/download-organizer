"""Accuracy check: does the model's classification match the folder each PDF already lives in?

Read-only — extracts text and asks the model, never moves or writes files. Ground truth is
simply the folder each PDF is already correctly filed in, so this only tests course-material
recognition, not the personal/administrative-document NONE cases the original evaluation in
docs/ROADMAP.md covered. Re-run this after any change to the prompt, schema, or CLI flags in
organizer/claude_client.py to catch accuracy regressions before they ship.

Usage:
    .venv\\Scripts\\python.exe scripts\\eval_accuracy.py [--out PATH]

Output CSV defaults to state/eval_accuracy.csv (state/ is already gitignored) — never printed
or written anywhere that gets committed, since file names may reveal real course/personal data.
"""
import argparse
import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from organizer import config as cfgmod
from organizer import extract
from organizer import folders as fl
from organizer.classifier import Classifier, DocInfo, build_llm
from organizer.history import History


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=None, help="CSV output path (default: state/eval_accuracy.csv)")
    args = parser.parse_args()

    cfg = cfgmod.load()
    out_path = Path(args.out) if args.out else cfg.state_dir / "eval_accuracy.csv"

    folders = fl.discover(cfg, learned=[])
    llm = build_llm(cfg)
    ok, msg = llm.status()
    print("backend:", msg)
    if not ok:
        print("backend not available, aborting")
        sys.exit(1)
    history = History(cfg.state_dir)
    clf = Classifier(cfg, llm, history)

    rows = []
    for f in folders:
        pdfs = sorted(p for p in f.path.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
        for p in pdfs:
            ex = extract.extract(p, cfg.pages_to_read, cfg.max_chars)
            if ex.error or not ex.has_text(cfg.min_text_chars):
                print(f"SKIP {f.key}/{p.name}: {ex.error or 'too little text'}")
                continue
            doc = DocInfo(filename=p.name, text=ex.text, title=ex.title, source_key=None, source_url=None)
            t = time.perf_counter()
            result = clf.ask_llm(folders, doc)
            secs = time.perf_counter() - t
            correct = result is not None and result.folder == f.key
            print(f"{'OK  ' if correct else 'FAIL'} {f.key:10} {p.name:45} -> "
                  f"{result.folder if result else 'ERROR':10} ({result.confidence if result else '-'}, {secs:.1f}s)")
            rows.append({
                "expected_folder": f.key, "file": p.name,
                "model_folder": result.folder if result else "ERROR",
                "model_confidence": result.confidence if result else "",
                "correct": correct, "seconds": round(secs, 1),
                "reason": result.reason if result else "",
            })

    if not rows:
        print("\nno classifiable PDFs found")
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    n_correct = sum(r["correct"] for r in rows)
    print(f"\n{n_correct}/{len(rows)} correct  ->  {out_path}")


if __name__ == "__main__":
    main()
