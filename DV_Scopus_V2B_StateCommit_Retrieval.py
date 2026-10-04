import os
import sys
import csv
import json
import time
from datetime import datetime, timezone

import requests


# ============================================================
# CONFIGURATION
# ============================================================

API_KEY = os.getenv("SCOPUS_API_KEY")

if not API_KEY:
    raise RuntimeError(
        "SCOPUS_API_KEY is not set.\n"
        "PowerShell example:\n"
        '$env:SCOPUS_API_KEY="10c4a5c2ae7701e8569de14b56875e52"'
    )

BASE_URL = "https://api.elsevier.com/content/search/scopus"

OUTPUT_CSV = "Scopus_V2B_StateCommit_Candidate.csv"
OUTPUT_AUDIT = "Scopus_V2B_StateCommit_Audit.json"

VIEW = "STANDARD"
PAGE_SIZE = 25
MAX_RETRIES = 5
REQUEST_DELAY = 0.25


# ============================================================
# SEARCH QUERY
# ============================================================

QUERY = r'''
TITLE-ABS-KEY(
 (
   "LLM agent*" OR
   "large language model agent*" OR
   "agentic AI" OR
   "agentic system*" OR
   "autonomous AI agent*" OR
   "tool-using agent*" OR
   "computer-use agent*" OR
   "GUI agent*"
 )
 AND
 (
   "decision conflict*" OR
   "decision condition*" OR
   "decision valid*" OR
   revalidat* OR
   "state change*" OR
   "state valid*" OR
   "state inconsisten*" OR
   "state verification" OR
   stale* OR
   freshness OR
   TOCTOU OR
   "time-of-check" OR
   "time of check" OR
   "semantic transaction*" OR
   "transaction boundary" OR
   "transactional execution" OR
   "commit semantics" OR
   "commit protocol*" OR
   "compare-and-set" OR
   rollback OR
   compensation OR
   "effect verification" OR
   "effect validation" OR
   "execution verification"
 )
)
'''
# Remove unnecessary whitespace/newlines.
QUERY = " ".join(QUERY.split())


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "X-ELS-APIKey": API_KEY,
    "Accept": "application/json"
})


def scopus_request(params):
    """
    Send a Scopus Search API request with retry handling.
    """

    for attempt in range(1, MAX_RETRIES + 1):

        try:
            response = session.get(
                BASE_URL,
                params=params,
                timeout=60
            )

        except requests.RequestException as exc:

            if attempt == MAX_RETRIES:
                raise

            wait = 2 ** attempt
            print(f"Network error: {exc}")
            print(f"Retrying in {wait} seconds...")
            time.sleep(wait)
            continue

        # Success
        if response.status_code == 200:
            return response

        # Rate limiting
        if response.status_code == 429:

            reset = response.headers.get("X-RateLimit-Reset")

            print("Rate limit reached.")

            if reset:
                try:
                    reset_epoch = int(reset)
                    now_epoch = int(time.time())

                    wait = max(
                        5,
                        min(reset_epoch - now_epoch + 2, 300)
                    )

                except Exception:
                    wait = 30
            else:
                wait = 30

            print(f"Waiting {wait} seconds...")
            time.sleep(wait)
            continue

        # Authentication / entitlement errors
        if response.status_code in (401, 403):

            print("\nAUTHENTICATION / ENTITLEMENT ERROR")
            print("HTTP:", response.status_code)

            try:
                print(
                    json.dumps(
                        response.json(),
                        indent=2
                    )[:5000]
                )
            except Exception:
                print(response.text[:5000])

            sys.exit(1)

        # Other API error
        print("\nSCOPUS API ERROR")
        print("HTTP:", response.status_code)

        try:
            print(
                json.dumps(
                    response.json(),
                    indent=2
                )[:5000]
            )
        except Exception:
            print(response.text[:5000])

        sys.exit(1)

    raise RuntimeError("Maximum retries exceeded.")


# ============================================================
# STEP 1 — COUNT QUERY
# ============================================================

print("=" * 78)
print("SCOPUS V2 PRODUCTION-CANDIDATE RETRIEVAL")
print("=" * 78)

