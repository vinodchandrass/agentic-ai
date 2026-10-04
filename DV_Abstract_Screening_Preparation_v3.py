import re
import json
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

# ============================================================
# FILES
# ============================================================

INPUT = Path("DV_Abstract_Enriched_Master_v2.csv")

OUT_SCREEN = Path("DV_Abstract_Screening_Package_v3.csv")
OUT_CORE = Path("DV_HighPriority_Manual_Set_v3.csv")
OUT_AUDIT = Path("DV_Abstract_Screening_Preparation_Audit_v3.json")

if not INPUT.exists():
    raise FileNotFoundError(INPUT.resolve())

df = pd.read_csv(INPUT, dtype=str).fillna("")

# Only records with real recovered abstracts
resolved = df[
    df["abstract"].str.strip().ne("")
].copy()

print("=" * 76)
print("DECISION-VALIDITY ABSTRACT SCREENING PREPARATION v3")
print("=" * 76)
print("Master records :", len(df))
print("With abstracts :", len(resolved))

# ============================================================
# NORMALIZATION
# ============================================================

def normalize(text):
    text = str(text).replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def sentences(text):
    text = normalize(text)

    if not text:
        return []

    return [
        x.strip()
        for x in re.split(
            r"(?<=[.!?])\s+(?=[A-Z0-9])",
            text
        )
        if x.strip()
    ]

# ============================================================
# EVIDENCE DIMENSIONS
#
# Retrieval/evidence coding only.
# These are NOT automatic eligibility criteria.
# ============================================================

DIMENSIONS = {

    "INTENT_SPECIFICATION": [
        r"\bintent",
        r"\buser mandate",
        r"\bgoal specification",
        r"\brequirement",
        r"\bspecification",
        r"\bsemantic valid",
        r"\bsemantic consistency",
        r"\bconstraint satisf",
        r"\bprecondition",
        r"\bpostcondition"
    ],

    "DECISION_JUSTIFICATION": [
        r"\bdecision",
        r"\bjustif",
        r"\bevidence",
        r"\bpredicate",
        r"\bcondition",
        r"\bdecision context",
        r"\breasoning trace",
        r"\bdecision trace"
    ],

    "STATE_DEPENDENCY": [
        r"\bstate",
        r"\bcontext",
        r"\bdependency",
        r"\bprovenance",
        r"\blineage",
        r"\bfreshness",
        r"\bstale",
        r"\bversion",
        r"\bmemory conflict"
    ],

    "TEMPORAL_VALIDITY": [
        r"\btemporal",
        r"\bstale",
        r"\bfreshness",
        r"\btime[- ]of[- ]check",
        r"\btime[- ]of[- ]use",
        r"\btoctou",
        r"\bstate change",
        r"\bversion conflict",
        r"\brace condition",
        r"\brevocation",
        r"\bexpired"
    ],

    "REVALIDATION": [
        r"\brevalidat",
        r"\bre[- ]?verif",
        r"\brecheck",
        r"\bpre[- ]execution check",
        r"\bverification before",
        r"\bvalidate before",
        r"\bverification condition",
        r"\bruntime verification",
        r"\bruntime assurance"
    ],

    "AUTHORITY_DELEGATION": [
        r"\bauthori",
        r"\bpermission",
        r"\bdelegat",
        r"\bprivilege",
        r"\bcapability token",
        r"\bpermit[- ]to[- ]act",
        r"\baccess control",
        r"\bleast privilege",
        r"\bscope monotonic"
    ],

    "ACTION_EXECUTION": [
        r"\baction",
        r"\bexecution",
        r"\bexecute",
        r"\btool call",
        r"\btool invocation",
        r"\bexternalization",
        r"\bactuat",
        r"\bworkflow",
        r"\boperation"
    ],

    "COMMIT_TRANSACTION": [
        r"\bcommit",
        r"\btransaction",
        r"\batomic",
        r"\bsettlement",
        r"\bsemantic transaction",
        r"\bcommit[- ]before",
        r"\bexactly[- ]once",
        r"\bidempoten"
    ],

    "EFFECT_VALIDATION": [
        r"\bexternal effect",
        r"\bpost[- ]decision effect",
        r"\boutcome",
        r"\baction validity",
        r"\beffect validation",
        r"\bexecution result",
        r"\bpostcondition",
        r"\bstate transition",
        r"\bexternal state"
    ],

    "RECOVERY_COMPENSATION": [
        r"\brollback",
        r"\brecovery",
        r"\bcompensat",
        r"\breconcile",
        r"\bretry",
        r"\bpartial execution",
        r"\bpartial failure",
        r"\bduplicate",
        r"\bfailure recovery"
    ],

    "FORMAL_RUNTIME_ASSURANCE": [
        r"\bformal verification",
        r"\bprovabl",
        r"\btheorem",
        r"\binvariant",
        r"\bsafety envelope",
        r"\bmodel checking",
        r"\btla\+",
        r"\bruntime enforcement",
        r"\breference monitor"
    ]
}

