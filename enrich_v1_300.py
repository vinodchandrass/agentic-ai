import csv
import json
import re
import time
import requests
from difflib import SequenceMatcher
from datetime import datetime

INPUT = "scopus_v1_stratified_sample_300.csv"

OUTPUT = "scopus_v1_300_enriched.csv"
UNRESOLVED = "scopus_v1_300_unresolved.csv"
AUDIT = "scopus_v1_300_enrichment_audit.json"

# Optional but strongly recommended:
# put your own email here for polite API identification.
EMAIL = "vinod@keralauniversity.ac.in"

session = requests.Session()
session.headers.update({
    "User-Agent":
        f"AgenticCorrectnessReview/1.0 (mailto:{EMAIL})"
})

# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def clean_doi(doi):
    if not doi:
        return ""

    doi = str(doi).strip()

    doi = re.sub(
        r"^https?://(dx\.)?doi\.org/",
        "",
        doi,
        flags=re.I
    )

    doi = re.sub(
        r"^doi:\s*",
        "",
        doi,
        flags=re.I
    )

    return doi.strip()


def normalize_title(title):
    if not title:
        return ""

    title = title.lower()

    title = re.sub(
        r"[^a-z0-9]+",
        " ",
        title
    )

    return " ".join(title.split())


def similarity(a, b):
    a = normalize_title(a)
    b = normalize_title(b)

    if not a or not b:
        return 0.0

    return SequenceMatcher(
        None, a, b
    ).ratio()


def reconstruct_openalex_abstract(index):
    """
    OpenAlex stores many abstracts as an inverted index.
    Reconstruct the original word sequence.
    """

    if not index:
        return ""

    positions = []

    for word, locs in index.items():
        for loc in locs:
            positions.append((loc, word))

    positions.sort(
        key=lambda x: x[0]
    )

    return " ".join(
        word for _, word in positions
    )


def get_json(url, params=None, attempts=4):

    for attempt in range(1, attempts + 1):

        try:

            r = session.get(
                url,
                params=params,
                timeout=45
            )

            if r.status_code == 200:
                return r.json(), 200

            if r.status_code == 404:
                return None, 404

            if r.status_code == 429 or \
               500 <= r.status_code <= 599:

                wait = min(
                    2 ** attempt,
                    20
                )

                time.sleep(wait)
                continue

            return None, r.status_code

        except requests.RequestException:

            if attempt == attempts:
                return None, -1

            time.sleep(
                min(2 ** attempt, 20)
            )

    return None, -1


# ------------------------------------------------------------
# OPENALEX DOI LOOKUP
# ------------------------------------------------------------

def openalex_by_doi(doi):

    if not doi:
        return None, None

    url = (
        "https://api.openalex.org/"
        "works/https://doi.org/"
        + doi
    )

    params = {}

    if EMAIL != "YOUR_EMAIL_HERE":
        params["mailto"] = EMAIL

    data, status = get_json(
        url,
        params=params
    )

    return data, status


# ------------------------------------------------------------
# OPENALEX TITLE FALLBACK
# ------------------------------------------------------------

def openalex_by_title(title):

    if not title:
        return None, None, 0.0

    url = (
        "https://api.openalex.org/works"
    )

    params = {
        "search": title,
        "per-page": 5
    }

    if EMAIL != "YOUR_EMAIL_HERE":
        params["mailto"] = EMAIL

    data, status = get_json(
        url,
        params=params
    )

    if status != 200 or not data:
        return None, status, 0.0

    candidates = data.get(
        "results", []
    )

    best = None
    best_score = 0.0

    for candidate in candidates:

        candidate_title = (
            candidate.get(
                "display_name"
            )
            or candidate.get("title")
            or ""
        )

        score = similarity(
            title,
            candidate_title
        )

        if score > best_score:
            best = candidate
            best_score = score

    # Conservative threshold.
    # Anything below this remains unresolved.
    if best_score >= 0.90:
        return best, status, best_score

    return None, status, best_score


# ------------------------------------------------------------
# CROSSREF DOI LOOKUP
# ------------------------------------------------------------

def crossref_by_doi(doi):

    if not doi:
        return None, None

    url = (
        "https://api.crossref.org/"
        "works/"
        + doi
    )

    params = {}

    if EMAIL != "YOUR_EMAIL_HERE":
        params["mailto"] = EMAIL

    data, status = get_json(
        url,
        params=params
    )

    if (
        status == 200
        and data
        and "message" in data
    ):
        return data["message"], status

    return None, status


# ------------------------------------------------------------
# LOAD SCOPUS SAMPLE
# ------------------------------------------------------------