print("\nQuery:")
print(QUERY)

print("\nChecking total result count...")

count_params = {
    "query": QUERY,
    "view": VIEW,
    "count": 1,
    "start": 0
}

response = scopus_request(count_params)
payload = response.json()

search_results = payload.get("search-results", {})

total_results = int(
    search_results.get(
        "opensearch:totalResults",
        0
    )
)

print("\nTOTAL_RESULTS =", total_results)


# ============================================================
# IMPORTANT LIMIT CHECK
# ============================================================

# Elsevier documents a 5000-result non-cursor limit.
# If the query unexpectedly exceeds that, stop rather than
# silently producing an incomplete dataset.

if total_results > 5000:

    print("\nSTOPPING.")
    print(
        "The query returned more than 5,000 records."
    )
    print(
        "Do not retrieve an incomplete corpus using start pagination."
    )
    print(
        "Report TOTAL_RESULTS to ChatGPT so we can switch to "
        "cursor pagination or redesign retrieval."
    )

    audit = {
        "pipeline":
            "Scopus V2 production-candidate retrieval",
        "timestamp_utc":
            datetime.now(timezone.utc).isoformat(),
        "query":
            QUERY,
        "view":
            VIEW,
        "total_results":
            total_results,
        "retrieval_status":
            "COUNT_ONLY_OVER_5000",
        "records_retrieved":
            0
    }

    with open(
        OUTPUT_AUDIT,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            audit,
            f,
            indent=2,
            ensure_ascii=False
        )

    sys.exit(0)


# ============================================================
# STEP 2 — RETRIEVE ALL RECORDS
# ============================================================

records = []

print("\nRetrieving records...")

for start in range(
    0,
    total_results,
    PAGE_SIZE
):

    count = min(
        PAGE_SIZE,
        total_results - start
    )

    print(
        f"Retrieving {start + 1}"
        f"–{start + count}"
        f" / {total_results}"
    )

    params = {
        "query": QUERY,
        "view": VIEW,
        "count": count,
        "start": start
    }

    response = scopus_request(params)

    data = response.json()

    entries = (
        data
        .get("search-results", {})
        .get("entry", [])
    )

    if not isinstance(entries, list):
        entries = [entries]

    records.extend(entries)

    time.sleep(REQUEST_DELAY)


# ============================================================
# STEP 3 — NORMALIZE RECORDS
# ============================================================

def get_value(record, key):
    value = record.get(key, "")

    if value is None:
        return ""

    if isinstance(value, (dict, list)):
        return json.dumps(
            value,
            ensure_ascii=False
        )

    return str(value).strip()


normalized = []

for rank, record in enumerate(
    records,
    start=1
):

    normalized.append({

        "scopus_result_rank":
            rank,

        "eid":
            get_value(
                record,
                "eid"
            ),

        "scopus_id":
            get_value(
                record,
                "dc:identifier"
            ),

        "doi":
            get_value(
                record,
                "prism:doi"
            ),

        "title":
            get_value(
                record,
                "dc:title"
            ),

        "publication":
            get_value(
                record,
                "prism:publicationName"
            ),

        "issn":
            get_value(
                record,
                "prism:issn"
            ),

        "eissn":
            get_value(
                record,
                "prism:eIssn"
            ),

        "volume":
            get_value(
                record,
                "prism:volume"
            ),

        "issue":
            get_value(
                record,
                "prism:issueIdentifier"
            ),

        "page_range":
            get_value(
                record,
                "prism:pageRange"
            ),

        "cover_date":
            get_value(
                record,
                "prism:coverDate"
            ),

        "cover_display_date":
            get_value(
                record,
                "prism:coverDisplayDate"
            ),

        "document_type":
            get_value(
                record,
                "subtypeDescription"
            ),

        "subtype":
            get_value(
                record,
                "subtype"
            ),

        "cited_by":
            get_value(
                record,
                "citedby-count"
            ),

        "aggregation_type":
            get_value(
                record,
                "prism:aggregationType"
            ),

        "open_access":
            get_value(
                record,
                "openaccess"
            ),

        "scopus_url":
            get_value(
                record,
                "prism:url"
            )
    })


