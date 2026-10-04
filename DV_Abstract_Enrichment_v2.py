import os
import re
import json
import time
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import requests

# ============================================================
# CONFIGURATION
# ============================================================

CANDIDATE_FILE = Path("DV_HighSensitivity_Candidates_v1.csv")
REVIEW_FILE = Path("DV_Review_Novelty_Set_v1.csv")

OUTPUT_MASTER = Path("DV_Abstract_Enriched_Master_v2.csv")
OUTPUT_UNRESOLVED = Path("DV_Abstract_Unresolved_v2.csv")
OUTPUT_AUDIT = Path("DV_Abstract_Enrichment_Audit_v2.json")
CACHE_FILE = Path("DV_Abstract_Enrichment_Cache_v2.json")

SCOPUS_API_KEY = os.getenv("SCOPUS_API_KEY")

# Optional but recommended.
# Example:
# $env:OPENALEX_EMAIL="your_email@institution.edu"
OPENALEX_EMAIL = os.getenv("OPENALEX_EMAIL", "").strip()

SCOPUS_ABSTRACT_BASE = (
    "https://api.elsevier.com/content/abstract"
)

OPENALEX_BASE = "https://api.openalex.org/works"
CROSSREF_BASE = "https://api.crossref.org/works"

TIMEOUT = 30
MAX_RETRIES = 4
REQUEST_DELAY = 0.20

# ============================================================
# CHECK INPUTS
# ============================================================

for p in [CANDIDATE_FILE, REVIEW_FILE]:
    if not p.exists():
        raise FileNotFoundError(
            f"Missing required file: {p.resolve()}"
        )

# ============================================================
# HELPERS
# ============================================================

