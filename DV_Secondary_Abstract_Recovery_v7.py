import os
import re
import json
import time
import html
from pathlib import Path
from datetime import datetime, timezone
from difflib import SequenceMatcher

import pandas as pd
import requests

# ============================================================
# INPUT / OUTPUT
# ============================================================

INPUT = Path("DV_Abstract_Unresolved_v2.csv")

OUT_MASTER = Path(
    "DV_Secondary_Abstract_Recovery_Master_v7.csv"
)

OUT_RECOVERED = Path(
    "DV_Secondary_Abstract_Recovered_v7.csv"
)

OUT_UNRESOLVED = Path(
    "DV_Still_Unresolved_v7.csv"
)

OUT_AUDIT = Path(
    "DV_Secondary_Abstract_Recovery_Audit_v7.json"
)

CACHE_FILE = Path(
    "DV_Secondary_Abstract_Recovery_Cache_v7.json"
)

if not INPUT.exists():
    raise FileNotFoundError(INPUT.resolve())

df = pd.read_csv(INPUT, dtype=str).fillna("")

print("=" * 78)
print("DECISION VALIDITY SECONDARY ABSTRACT RECOVERY v7")
print("=" * 78)
print("Input unresolved records:", len(df))

# ============================================================
# CONFIGURATION
# ============================================================

OPENALEX_EMAIL = os.getenv(
    "OPENALEX_EMAIL", ""
).strip()

USER_AGENT = (
    "DecisionValiditySystematicReview/1.0"
)

if OPENALEX_EMAIL:
    USER_AGENT += f" mailto:{OPENALEX_EMAIL}"

session = requests.Session()

session.headers.update({
    "User-Agent": USER_AGENT
})

TIMEOUT = 30

# Conservative matching.
OA_TITLE_THRESHOLD = 0.92
CR_TITLE_THRESHOLD = 0.94

# ============================================================
# CACHE
# ============================================================