with open(
    INPUT,
    "r",
    encoding="utf-8-sig"
) as f:

    reader = csv.DictReader(f)
    rows = list(reader)

print("=" * 72)
print("V1 SAMPLE METADATA ENRICHMENT")
print("=" * 72)

print("Input records:", len(rows))
print()

# ------------------------------------------------------------
# COUNTERS
# ------------------------------------------------------------

stats = {
    "input_records": len(rows),

    "records_with_scopus_doi": 0,

    "openalex_doi_matches": 0,
    "openalex_title_matches": 0,

    "crossref_doi_matches": 0,

    "openalex_abstracts": 0,

    "crossref_abstracts": 0,

    "abstract_available_any_source": 0,

    "unresolved_records": 0,

    "doi_disagreement_count": 0
}

enriched = []
unresolved = []

# ------------------------------------------------------------
# PROCESS RECORDS
# ------------------------------------------------------------

for number, row in enumerate(
    rows,
    start=1
):

    print(
        f"[{number:03d}/{len(rows)}] "
        f"{row.get('title', '')[:70]}"
    )

    scopus_doi = clean_doi(
        row.get("doi")
    )

    if scopus_doi:
        stats[
            "records_with_scopus_doi"
        ] += 1

    # ========================================================
    # OPENALEX
    # ========================================================

    oa = None
    oa_method = ""
    oa_title_similarity = ""

    if scopus_doi:

        oa, oa_status = (
            openalex_by_doi(
                scopus_doi
            )
        )

        if oa:
            oa_method = "DOI"
            stats[
                "openalex_doi_matches"
            ] += 1

    # Fallback to title if DOI absent
    # or DOI lookup failed.
    if not oa:

        oa, oa_status, score = (
            openalex_by_title(
                row.get("title", "")
            )
        )

        oa_title_similarity = (
            f"{score:.4f}"
        )

        if oa:
            oa_method = "TITLE"
            stats[
                "openalex_title_matches"
            ] += 1

    oa_title = ""
    oa_doi = ""
    oa_id = ""
    oa_year = ""
    oa_type = ""
    oa_abstract = ""
    oa_cited_by = ""
    oa_primary_source = ""

    if oa:

        oa_title = (
            oa.get("display_name")
            or oa.get("title")
            or ""
        )

        oa_doi = clean_doi(
            oa.get("doi")
        )

        oa_id = (
            oa.get("id") or ""
        )

        oa_year = (
            oa.get(
                "publication_year"
            )
            or ""
        )

        oa_type = (
            oa.get("type") or ""
        )

        oa_cited_by = (
            oa.get(
                "cited_by_count"
            )
            or 0
        )

        oa_abstract = (
            reconstruct_openalex_abstract(
                oa.get(
                    "abstract_inverted_index"
                )
            )
        )

        if oa_abstract:
            stats[
                "openalex_abstracts"
            ] += 1

        primary = (
            oa.get(
                "primary_location"
            )
            or {}
        )

        source = (
            primary.get("source")
            or {}
        )

        oa_primary_source = (
            source.get(
                "display_name"
            )
            or ""
        )

    # ========================================================
    # CROSSREF
    # ========================================================

    cr = None
    cr_status = None

    if scopus_doi:

        cr, cr_status = (
            crossref_by_doi(
                scopus_doi
            )
        )

    cr_title = ""
    cr_doi = ""
    cr_type = ""
    cr_publisher = ""
    cr_container = ""
    cr_abstract = ""

    if cr:

        stats[
            "crossref_doi_matches"
        ] += 1

        titles = cr.get(
            "title", []
        )

        if titles:
            cr_title = titles[0]

        cr_doi = clean_doi(
            cr.get("DOI")
        )

        cr_type = (
            cr.get("type") or ""
        )

        cr_publisher = (
            cr.get("publisher")
            or ""
        )

        containers = cr.get(
            "container-title",
            []
        )

        if containers:
            cr_container = (
                containers[0]
            )

        cr_abstract = (
            cr.get("abstract")
            or ""
        )

        if cr_abstract:
            stats[
                "crossref_abstracts"
            ] += 1

    # ========================================================
    # DOI CONSISTENCY
    # ========================================================

    doi_disagreement = ""

    if (
        scopus_doi
        and oa_doi
        and scopus_doi.lower()
            != oa_doi.lower()
    ):
        doi_disagreement = (
            "SCOPUS_OPENALEX"
        )

        stats[
            "doi_disagreement_count"
        ] += 1

    if (
        scopus_doi
        and cr_doi
        and scopus_doi.lower()
            != cr_doi.lower()
    ):

        if doi_disagreement:
            doi_disagreement += (
                ";SCOPUS_CROSSREF"
            )
        else:
            doi_disagreement = (
                "SCOPUS_CROSSREF"
            )

        stats[
            "doi_disagreement_count"
        ] += 1

    # ========================================================
    # ABSTRACT SELECTION
    # ========================================================

    # We do not merge text from different sources.
    # OpenAlex preferred simply because its abstract
    # representation is already normalized plain text.

    selected_abstract = ""
    abstract_source = ""

    if oa_abstract:

        selected_abstract = (
            oa_abstract
        )

        abstract_source = (
            "OPENALEX"
        )

    elif cr_abstract:

        selected_abstract = (
            cr_abstract
        )

        abstract_source = (
            "CROSSREF"
        )

    if selected_abstract:

        stats[
            "abstract_available_any_source"
        ] += 1

    # ========================================================
    # CREATE ENRICHED ROW
    # ========================================================

    new_row = dict(row)

    new_row.update({

        "normalized_scopus_doi":
            scopus_doi,

        "openalex_match_method":
            oa_method,

        "openalex_title_similarity":
            oa_title_similarity,

        "openalex_id":
            oa_id,

        "openalex_doi":
            oa_doi,

        "openalex_title":
            oa_title,

        "openalex_year":
            oa_year,

        "openalex_type":
            oa_type,

        "openalex_primary_source":
            oa_primary_source,

        "openalex_cited_by":
            oa_cited_by,

        "openalex_abstract":
            oa_abstract,

        "crossref_doi":
            cr_doi,

        "crossref_title":
            cr_title,

        "crossref_type":
            cr_type,

        "crossref_publisher":
            cr_publisher,

        "crossref_container":
            cr_container,

        "crossref_abstract":
            cr_abstract,

        "doi_disagreement":
            doi_disagreement,

        "selected_abstract":
            selected_abstract,

        "abstract_source":
            abstract_source,

        # Screening fields intentionally blank.
        "screen_decision":
            "",

        "exclusion_reason":
            "",

        "evidence_codes":
            "",

        "screening_notes":
            ""
    })

    enriched.append(new_row)

    # A record is unresolved for screening
    # if no abstract was recovered.
    if not selected_abstract:

        unresolved.append(
            new_row
        )

    # Conservative pacing
    time.sleep(0.08)

