import os
import csv
import json
import time
import random
import requests
from datetime import datetime

# ============================================================
# CONFIGURATION
# ============================================================

API_URL = "https://api.elsevier.com/content/search/scopus"

API_KEY = os.getenv("SCOPUS_API_KEY")

if not API_KEY:
    raise RuntimeError("SCOPUS_API_KEY is not set.")

TOTAL_RESULTS = 4610

# 300 gives a substantially better audit than the original 200
# while keeping API usage very small.
SAMPLE_SIZE = 300

RANDOM_SEED = 20261001

# Retrieve one selected record at each chosen position.
PAGE_SIZE = 1

# ============================================================
# V1 QUERY -- FROZEN FOR AUDIT
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

QUERY = " ".join(QUERY.split())

HEADERS = {
    "X-ELS-APIKey": API_KEY,
    "Accept": "application/json"
}

# ============================================================
# GENERATE REPRODUCIBLE SAMPLE POSITIONS
# ============================================================

random.seed(RANDOM_SEED)

positions = sorted(
    random.sample(
        range(TOTAL_RESULTS),
        SAMPLE_SIZE
    )
)

print("=" * 72)
print("SCOPUS V1 REPRESENTATIVE AUDIT")
print("=" * 72)

print("Total V1 corpus :", TOTAL_RESULTS)
print("Sample size     :", SAMPLE_SIZE)
print("Random seed     :", RANDOM_SEED)
print("View            : STANDARD")
print()

# ============================================================
# STORAGE
# ============================================================

records = []
failures = []

# ============================================================
# RETRIEVAL FUNCTION
# ============================================================

def retrieve_position(position, max_attempts=4):

    params = {
        "query": QUERY,
        "start": position,
        "count": PAGE_SIZE,
        "view": "STANDARD"
    }

    for attempt in range(1, max_attempts + 1):

        try:

            r = requests.get(
                API_URL,
                headers=HEADERS,
                params=params,
                timeout=60
            )

        except requests.RequestException as exc:

            print(
                f"Network error at position "
                f"{position}: {exc}"
            )

            if attempt < max_attempts:
                time.sleep(2 ** attempt)
                continue

            return None, {
                "position": position,
                "error": str(exc)
            }

        if r.status_code == 200:

            data = r.json()

            entries = (
                data
                .get("search-results", {})
                .get("entry", [])
            )

            if not entries:

                return None, {
                    "position": position,
                    "error": "No entry returned"
                }

            return entries[0], None

        # Retry temporary server/rate-limit errors
        if r.status_code in [429, 500, 502, 503, 504]:

            wait = 2 ** attempt

            print(
                f"Temporary HTTP {r.status_code}; "
                f"waiting {wait}s"
            )

            time.sleep(wait)
            continue

        return None, {
            "position": position,
            "http_status": r.status_code,
            "response": r.text[:1000]
        }

    return None, {
        "position": position,
        "error": "Maximum attempts exceeded"
    }

# ============================================================
# RETRIEVE SAMPLE
# ============================================================

for i, position in enumerate(positions, start=1):

    print(
        f"[{i:03d}/{SAMPLE_SIZE}] "
        f"Scopus position {position + 1}"
    )

    entry, error = retrieve_position(position)

    if error:

        failures.append(error)
        print("   FAILED")
        continue

    cover_date = entry.get("prism:coverDate")

    year = None

    if cover_date:
        year = cover_date[:4]

    record = {

        "sample_number": i,

        # Store zero-based API position and
        # human-readable one-based rank separately.
        "scopus_start_position": position,
        "scopus_result_rank": position + 1,

        "eid": entry.get("eid"),
        "doi": entry.get("prism:doi"),

        "title": entry.get("dc:title"),

        "year": year,

        "cover_date": cover_date,

        "publication":
            entry.get("prism:publicationName"),

        "document_type":
            entry.get("subtypeDescription"),

        "cited_by":
            entry.get("citedby-count"),

        "abstract":
            entry.get("dc:description"),

        "author_keywords":
            entry.get("authkeywords"),

        "scopus_url":
            entry.get("prism:url")
    }

    records.append(record)

    # Gentle pacing
    time.sleep(0.10)

