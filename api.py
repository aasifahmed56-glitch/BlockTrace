"""
BlockTrace API — FastAPI backend.

Replaces the Streamlit UI entirely. All business logic (detection heuristics, risk
scoring, narrative generation, sanctions screening, certificates) is unchanged and
still lives in logic.py — this file only handles HTTP request/response wiring and
the Neo4j/Etherscan I/O that used to live inline in app.py.

Run with:
    uvicorn api:app --reload --port 8000

Interactive API docs (auto-generated) are then available at:
    http://localhost:8000/docs
"""

import os
import time
import hashlib
import json as jsonlib
from typing import Optional, List

import requests
from dotenv import load_dotenv
from neo4j import GraphDatabase
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from logic import (
    short, risk_tier, compute_wallet_risk, build_narrative,
    check_sanctions, get_entity_label, compute_certificate_hash, verify_certificate
)
import case_manager
from report_generator import generate_report

load_dotenv()

ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE")
ETHERSCAN_URL = "https://api.etherscan.io/v2/api"

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

CHAIN_OPTIONS = {
    "Ethereum": 1,
    "BNB Smart Chain": 56,
    "Polygon": 137,
}

CURATED_CASES = {
    "Ronin Bridge Hack ($600M, 2022)": {
        "address": "0x098B716B8Aaf21512996dC57EB0615e2383E2f96",
        "chainid": 1,
        "description": "Wallet linked to the Axie Infinity / Ronin Bridge exploit. "
                        "Sanctioned by the U.S. Treasury (OFAC) and attributed to the Lazarus Group."
    },
    "Poly Network Hack ($611M, 2021)": {
        "address": "0xC8a65Fadf0e0dDAf421F28FEAb69Bf6E2E589963",
        "chainid": 1,
        "description": "Largest DeFi exploit at the time, draining assets across Ethereum, BSC, "
                        "and Polygon. Most funds were later voluntarily returned by the attacker, "
                        "but the full on-chain trail remains public."
    },
    "Wormhole Bridge Hack ($321M, 2022)": {
        "address": "0x629e7Da20197a5429d30da36E77D06CdF796b71a",
        "chainid": 1,
        "description": "Exploit of the Ethereum-Solana Wormhole token bridge. This address is "
                        "directly labeled 'Wormhole Network Exploiter' on Etherscan."
    }
}

app = FastAPI(
    title="BlockTrace API",
    description="Explainable blockchain crime investigation — REST backend.",
    version="1.0.0",
)

# Dev-friendly CORS: allows any frontend (React dev server, etc.) to call this API.
# Tighten allow_origins to your actual frontend URL before deploying publicly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== Request/response models ====================

class ExpandRequest(BaseModel):
    wallet: str
    hops: int = Field(2, ge=1, le=3)
    tx_per_wallet: int = Field(15, ge=5, le=30)
    chain: str = "Ethereum"


class PathRequest(BaseModel):
    source: str
    destination: str
    max_hops: int = Field(4, ge=1, le=6)
    tx_per_wallet: int = Field(15, ge=5, le=30)
    chain: str = "Ethereum"


class SaveCaseRequest(BaseModel):
    name: str
    start_wallet: Optional[str] = None


class CertificateRequest(BaseModel):
    start_wallet: Optional[str] = None


class CertificateVerifyRequest(BaseModel):
    certificate_hash: str
    previous_hash: str
    payload: dict


# ==================== Etherscan + Neo4j data layer ====================
# (Same logic as the old app.py — just with no Streamlit calls mixed in.)

def fetch_transactions(wallet_address, limit=15, chainid=1):
    params = {
        "chainid": chainid, "module": "account", "action": "txlist",
        "address": wallet_address, "startblock": 0, "endblock": 99999999,
        "sort": "desc", "apikey": ETHERSCAN_API_KEY
    }
    response = requests.get(ETHERSCAN_URL, params=params)
    data = response.json()
    if data["status"] != "1":
        return []
    return data["result"][:limit]


