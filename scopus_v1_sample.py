import os
import csv
import json
import requests
from datetime import datetime

# ============================================================
# CONFIGURATION
# ============================================================

API_URL = "https://api.elsevier.com/content/search/scopus"

API_KEY = os.getenv("SCOPUS_API_KEY")

if not API_KEY:
    raise RuntimeError(
        "SCOPUS_API_KEY environment variable is not set."
    )

# Start conservatively because your service level rejected count=50.
PAGE_SIZE = 25
TARGET_RECORDS = 200

# ============================================================
# SCOPUS V1 QUERY -- DO NOT MODIFY
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
# RETRIEVAL
# ============================================================

all_records = []
raw_pages = []

print("=" * 70)
print("SCOPUS V1 SAMPLE RETRIEVAL")
print("=" * 70)
print(f"Target records : {TARGET_RECORDS}")
print(f"Page size      : {PAGE_SIZE}")
print("View           : STANDARD")
print()

for start in range(0, TARGET_RECORDS, PAGE_SIZE):

    remaining = TARGET_RECORDS - len(all_records)
    requested_count = min(PAGE_SIZE, remaining)

    params = {
        "query": QUERY,
        "start": start,
        "count": requested_count,
        "view": "STANDARD"
    }

    print(
        f"Retrieving records "
        f"{start + 1}-{start + requested_count}..."
    )

    response = requests.get(
        API_URL,
        headers=HEADERS,
        params=params,
        timeout=90
    )

    print("HTTP:", response.status_code)

    if response.status_code != 200:

        print("\nSCOPUS ERROR")
        print("-" * 70)
        print(response.text[:4000])

        print("\nNo further pages requested.")

        # Save diagnostic information
        diagnostic = {
            "timestamp": datetime.now().isoformat(),
            "http_status": response.status_code,
            "start": start,
            "count": requested_count,
            "view": "STANDARD",
            "response": response.text[:4000]
        }

        with open(
            "scopus_v1_error_diagnostic.json",
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                diagnostic,
                f,
                ensure_ascii=False,
                indent=2
            )

        raise SystemExit(1)

    data = response.json()
    raw_pages.append(data)

    search_results = data.get("search-results", {})

    if start == 0:
        total_results = search_results.get(
            "opensearch:totalResults"
        )
        print("Scopus total results:", total_results)

    entries = search_results.get("entry", [])

    print("Entries returned:", len(entries))

    if not entries:
        print("No additional entries returned.")
        break

    for e in entries:

        title = e.get("dc:title")
        doi = e.get("prism:doi")
        eid = e.get("eid")
        cover_date = e.get("prism:coverDate")

        year = None
        if cover_date:
            year = cover_date[:4]

        record = {
            "eid": eid,
            "doi": doi,
            "title": title,
            "year": year,
            "cover_date": cover_date,
            "publication": e.get(
                "prism:publicationName"
            ),
            "document_type": e.get(
                "subtypeDescription"
            ),
            "cited_by": e.get(
                "citedby-count"
            ),

            # These may be absent under STANDARD.
            # We retain the columns intentionally.
            "abstract": e.get(
                "dc:description"
            ),
            "author_keywords": e.get(
                "authkeywords"
            ),

            "scopus_url": e.get(
                "prism:url"
            )
        }

        all_records.append(record)

    if len(all_records) >= TARGET_RECORDS:
        break

# Trim defensively
all_records = all_records[:TARGET_RECORDS]

print()
print("=" * 70)
print("RETRIEVAL COMPLETE")
print("=" * 70)
print("Records retrieved:", len(all_records))

# ============================================================
# FIELD AVAILABILITY CHECK
# ============================================================

if raw_pages:

    first_entries = (
        raw_pages[0]
        .get("search-results", {})
        .get("entry", [])
    )

    if first_entries:

        print("\nFields available in first STANDARD record:")

        for key in sorted(first_entries[0].keys()):
            print(" ", key)

# ============================================================
# CSV OUTPUT
# ============================================================

csv_file = "scopus_v1_sample_200.csv"

fields = [
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
    csv_file,
    "w",
    newline="",
    encoding="utf-8-sig"
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=fields
    )

    writer.writeheader()
    writer.writerows(all_records)

# ============================================================
# RAW JSON
# ============================================================

raw_file = "scopus_v1_sample_200_raw.json"

with open(
    raw_file,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        raw_pages,
        f,
        ensure_ascii=False,
        indent=2
    )

# ============================================================
# AUDIT FILE
# ============================================================

abstract_count = sum(
    1 for r in all_records
    if r.get("abstract")
)

keyword_count = sum(
    1 for r in all_records
    if r.get("author_keywords")
)

doi_count = sum(
    1 for r in all_records
    if r.get("doi")
)

audit = {
    "query_version": "SCOPUS_V1",
    "retrieval_timestamp":
        datetime.now().isoformat(),
    "query": QUERY,
    "scopus_v1_total_count": 4610,
    "target_sample": TARGET_RECORDS,
    "retrieved_records":
        len(all_records),
    "page_size": PAGE_SIZE,
    "view": "STANDARD",
    "doi_available":
        doi_count,
    "abstract_available":
        abstract_count,
    "author_keywords_available":
        keyword_count,
    "sampling_method":
        "First 200 Scopus results; preliminary query audit only",
    "purpose":
        "Precision/error analysis before production retrieval"
}

audit_file = "scopus_v1_sample_200_audit.json"

with open(
    audit_file,
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

print("\nMetadata availability")
print("-" * 70)
print(
    f"DOI:             {doi_count}/{len(all_records)}"
)
print(
    f"Abstract:        {abstract_count}/{len(all_records)}"
)
print(
    f"Author keywords: {keyword_count}/{len(all_records)}"
)

print("\nFiles saved")
print("-" * 70)
print(csv_file)
print(raw_file)
print(audit_file)

print("\nDONE.")