# ------------------------------------------------------------
# WRITE ENRICHED CSV
# ------------------------------------------------------------

fieldnames = list(
    enriched[0].keys()
)

with open(
    OUTPUT,
    "w",
    newline="",
    encoding="utf-8-sig"
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=fieldnames
    )

    writer.writeheader()
    writer.writerows(enriched)

# ------------------------------------------------------------
# WRITE UNRESOLVED CSV
# ------------------------------------------------------------

with open(
    UNRESOLVED,
    "w",
    newline="",
    encoding="utf-8-sig"
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=fieldnames
    )

    writer.writeheader()
    writer.writerows(unresolved)

stats[
    "unresolved_records"
] = len(unresolved)

# ------------------------------------------------------------
# AUDIT
# ------------------------------------------------------------

audit = {

    "pipeline":
        "SCOPUS_V1_300_ENRICHMENT_V1",

    "timestamp":
        datetime.now().isoformat(),

    "input":
        INPUT,

    "input_sample_design":
        (
            "300-record reproducible random "
            "sample from 4,610 Scopus V1 results"
        ),

    "sources":
        [
            "Scopus STANDARD metadata",
            "OpenAlex API",
            "Crossref REST API"
        ],

    "matching_policy": {

        "primary":
            "DOI exact lookup",

        "fallback":
            (
                "OpenAlex title search with "
                "normalized-title similarity >= 0.90"
            ),

        "crossref":
            "Exact DOI lookup only"
    },

    "abstract_policy":
        (
            "OpenAlex abstract preferred; "
            "Crossref abstract used only when "
            "OpenAlex abstract unavailable. "
            "No synthetic abstracts."
        ),

    "statistics":
        stats
}

with open(
    AUDIT,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        audit,
        f,
        ensure_ascii=False,
        indent=2
    )

# ------------------------------------------------------------
# SUMMARY
# ------------------------------------------------------------

print()
print("=" * 72)
print("ENRICHMENT COMPLETE")
print("=" * 72)

for key, value in stats.items():
    print(
        f"{key:35s}: {value}"
    )

print()
print("Files saved")
print("-" * 72)

print(OUTPUT)
print(UNRESOLVED)
print(AUDIT)

print()
print("IMPORTANT:")
print(
    "Do not manually classify unresolved records yet."
)

print(
    "Upload the enriched CSV and audit JSON for "
    "the evidence-screening stage."
)

print("\nDONE.")