def load_transactions(session, transactions):
    new_wallets = set()
    for tx in transactions:
        from_addr, to_addr = tx["from"], tx["to"]
        if not to_addr:
            continue
        try:
            value_eth = int(tx["value"]) / 1e18
        except (ValueError, TypeError):
            continue

        # Sanity cap — see MASTER_ARCHITECTURE.md section 3.13 for why this exists.
        if value_eth < 0 or value_eth > 1_000_000:
            continue

        session.run(
            """
            MERGE (a:Wallet {address: $from_addr})
            MERGE (b:Wallet {address: $to_addr})
            MERGE (a)-[t:SENT {hash: $tx_hash}]->(b)
            SET t.value = $value_eth, t.timestamp = $timestamp
            """,
            from_addr=from_addr, to_addr=to_addr, tx_hash=tx["hash"],
            value_eth=value_eth, timestamp=tx["timeStamp"]
        )
        new_wallets.add(from_addr)
        new_wallets.add(to_addr)
    return new_wallets


def expand_from_wallet(start_wallet, hops=2, tx_per_wallet=15, chainid=1):
    visited = set()
    current_layer = {start_wallet}
    with driver.session(database=NEO4J_DATABASE) as session:
        for hop in range(hops):
            next_layer = set()
            for wallet in current_layer:
                if wallet in visited:
                    continue
                visited.add(wallet)
                txs = fetch_transactions(wallet, limit=tx_per_wallet, chainid=chainid)
                new_wallets = load_transactions(session, txs)
                next_layer.update(new_wallets)
                time.sleep(0.25)
            current_layer = next_layer - visited
    return len(visited)


def expand_until_found(source, destination, max_hops=6, tx_per_wallet=15, chainid=1):
    destination_lower = destination.lower()
    existing = {a.lower() for a in get_all_wallet_addresses()}
    if destination_lower in existing:
        return 0, True

    visited = set()
    current_layer = {source}
    found = False
    with driver.session(database=NEO4J_DATABASE) as session:
        for hop in range(max_hops):
            next_layer = set()
            for wallet in current_layer:
                if wallet in visited:
                    continue
                visited.add(wallet)
                txs = fetch_transactions(wallet, limit=tx_per_wallet, chainid=chainid)
                new_wallets = load_transactions(session, txs)
                next_layer.update(new_wallets)
                if destination_lower in {w.lower() for w in new_wallets}:
                    found = True
                time.sleep(0.25)
            current_layer = next_layer - visited
            if found:
                break
    return len(visited), found


def get_graph_data(limit=300):
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run(
            "MATCH (a:Wallet)-[r:SENT]->(b:Wallet) RETURN a.address AS from_addr, b.address AS to_addr, r.value AS value LIMIT $limit",
            limit=limit
        )
        return [(r["from_addr"], r["to_addr"], r["value"]) for r in result]


def get_summary_stats():
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run(
            "MATCH (w:Wallet) OPTIONAL MATCH (w)-[r:SENT]->() RETURN count(DISTINCT w) AS wallets, count(r) AS txs"
        )
        record = result.single()
        return record["wallets"], record["txs"]


def get_hub_wallets(limit=1000):
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run(
            """
            MATCH (w:Wallet)-[r:SENT]-()
            RETURN w.address AS wallet, count(r) AS total_txs
            ORDER BY total_txs DESC LIMIT $limit
            """, limit=limit
        )
        return [(r["wallet"], r["total_txs"]) for r in result]


def get_fanout_wallets(min_recipients=4, limit=1000):
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run(
            """
            MATCH (a:Wallet)-[:SENT]->(b:Wallet)
            WITH a, count(DISTINCT b) AS distinct_recipients
            WHERE distinct_recipients >= $min_recipients
            RETURN a.address AS wallet, distinct_recipients
            ORDER BY distinct_recipients DESC LIMIT $limit
            """, min_recipients=min_recipients, limit=limit
        )
        return [(r["wallet"], r["distinct_recipients"]) for r in result]