# ============================================================
# STEP 4 — SAVE CSV
# ============================================================

fieldnames = [
    "scopus_result_rank",
    "eid",
    "scopus_id",
    "doi",
    "title",
    "publication",
    "issn",
    "eissn",
    "volume",
    "issue",
    "page_range",
    "cover_date",
    "cover_display_date",
    "document_type",
    "subtype",
    "cited_by",
    "aggregation_type",
    "open_access",
    "scopus_url"
]


with open(
    OUTPUT_CSV,
    "w",
    newline="",
    encoding="utf-8-sig"
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=fieldnames
    )

    writer.writeheader()
    writer.writerows(normalized)


# ============================================================
# STEP 5 — AUDIT / QUALITY CHECKS
# ============================================================

eids = [
    r["eid"]
    for r in normalized
    if r["eid"]
]

dois = [
    r["doi"].lower()
    for r in normalized
    if r["doi"]
]

titles = [
    r["title"].lower()
    for r in normalized
    if r["title"]
]


duplicate_eids = (
    len(eids) - len(set(eids))
)

duplicate_dois = (
    len(dois) - len(set(dois))
)

duplicate_titles = (
    len(titles) - len(set(titles))
)


# Year distribution

year_distribution = {}

for r in normalized:

    date = r["cover_date"]

    if date and len(date) >= 4:
        year = date[:4]
    else:
        year = "UNKNOWN"

    year_distribution[year] = (
        year_distribution.get(year, 0) + 1
    )


# Document type distribution

doctype_distribution = {}

for r in normalized:

    dt = (
        r["document_type"]
        if r["document_type"]
        else "UNKNOWN"
    )

    doctype_distribution[dt] = (
        doctype_distribution.get(dt, 0) + 1
    )


audit = {

    "pipeline":
        "Scopus V2 production-candidate retrieval",

    "timestamp_utc":
        datetime.now(timezone.utc).isoformat(),

    "endpoint":
        BASE_URL,

    "query":
        QUERY,

    "view":
        VIEW,

    "page_size":
        PAGE_SIZE,

    "filters_applied":
        {
            "year": None,
            "subject_area": None,
            "language": None,
            "document_type": None
        },

    "total_results_reported":
        total_results,

    "records_retrieved":
        len(normalized),

    "eid_available":
        len(eids),

    "doi_available":
        len(dois),

    "title_available":
        len(titles),

    "duplicate_eids":
        duplicate_eids,

    "duplicate_dois":
        duplicate_dois,

    "duplicate_titles":
        duplicate_titles,

    "year_distribution":
        dict(
            sorted(
                year_distribution.items(),
                reverse=True
            )
        ),

    "document_type_distribution":
        dict(
            sorted(
                doctype_distribution.items(),
                key=lambda x: (
                    -x[1],
                    x[0]
                )
            )
        ),

    "output_csv":
        OUTPUT_CSV,

    "corpus_status":
        (
            "PRODUCTION_CANDIDATE_NOT_FROZEN"
        )
}


with open(
    OUTPUT_AUDIT,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        audit,
        f,
        indent=2,
        ensure_ascii=False
    )


# ============================================================
# FINAL REPORT
# ============================================================

print("\n" + "=" * 78)
print("RETRIEVAL COMPLETE")
print("=" * 78)

print(
    "Scopus reported:",
    total_results
)

print(
    "Records retrieved:",
    len(normalized)
)

print(
    "DOIs available:",
    len(dois)
)

print(
    "Duplicate EIDs:",
    duplicate_eids
)

print(
    "Duplicate DOIs:",
    duplicate_dois
)

print(
    "Duplicate titles:",
    duplicate_titles
)

print("\nYear distribution:")

for year, count in sorted(
    year_distribution.items(),
    reverse=True
):
    print(
        f"  {year}: {count}"
    )

print("\nFiles created:")

print(
    " ",
    OUTPUT_CSV
)

print(
    " ",
    OUTPUT_AUDIT
)

print(
    "\nSTATUS: PRODUCTION CANDIDATE — NOT FROZEN"
)