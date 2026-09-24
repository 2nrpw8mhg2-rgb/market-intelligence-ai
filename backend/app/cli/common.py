import json
from pathlib import Path
from typing import Any


def parse_tickers(value: str | None) -> list[str]:
    if not value:
        return []
    return sorted({ticker.strip().upper() for ticker in value.split(",") if ticker.strip()})


def emit_report(report: dict[str, Any], output: str | None = None) -> None:
    rendered = json.dumps(report, indent=2, sort_keys=True, default=str)
    print(rendered)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