def get_peel_chains(limit=1000):
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run(
            """
            MATCH (mid:Wallet)-[r2:SENT]->(next1:Wallet)
            MATCH (mid)-[r3:SENT]->(next2:Wallet)
            WHERE elementId(next1) < elementId(next2) AND r2.value > 0.001 AND r3.value > 0.001
            WITH mid,
                 CASE WHEN r2.value > r3.value THEN r2.value ELSE r3.value END AS bigger,
                 CASE WHEN r2.value > r3.value THEN r3.value ELSE r2.value END AS smaller
            WHERE (smaller / bigger) < 0.15
            WITH mid, bigger, smaller
            ORDER BY bigger DESC
            WITH mid, collect({main: bigger, peel: smaller})[0] AS top_match
            RETURN mid.address AS wallet, top_match.main AS main_amount, top_match.peel AS peel_amount
            ORDER BY main_amount DESC
            LIMIT $limit
            """, limit=limit
        )
        return [(r["wallet"], r["main_amount"], r["peel_amount"]) for r in result]


def get_round_number_transactions(min_value=1.0, limit=1000):
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run(
            """
            MATCH (a:Wallet)-[r:SENT]->(b:Wallet)
            WHERE r.value >= $min_value AND r.value = toInteger(r.value)
            RETURN a.address AS from_addr, b.address AS to_addr, r.value AS value
            ORDER BY r.value DESC
            LIMIT $limit
            """, min_value=min_value, limit=limit
        )
        return [(r["from_addr"], r["to_addr"], r["value"]) for r in result]


def get_circular_flows(max_hops=4, limit=1000):
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run(
            """
            MATCH path = (a:Wallet)-[:SENT*2..%d]->(a)
            RETURN DISTINCT a.address AS wallet, length(path) AS hops
            ORDER BY hops ASC
            LIMIT $limit
            """ % max_hops, limit=limit
        )
        return [(r["wallet"], r["hops"]) for r in result]


def get_all_wallet_addresses():
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run("MATCH (w:Wallet) RETURN w.address AS address")
        return [r["address"] for r in result]


def clear_graph():
    with driver.session(database=NEO4J_DATABASE) as session:
        session.run("MATCH (n:Wallet) DETACH DELETE n")


def load_case_edges(edges):
    with driver.session(database=NEO4J_DATABASE) as session:
        for i, e in enumerate(edges):
            synthetic_hash = hashlib.sha256(
                f"{e['from']}-{e['to']}-{e['value']}-{i}".encode()
            ).hexdigest()
            session.run(
                """
                MERGE (a:Wallet {address: $from_addr})
                MERGE (b:Wallet {address: $to_addr})
                MERGE (a)-[t:SENT {hash: $tx_hash}]->(b)
                SET t.value = $value_eth
                """,
                from_addr=e["from"], to_addr=e["to"], tx_hash=synthetic_hash, value_eth=e["value"]
            )


def get_paths_between(source, destination, max_hops=6, limit=10):
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run(
            """
            MATCH (a:Wallet), (b:Wallet)
            WHERE toLower(a.address) = toLower($source) AND toLower(b.address) = toLower($destination)
            MATCH p = (a)-[:SENT*1..%d]->(b)
            RETURN [n IN nodes(p) | n.address] AS wallets,
                   [r IN relationships(p) | {from: startNode(r).address, to: endNode(r).address, value: r.value}] AS rels,
                   length(p) AS hops
            ORDER BY hops ASC
            LIMIT $limit
            """ % max_hops,
            source=source, destination=destination, limit=limit
        )
        return [{"wallets": r["wallets"], "rels": r["rels"], "hops": r["hops"]} for r in result]


def get_last_certificate():
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run(
            """
            MATCH (c:Certificate)
            RETURN c.hash AS hash, c.created_at AS created_at
            ORDER BY c.created_at DESC LIMIT 1
            """
        )
        record = result.single()
        if record:
            return record["hash"], record["created_at"]
        return None, None


def store_certificate(cert_hash, prev_hash, wallet, created_at):
    with driver.session(database=NEO4J_DATABASE) as session:
        session.run(
            """
            CREATE (c:Certificate {hash: $hash, prev_hash: $prev_hash, wallet: $wallet, created_at: $created_at})
            """,
            hash=cert_hash, prev_hash=prev_hash, wallet=wallet, created_at=created_at
        )


def _resolve_chainid(chain_name):
    if chain_name not in CHAIN_OPTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown chain '{chain_name}'. Valid options: {list(CHAIN_OPTIONS.keys())}")
    return CHAIN_OPTIONS[chain_name]


# ==================== Endpoints ====================

