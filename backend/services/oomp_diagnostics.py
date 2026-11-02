"""Local administration: diagnostics, bounded delivery, consented backfill, exclusion."""
from __future__ import annotations
import argparse
import json
import sys
import math
import time

from .oomp_config import get_configuration
from .oomp_client import OOMPClient, OOMPError


def diagnose(config):
    report = {"mode": config.mode, "retrieval_api": config.retrieval_api, "configuration_valid": True, "connected": False,
              "evidence_budget_bytes": config.evidence_budget, "max_results": config.max_results,
              "max_prompt_bytes": config.max_prompt_bytes, "timeout_seconds": config.timeout_seconds,
              "ingestion_ready": False}
    if config.mode == "off":
        return report
    client = OOMPClient(config)
    status = client.call("memory.status", {})
    report["connected"] = "read" in status.get("capabilities", [])
    report["protocol"] = client.last_protocol_version
    report["context_capability_available"] = "memory.context" in client.last_tool_names
    report["context_contract_expected"] = "oomp.context.v1" if config.retrieval_api == "context_v1" else None
    report["worker_started_by_server"] = status.get("mind_worker_started_by_server")
    if config.mode == "retrieve_and_ingest":
        states = [client.call("memory.status", {}, token=grant.credential()) for grant in config.writers.values()]
        report["ingestion_ready"] = all("ingest" in state.get("capabilities", []) for state in states)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", nargs="?", default="status",
                        choices=("status", "drain", "work", "reconcile", "backfill", "exclude"))
    parser.add_argument("--owner", help="explicit configured TRACE owner")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--after-id")
    parser.add_argument("--cycles", type=int, default=0, help="worker passes; 0 means until Ctrl+C")
    parser.add_argument("--poll-seconds", type=float, default=2)
    parser.add_argument("--interaction-id")
    parser.add_argument("--approve", action="store_true",
                        help="perform the scoped administrative operation; otherwise dry run")
    args = parser.parse_args(argv)
    database_client = None
    try:
        config = get_configuration()
        if args.operation == "status":
            print(json.dumps(diagnose(config)))
            return 0
        if config.mode != "retrieve_and_ingest" or args.owner != config.owner_id:
            raise OOMPError("owner_rejected")
        from pymongo import MongoClient
        from backend.database.database import MONGO_URI, MONGO_DB_NAME
        from .oomp_publisher import Publisher, backfill, exclude
        database_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
        database_client.admin.command("ping")
        database = database_client[MONGO_DB_NAME]
        publisher = Publisher(database, config)
        if args.operation == "backfill":
            report = backfill(database, config, owner_id=args.owner, limit=args.limit,
                              after_id=args.after_id, approve=args.approve)
        elif args.operation == "reconcile":
            report = publisher.reconcile(limit=args.limit, after_id=args.after_id, dry_run=not args.approve)
        elif args.operation == "work":
            if not args.approve:
                raise OOMPError("approval_required")
            for report in work(publisher, limit=args.limit, cycles=args.cycles, poll_seconds=args.poll_seconds):
                print(json.dumps(report), flush=True)
            return 0
        elif args.operation == "drain":
            if not args.approve:
                raise OOMPError("approval_required")
            report = publisher.drain(limit=args.limit)
        else:
            if not args.approve or not args.interaction_id:
                raise OOMPError("approval_required")
            report = exclude(database, config, args.interaction_id)
        print(json.dumps(report))
        return 0
    except KeyboardInterrupt:
        return 130
    except OOMPError as error:
        print(json.dumps({"ok": False, "code": error.code}), file=sys.stderr)
        return 1
    except Exception:
        print(json.dumps({"ok": False, "code": "configuration_or_storage_unavailable"}), file=sys.stderr)
        return 1
    finally:
        if database_client is not None:
            database_client.close()


def work(publisher, *, limit=20, cycles=0, poll_seconds=2):
    if (type(cycles) is not int or not 0 <= cycles <= 1000
            or type(limit) is not int or not 1 <= limit <= 100
            or not math.isfinite(poll_seconds) or not .1 <= poll_seconds <= 60):
        raise OOMPError("resource_limit")
    cursor = None
    completed = 0
    while cycles == 0 or completed < cycles:
        reconciled = publisher.reconcile(limit=limit, after_id=cursor, dry_run=False)
        cursor = reconciled["next_after_id"]
        delivered = publisher.drain(limit=limit)
        completed += 1
        yield {"cycle": completed, "reconciliation": reconciled, "delivery": delivered}
        if cycles == 0 or completed < cycles:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())