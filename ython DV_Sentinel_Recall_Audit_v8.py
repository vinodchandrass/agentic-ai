import pandas as pd
import re
from difflib import SequenceMatcher

FILE = r"D:\ACM\Scopus_V2_Production_Candidate.csv"

sentinels = [
    ("ATR",
     "From Version Conflicts to Decision Conflicts: Selective Revalidation for Long-Running AI Agents"),

    ("CORDON",
     "Cordon: Semantic Transactions for Tool-Using LLM Agents"),

    ("TOCTOU",
     "Temporal UI State Inconsistency in Desktop GUI Agents: Formalizing and Defending Against TOCTOU Attacks on Computer-Use Agents"),

    ("IEIB",
     "A Trusted Provenance and TEE-Based Reference Architecture for Intent-Execution Binding in LLM Agents"),

    ("IBBC",
     "IBBC-Guard: Intent-Bound Behavior-Chain Modeling for Unauthorized Tool-Call Detection and Dynamic Permission Control in LLM Agents"),

    ("VERIACT",
     "VeriAct-Agent: Evidence-Verified Tool Execution for Reliable LLM Agents"),

    ("AGENTGUARD",
     "AgentGuard: Runtime Verification of AI Agents"),
]

def norm(s):
    s = str(s).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

df = pd.read_csv(FILE, dtype=str).fillna("")

title_col = "title"

rows = []

for code, target in sentinels:
    target_n = norm(target)

    best_score = 0
    best_row = None

    for _, r in df.iterrows():
        score = SequenceMatcher(
            None,
            target_n,
            norm(r.get(title_col, ""))
        ).ratio()

        if score > best_score:
            best_score = score
            best_row = r

    found = best_score >= 0.90

    rows.append({
        "sentinel": code,
        "target_title": target,
        "FOUND": found,
        "similarity": round(best_score, 4),
        "matched_title":
            best_row.get("title", "") if best_row is not None else "",
        "doi":
            best_row.get("doi", "") if best_row is not None else "",
        "eid":
            best_row.get("eid", "") if best_row is not None else ""
    })

out = pd.DataFrame(rows)

out.to_csv(
    r"D:\ACM\DV_Sentinel_Recall_Audit_v8.csv",
    index=False,
    encoding="utf-8-sig"
)

print(out.to_string(index=False))

print()
print("Sentinels found :", out["FOUND"].sum(), "/", len(out))
print("Sentinels missed:", (~out["FOUND"]).sum())

if not out["FOUND"].all():
    print("\n*** PRODUCTION SEARCH MUST NOT BE FROZEN ***")
else:
    print("\nAll sentinels recovered.")