@app.get("/")
def health_check():
    return {"status": "ok", "service": "BlockTrace API"}


@app.get("/chains")
def list_chains():
    return {"chains": list(CHAIN_OPTIONS.keys())}


@app.get("/curated-cases")
def list_curated_cases():
    return {
        "cases": [
            {"name": name, "address": info["address"], "chainid": info["chainid"], "description": info["description"]}
            for name, info in CURATED_CASES.items()
        ]
    }


@app.post("/curated-cases/{case_name}/load")
def load_curated_case(case_name: str):
    if case_name not in CURATED_CASES:
        raise HTTPException(status_code=404, detail="Unknown curated case name.")
    info = CURATED_CASES[case_name]
    visited = expand_from_wallet(info["address"], hops=2, tx_per_wallet=15, chainid=info["chainid"])
    return {"wallets_visited": visited, "start_wallet": info["address"]}


@app.post("/expand")
def expand(req: ExpandRequest):
    chainid = _resolve_chainid(req.chain)
    visited = expand_from_wallet(req.wallet, hops=req.hops, tx_per_wallet=req.tx_per_wallet, chainid=chainid)
    return {"wallets_visited": visited, "start_wallet": req.wallet}


@app.post("/clear")
def clear():
    clear_graph()
    return {"status": "cleared"}


@app.get("/summary")
def summary():
    wallets, txs = get_summary_stats()
    return {"wallets_traced": wallets, "transactions_mapped": txs}


@app.get("/graph")
def graph():
    edges = get_graph_data()
    return {"edges": [{"from": f, "to": t, "value": v} for f, t, v in edges]}


@app.get("/detections/hub")
def detections_hub():
    return {"results": [{"wallet": w, "total_txs": c, "label": get_entity_label(w)} for w, c in get_hub_wallets()]}


@app.get("/detections/fanout")
def detections_fanout():
    return {"results": [{"wallet": w, "distinct_recipients": c, "label": get_entity_label(w)} for w, c in get_fanout_wallets()]}


@app.get("/detections/peel-chains")
def detections_peel():
    return {"results": [{"wallet": w, "main_amount": m, "peel_amount": p, "label": get_entity_label(w)} for w, m, p in get_peel_chains()]}


@app.get("/detections/round-number")
def detections_round():
    return {"results": [{"from": f, "to": t, "value": v} for f, t, v in get_round_number_transactions()]}


@app.get("/detections/circular")
def detections_circular():
    return {"results": [{"wallet": w, "hops": h, "label": get_entity_label(w)} for w, h in get_circular_flows()]}


@app.get("/sanctions")
def sanctions():
    matches = check_sanctions(get_all_wallet_addresses())
    return {"matches": [{"wallet": addr, **entry} for addr, entry in matches]}


@app.get("/risk")
def risk():
    hub_data = get_hub_wallets()
    fanout_data = get_fanout_wallets()
    peel_data = get_peel_chains()
    round_data = get_round_number_transactions()
    circular_data = get_circular_flows()
    sanctioned = {addr for addr, _ in check_sanctions(get_all_wallet_addresses())}

    rows = compute_wallet_risk(hub_data, fanout_data, peel_data, round_data, circular_data,
                                sanctioned_addresses=sanctioned)
    result = []
    for wallet, signals, score in rows:
        tier_label, tier_class = risk_tier(score)
        result.append({
            "wallet": wallet, "signals": signals, "score": score,
            "tier": tier_label, "label": get_entity_label(wallet)
        })
    return {"results": result}


@app.get("/narrative")
def narrative(start_wallet: Optional[str] = None):
    hub_data = get_hub_wallets()
    fanout_data = get_fanout_wallets()
    peel_data = get_peel_chains()
    round_data = get_round_number_transactions()
    circular_data = get_circular_flows()
    sanctioned = {addr for addr, _ in check_sanctions(get_all_wallet_addresses())}
    risk_rows = compute_wallet_risk(hub_data, fanout_data, peel_data, round_data, circular_data,
                                     sanctioned_addresses=sanctioned)
    wallets_count, txs_count = get_summary_stats()

    if not start_wallet:
        edges = get_graph_data()
        start_wallet = edges[0][0] if edges else ""

    paragraphs = build_narrative(
        start_wallet, wallets_count, txs_count,
        hub_data, fanout_data, peel_data, round_data, circular_data, risk_rows
    )
    return {"paragraphs": paragraphs}


