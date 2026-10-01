import argparse
import csv
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from app.pit.alias_chain import build_linear_alias_chain


START = date(2021, 9, 27)
END = date(2026, 9, 22)


def parser():
    command = argparse.ArgumentParser(description="Build proven temporal alias chains")
    command.add_argument("--audit", default="data/eodhd_poc3/audit.json")
    command.add_argument("--evidence", default="docs/PIT_ALIAS_CHAIN_EVIDENCE.json")
    command.add_argument("--exceptions", default="docs/PIT_MEMBERSHIP_EXCEPTIONS.json")
    command.add_argument("--output", default="docs/PIT_TEMPORAL_ALIAS_CHAINS.csv")
    return command


def run(args):
    master = json.loads(Path(args.audit).read_text())["security_master"]
    evidence = json.loads(Path(args.evidence).read_text())
    exceptions = json.loads(Path(args.exceptions).read_text())
    output = []
    blocked = []
    security_count = multi_count = 0
    for row in master:
        membership = row["membership"]
        start = date.fromisoformat(str(membership.get("start") or membership["first_assertable_membership"]))
        end = date.fromisoformat(str(membership["end"])) if membership.get("end") else None
        if start > END or (end is not None and end <= START):
            continue
        if str(row["security_id"]) in exceptions:
            continue
        security_count += 1
        item_evidence = evidence.get(str(row["security_id"]), {})
        if item_evidence.get("classification") == "IDENTITY_BLOCKED":
            blocked.append(str(row["security_id"]))
            continue
        chain = build_linear_alias_chain(
            row, predecessor_override=item_evidence.get("predecessor_override"),
            replacement_identity=item_evidence.get("replacement_identity"),
            symbol_changes_override=item_evidence.get("symbol_changes_override"),
        )
        if len(chain) > 1:
            multi_count += 1
        for item in chain:
            value = asdict(item)
            value["valid_from"] = item.valid_from.isoformat()
            value["valid_to"] = item.valid_to.isoformat() if item.valid_to else ""
            value["identifiers"] = json.dumps(dict(item.identifiers), sort_keys=True)
            output.append(value)
    path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(output)
    print(json.dumps({"eligible_security_records": security_count,
                      "chains_written": security_count-len(blocked),
                      "multi_alias_securities": multi_count,
                      "alias_intervals": len(output), "identity_blocked": blocked}, indent=2))


if __name__ == "__main__":
    run(parser().parse_args())
