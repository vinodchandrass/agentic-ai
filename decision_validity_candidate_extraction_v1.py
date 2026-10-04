import pandas as pd
import re
import json
from pathlib import Path
from datetime import datetime, timezone

# ============================================================
# CONFIGURATION
# ============================================================

INPUT = Path("Scopus_V2_Production_Candidate.csv")

OUT_ALL = Path("DV_All_993_Coded_v1.csv")
OUT_CANDIDATES = Path("DV_HighSensitivity_Candidates_v1.csv")
OUT_REVIEWS = Path("DV_Review_Novelty_Set_v1.csv")
OUT_AUDIT = Path("DV_Candidate_Extraction_Audit_v1.json")

if not INPUT.exists():
    raise FileNotFoundError(
        f"Cannot find {INPUT.resolve()}"
    )

# ============================================================
# LOAD
# ============================================================

df = pd.read_csv(INPUT, dtype=str).fillna("")

print("=" * 78)
print("DECISION-VALIDITY HIGH-SENSITIVITY CANDIDATE EXTRACTION")
print("=" * 78)
print(f"Input records: {len(df)}")

if len(df) != 993:
    print(
        f"WARNING: expected 993 records, found {len(df)}."
    )

# ============================================================
# NORMALIZATION
# ============================================================

def norm(x):
    x = str(x).lower()
    x = re.sub(r"[\-_]", " ", x)
    x = re.sub(r"\s+", " ", x)
    return x.strip()

# Current Scopus STANDARD retrieval mainly gives title-level
# bibliographic metadata. We therefore code ONLY available text.
df["_screen_text"] = df["title"].map(norm)

# ============================================================
# EVIDENCE DIMENSIONS
#
# These are retrieval aids, NOT final taxonomy and NOT
# automatic inclusion criteria.
# ============================================================

DIMENSIONS = {

    "decision_basis": [
        r"\bdecision",
        r"\bjustif",
        r"\bprecondition",
        r"\bpostcondition",
        r"\bspecification",
        r"\brequirement",
        r"\bconstraint",
        r"\binvariant",
        r"\bpredicate",
        r"\bcondition"
    ],

    "dependency_binding": [
        r"\bdependenc",
        r"\blineage",
        r"\bprovenance",
        r"\bbinding",
        r"\btrace",
        r"\bcausal",
        r"\bevidence"
    ],

    "temporal_validity": [
        r"\btemporal",
        r"\bstale",
        r"\bfreshness",
        r"\btime of check",
        r"\btime of use",
        r"\btoctou",
        r"\bstate change",
        r"\bversion conflict",
        r"\brace condition"
    ],

    "conflict_detection": [
        r"\bdecision conflict",
        r"\bconflict detect",
        r"\bconflict",
        r"\binvalidat",
        r"\bconsisten",
        r"\bstate valid",
        r"\bstate conflict"
    ],

    "revalidation": [
        r"\brevalidat",
        r"\bre verify",
        r"\breverify",
        r"\bverification",
        r"\bverify",
        r"\bvalidation",
        r"\bvalidate",
        r"\bruntime verification",
        r"\bruntime assurance"
    ],

    "authority_validity": [
        r"\bauthori",
        r"\bpermission",
        r"\bdelegat",
        r"\baccess control",
        r"\bcapabilit",
        r"\bprivilege",
        r"\bpolicy enforcement",
        r"\bpolicy compliance"
    ],

    "commit_binding": [
        r"\bcommit",
        r"\btransaction",
        r"\batomic",
        r"\bsemantic transaction",
        r"\bexecution",
        r"\baction release",
        r"\btool execution",
        r"\btool call"
    ],

    "effect_validation": [
        r"\beffect validation",
        r"\bexternal effect",
        r"\bpostcondition",
        r"\boutcome verification",
        r"\baction validation",
        r"\beffect",
        r"\bexecution result"
    ],

    "recovery": [
        r"\brollback",
        r"\brecovery",
        r"\bcompensat",
        r"\breconcile",
        r"\bretry",
        r"\bidempoten",
        r"\bpartial failure",
        r"\bduplicate action",
        r"\bfailure recovery"
    ],

    "formal_assurance": [
        r"\bformal verification",
        r"\bprovabl",
        r"\btheorem",
        r"\bsafety envelope",
        r"\binvariant",
        r"\bmodel checking",
        r"\bruntime assurance",
        r"\bformal method"
    ]
}

