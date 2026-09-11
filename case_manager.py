"""
Case management — save and reload named investigations without re-hitting the
Etherscan API each time. A "case" is just the set of transactions currently in the
graph, saved as JSON under ./cases/<name>.json.

Kept separate from app.py so the file I/O logic can be tested independently.
"""

import os
import json
from datetime import datetime

CASES_DIR = "cases"


def _ensure_cases_dir():
    os.makedirs(CASES_DIR, exist_ok=True)


def save_case(name, start_wallet, edges):
    """edges: list of (from_addr, to_addr, value) as returned by get_graph_data().
    Saves to cases/<name>.json. Overwrites if a case with the same name exists."""
    _ensure_cases_dir()
    safe_name = "".join(c for c in name if c.isalnum() or c in (" ", "-", "_")).strip()
    if not safe_name:
        raise ValueError("Case name must contain at least one alphanumeric character.")

    payload = {
        "name": safe_name,
        "start_wallet": start_wallet,
        "saved_at": datetime.now().isoformat(),
        "edge_count": len(edges),
        "edges": [{"from": f, "to": t, "value": v} for f, t, v in edges],
    }

    path = os.path.join(CASES_DIR, f"{safe_name}.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    return path


def list_cases():
    """Returns a list of (case_name, saved_at, edge_count) for every saved case,
    most recently saved first."""
    _ensure_cases_dir()
    cases = []
    for fname in os.listdir(CASES_DIR):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(CASES_DIR, fname)) as f:
                data = json.load(f)
            cases.append((data["name"], data.get("saved_at", ""), data.get("edge_count", 0)))
        except (json.JSONDecodeError, KeyError, OSError):
            continue  # skip corrupted/unreadable case files rather than crashing
    cases.sort(key=lambda c: c[1], reverse=True)
    return cases


def load_case(name):
    """Returns the full case payload dict for a given case name, or None if not found."""
    path = os.path.join(CASES_DIR, f"{name}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def delete_case(name):
    """Deletes a saved case file. Returns True if deleted, False if it didn't exist."""
    path = os.path.join(CASES_DIR, f"{name}.json")
    if os.path.exists(path):
        os.remove(path)
        return True
    return False