# ============================================================
# NEGATIVE / APPLICATION-ONLY SIGNALS
#
# Used only to help manual reviewers notice likely noise.
# Never causes automatic exclusion.
# ============================================================

APPLICATION_SIGNALS = [
    r"\bdiagnos",
    r"\bclinical question",
    r"\brecommendation accuracy",
    r"\banswer relevancy",
    r"\banswer accuracy",
    r"\bclassification accuracy",
    r"\bcustomer satisfaction",
    r"\bpurchase intention",
    r"\bconsumer acceptance",
    r"\blearning outcome",
    r"\bstudent performance"
]

# ============================================================
# EVIDENCE EXTRACTION
# ============================================================

def evidence_for_dimension(abstract, patterns):
    hits = []

    for sentence in sentences(abstract):
        if any(
            re.search(p, sentence, re.I)
            for p in patterns
        ):
            hits.append(sentence)

    # Keep compact evidence window
    return " || ".join(hits[:3])


def signal_present(text, patterns):
    return int(
        any(
            re.search(p, text, re.I)
            for p in patterns
        )
    )

for dim, patterns in DIMENSIONS.items():

    resolved[f"{dim}_FLAG"] = (
        resolved["abstract"].apply(
            lambda x: signal_present(
                x, patterns
            )
        )
    )

    resolved[f"{dim}_EVIDENCE"] = (
        resolved["abstract"].apply(
            lambda x: evidence_for_dimension(
                x, patterns
            )
        )
    )

flag_cols = [
    f"{d}_FLAG"
    for d in DIMENSIONS
]

resolved["MECHANISM_DIMENSION_COUNT"] = (
    resolved[flag_cols]
    .astype(int)
    .sum(axis=1)
)

resolved["MATCHED_DIMENSIONS"] = (
    resolved.apply(
        lambda row: "; ".join(
            d for d in DIMENSIONS
            if int(row[f"{d}_FLAG"]) == 1
        ),
        axis=1
    )
)

resolved["APPLICATION_ONLY_SIGNAL"] = (
    resolved["abstract"].apply(
        lambda x: signal_present(
            x,
            APPLICATION_SIGNALS
        )
    )
)

# ============================================================
# CROSS-LIFECYCLE SIGNALS
#
# These are useful because our proposed contribution concerns
# validity across stages, rather than isolated safety controls.
# ============================================================

resolved["PRE_ACTION_SIGNAL"] = (
    (
        resolved["INTENT_SPECIFICATION_FLAG"].astype(int)
        |
        resolved["DECISION_JUSTIFICATION_FLAG"].astype(int)
        |
        resolved["STATE_DEPENDENCY_FLAG"].astype(int)
        |
        resolved["AUTHORITY_DELEGATION_FLAG"].astype(int)
    )
).astype(int)

resolved["BOUNDARY_SIGNAL"] = (
    (
        resolved["TEMPORAL_VALIDITY_FLAG"].astype(int)
        |
        resolved["REVALIDATION_FLAG"].astype(int)
        |
        resolved["ACTION_EXECUTION_FLAG"].astype(int)
        |
        resolved["COMMIT_TRANSACTION_FLAG"].astype(int)
    )
).astype(int)

resolved["POST_ACTION_SIGNAL"] = (
    (
        resolved["EFFECT_VALIDATION_FLAG"].astype(int)
        |
        resolved["RECOVERY_COMPENSATION_FLAG"].astype(int)
    )
).astype(int)

resolved["LIFECYCLE_STAGE_COUNT"] = (
    resolved[
        [
            "PRE_ACTION_SIGNAL",
            "BOUNDARY_SIGNAL",
            "POST_ACTION_SIGNAL"
        ]
    ]
    .astype(int)
    .sum(axis=1)
)

# ============================================================
# MANUAL PRIORITY
#
# PRIORITY != eligibility.
# ============================================================

def priority(row):

    dimensions = int(
        row["MECHANISM_DIMENSION_COUNT"]
    )

    lifecycle = int(
        row["LIFECYCLE_STAGE_COUNT"]
    )

    temporal = int(
        row["TEMPORAL_VALIDITY_FLAG"]
    )

    revalidation = int(
        row["REVALIDATION_FLAG"]
    )

    commit = int(
        row["COMMIT_TRANSACTION_FLAG"]
    )

    effect = int(
        row["EFFECT_VALIDATION_FLAG"]
    )

    if (
        lifecycle == 3
        or
        (
            dimensions >= 4
            and (
                temporal
                or revalidation
                or commit
                or effect
            )
        )
    ):
        return "A_CORE_FIRST"

    if dimensions >= 3:
        return "B_HIGH"

    if dimensions >= 2:
        return "C_MEDIUM"

    return "D_LOW"


