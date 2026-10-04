import os
import json
import requests
from datetime import datetime

# ============================================================
# SCOPUS V1 PILOT — COUNT ONLY
# ============================================================

API_URL = "https://api.elsevier.com/content/search/scopus"

# ------------------------------------------------------------
# API KEY
# Recommended:
# Windows CMD:
#   set SCOPUS_API_KEY=YOUR_KEY
#
# PowerShell:
#   $env:SCOPUS_API_KEY="YOUR_KEY"
#
# Do NOT paste the key into files that will be shared.
# ------------------------------------------------------------

API_KEY = os.getenv("SCOPUS_API_KEY")

if not API_KEY:
    raise RuntimeError(
        "SCOPUS_API_KEY environment variable is not set."
    )

# ============================================================
# V1 HIGH-RECALL PILOT QUERY
# No year/document-type/subject restriction yet.
# ============================================================

QUERY = r'''
TITLE-ABS-KEY(
  (
    "LLM agent*" OR
    "large language model agent*" OR
    "AI agent*" OR
    "agentic AI" OR
    "agentic system*" OR
    "autonomous AI agent*" OR
    "tool-using agent*"
  )
  AND
  (
    correct* OR
    valid* OR
    integrity OR
    consisten* OR
    verif* OR
    validation OR
    invariant* OR
    specification* OR
    contract* OR
    "runtime verification" OR
    "runtime assurance" OR
    enforcement OR
    provenance OR
    authori* OR
    delegation OR
    transaction* OR
    commit* OR
    rollback OR
    stale* OR
    freshness OR
    "state consistency" OR
    "state validity" OR
    "decision conflict*" OR
    "semantic transaction*" OR
    "effect validation" OR
    "action validation"
  )
)
'''

# Collapse whitespace for cleaner API transmission
QUERY = " ".join(QUERY.split())

headers = {
    "X-ELS-APIKey": API_KEY,
    "Accept": "application/json"
}

params = {
    "query": QUERY,
    "count": 1,
    "view": "STANDARD"
}

print("=" * 70)
print("SCOPUS V1 PILOT")
print("=" * 70)
print("Retrieval time:", datetime.now().isoformat(timespec="seconds"))
print("\nQuery:")
print(QUERY)
print("\nContacting Scopus...")

response = requests.get(
    API_URL,
    headers=headers,
    params=params,
    timeout=60
)

print("\nHTTP status:", response.status_code)

# ------------------------------------------------------------
# ERROR HANDLING
# ------------------------------------------------------------

if response.status_code != 200:

    print("\nScopus API returned an error.")

    print("\nResponse headers:")
    for key, value in response.headers.items():
        if key.lower().startswith(("x-els", "x-rate")):
            print(f"{key}: {value}")

    print("\nResponse body:")
    print(response.text[:3000])

    raise SystemExit(1)

# ------------------------------------------------------------
# PARSE COUNT
# ------------------------------------------------------------

data = response.json()

search_results = data.get("search-results", {})

total = search_results.get("opensearch:totalResults")

if total is None:
    print("\nCould not locate opensearch:totalResults.")
    print(json.dumps(data, indent=2)[:5000])
    raise SystemExit(1)

total = int(total)

print("\n" + "=" * 70)
print("RESULT")
print("=" * 70)

print(f"\nSCOPUS V1 COUNT = {total:,}")

# ------------------------------------------------------------
# QUOTA INFORMATION
# ------------------------------------------------------------

print("\nAPI quota/rate information returned:")

quota_headers = [
    "X-RateLimit-Limit",
    "X-RateLimit-Remaining",
    "X-RateLimit-Reset"
]

for h in quota_headers:
    if h in response.headers:
        print(f"{h}: {response.headers[h]}")

# ------------------------------------------------------------
# SAVE AUDIT RECORD
# ------------------------------------------------------------

audit = {
    "query_version": "SCOPUS_V1",
    "retrieval_timestamp": datetime.now().isoformat(),
    "query": QUERY,
    "total_results": total,
    "http_status": response.status_code,
    "rate_limit_limit": response.headers.get("X-RateLimit-Limit"),
    "rate_limit_remaining": response.headers.get(
        "X-RateLimit-Remaining"
    ),
    "rate_limit_reset": response.headers.get(
        "X-RateLimit-Reset"
    )
}

output_file = "scopus_v1_count_audit.json"

with open(output_file, "w", encoding="utf-8") as f:
    json.dump(
        audit,
        f,
        ensure_ascii=False,
        indent=2
    )

print(f"\nAudit saved to: {output_file}")

print("\nDONE.")