# ============================================================
# OUTPUT CSV
# ============================================================

CSV_FILE = "scopus_v1_stratified_sample_300.csv"

FIELDS = [
    "sample_number",
    "scopus_start_position",
    "scopus_result_rank",
    "eid",
    "doi",
    "title",
    "year",
    "cover_date",
    "publication",
    "document_type",
    "cited_by",
    "abstract",
    "author_keywords",
    "scopus_url"
]

with open(
    CSV_FILE,
    "w",
    newline="",
    encoding="utf-8-sig"
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=FIELDS
    )

    writer.writeheader()
    writer.writerows(records)

# ============================================================
# SCREENING TEMPLATE
# ============================================================

SCREEN_FILE = (
    "scopus_v1_stratified_sample_300_screening.csv"
)

SCREEN_FIELDS = FIELDS + [

    "screen_decision",
    # INCLUDE / BORDERLINE / EXCLUDE

    "exclusion_reason",

    "agentic_relevance",

    "correctness_relevance",

    "external_action_relevance",

    "evidence_codes",

    "notes"
]

with open(
    SCREEN_FILE,
    "w",
    newline="",
    encoding="utf-8-sig"
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=SCREEN_FIELDS
    )

    writer.writeheader()

    for record in records:

        row = dict(record)

        row.update({
            "screen_decision": "",
            "exclusion_reason": "",
            "agentic_relevance": "",
            "correctness_relevance": "",
            "external_action_relevance": "",
            "evidence_codes": "",
            "notes": ""
        })

        writer.writerow(row)

# ============================================================
# AUDIT
# ============================================================

doi_count = sum(
    bool(r.get("doi"))
    for r in records
)

abstract_count = sum(
    bool(r.get("abstract"))
    for r in records
)

keyword_count = sum(
    bool(r.get("author_keywords"))
    for r in records
)

years = {}

for r in records:

    y = r.get("year") or "UNKNOWN"

    years[y] = years.get(y, 0) + 1

audit = {

    "query_version":
        "SCOPUS_V1",

    "retrieval_timestamp":
        datetime.now().isoformat(),

    "query":
        QUERY,

    "known_v1_total":
        TOTAL_RESULTS,

    "sampling_method":
        "Simple random sampling of Scopus result positions",

    "sample_size_requested":
        SAMPLE_SIZE,

    "sample_size_retrieved":
        len(records),

    "random_seed":
        RANDOM_SEED,

    "random_positions_zero_based":
        positions,

    "view":
        "STANDARD",

    "page_size":
        PAGE_SIZE,

    "doi_available":
        doi_count,

    "abstract_available":
        abstract_count,

    "author_keywords_available":
        keyword_count,

    "year_distribution":
        years,

    "failed_positions":
        failures,

    "important_note":
        (
            "Sample is for query-performance audit. "
            "Final systematic-review corpus has not "
            "been frozen."
        )
}

AUDIT_FILE = (
    "scopus_v1_stratified_sample_300_audit.json"
)

with open(
    AUDIT_FILE,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        audit,
        f,
        ensure_ascii=False,
        indent=2
    )

# ============================================================
# SUMMARY
# ============================================================

print()
print("=" * 72)
print("AUDIT RETRIEVAL COMPLETE")
print("=" * 72)

print(
    "Requested :",
    SAMPLE_SIZE
)

print(
    "Retrieved :",
    len(records)
)

print(
    "Failures  :",
    len(failures)
)

print()
print("Metadata availability")
print("-" * 72)

print(
    f"DOI             : "
    f"{doi_count}/{len(records)}"
)

print(
    f"Abstract        : "
    f"{abstract_count}/{len(records)}"
)

print(
    f"Author keywords : "
    f"{keyword_count}/{len(records)}"
)

print()
print("Year distribution")

for year in sorted(years):
    print(
        f"  {year}: {years[year]}"
    )

print()
print("Files saved")
print("-" * 72)

print(CSV_FILE)
print(SCREEN_FILE)
print(AUDIT_FILE)

print()
print("DONE.")