# ============================================================
# AGENT / ACTION SIGNALS
# ============================================================

AGENT_PATTERNS = [
    r"\bagentic\b",
    r"\bllm agent",
    r"\blarge language model agent",
    r"\bai agent",
    r"\bautonomous ai",
    r"\bautonomous agent",
    r"\btool using agent",
    r"\bmulti agent",
    r"\bmultiagent",
    r"\bagent based",
    r"\bagent system"
]

ACTION_PATTERNS = [
    r"\baction",
    r"\bexecution",
    r"\btool",
    r"\bworkflow",
    r"\bplan",
    r"\bplanning",
    r"\bdecision",
    r"\bcommand",
    r"\bcontrol",
    r"\boperation"
]

# ============================================================
# MATCHING
# ============================================================

def has_any(text, patterns):
    return any(
        re.search(p, text, flags=re.I)
        for p in patterns
    )

def matched_terms(text, patterns):
    found = []
    for p in patterns:
        if re.search(p, text, flags=re.I):
            found.append(p)
    return found

df["agent_signal"] = df["_screen_text"].apply(
    lambda x: int(has_any(x, AGENT_PATTERNS))
)

df["action_signal"] = df["_screen_text"].apply(
    lambda x: int(has_any(x, ACTION_PATTERNS))
)

for dimension, patterns in DIMENSIONS.items():

    df[dimension] = df["_screen_text"].apply(
        lambda x: int(has_any(x, patterns))
    )

    df[f"{dimension}_matches"] = df["_screen_text"].apply(
        lambda x: " | ".join(
            matched_terms(x, patterns)
        )
    )

dimension_cols = list(DIMENSIONS.keys())

df["dimension_count"] = df[dimension_cols].sum(axis=1)

df["matched_dimensions"] = df.apply(
    lambda row: "; ".join(
        d for d in dimension_cols
        if row[d] == 1
    ),
    axis=1
)

# ============================================================
# HIGH-SENSITIVITY CANDIDATE RULE
#
# Deliberately permissive.
#
# Candidate if:
#   agent signal AND >=1 mechanism dimension
# OR
#   action signal AND >=2 mechanism dimensions
#
# This does NOT mean "included study".
# ============================================================

df["candidate_flag"] = (
    (
        (df["agent_signal"] == 1) &
        (df["dimension_count"] >= 1)
    )
    |
    (
        (df["action_signal"] == 1) &
        (df["dimension_count"] >= 2)
    )
).astype(int)

# Higher-density records get priority for enrichment/manual review.
df["candidate_priority"] = "LOW"

df.loc[
    df["candidate_flag"] == 1,
    "candidate_priority"
] = "MEDIUM"

df.loc[
    (
        (df["candidate_flag"] == 1) &
        (df["dimension_count"] >= 2)
    ),
    "candidate_priority"
] = "HIGH"

df.loc[
    (
        (df["candidate_flag"] == 1) &
        (df["dimension_count"] >= 3)
    ),
    "candidate_priority"
] = "VERY_HIGH"

# ============================================================
# REVIEW / NOVELTY SET
# ============================================================

doctype = df["document_type"].map(norm)

df["review_flag"] = doctype.isin([
    "review",
    "conference review",
    "short survey"
]).astype(int)

reviews = df[df["review_flag"] == 1].copy()

# ============================================================
# MANUAL SCREENING FIELDS
# ============================================================

for col in [
    "abstract",
    "abstract_source",
    "manual_decision",
    "manual_reason",
    "evidence_notes",
    "full_text_needed"
]:
    if col not in df.columns:
        df[col] = ""

# ============================================================
# OUTPUTS
# ============================================================

# Remove helper text only.
all_out = df.drop(columns=["_screen_text"])

all_out.to_csv(
    OUT_ALL,
    index=False,
    encoding="utf-8-sig"
)

