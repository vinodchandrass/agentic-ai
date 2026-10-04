import requests
import pandas as pd
import time
import getpass
import re
from pathlib import Path

# ============================================================
# Scopus V2D Query-Repair Retrieval
# Decision Validity in Agentic AI
# ============================================================

OUTDIR = Path(".")
OUTDIR.mkdir(exist_ok=True)

# Enter key securely -- it will not be displayed
API_KEY = getpass.getpass("Enter your Scopus API key: ").strip()

if not API_KEY:
    raise SystemExit("No API key entered.")

QUERY = r'''
TITLE-ABS-KEY(
 (
   "LLM agent*" OR
   "large language model agent*" OR
   "agentic AI" OR
   "agentic system*" OR
   "autonomous AI agent*" OR
   "autonomous agent*" OR
   "tool-using agent*" OR
   "generative AI agent*" OR
   "multi-agent system*" OR
   "multi-agent orchestration"
 )
 AND
 (
   (
     "intent-bound delegation" OR
     "intent-bound" OR
     "capability sandbox*" OR
     "behavioral attestation" OR
     "delegation integrity" OR
     "capability-level control"
   )
   OR
   (
     "policy-feasible action*" OR
     "policy feasible action*" OR
     "execution feasibility" OR
     "constraint projection" OR
     "policy predicate*" OR
     "feasible action*"
   )
   OR
   (
     "MCP gateway*" OR
     "Model Context Protocol" OR
     "semantic compatibility" OR
     "schema validation" OR
     "mediated action*"
   )
 )
)
'''

URL = "https://api.elsevier.com/content/search/scopus"

HEADERS = {
    "X-ELS-APIKey": API_KEY,
    "Accept": "application/json"
}

COUNT = 25
start = 0
records = []
total = None

print("\nRunning Scopus V2D query-repair search...\n")

while True:

    params = {
        "query": QUERY,
        "view": "STANDARD",
        "count": COUNT,
        "start": start
    }

    r = requests.get(
        URL,
        headers=HEADERS,
        params=params,
        timeout=60
    )

    if r.status_code != 200:
        print("\nScopus API error:", r.status_code)
        print(r.text[:1500])
        raise SystemExit

    data = r.json()
    sr = data.get("search-results", {})

    if total is None:
        total = int(sr.get("opensearch:totalResults", 0))
        print("TOTAL RESULTS:", total)

    entries = sr.get("entry", [])

    if not entries:
        break

    for e in entries:

        records.append({
            "eid": e.get("eid", ""),
            "doi": e.get("prism:doi", ""),
            "title": e.get("dc:title", ""),
            "creator": e.get("dc:creator", ""),
            "source_title": e.get("prism:publicationName", ""),
            "cover_date": e.get("prism:coverDate", ""),
            "publication_year":
                str(e.get("prism:coverDate", ""))[:4],
            "document_type": e.get("subtypeDescription", ""),
            "aggregation_type": e.get("prism:aggregationType", ""),
            "citedby_count": e.get("citedby-count", ""),
            "scopus_url": e.get("prism:url", "")
        })

    start += len(entries)

    print(f"Retrieved {start}/{total}")

    if start >= total:
        break

    time.sleep(0.25)


# ============================================================
# Save raw retrieval
# ============================================================

df = pd.DataFrame(records)

raw_file = OUTDIR / "DV_Scopus_V2D_Raw_v53.csv"
df.to_csv(raw_file, index=False, encoding="utf-8-sig")


# ============================================================
# Basic deduplication
# ============================================================

def norm_title(x):
    x = str(x).lower()
    x = re.sub(r"[^a-z0-9]+", " ", x)
    return re.sub(r"\s+", " ", x).strip()


df["normalized_title"] = df["title"].map(norm_title)

before = len(df)

if "eid" in df.columns:
    df = df.drop_duplicates(subset=["eid"], keep="first")

df = df.drop_duplicates(
    subset=["normalized_title"],
    keep="first"
)

after = len(df)

dedup_file = OUTDIR / "DV_Scopus_V2D_Deduplicated_v53.csv"

df.to_csv(
    dedup_file,
    index=False,
    encoding="utf-8-sig"
)


# ============================================================
# Sentinel test
# ============================================================

SENTINELS = {
    "Identity Fabric":
        "Future-Proofing Identity Security for Agentic AI Systems",

    "CAMCO":
        "Safe and Policy-Compliant Multi-Agent Orchestration for Enterprise AI",

    "MCP Gateway":
        "Governed Agentic Cloud Data Pipelines with MCP Gateways",

    "IBBC-Guard":
        "IBBC-Guard",

    "AgentGuard":
        "AgentGuard",

    "VeriAct":
        "VeriAct",

    "Intent-Execution Binding":
        "Intent-Execution Binding"
}


sentinel_rows = []

all_titles = " || ".join(
    df["title"].fillna("").astype(str)
).lower()

for name, phrase in SENTINELS.items():

    found = phrase.lower() in all_titles

    sentinel_rows.append({
        "sentinel": name,
        "search_phrase": phrase,
        "retrieved_by_V2D": found
    })


sentinel_df = pd.DataFrame(sentinel_rows)

sentinel_file = (
    OUTDIR /
    "DV_Scopus_V2D_Sentinel_Audit_v53.csv"
)

sentinel_df.to_csv(
    sentinel_file,
    index=False,
    encoding="utf-8-sig"
)


# ============================================================
# Audit
# ============================================================

audit = pd.DataFrame([
    ["query_version", "V2D_v53"],
    ["total_results_reported_by_scopus", total],
    ["rows_retrieved", len(records)],
    ["unique_after_basic_deduplication", after],
    ["duplicates_removed", before - after],
    ["api_view", "STANDARD"],
    ["automatic_eligibility_decisions", 0],
    ["title_only_exclusions", 0],
    ["corpus_status", "NOT_FROZEN"]
], columns=["field", "value"])

audit_file = (
    OUTDIR /
    "DV_Scopus_V2D_Retrieval_Audit_v53.csv"
)

audit.to_csv(
    audit_file,
    index=False,
    encoding="utf-8-sig"
)


print("\n========================================")
print("V2D RETRIEVAL COMPLETE")
print("========================================")

print("Scopus total:", total)
print("Rows retrieved:", len(records))
print("Unique records:", after)

print("\nSentinel test:")
print(
    sentinel_df[
        ["sentinel", "retrieved_by_V2D"]
    ].to_string(index=False)
)

print("\nFiles created:")
print(raw_file)
print(dedup_file)
print(sentinel_file)
print(audit_file)

print(
    "\nIMPORTANT: No eligibility decisions were "
    "made automatically."
)