@app.post("/path")
def find_path(req: PathRequest):
    chainid = _resolve_chainid(req.chain)
    visited, found = expand_until_found(
        req.source, req.destination, max_hops=req.max_hops,
        tx_per_wallet=req.tx_per_wallet, chainid=chainid
    )
    if not found:
        return {"found": False, "wallets_visited": visited, "paths": []}

    paths = get_paths_between(req.source, req.destination, max_hops=req.max_hops)
    return {"found": len(paths) > 0, "wallets_visited": visited, "paths": paths}


@app.get("/cases")
def list_cases():
    cases = case_manager.list_cases()
    return {"cases": [{"name": n, "saved_at": s, "edge_count": c} for n, s, c in cases]}


@app.post("/cases")
def save_case(req: SaveCaseRequest):
    edges = get_graph_data()
    if not edges:
        raise HTTPException(status_code=400, detail="Nothing to save — the graph is empty.")
    start = req.start_wallet or edges[0][0]
    try:
        path = case_manager.save_case(req.name, start, edges)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "saved", "path": path, "edge_count": len(edges)}


@app.post("/cases/{name}/load")
def load_case(name: str):
    case_data = case_manager.load_case(name)
    if not case_data:
        raise HTTPException(status_code=404, detail="Case not found.")
    clear_graph()
    load_case_edges(case_data["edges"])
    return {"status": "loaded", "name": case_data["name"], "edge_count": case_data["edge_count"],
            "start_wallet": case_data.get("start_wallet")}


@app.delete("/cases/{name}")
def delete_case(name: str):
    deleted = case_manager.delete_case(name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Case not found.")
    return {"status": "deleted"}


@app.post("/certificate")
def issue_certificate(req: CertificateRequest):
    edges = get_graph_data()
    if not edges:
        raise HTTPException(status_code=400, detail="Nothing to certify — the graph is empty.")

    hub_data = get_hub_wallets()
    fanout_data = get_fanout_wallets()
    peel_data = get_peel_chains()
    round_data = get_round_number_transactions()
    circular_data = get_circular_flows()
    sanctioned = {addr for addr, _ in check_sanctions(get_all_wallet_addresses())}
    risk_rows = compute_wallet_risk(hub_data, fanout_data, peel_data, round_data, circular_data,
                                     sanctioned_addresses=sanctioned)
    wallets_count, txs_count = get_summary_stats()
    start_wallet = req.start_wallet or edges[0][0]

    payload = {
        "start_wallet": start_wallet,
        "wallets_traced": wallets_count,
        "transactions_mapped": txs_count,
        "hub_wallets": hub_data[:10],
        "fanout_wallets": fanout_data[:10],
        "peel_chains": [(w, m, p) for w, m, p in peel_data[:10]],
        "round_number_txs": round_data[:10],
        "circular_flows": circular_data[:10],
        "sanctions_matches": list(sanctioned),
        "risk_summary": [(w, s, sc) for w, s, sc in risk_rows[:10]],
    }

    prev_hash, _ = get_last_certificate()
    prev_hash = prev_hash or "GENESIS"
    new_hash = compute_certificate_hash(payload, prev_hash)
    created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    store_certificate(new_hash, prev_hash, start_wallet, created_at)

    return {
        "certificate_hash": new_hash,
        "previous_hash": prev_hash,
        "created_at": created_at,
        "payload": payload,
        "verification_note": "To verify: POST this exact object to /certificate/verify."
    }


@app.post("/certificate/verify")
def verify_cert(req: CertificateVerifyRequest):
    is_valid = verify_certificate(req.payload, req.previous_hash, req.certificate_hash)
    return {"valid": is_valid}


@app.get("/report")
def report(start_wallet: Optional[str] = None):
    wallet = start_wallet or "0x098B716B8Aaf21512996dC57EB0615e2383E2f96"
    output_path = "investigation_report.pdf"
    generate_report(wallet, output_path=output_path)
    return FileResponse(output_path, media_type="application/pdf", filename="investigation_report.pdf")