candidates = all_out[
    all_out["candidate_flag"] == 1
].copy()

priority_order = {
    "VERY_HIGH": 0,
    "HIGH": 1,
    "MEDIUM": 2,
    "LOW": 3
}

candidates["_priority_sort"] = (
    candidates["candidate_priority"]
    .map(priority_order)
    .fillna(9)
)

candidates = candidates.sort_values(
    by=[
        "_priority_sort",
        "dimension_count",
        "cited_by"
    ],
    ascending=[
        True,
        False,
        False
    ]
)

candidates = candidates.drop(
    columns=["_priority_sort"]
)

candidates.to_csv(
    OUT_CANDIDATES,
    index=False,
    encoding="utf-8-sig"
)

reviews = all_out[
    all_out["review_flag"] == 1
].copy()

reviews.to_csv(
    OUT_REVIEWS,
    index=False,
    encoding="utf-8-sig"
)

# ============================================================
# DIMENSION COUNTS
# ============================================================

dimension_counts = {
    d: int(df[d].sum())
    for d in dimension_cols
}

priority_counts = (
    df[df["candidate_flag"] == 1]
    ["candidate_priority"]
    .value_counts()
    .to_dict()
)

year_counts = {}

for date in df["cover_date"]:
    year = str(date)[:4] if str(date) else "UNKNOWN"
    year_counts[year] = year_counts.get(year, 0) + 1

# ============================================================
# AUDIT
# ============================================================

audit = {
    "pipeline":
        "Decision Validity Candidate Extraction v1",

    "timestamp_utc":
        datetime.now(timezone.utc).isoformat(),

    "input_file":
        str(INPUT),

    "input_records":
        int(len(df)),

    "screening_basis":
        "Scopus STANDARD metadata title only",

    "automatic_decisions":
        "NONE",

    "candidate_rule": {
        "rule_1":
            "agent_signal AND dimension_count >= 1",
        "rule_2":
            "action_signal AND dimension_count >= 2",
        "interpretation":
            "High-sensitivity enrichment queue only; "
            "not study eligibility"
    },

    "candidate_records":
        int(df["candidate_flag"].sum()),

    "noncandidate_records":
        int(
            len(df) -
            df["candidate_flag"].sum()
        ),

    "review_novelty_records":
        int(df["review_flag"].sum()),

    "dimension_counts":
        dimension_counts,

    "candidate_priority_counts":
        {
            str(k): int(v)
            for k, v in priority_counts.items()
        },

    "year_distribution":
        year_counts,

    "outputs": {
        "all_coded":
            str(OUT_ALL),
        "high_sensitivity_candidates":
            str(OUT_CANDIDATES),
        "review_novelty_set":
            str(OUT_REVIEWS)
    },

    "corpus_status":
        "NOT_FROZEN",

    "important_warning":
        "Absence of title-level signals MUST NOT be used "
        "to exclude a record. Abstract/full-text screening "
        "is required before eligibility decisions."
}

with open(
    OUT_AUDIT,
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
print("RESULTS")
print("=" * 78)

print(f"Total records:       {len(df)}")
print(f"Candidates:          {len(candidates)}")
print(f"Novelty reviews:     {len(reviews)}")

print("\nEvidence dimensions:")

for d, n in sorted(
    dimension_counts.items(),
    key=lambda x: -x[1]
):
    print(f"  {d:24s} {n}")

print("\nCandidate priorities:")

for p in [
    "VERY_HIGH",
    "HIGH",
    "MEDIUM"
]:
    print(
        f"  {p:12s} "
        f"{priority_counts.get(p, 0)}"
    )

print("\nFiles created:")
print(f"  {OUT_ALL}")
print(f"  {OUT_CANDIDATES}")
print(f"  {OUT_REVIEWS}")
print(f"  {OUT_AUDIT}")

print()
print("IMPORTANT:")
print(
    "candidate_flag is NOT an inclusion decision."
)
print(
    "Records without title-level signals remain in "
    "DV_All_993_Coded_v1.csv."
)
print(
    "Do not delete or exclude them before abstract/full-text screening."
)