def clean(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def normalize_doi(doi):
    doi = clean(doi).lower()

    doi = re.sub(
        r"^https?://(dx\.)?doi\.org/",
        "",
        doi
    )

    doi = re.sub(
        r"^doi:\s*",
        "",
        doi
    )

    return doi.strip()


def normalize_title(title):
    title = clean(title).lower()
    title = re.sub(r"<[^>]+>", " ", title)
    title = re.sub(r"[^\w\s]", " ", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip()


def clean_abstract(text):
    text = clean(text)

    if not text:
        return ""

    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def request_with_retry(
    session,
    method,
    url,
    **kwargs
):
    last_error = None

    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):
        try:
            r = session.request(
                method,
                url,
                timeout=TIMEOUT,
                **kwargs
            )

            if r.status_code == 200:
                return r

            if r.status_code in (
                404,
                401,
                403
            ):
                return r

            if r.status_code == 429:
                wait = min(
                    2 ** attempt,
                    30
                )
                print(
                    f"  Rate limited; "
                    f"waiting {wait}s"
                )
                time.sleep(wait)
                continue

            if 500 <= r.status_code < 600:
                wait = min(
                    2 ** attempt,
                    30
                )
                time.sleep(wait)
                continue

            return r

        except requests.RequestException as e:
            last_error = str(e)

            if attempt < MAX_RETRIES:
                time.sleep(
                    min(2 ** attempt, 30)
                )

    raise RuntimeError(
        f"Request failed: {last_error}"
    )


# ============================================================
# LOAD + UNION
# ============================================================

candidates = pd.read_csv(
    CANDIDATE_FILE,
    dtype=str
).fillna("")

reviews = pd.read_csv(
    REVIEW_FILE,
    dtype=str
).fillna("")

print("=" * 78)
print("DECISION-VALIDITY ABSTRACT ENRICHMENT v2")
print("=" * 78)

print(
    f"Candidate input: {len(candidates)}"
)
print(
    f"Review input:    {len(reviews)}"
)

candidates["_candidate_source"] = "1"
reviews["_review_source"] = "1"

combined = pd.concat(
    [candidates, reviews],
    ignore_index=True,
    sort=False
).fillna("")

combined["_doi_norm"] = (
    combined["doi"]
    .apply(normalize_doi)
)

combined["_title_norm"] = (
    combined["title"]
    .apply(normalize_title)
)

# ============================================================
# DEDUPLICATE
#
# DOI first.
# EID second.
# Normalized title third.
# ============================================================

def dedupe_key(row):
    doi = row["_doi_norm"]
    eid = clean(row.get("eid", ""))
    title = row["_title_norm"]

    if doi:
        return "DOI:" + doi

    if eid:
        return "EID:" + eid

    return "TITLE:" + title


combined["_dedupe_key"] = combined.apply(
    dedupe_key,
    axis=1
)

# Preserve whether a record came from candidate/review set.
grouped_rows = []

for key, group in combined.groupby(
    "_dedupe_key",
    sort=False
):
    row = group.iloc[0].copy()

    row["in_candidate_set"] = int(
        "_candidate_source"
        in group.columns
        and
        (group["_candidate_source"] == "1").any()
    )

    row["in_novelty_review_set"] = int(
        "_review_source"
        in group.columns
        and
        (group["_review_source"] == "1").any()
    )

    grouped_rows.append(row)

master = pd.DataFrame(
    grouped_rows
).fillna("")

print(
    f"Unique union:    {len(master)}"
)

# ============================================================
# CACHE
# ============================================================

if CACHE_FILE.exists():
    try:
        with open(
            CACHE_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            cache = json.load(f)
    except Exception:
        cache = {}
else:
    cache = {}


def save_cache():
    with open(
        CACHE_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            cache,
            f,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# SESSIONS
# ============================================================

scopus_session = requests.Session()

if SCOPUS_API_KEY:
    scopus_session.headers.update({
        "X-ELS-APIKey":
            SCOPUS_API_KEY,
        "Accept":
            "application/json"
    })

oa_session = requests.Session()
oa_session.headers.update({
    "User-Agent":
        "DV-Systematic-Review/2.0"
})

crossref_session = requests.Session()

cr_agent = (
    "DV-Systematic-Review/2.0"
)

if OPENALEX_EMAIL:
    cr_agent += (
        f" (mailto:{OPENALEX_EMAIL})"
    )

crossref_session.headers.update({
    "User-Agent": cr_agent
})

# ============================================================
# SCOPUS ABSTRACT RETRIEVAL
# ============================================================

def scopus_abstract(eid, doi):
    if not SCOPUS_API_KEY:
        return {
            "status":
                "NO_API_KEY"
        }

    identifiers = []

    if eid:
        identifiers.append(
            ("eid", eid)
        )

    if doi:
        identifiers.append(
            ("doi", doi)
        )

    for kind, identifier in identifiers:

        if kind == "eid":
            url = (
                f"{SCOPUS_ABSTRACT_BASE}"
                f"/eid/{identifier}"
            )
        else:
            url = (
                f"{SCOPUS_ABSTRACT_BASE}"
                f"/doi/{identifier}"
            )

        r = request_with_retry(
            scopus_session,
            "GET",
            url,
            params={
                "view": "FULL"
            }
        )

        if r.status_code == 401:
            return {
                "status":
                    "AUTHORIZATION_ERROR"
            }

        if r.status_code == 403:
            return {
                "status":
                    "FORBIDDEN"
            }

        if r.status_code != 200:
            continue

        try:
            data = r.json()
        except Exception:
            continue

        response = (
            data
            .get(
                "abstracts-retrieval-response",
                {}
            )
        )

        core = response.get(
            "coredata",
            {}
        )

        abstract = clean_abstract(
            core.get(
                "dc:description",
                ""
            )
        )

        retrieved_doi = normalize_doi(
            core.get(
                "prism:doi",
                ""
            )
        )

        if abstract:
            return {
                "status": "FOUND",
                "abstract": abstract,
                "doi": retrieved_doi,
                "identifier_used":
                    kind
            }

    return {
        "status":
            "NOT_FOUND"
    }


# ============================================================
# OPENALEX
# ============================================================

def reconstruct_openalex_abstract(
    inverted
):
    if not inverted:
        return ""

    positions = []

    for word, locs in inverted.items():
        for pos in locs:
            positions.append(
                (int(pos), word)
            )

    positions.sort(
        key=lambda x: x[0]
    )

    return clean_abstract(
        " ".join(
            word
            for _, word in positions
        )
    )


def openalex_by_doi(doi):
    if not doi:
        return None

    url = (
        OPENALEX_BASE
        + "/https://doi.org/"
        + doi
    )

    params = {}

    if OPENALEX_EMAIL:
        params["mailto"] = (
            OPENALEX_EMAIL
        )

    r = request_with_retry(
        oa_session,
        "GET",
        url,
        params=params
    )

    if r.status_code != 200:
        return None

    try:
        work = r.json()
    except Exception:
        return None

    abstract = (
        reconstruct_openalex_abstract(
            work.get(
                "abstract_inverted_index"
            )
        )
    )

    if not abstract:
        return None

    oa_doi = normalize_doi(
        work.get("doi", "")
    )

    return {
        "abstract": abstract,
        "doi": oa_doi,
        "openalex_id":
            clean(work.get("id", ""))
    }


# ============================================================
# CROSSREF
# ============================================================

def crossref_by_doi(doi):
    if not doi:
        return None

    url = (
        CROSSREF_BASE
        + "/"
        + doi
    )

    r = request_with_retry(
        crossref_session,
        "GET",
        url
    )

    if r.status_code != 200:
        return None

    try:
        message = (
            r.json()
            .get(
                "message",
                {}
            )
        )
    except Exception:
        return None

    abstract = clean_abstract(
        message.get(
            "abstract",
            ""
        )
    )

    if not abstract:
        return None

    cr_doi = normalize_doi(
        message.get(
            "DOI",
            ""
        )
    )

    return {
        "abstract": abstract,
        "doi": cr_doi
    }


# ============================================================
# ENRICH
# ============================================================

results = []

stats = {
    "cache_hit": 0,
    "scopus_abstract": 0,
    "openalex_abstract": 0,
    "crossref_abstract": 0,
    "unresolved": 0,
    "scopus_auth_error": 0,
    "doi_disagreement": 0
}

scopus_disabled = False

for i, row in master.iterrows():

    eid = clean(
        row.get(
            "eid",
            ""
        )
    )

    doi = normalize_doi(
        row.get(
            "doi",
            ""
        )
    )

    title = clean(
        row.get(
            "title",
            ""
        )
    )

    cache_key = (
        doi
        if doi
        else (
            eid
            if eid
            else normalize_title(title)
        )
    )

    print(
        f"[{i + 1}/{len(master)}] "
        f"{title[:70]}"
    )

    if cache_key in cache:
        enriched = cache[
            cache_key
        ].copy()

        stats["cache_hit"] += 1

    else:
        enriched = {
            "abstract": "",
            "abstract_source": "",
            "retrieved_doi": "",
            "retrieval_status":
                "UNRESOLVED",
            "doi_disagreement": 0
        }

        # --------------------------------
        # 1. SCOPUS
        # --------------------------------

        if not scopus_disabled:

            s = scopus_abstract(
                eid,
                doi
            )

            if s.get(
                "status"
            ) == "FOUND":

                enriched[
                    "abstract"
                ] = s[
                    "abstract"
                ]

                enriched[
                    "abstract_source"
                ] = "SCOPUS"

                enriched[
                    "retrieved_doi"
                ] = s.get(
                    "doi",
                    ""
                )

                enriched[
                    "retrieval_status"
                ] = "RESOLVED"

                stats[
                    "scopus_abstract"
                ] += 1

            elif s.get(
                "status"
            ) in (
                "AUTHORIZATION_ERROR",
                "FORBIDDEN"
            ):

                stats[
                    "scopus_auth_error"
                ] += 1

                # Avoid hundreds of known-failing
                # Scopus abstract calls.
                scopus_disabled = True

                print(
                    "  Scopus Abstract "
                    "Retrieval unavailable; "
                    "disabling for remainder."
                )

        # --------------------------------
        # 2. OPENALEX
        # --------------------------------

        if not enriched["abstract"]:

            oa = openalex_by_doi(
                doi
            )

            if oa:

                enriched[
                    "abstract"
                ] = oa[
                    "abstract"
                ]

                enriched[
                    "abstract_source"
                ] = "OPENALEX"

                enriched[
                    "retrieved_doi"
                ] = oa.get(
                    "doi",
                    ""
                )

                enriched[
                    "retrieval_status"
                ] = "RESOLVED"

                stats[
                    "openalex_abstract"
                ] += 1

        # --------------------------------
        # 3. CROSSREF
        # --------------------------------

        if not enriched["abstract"]:

            cr = crossref_by_doi(
                doi
            )

            if cr:

                enriched[
                    "abstract"
                ] = cr[
                    "abstract"
                ]

                enriched[
                    "abstract_source"
                ] = "CROSSREF"

                enriched[
                    "retrieved_doi"
                ] = cr.get(
                    "doi",
                    ""
                )

                enriched[
                    "retrieval_status"
                ] = "RESOLVED"

                stats[
                    "crossref_abstract"
                ] += 1

        # --------------------------------
        # DOI disagreement
        # --------------------------------

        retrieved_doi = normalize_doi(
            enriched.get(
                "retrieved_doi",
                ""
            )
        )

        if (
            doi
            and retrieved_doi
            and doi != retrieved_doi
        ):
            enriched[
                "doi_disagreement"
            ] = 1

            stats[
                "doi_disagreement"
            ] += 1

        if not enriched["abstract"]:
            stats[
                "unresolved"
            ] += 1

        cache[
            cache_key
        ] = enriched

        if (
            (i + 1) % 10 == 0
        ):
            save_cache()

        time.sleep(
            REQUEST_DELAY
        )

    result_row = row.to_dict()

    result_row.update(
        enriched
    )

    results.append(
        result_row
    )

save_cache()

# ============================================================
# OUTPUT
# ============================================================

out = pd.DataFrame(
    results
).fillna("")

# Remove internal helper columns.
drop_cols = [
    "_candidate_source",
    "_review_source",
    "_doi_norm",
    "_title_norm",
    "_dedupe_key"
]

for c in drop_cols:
    if c in out.columns:
        out = out.drop(
            columns=[c]
        )

out.to_csv(
    OUTPUT_MASTER,
    index=False,
    encoding="utf-8-sig"
)

unresolved = out[
    out["abstract"]
    .astype(str)
    .str.strip()
    .eq("")
].copy()

unresolved.to_csv(
    OUTPUT_UNRESOLVED,
    index=False,
    encoding="utf-8-sig"
)

# ============================================================
# FINAL AUDIT
# ============================================================

abstract_source_counts = (
    out[
        "abstract_source"
    ]
    .replace(
        "",
        "UNRESOLVED"
    )
    .value_counts()
    .to_dict()
)

audit = {
    "pipeline":
        "Decision Validity Abstract Enrichment v2",

    "timestamp_utc":
        datetime.now(
            timezone.utc
        ).isoformat(),

    "candidate_input_records":
        int(len(candidates)),

    "novelty_review_input_records":
        int(len(reviews)),

    "combined_before_dedup":
        int(
            len(candidates)
            + len(reviews)
        ),

    "unique_union_after_dedup":
        int(len(master)),

    "records_with_abstract":
        int(
            (
                out["abstract"]
                .astype(str)
                .str.strip()
                != ""
            ).sum()
        ),

    "unresolved_records":
        int(len(unresolved)),

    "abstract_source_counts":
        {
            str(k): int(v)
            for k, v
            in abstract_source_counts.items()
        },

    "doi_disagreements":
        int(
            pd.to_numeric(
                out[
                    "doi_disagreement"
                ],
                errors="coerce"
            )
            .fillna(0)
            .sum()
        ),

    "scopus_abstract_retrieval_disabled":
        bool(scopus_disabled),

    "source_priority": [
        "Scopus Abstract Retrieval",
        "OpenAlex DOI",
        "Crossref DOI"
    ],

    "synthetic_abstracts":
        False,

    "eligibility_decisions":
        "NONE",

    "outputs": {
        "enriched_master":
            str(OUTPUT_MASTER),
        "unresolved":
            str(OUTPUT_UNRESOLVED),
        "cache":
            str(CACHE_FILE)
    },

    "corpus_status":
        "NOT_FROZEN"
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
# REPORT
# ============================================================

print()
print("=" * 78)
print("ENRICHMENT COMPLETE")
print("=" * 78)

print(
    f"Unique union:       "
    f"{len(master)}"
)

print(
    f"Abstract available: "
    f"{audit['records_with_abstract']}"
)

print(
    f"Unresolved:         "
    f"{len(unresolved)}"
)

print(
    f"DOI disagreements:  "
    f"{audit['doi_disagreements']}"
)

print("\nAbstract sources:")

for source, n in (
    abstract_source_counts.items()
):
    print(
        f"  {source:15s} {n}"
    )

print("\nFiles created:")
print(f"  {OUTPUT_MASTER}")
print(f"  {OUTPUT_UNRESOLVED}")
print(f"  {OUTPUT_AUDIT}")
print(f"  {CACHE_FILE}")

print()
print(
    "No study has been automatically "
    "included or excluded."
)