resolved["SCREENING_PRIORITY"] = (
    resolved.apply(
        priority,
        axis=1
    )
)

# ============================================================
# MANUAL ADJUDICATION FIELDS
# ============================================================

resolved["MANUAL_DECISION"] = ""

resolved["MANUAL_REASON_CODE"] = ""

resolved["MANUAL_NOTES"] = ""

resolved["FULL_TEXT_REQUIRED"] = ""

resolved["FINAL_MECHANISM_FAMILY"] = ""

# Recommended manual decision vocabulary:
#
# CORE
# ADJACENT
# EXCLUDE
# UNCERTAIN
#
# Do not use blank as an implicit exclusion.

# ============================================================
# SORT
# ============================================================

priority_order = {
    "A_CORE_FIRST": 0,
    "B_HIGH": 1,
    "C_MEDIUM": 2,
    "D_LOW": 3
}

resolved["_SORT"] = (
    resolved["SCREENING_PRIORITY"]
    .map(priority_order)
)

resolved = resolved.sort_values(
    [
        "_SORT",
        "LIFECYCLE_STAGE_COUNT",
        "MECHANISM_DIMENSION_COUNT"
    ],
    ascending=[
        True,
        False,
        False
    ]
).drop(columns="_SORT")

# ============================================================
# SAVE FULL SCREENING PACKAGE
# ============================================================

resolved.to_csv(
    OUT_SCREEN,
    index=False,
    encoding="utf-8-sig"
)

# ============================================================
# HIGH-PRIORITY SET
# ============================================================

high = resolved[
    resolved["SCREENING_PRIORITY"].isin(
        ["A_CORE_FIRST", "B_HIGH"]
    )
].copy()

high.to_csv(
    OUT_CORE,
    index=False,
    encoding="utf-8-sig"
)

# ============================================================
# AUDIT
# ============================================================

priority_counts = (
    resolved["SCREENING_PRIORITY"]
    .value_counts()
    .to_dict()
)

dimension_counts = {
    dim: int(
        resolved[f"{dim}_FLAG"]
        .astype(int)
        .sum()
    )
    for dim in DIMENSIONS
}

lifecycle_counts = (
    resolved["LIFECYCLE_STAGE_COUNT"]
    .value_counts()
    .sort_index()
    .to_dict()
)

audit = {

    "pipeline":
        "DV Abstract Screening Preparation v3",

    "timestamp_utc":
        datetime.now(timezone.utc).isoformat(),

    "input_file":
        str(INPUT),

    "input_master_records":
        int(len(df)),

    "records_with_abstract":
        int(len(resolved)),

    "automatic_inclusion_decisions":
        0,

    "automatic_exclusion_decisions":
        0,

    "screening_priority_is_eligibility":
        False,

    "dimension_counts":
        dimension_counts,

    "lifecycle_stage_counts":
        {
            str(k): int(v)
            for k, v in lifecycle_counts.items()
        },

    "priority_counts":
        {
            str(k): int(v)
            for k, v in priority_counts.items()
        },

    "high_priority_manual_records":
        int(len(high)),

    "manual_decision_vocabulary": [
        "CORE",
        "ADJACENT",
        "EXCLUDE",
        "UNCERTAIN"
    ],

    "corpus_status":
        "NOT_FROZEN",

    "outputs": {
        "screening_package":
            str(OUT_SCREEN),
        "high_priority_manual_set":
            str(OUT_CORE)
    },

    "warning":
        "Regex evidence flags and priority classes are "
        "screening aids only. They must not be interpreted "
        "as study eligibility decisions."
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
print("=" * 76)
print("SCREENING PREPARATION COMPLETE")
print("=" * 76)

print(
    "Records prepared:",
    len(resolved)
)

print(
    "High priority:",
    len(high)
)

print("\nPriorities:")

for p in [
    "A_CORE_FIRST",
    "B_HIGH",
    "C_MEDIUM",
    "D_LOW"
]:
    print(
        f"  {p:15s}",
        priority_counts.get(p, 0)
    )

print("\nLifecycle coverage:")

for k in sorted(lifecycle_counts):
    print(
        f"  {k} stages:",
        lifecycle_counts[k]
    )

print("\nMechanism dimensions:")

for d, n in sorted(
    dimension_counts.items(),
    key=lambda x: -x[1]
):
    print(
        f"  {d:28s} {n}"
    )

print("\nCreated:")
print(" ", OUT_SCREEN)
print(" ", OUT_CORE)
print(" ", OUT_AUDIT)

print()
print(
    "IMPORTANT: no record has been automatically "
    "included or excluded."
)