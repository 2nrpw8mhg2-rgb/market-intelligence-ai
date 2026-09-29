import argparse
import asyncio
import csv
import json
from datetime import date
from pathlib import Path

from app.database.repositories import MarketBarRepository, UniverseRepository
from app.database.session import SessionFactory
from app.market_data.calendar import NYSETradingCalendar
from app.pit.readiness import assess_alias_readiness, merge_provider_bars, readiness_summary


START = date(2021, 9, 27)
END = date(2026, 9, 22)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Security-id-native PIT execution readiness check")
    command.add_argument("--output", default="data/pit_materialization/readiness.json")
    command.add_argument("--identity-evidence", default="docs/PIT_ALIAS_CHAIN_EVIDENCE.json")
    command.add_argument("--audit", default="data/eodhd_poc3/audit.json")
    return command


async def run(args: argparse.Namespace) -> None:
    calendar = NYSETradingCalendar()
    sessions = calendar.trading_days_between(START, END)
    warmup = calendar.session_offset(START, -260)
    horizon_end = calendar.session_offset(END, 60)
    results = []
    evidence = json.loads(Path(args.identity_evidence).read_text())
    audit = json.loads(Path(args.audit).read_text())
    terminal_ids = {
        str(item["security_id"])
        for item in audit["security_master"]
        if any(
            item.get("prices", {}).get("missing_by_reason", {}).get(reason, 0)
            for reason in ("TERMINAL_EVENT", "SYMBOL_CHANGE_BOUNDARY")
        )
    }
    providers: dict[str, int] = {}
    async with SessionFactory() as session:
        memberships = await UniverseRepository(session).list_period_memberships("SP500", START, END)
        bars_repository = MarketBarRepository(session)
        for membership in memberships:
            policy = evidence.get(str(membership.security_id), {})
            natural = {date.fromisoformat(value) for value in policy.get("natural_unavailable_sessions", [])}
            preferred = policy.get("preferred_price_provider")
            supplemental = policy.get("supplemental_price_provider")
            if supplemental:
                _, primary_bars = await bars_repository.list_security_daily_bars(
                    membership.security_id, membership.ticker, warmup, horizon_end,
                    providers=(preferred,),
                )
                _, supplemental_bars = await bars_repository.list_security_daily_bars(
                    membership.security_id, membership.ticker, warmup, horizon_end,
                    providers=(supplemental,),
                )
                bars = merge_provider_bars(primary_bars, supplemental_bars)
                assessment = assess_alias_readiness(
                    membership, bars, sessions, natural_unavailable_sessions=natural
                )
                provider = f"{preferred}+{supplemental}"
                assessment.update({
                    "supplemental_sessions": len({bar.timestamp.date() for bar in supplemental_bars}
                                                 - {bar.timestamp.date() for bar in primary_bars})
                })
                candidates = []
            else:
                candidates = []
            provider_order = tuple(filter(None, (preferred, "massive", "eodhd_adjusted_derived")))
            provider_order = tuple(dict.fromkeys(provider_order))
            for candidate_provider in (() if supplemental else provider_order):
                provider, bars = await bars_repository.list_security_daily_bars(
                    membership.security_id, membership.ticker, warmup, horizon_end,
                    providers=(candidate_provider,),
                )
                if provider:
                    item = assess_alias_readiness(
                        membership, bars, sessions,
                        natural_unavailable_sessions=natural,
                    )
                    candidates.append((item.get("missing_membership_sessions", 0),
                                       -item.get("evaluable_sessions", 0),
                                       provider != preferred if preferred else False,
                                       provider, item, bars))
            if candidates:
                _, _, _, provider, assessment, bars = min(candidates)
            elif not supplemental:
                provider, assessment = None, assess_alias_readiness(
                    membership, [], sessions, natural_unavailable_sessions=natural
                )
            if str(membership.security_id) in terminal_ids and assessment.get("last_price"):
                last_price = date.fromisoformat(assessment["last_price"])
                terminal_natural = {
                    value for value in sessions
                    if value > last_price and membership.valid_from <= value
                    and (membership.valid_to is None or value < membership.valid_to)
                }
                if terminal_natural - natural:
                    natural |= terminal_natural
                    assessment = assess_alias_readiness(
                        membership, bars, sessions, natural_unavailable_sessions=natural
                    )
            assessment.update({
                "ticker": membership.ticker, "security_id": str(membership.security_id),
                "provider": provider,
            })
            results.append(assessment)
            providers[provider or "missing"] = providers.get(provider or "missing", 0) + 1
    payload = {
        "research_window": [START.isoformat(), END.isoformat()],
        "sessions": len(sessions), "memberships": len(memberships),
        "provider_breakdown": providers, "status_breakdown": readiness_summary(results),
        "missing_price_series": sum(item["provider"] is None for item in results),
        "total_evaluable_security_sessions": sum(item.get("evaluable_sessions", 0) for item in results),
        "total_missing_membership_sessions": sum(item.get("missing_membership_sessions", 0) for item in results),
        "total_natural_lifecycle_sessions": sum(item.get("natural_lifecycle_sessions", 0) for item in results),
        "total_feature_warmup_sessions": sum(item.get("feature_warmup_sessions", 0) for item in results),
        "blocked": [item for item in results if item["status"] == "BLOCKED"],
        "limitations": [item for item in results if item["status"] == "READY_WITH_DOCUMENTED_LIMITATION"],
        "dry_run": "FEATURES_ONLY_NO_RETURNS",
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2))
    print(json.dumps({key: value for key, value in payload.items()
                      if key not in {"blocked", "limitations"}}, indent=2))


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