if CACHE_FILE.exists():
    try:
        cache = json.loads(
            CACHE_FILE.read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        cache = {}
else:
    cache = {}


def save_cache():
    CACHE_FILE.write_text(
        json.dumps(
            cache,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

# ============================================================
# NORMALIZATION
# ============================================================

def clean_doi(x):
    x = str(x).strip().lower()

    x = re.sub(
        r"^https?://(dx\.)?doi\.org/",
        "",
        x
    )

    x = re.sub(
        r"^doi:\s*",
        "",
        x
    )

    return x.strip()


def norm_title(x):
    x = html.unescape(str(x))
    x = x.lower()

    x = re.sub(
        r"<[^>]+>",
        " ",
        x
    )

    x = re.sub(
        r"[^a-z0-9]+",
        " ",
        x
    )

    return re.sub(
        r"\s+",
        " ",
        x
    ).strip()


def title_similarity(a, b):
    a = norm_title(a)
    b = norm_title(b)

    if not a or not b:
        return 0.0

    return SequenceMatcher(
        None, a, b
    ).ratio()


def clean_abstract(x):
    if not x:
        return ""

    x = html.unescape(str(x))

    x = re.sub(
        r"<[^>]+>",
        " ",
        x
    )

    x = re.sub(
        r"\s+",
        " ",
        x
    )

    return x.strip()


# ============================================================
# OPENALEX ABSTRACT RECONSTRUCTION
# ============================================================

def reconstruct_oa_abstract(inv):
    if not inv:
        return ""

    positions = []

    for word, indexes in inv.items():
        for idx in indexes:
            positions.append(
                (idx, word)
            )

    positions.sort(
        key=lambda x: x[0]
    )

    return " ".join(
        word for _, word in positions
    )


# ============================================================
# OPENALEX DOI
# ============================================================

def openalex_by_doi(doi):
    if not doi:
        return None

    key = f"oa_doi::{doi}"

    if key in cache:
        return cache[key]

    url = (
        "https://api.openalex.org/works/"
        f"https://doi.org/{doi}"
    )

    params = {}

    if OPENALEX_EMAIL:
        params["mailto"] = OPENALEX_EMAIL

    try:
        r = session.get(
            url,
            params=params,
            timeout=TIMEOUT
        )

        if r.status_code == 200:
            data = r.json()

            result = {
                "status": "FOUND",
                "doi": clean_doi(
                    data.get("doi", "")
                ),
                "title": data.get(
                    "display_name", ""
                ),
                "abstract":
                    reconstruct_oa_abstract(
                        data.get(
                            "abstract_inverted_index"
                        )
                    )
            }

        else:
            result = {
                "status":
                    f"HTTP_{r.status_code}"
            }

    except Exception as e:
        result = {
            "status": "ERROR",
            "error": str(e)
        }

    cache[key] = result
    save_cache()

    time.sleep(0.12)

    return result


# ============================================================
# OPENALEX TITLE SEARCH
# ============================================================

def openalex_by_title(title):
    if not title:
        return None

    nt = norm_title(title)

    key = f"oa_title::{nt}"

    if key in cache:
        return cache[key]

    params = {
        "search": title,
        "per-page": 5
    }

    if OPENALEX_EMAIL:
        params["mailto"] = OPENALEX_EMAIL

    try:
        r = session.get(
            "https://api.openalex.org/works",
            params=params,
            timeout=TIMEOUT
        )

        if r.status_code != 200:
            result = {
                "status":
                    f"HTTP_{r.status_code}"
            }

        else:
            candidates = []

            for item in (
                r.json().get(
                    "results", []
                )
            ):

                candidate_title = (
                    item.get(
                        "display_name", ""
                    )
                )

                score = title_similarity(
                    title,
                    candidate_title
                )

                candidates.append({
                    "score": score,
                    "title":
                        candidate_title,
                    "doi":
                        clean_doi(
                            item.get(
                                "doi", ""
                            )
                        ),
                    "abstract":
                        reconstruct_oa_abstract(
                            item.get(
                                "abstract_inverted_index"
                            )
                        )
                })

            candidates.sort(
                key=lambda x: x["score"],
                reverse=True
            )

            if candidates:
                best = candidates[0]

                result = {
                    "status": "FOUND",
                    **best
                }

            else:
                result = {
                    "status": "NOT_FOUND"
                }

    except Exception as e:
        result = {
            "status": "ERROR",
            "error": str(e)
        }

    cache[key] = result
    save_cache()

    time.sleep(0.15)

    return result


# ============================================================
# CROSSREF DOI
# ============================================================

def crossref_by_doi(doi):
    if not doi:
        return None

    key = f"cr_doi::{doi}"

    if key in cache:
        return cache[key]

    url = (
        "https://api.crossref.org/works/"
        + requests.utils.quote(
            doi,
            safe=""
        )
    )

    params = {}

    if OPENALEX_EMAIL:
        params["mailto"] = OPENALEX_EMAIL

    try:
        r = session.get(
            url,
            params=params,
            timeout=TIMEOUT
        )

        if r.status_code == 200:

            msg = r.json().get(
                "message", {}
            )

            titles = msg.get(
                "title", []
            )

            result = {
                "status": "FOUND",
                "doi": clean_doi(
                    msg.get("DOI", "")
                ),
                "title":
                    titles[0]
                    if titles else "",
                "abstract":
                    clean_abstract(
                        msg.get(
                            "abstract", ""
                        )
                    )
            }

        else:
            result = {
                "status":
                    f"HTTP_{r.status_code}"
            }

    except Exception as e:
        result = {
            "status": "ERROR",
            "error": str(e)
        }

    cache[key] = result
    save_cache()

    time.sleep(0.12)

    return result


# ============================================================
# CROSSREF BIBLIOGRAPHIC TITLE SEARCH
# ============================================================

def crossref_by_title(title):
    if not title:
        return None

    nt = norm_title(title)

    key = f"cr_title::{nt}"

    if key in cache:
        return cache[key]

    params = {
        "query.bibliographic":
            title,
        "rows": 5,
        "select":
            "DOI,title,abstract"
    }

    if OPENALEX_EMAIL:
        params["mailto"] = OPENALEX_EMAIL

    try:
        r = session.get(
            "https://api.crossref.org/works",
            params=params,
            timeout=TIMEOUT
        )

        if r.status_code != 200:
            result = {
                "status":
                    f"HTTP_{r.status_code}"
            }

        else:
            items = (
                r.json()
                .get("message", {})
                .get("items", [])
            )

            candidates = []

            for item in items:

                titles = item.get(
                    "title", []
                )

                candidate_title = (
                    titles[0]
                    if titles
                    else ""
                )

                candidates.append({
                    "score":
                        title_similarity(
                            title,
                            candidate_title
                        ),
                    "title":
                        candidate_title,
                    "doi":
                        clean_doi(
                            item.get(
                                "DOI", ""
                            )
                        ),
                    "abstract":
                        clean_abstract(
                            item.get(
                                "abstract", ""
                            )
                        )
                })

            candidates.sort(
                key=lambda x: x["score"],
                reverse=True
            )

            if candidates:
                result = {
                    "status": "FOUND",
                    **candidates[0]
                }
            else:
                result = {
                    "status": "NOT_FOUND"
                }

    except Exception as e:
        result = {
            "status": "ERROR",
            "error": str(e)
        }

    cache[key] = result
    save_cache()

    time.sleep(0.15)

    return result


# ============================================================
# RECOVERY
# ============================================================

records = []

for n, (_, row) in enumerate(
    df.iterrows(),
    start=1
):

    title = row.get(
        "title", ""
    ).strip()

    doi = clean_doi(
        row.get("doi", "")
    )

    recovered_abstract = ""
    recovered_source = ""
    match_method = ""
    match_score = ""
    recovered_doi = ""
    recovered_title = ""

    attempts = []

    # --------------------------------------------------------
    # 1. OPENALEX DOI
    # --------------------------------------------------------

    if doi:

        result = openalex_by_doi(
            doi
        )

        attempts.append(
            "OPENALEX_DOI"
        )

        if (
            result
            and result.get("status")
            == "FOUND"
            and result.get(
                "abstract", ""
            ).strip()
        ):

            recovered_abstract = (
                result["abstract"]
            )

            recovered_source = (
                "OPENALEX"
            )

            match_method = (
                "DOI_EXACT"
            )

            match_score = 1.0

            recovered_doi = (
                result.get(
                    "doi", ""
                )
            )

            recovered_title = (
                result.get(
                    "title", ""
                )
            )

    # --------------------------------------------------------
    # 2. CROSSREF DOI
    # --------------------------------------------------------

    if not recovered_abstract and doi:

        result = crossref_by_doi(
            doi
        )

        attempts.append(
            "CROSSREF_DOI"
        )

        if (
            result
            and result.get("status")
            == "FOUND"
            and result.get(
                "abstract", ""
            ).strip()
        ):

            recovered_abstract = (
                result["abstract"]
            )

            recovered_source = (
                "CROSSREF"
            )

            match_method = (
                "DOI_EXACT"
            )

            match_score = 1.0

            recovered_doi = (
                result.get(
                    "doi", ""
                )
            )

            recovered_title = (
                result.get(
                    "title", ""
                )
            )

    # --------------------------------------------------------
    # 3. OPENALEX TITLE FALLBACK
    # --------------------------------------------------------

    if not recovered_abstract and title:

        result = openalex_by_title(
            title
        )

        attempts.append(
            "OPENALEX_TITLE"
        )

        if (
            result
            and result.get("status")
            == "FOUND"
        ):

            score = float(
                result.get(
                    "score", 0
                )
            )

            if (
                score >=
                OA_TITLE_THRESHOLD
                and result.get(
                    "abstract", ""
                ).strip()
            ):

                recovered_abstract = (
                    result["abstract"]
                )

                recovered_source = (
                    "OPENALEX"
                )

                match_method = (
                    "TITLE_FALLBACK"
                )

                match_score = score

                recovered_doi = (
                    result.get(
                        "doi", ""
                    )
                )

                recovered_title = (
                    result.get(
                        "title", ""
                    )
                )

    # --------------------------------------------------------
    # 4. CROSSREF TITLE FALLBACK
    # --------------------------------------------------------

    if not recovered_abstract and title:

        result = crossref_by_title(
            title
        )

        attempts.append(
            "CROSSREF_TITLE"
        )

        if (
            result
            and result.get("status")
            == "FOUND"
        ):

            score = float(
                result.get(
                    "score", 0
                )
            )

            if (
                score >=
                CR_TITLE_THRESHOLD
                and result.get(
                    "abstract", ""
                ).strip()
            ):

                recovered_abstract = (
                    result["abstract"]
                )

                recovered_source = (
                    "CROSSREF"
                )

                match_method = (
                    "TITLE_FALLBACK"
                )

                match_score = score

                recovered_doi = (
                    result.get(
                        "doi", ""
                    )
                )

                recovered_title = (
                    result.get(
                        "title", ""
                    )
                )

    # --------------------------------------------------------
    # DOI CONSISTENCY
    # --------------------------------------------------------

    doi_disagreement = 0

    if (
        doi
        and recovered_doi
        and clean_doi(doi)
        != clean_doi(
            recovered_doi
        )
    ):
        doi_disagreement = 1

    # A title fallback with DOI disagreement is not
    # automatically rejected; it is explicitly flagged
    # for human verification.

    status = (
        "RECOVERED"
        if recovered_abstract
        else "UNRESOLVED"
    )

    newrow = row.to_dict()

    newrow.update({
        "secondary_abstract":
            recovered_abstract,

        "secondary_source":
            recovered_source,

        "secondary_match_method":
            match_method,

        "secondary_match_score":
            match_score,

        "secondary_retrieved_doi":
            recovered_doi,

        "secondary_retrieved_title":
            recovered_title,

        "doi_disagreement":
            doi_disagreement,

        "secondary_status":
            status,

        "retrieval_attempts":
            ";".join(attempts),

        "manual_eligibility":
            "",

        "manual_notes":
            ""
    })

    records.append(newrow)

    print(
        f"[{n:03d}/{len(df):03d}] "
        f"{status:10s} "
        f"{recovered_source:10s} "
        f"{title[:55]}"
    )

# ============================================================
# OUTPUTS
# ============================================================

master = pd.DataFrame(
    records
)

recovered = master[
    master["secondary_status"]
    == "RECOVERED"
].copy()

unresolved = master[
    master["secondary_status"]
    == "UNRESOLVED"
].copy()

master.to_csv(
    OUT_MASTER,
    index=False,
    encoding="utf-8-sig"
)

recovered.to_csv(
    OUT_RECOVERED,
    index=False,
    encoding="utf-8-sig"
)

unresolved.to_csv(
    OUT_UNRESOLVED,
    index=False,
    encoding="utf-8-sig"
)

# ============================================================
# AUDIT
# ============================================================

source_counts = (
    recovered[
        "secondary_source"
    ]
    .value_counts()
    .to_dict()
)

method_counts = (
    recovered[
        "secondary_match_method"
    ]
    .value_counts()
    .to_dict()
)

audit = {

    "pipeline":
        "DV Secondary Abstract Recovery v7",

    "timestamp_utc":
        datetime.now(
            timezone.utc
        ).isoformat(),

    "input_file":
        str(INPUT),

    "input_unresolved_records":
        int(len(df)),

    "recovered_records":
        int(len(recovered)),

    "still_unresolved_records":
        int(len(unresolved)),

    "recovery_rate":
        (
            round(
                len(recovered)
                / len(df),
                4
            )
            if len(df)
            else 0
        ),

    "source_counts": {
        str(k): int(v)
        for k, v
        in source_counts.items()
    },

    "match_method_counts": {
        str(k): int(v)
        for k, v
        in method_counts.items()
    },

    "doi_disagreements":
        int(
            master[
                "doi_disagreement"
            ]
            .astype(int)
            .sum()
        ),

    "openalex_title_threshold":
        OA_TITLE_THRESHOLD,

    "crossref_title_threshold":
        CR_TITLE_THRESHOLD,

    "synthetic_abstracts":
        False,

    "automatic_eligibility_decisions":
        0,

    "corpus_status":
        "NOT_FROZEN",

    "outputs": {
        "master":
            str(OUT_MASTER),
        "recovered":
            str(OUT_RECOVERED),
        "unresolved":
            str(OUT_UNRESOLVED),
        "cache":
            str(CACHE_FILE)
    },

    "warning":
        (
            "Title-fallback matches are "
            "retrieval candidates, not "
            "eligibility decisions. DOI "
            "disagreements and borderline "
            "matches require manual review."
        )
}

OUT_AUDIT.write_text(
    json.dumps(
        audit,
        indent=2,
        ensure_ascii=False
    ),
    encoding="utf-8"
)

save_cache()

print()
print("=" * 78)
print("SECONDARY RECOVERY COMPLETE")
print("=" * 78)

print(
    "Input unresolved :",
    len(df)
)

print(
    "Recovered        :",
    len(recovered)
)

print(
    "Still unresolved :",
    len(unresolved)
)

print(
    "DOI disagreements:",
    audit[
        "doi_disagreements"
    ]
)

print("\nSources:")
print(source_counts)

print("\nMethods:")
print(method_counts)

print("\nCreated:")
print(" ", OUT_MASTER)
print(" ", OUT_RECOVERED)
print(" ", OUT_UNRESOLVED)
print(" ", OUT_AUDIT)
print(" ", CACHE_FILE)

print(
    "\nNo eligibility decisions "
    "were made automatically."
)