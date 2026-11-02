"""Frozen P4B synthetic adapter evaluation, never a ranking/model benchmark.

Only public MCP wire data and owner-scoped mongomock sources enter the actual
TRACE pre-generation orchestrator. No OOMP internals or service is imported.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import time
from unittest.mock import patch

from bson import ObjectId
from fastapi import HTTPException
import mongomock

from backend.routes.chat import ChatRequest, build_context_prompt, chat, format_context_prompt, load_recent_context
from backend.services.chat_orchestrator import prepare_prompt
from backend.services.oomp_client import OOMPClient
from p4b_support import activate_context, context_unit, prompt_data, synthetic_mcp
from stage8_support import http_request, route_database

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "p4b" / "v1"
WIRE_LIE = "UNTRUSTED_WIRE_SUMMARY_DO_NOT_RENDER_AS_AUTHORITY"


def fixtures():
    manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8-sig"))
    for entry in manifest["files"]:
        raw = (FIXTURE / entry["file"]).read_bytes()
        assert len(raw) == entry["bytes"]
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
    data = {name: json.loads((FIXTURE / (name + ".json")).read_text(encoding="utf-8-sig"))
            for name in ("sources", "scenarios", "gold", "workloads", "negative-controls")}
    amendment = json.loads((FIXTURE / "amendment-01-metric-arithmetic.json").read_text(encoding="utf-8-sig"))
    data["amendment"] = amendment
    return data


def stamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def source_row(source):
    row = {"_id": ObjectId(source["interaction_id"]), "user_id": source["owner_id"],
           "session_id": source["session_id"], "user_message": source["user_message"],
           "llama_response": source["assistant_message"],
           "timestamp": stamp(source["request_start_time"]),
           "request_start_time": stamp(source["request_start_time"]),
           "response_end_time": (stamp(source["response_end_time"]) if "response_end_time" in source
                                 else stamp(source["request_start_time"]) + timedelta(seconds=1)),
           "oomp_publication": deepcopy(source.get("publication", {})),
           "feedback": deepcopy(source["feedback"])}
    row["feedback"]["submitted_at"] = stamp(row["feedback"]["submitted_at"])
    return row


def source_database(data):
    db = mongomock.MongoClient(tz_aware=True)["p4b-frozen-fictional"]
    sources = data["sources"]
    for session in sources["sessions"]:
        db.sessions.insert_one({"session_id": session["session_id"], "user_id": session["owner_id"],
                                "status": session["status"]})
    by_id = {source["source_id"]: source_row(source)
             for source in [*sources["interactions"], sources["foreign_control"]]}
    db.chat_history.insert_many(deepcopy(list(by_id.values())))
    return db, by_id


def enable(monkeypatch, tmp_path, data):
    workload = data["workloads"]["long_eight"]
    return activate_context(monkeypatch, tmp_path, owner_id=data["sources"]["owner_id"],
                            max_prompt_bytes=workload["max_prompt_bytes"],
                            num_ctx=workload["model_context_allowance"],
                            evidence_budget=workload["evidence_budget"], max_results=20,
                            generation_reserve=workload["output_reserve"])


def make_units(rows):
    return [context_unit(row, unit_id="unit-" + str(row["_id"]),
                         memory_id="memory-" + str(row["_id"]), content=WIRE_LIE)
            for row in rows]


def orchestrate(db, config, message, *, session="p4b-session-2", units=(), mutate=None):
    request = SimpleNamespace(message=message, user_id=config.owner_id, session_id=session)
    started = time.perf_counter()
    with route_database(db), synthetic_mcp(units=units,
            status="found_relevant_evidence" if units else "no_relevant_evidence", mutate=mutate) as calls:
        prompt, diagnostics = prepare_prompt(request, http_request(owner=config.owner_id),
                                             build_context_prompt, load_recent_context, format_context_prompt)
    elapsed = (time.perf_counter() - started) * 1000
    assert WIRE_LIE not in prompt
    assert len(prompt.encode("utf-8")) == diagnostics["prompt_bytes"] <= config.max_prompt_bytes
    assert diagnostics["prompt_bytes"] + config.generation_reserve + 256 <= config.num_ctx
    assert len(calls) == 1 and calls[0][0] == "memory.context"
    assert "include_source_content" not in calls[0][1]
    assert not {"tenant_id", "principal_id", "namespace", "source_ids"} & calls[0][1].keys()
    return prompt, diagnostics, elapsed


def route_orchestrate(db, config, message, *, session="p4b-session-2", units=()):
    """Execute actual chat persistence with a deterministic JSON answer stub."""
    started = time.perf_counter()
    with route_database(db), synthetic_mcp(units=units,
            status="found_relevant_evidence" if units else "no_relevant_evidence") as calls, \
         patch("backend.routes.chat.generate_response", side_effect=lambda prompt: json.dumps(fake_answer(prompt))) as model:
        response = chat(ChatRequest(message=message, user_id=config.owner_id, session_id=session),
                        http_request(owner=config.owner_id))
    elapsed = (time.perf_counter() - started) * 1000
    model.assert_called_once()
    prompt = model.call_args.args[0]
    saved = db.chat_history.find_one({"_id": ObjectId(response["interaction_id"])})
    diagnostics = saved["oomp_diagnostics"]
    assert json.loads(response["llama_response"]) == fake_answer(prompt)
    assert saved["feedback"]["submitted"] is False
    assert "oomp_publication" not in saved  # read-only mode cannot stage ingest
    assert WIRE_LIE not in prompt
    assert len(prompt.encode("utf-8")) == diagnostics["prompt_bytes"] <= config.max_prompt_bytes
    assert diagnostics["prompt_bytes"] + config.generation_reserve + 256 <= config.num_ctx
    assert len(calls) == 1 and calls[0][0] == "memory.context"
    assert "include_source_content" not in calls[0][1]
    assert not {"tenant_id", "principal_id", "namespace", "source_ids"} & calls[0][1].keys()
    return prompt, diagnostics, elapsed

def rendered_sources(prompt):
    return [source for unit in prompt_data(prompt)["HISTORICAL_CONTEXT"]["authoritative_source_units"]
            for source in unit["authoritative_sources"]]


def fake_answer(prompt):
    """Conservative deterministic inspection stub, not a language model.

    It names the source IDs it received and declines to make any new personal
    assertion. Therefore abstention/false-assertion counts are stub-only checks.
    Continuity and correction are measured separately as prompt source retention.
    """
    return {"source_ids": sorted({source["source_interaction_id"] for source in rendered_sources(prompt)}),
            "personal_assertions": [], "abstains": True}


def evaluate_scenarios(monkeypatch, tmp_path):
    data = fixtures()
    config = enable(monkeypatch, tmp_path, data)
    mapping = {source["interaction_id"]: source["source_id"] for source in [
        *data["sources"]["interactions"], data["sources"]["foreign_control"]]}
    records = []
    matched = included = proof_count = valid_proofs = foreign_injected = foreign_rejected = 0
    macro = []
    continuity = temporal = abstention = false_assertions = unauthorized_included = 0
    claims = {claim["claim_id"]: claim for claim in data["gold"]["claims"]}
    for case in data["scenarios"]["scenarios"]:
        db, rows = source_database(data)
        before = list(db.chat_history.find({}).sort("_id", 1))
        selected = [rows[source_id] for source_id in case["supplied_mcp_sources"]]
        prompt, diagnostics, elapsed = route_orchestrate(db, config, case["query"], units=make_units(selected))
        sources = rendered_sources(prompt)
        actual = {mapping[source["source_interaction_id"]] for source in sources}
        gold = set(case["gold_source_ids"])
        hits = len(actual & gold)
        matched += hits
        included += len(actual)
        if gold:
            macro.append(hits / len(gold))
        for source in sources:
            proof_count += 1
            original = rows[mapping[source["source_interaction_id"]]]
            unauthorized_included += int(original["user_id"] != config.owner_id)
            assert original["user_id"] == config.owner_id
            assert source["role"] == "user"
            assert source["source_content"] == original["user_message"]
            assert source["validated_source_span"] == {"start": 0, "end": len(original["user_message"])}
            assert source["event_id"] == next(unit["source_proofs"][0]["event_id"]
                for unit in make_units([original]))
            valid_proofs += 1
        if "p4b-source-foreign-pet" in case["supplied_mcp_sources"]:
            foreign_injected += 1
            foreign_rejected += int("p4b-source-foreign-pet" not in actual)
        answer = fake_answer(prompt)
        if case.get("must_abstain_personal_claim"):
            abstention += int(answer["abstains"] and not answer["personal_assertions"])
        false_assertions += len(answer["personal_assertions"])
        if case["case_id"] == "continuity":
            continuity = sum(set(claims[claim]["required_sources"]) <= actual for claim in case["gold_claims"])
        if case["case_id"] == "relocation":
            temporal = int(gold <= actual and all(unit["uncertain"] for unit in
                prompt_data(prompt)["HISTORICAL_CONTEXT"]["authoritative_source_units"]))
        assert db.chat_history.count_documents({}) == len(before) + 1
        for original in before:
            assert db.chat_history.find_one({"_id": original["_id"]}) == original
        assert set(db.list_collection_names()) == {"sessions", "chat_history"}
        records.append({"case_id": case["case_id"], "gold_sources": sorted(gold),
                        "included_sources": sorted(actual), "matched": hits,
                        "prompt_bytes": diagnostics["prompt_bytes"],
                        "prompt_token_upper_bound": diagnostics["prompt_token_upper_bound"],
                        "retrieval_latency_ms": diagnostics["retrieval_latency_ms"],
                        "orchestration_latency_ms": diagnostics["orchestration_latency_ms"],
                        "full_fake_chat_route_wall_ms": elapsed, "status": diagnostics["context_status"],
                        "excluded_units": diagnostics["omitted_context_units"],
                        "stub_abstains": answer["abstains"]})
    return {"scope": "mocked supplied-evidence adapter retention; no OOMP ranking or real answer quality",
            "fixture_version": "p4b.synthetic.v1", "metric_amendment": "amendment-01-metric-arithmetic.json",
            "source_recall": {"matched": matched, "gold_pairs": 16, "macro_cases": 10,
                              "macro_recall": sum(macro) / len(macro)},
            "source_precision": {"relevant_included": matched, "included_pairs": included},
            "prompt_integrity": {"valid": valid_proofs, "included": proof_count},
            "continuity_prompt_claims": {"retained": continuity, "opportunities": 5},
            "temporal_correction_prompt": {"preserved": temporal, "cases": 1},
            "fake_stub_personal_abstention": {"successes": abstention, "cases": 4,
                                             "false_assertions": false_assertions},
            "cross_owner": {"included": unauthorized_included, "foreign_injected": foreign_injected,
                            "foreign_rejected": foreign_rejected},
            "configuration": {"max_prompt_bytes": config.max_prompt_bytes, "num_ctx": config.num_ctx,
                              "generation_reserve": config.generation_reserve, "safety_reserve": 256,
                              "evidence_budget": config.evidence_budget, "num_predict": 140},
            "cases": records}


def evaluate_long_eight(monkeypatch, tmp_path):
    data = fixtures()
    config = enable(monkeypatch, tmp_path, data)
    workload = data["workloads"]["long_eight"]
    db, rows = source_database(data)
    long_rows = [source_row(source) for source in workload["interactions"]]
    db.sessions.insert_one({"session_id": workload["session_id"], "user_id": config.owner_id, "status": "active"})
    db.chat_history.insert_many(deepcopy(long_rows))
    request = SimpleNamespace(message=workload["current_message"], user_id=config.owner_id,
                              session_id=workload["session_id"])
    legacy = config.model_copy(update={"retrieval_api": "retrieve"})
    with route_database(db), patch("backend.services.chat_orchestrator.get_configuration", return_value=legacy), \
         patch.object(OOMPClient, "retrieve") as forbidden:
        try:
            prepare_prompt(request, http_request(owner=config.owner_id),
                           build_context_prompt, load_recent_context, format_context_prompt)
        except HTTPException as error:
            old_status = error.status_code
        else:
            old_status = 200
    forbidden.assert_not_called()
    old_prompt_bytes = len(build_with_db(db, request).encode("utf-8"))
    prompt, diagnostics, elapsed = route_orchestrate(db, config, request.message, session=request.session_id,
        units=make_units([rows["p4b-source-project"], rows["p4b-source-relocation-proposal"],
                          rows["p4b-source-relocation-correction"]]))
    parsed = prompt_data(prompt)
    assert parsed["CURRENT_USER_MESSAGE"] == request.message
    recent = parsed["RECENT_SESSION_CONTEXT"]["complete_exchanges"]
    assert recent[-1]["source_interaction_id"] == workload["mandatory_recent_interaction"]
    assert recent[-1]["user_message"] == long_rows[-1]["user_message"]
    assert recent[-1]["assistant_message"] == long_rows[-1]["llama_response"]
    assert recent[-1]["submitted_feedback"]["submitted"] is True
    return {"legacy_http_status": old_status, "context_http_status": 200,
            "legacy_prompt_bytes": old_prompt_bytes,
            "context_prompt_bytes": diagnostics["prompt_bytes"],
            "selected_recent": diagnostics["selected_recent_interactions"],
            "omitted_recent": diagnostics["omitted_recent_interactions"],
            "selected_context_units": diagnostics["selected_context_units"],
            "full_fake_chat_route_wall_ms": elapsed, "retrieval_latency_ms": diagnostics["retrieval_latency_ms"],
            "generation_reserve": config.generation_reserve, "num_predict": workload["num_predict"]}


def build_with_db(db, request):
    with route_database(db):
        return build_context_prompt(request.session_id, request.user_id, request.message)


def run_negative_control(control_id, monkeypatch, tmp_path):
    data = fixtures()
    config = enable(monkeypatch, tmp_path, data)
    db, rows = source_database(data)
    semantic = {"project-as-alias": "project", "robot-as-pet": "robot",
                "hypothetical-as-personal": "quoted-hypothetical", "assistant-as-personal": "quoted-hypothetical",
                "tentative-as-completed": "relocation-proposal", "correction-omitted": "relocation-proposal",
                "political-affiliation": "political-topic"}
    source_id = "p4b-source-" + semantic.get(control_id, "project")
    if control_id in {"utf16-span", "byte-span", "wrong-quote"}:
        source_id = "p4b-source-unicode"
    if control_id == "foreign-owner":
        source_id = "p4b-source-foreign-pet"
    row = rows[source_id]
    unit = make_units([row])[0]
    if control_id == "assistant-as-personal":
        unit = context_unit(row, role="assistant", content=WIRE_LIE)
    proof = unit["source_proofs"][0]
    reference = proof["source_reference"]
    mutate = None
    if control_id == "foreign-session":
        db.sessions.update_one({"session_id": row["session_id"]}, {"$set": {"user_id": data["sources"]["foreign_owner_id"]}})
    elif control_id == "tenant-principal":
        mutate = lambda value: value.update(tenant_id="forged-owner", principal_id="forged-principal")
    elif control_id == "wrong-source-system": reference["source_system"] = "foreign-system"
    elif control_id == "wrong-event-id": proof["event_id"] = "wrong-event"
    elif control_id == "wrong-session-id": reference["session_id"] = "wrong-session"
    elif control_id == "wrong-turn-id": reference["turn_id"] = "trace-assistant-" + str(row["_id"])
    elif control_id == "wrong-timestamp": reference["timestamp"] = (row["request_start_time"] + timedelta(seconds=1)).isoformat()
    elif control_id == "unexpected-locator": reference["locator"] = "https://invalid.example/source"
    elif control_id == "missing-source": db.chat_history.delete_one({"_id": row["_id"]})
    elif control_id == "deleted-session": db.sessions.delete_one({"session_id": row["session_id"]})
    elif control_id == "excluded-source": db.chat_history.update_one({"_id": row["_id"]}, {"$set": {"oomp_publication.excluded": True}})
    elif control_id == "retracted-unit": unit["temporal_status"] = "retracted"
    elif control_id == "span-negative": proof["span_start"] = -1
    elif control_id == "span-reversed": proof.update(span_start=5, span_end=4)
    elif control_id == "span-overrun": proof["span_end"] = len(row["user_message"]) + 1
    elif control_id == "span-empty": proof.update(span_start=4, span_end=4)
    elif control_id == "utf16-span": proof["span_end"] = len(row["user_message"].encode("utf-16-le")) // 2
    elif control_id == "byte-span": proof["span_end"] = len(row["user_message"].encode("utf-8"))
    elif control_id == "wrong-quote": proof["quote"] = "x" * len(row["user_message"])
    elif control_id == "duplicate-proof": unit["source_proofs"].append(deepcopy(proof))
    elif control_id == "unknown-field": unit["claimed_authority"] = "owner"
    elif control_id == "packet-outer-mismatch":
        def mutate(value):
            packet = json.loads(value["context_packet"])
            packet["evidence_packets"][0]["content"] = "X" * len(WIRE_LIE)
            value["context_packet"] = json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
    elif control_id == "wrong-byte-count":
        mutate = lambda value: value.update(selected_context_bytes=value["selected_context_bytes"] + 1)
    elif control_id == "wrong-call-budget":
        # A valid empty wire with a different returned per-call budget must fail.
        unit = None
        mutate = lambda value: value.update(token_budget=value["token_budget"] + 1)
    elif control_id == "untrusted-flag": mutate = lambda value: value.update(source_data_untrusted=False)
    prompt, diagnostics, _ = orchestrate(db, config, "What does the fictional historical source support?",
                                        units=[unit] if unit is not None else [], mutate=mutate)
    sources = rendered_sources(prompt)
    if control_id in semantic:
        assert len(sources) == 1
        role = "assistant" if control_id == "assistant-as-personal" else "user"
        assert sources[0]["role"] == role
        assert sources[0]["source_content"] == (row["llama_response"] if role == "assistant" else row["user_message"])
        assert all(unit["uncertain"] for unit in prompt_data(prompt)["HISTORICAL_CONTEXT"]["authoritative_source_units"])
        assert "Assistant text is not a statement by the user" in prompt
        assert "never infer a completed move" in prompt.lower()
        assert fake_answer(prompt)["personal_assertions"] == []
        return {"control_id": control_id, "passed": True, "kind": "attribution/uncertainty+conservative_fake_stub"}
    assert sources == [], control_id
    assert diagnostics["context_status"] == "invalid_evidence", control_id
    return {"control_id": control_id, "passed": True, "kind": "strict_wire_or_authoritative_source_rejection"}