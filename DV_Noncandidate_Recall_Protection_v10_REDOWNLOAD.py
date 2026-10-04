#!/usr/bin/env python
"""
DV_Noncandidate_Recall_Protection_v10.py

Purpose
-------
Protect recall among the 805 records that were NOT selected by the earlier
title-level candidate heuristic. Title-level nonselection is never treated as
an eligibility exclusion.

Input
-----
D:\ACM\DV_All_993_Coded_v1.csv
(or pass another path as the first command-line argument)

Outputs
-------
DV_Noncandidate_805_Abstract_Master_v10.csv
DV_Noncandidate_805_Resolved_v10.csv
DV_Noncandidate_805_Unresolved_v10.csv
DV_Noncandidate_805_HighPriority_v10.csv
DV_Noncandidate_Recall_Protection_Audit_v10.json
DV_Noncandidate_Abstract_Cache_v10.json

No automatic CORE/ADJACENT/EXCLUDE decisions are made.
"""

import os, re, sys, json, time, html
from pathlib import Path
from datetime import datetime, timezone
from difflib import SequenceMatcher

import pandas as pd
import requests

DEFAULT_INPUT = r"D:\ACM\DV_All_993_Coded_v1.csv"
INPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(DEFAULT_INPUT)
OUTDIR = INPUT.parent

OA = "https://api.openalex.org/works"
CR = "https://api.crossref.org/works"
EMAIL = os.getenv("OPENALEX_EMAIL", "").strip()
UA = f"DV-recall-protection/10.0 ({EMAIL})" if EMAIL else "DV-recall-protection/10.0"
S = requests.Session()
S.headers.update({"User-Agent": UA})

def norm_title(x):
    x = html.unescape(str(x or "")).lower()
    x = re.sub(r"<[^>]+>", " ", x)
    x = re.sub(r"[^a-z0-9]+", " ", x)
    return re.sub(r"\s+", " ", x).strip()

def norm_doi(x):
    x = str(x or "").strip().lower()
    x = re.sub(r"^https?://(dx\.)?doi\.org/", "", x)
    return x

def inv_index_to_text(inv):
    if not inv:
        return ""
    pos = []
    for word, positions in inv.items():
        for p in positions:
            pos.append((p, word))
    return " ".join(w for _, w in sorted(pos))

def clean_abstract(x):
    if not x:
        return ""
    x = html.unescape(str(x))
    x = re.sub(r"<[^>]+>", " ", x)
    return re.sub(r"\s+", " ", x).strip()

def get_json(url, params=None, tries=3):
    for attempt in range(tries):
        try:
            r = S.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            return None
        except requests.RequestException:
            time.sleep(2 ** attempt)
    return None

def oa_by_doi(doi):
    if not doi:
        return None
    j = get_json(f"{OA}/https://doi.org/{doi}", {"mailto": EMAIL} if EMAIL else None)
    if not j:
        return None
    return {
        "source": "OPENALEX_DOI",
        "title": j.get("title") or "",
        "doi": norm_doi(j.get("doi")),
        "abstract": inv_index_to_text(j.get("abstract_inverted_index")),
        "id": j.get("id") or ""
    }

def oa_by_title(title):
    params = {"search": title, "per-page": 5}
    if EMAIL:
        params["mailto"] = EMAIL
    j = get_json(OA, params)
    best = None
    for w in (j or {}).get("results", []):
        t = w.get("title") or ""
        score = SequenceMatcher(None, norm_title(title), norm_title(t)).ratio()
        if best is None or score > best["score"]:
            best = {
                "source": "OPENALEX_TITLE",
                "title": t,
                "doi": norm_doi(w.get("doi")),
                "abstract": inv_index_to_text(w.get("abstract_inverted_index")),
                "id": w.get("id") or "",
                "score": score
            }
    return best if best and best["score"] >= 0.92 else None

def cr_by_doi(doi):
    if not doi:
        return None
    j = get_json(f"{CR}/{doi}")
    m = (j or {}).get("message", {})
    if not m:
        return None
    return {
        "source": "CROSSREF_DOI",
        "title": (m.get("title") or [""])[0],
        "doi": norm_doi(m.get("DOI")),
        "abstract": clean_abstract(m.get("abstract")),
        "id": m.get("URL") or ""
    }

def cr_by_title(title):
    j = get_json(CR, {"query.title": title, "rows": 5})
    best = None
    for m in ((j or {}).get("message", {}).get("items", [])):
        t = (m.get("title") or [""])[0]
        score = SequenceMatcher(None, norm_title(title), norm_title(t)).ratio()
        if best is None or score > best["score"]:
            best = {
                "source": "CROSSREF_TITLE",
                "title": t,
                "doi": norm_doi(m.get("DOI")),
                "abstract": clean_abstract(m.get("abstract")),
                "id": m.get("URL") or "",
                "score": score
            }
    return best if best and best["score"] >= 0.94 else None

# Mechanism-sensitive prioritization only. These are NOT eligibility rules.
PATTERNS = {
    "DECISION_PREMISE": r"\b(decision (?:condition|premise|justification)|precondition|invariant)\b",
    "STATE_CHANGE": r"\b(state (?:change|validity|consistency|verification)|stale|freshness)\b",
    "TEMPORAL_REVALIDATION": r"\b(revalidat\w*|re-verif\w*|reverif\w*|TOCTOU|time[- ]of[- ]check)\b",
    "AUTHORITY_AT_EXECUTION": r"\b(authori[sz]\w*|delegat\w*|permission\w*|access control|policy enforcement)\b",
    "EXECUTION_BOUNDARY": r"\b(execut\w*|tool call\w*|actuat\w*|external action\w*|action gating)\b",
    "COMMIT_TRANSACTION": r"\b(commit\w*|transaction\w*|rollback|compensat\w*|idempot\w*)\b",
    "EFFECT_VALIDATION": r"\b(effect validation|postcondition|outcome verification|effect verification|reconciliation)\b",
    "FORMAL_RUNTIME": r"\b(runtime verification|runtime assurance|formal verification|model checking|safety envelope)\b",
}

def mechanism_flags(text):
    found = []
    for k, p in PATTERNS.items():
        if re.search(p, text, flags=re.I):
            found.append(k)
    boundary = any(k in found for k in ("EXECUTION_BOUNDARY","COMMIT_TRANSACTION","EFFECT_VALIDATION"))
    validity = any(k in found for k in ("DECISION_PREMISE","STATE_CHANGE","TEMPORAL_REVALIDATION",
                                        "AUTHORITY_AT_EXECUTION","FORMAL_RUNTIME"))
    if boundary and validity:
        priority = "A_RECALL_HIGH"
    elif len(found) >= 2:
        priority = "B_RECALL_MEDIUM"
    elif len(found) == 1:
        priority = "C_RECALL_LOW"
    else:
        priority = "D_NO_SIGNAL"
    return found, priority

if not INPUT.exists():
    raise FileNotFoundError(f"Input not found: {INPUT}")

df = pd.read_csv(INPUT)
if "candidate_flag" not in df.columns:
    raise RuntimeError("candidate_flag column not found.")

non = df[df["candidate_flag"].fillna(0).astype(int) == 0].copy()
if len(non) != 805:
    raise RuntimeError(f"Expected 805 noncandidates; found {len(non)}. Stop and verify input.")

cache_path = OUTDIR / "DV_Noncandidate_Abstract_Cache_v10.json"
cache = {}
if cache_path.exists():
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        cache = {}

rows = []
for n, (_, r) in enumerate(non.iterrows(), start=1):
    doi = norm_doi(r.get("doi"))
    title = str(r.get("title") or "")
    key = doi if doi else "TITLE::" + norm_title(title)

    if key in cache:
        rec = cache[key]
    else:
        candidates = []
        for fn in (lambda: oa_by_doi(doi), lambda: cr_by_doi(doi)):
            x = fn()
            if x:
                candidates.append(x)
            if x and x.get("abstract"):
                break

        if not any(x.get("abstract") for x in candidates):
            x = oa_by_title(title)
            if x:
                candidates.append(x)
        if not any(x.get("abstract") for x in candidates):
            x = cr_by_title(title)
            if x:
                candidates.append(x)

        with_abs = [x for x in candidates if x.get("abstract")]
        rec = with_abs[0] if with_abs else (candidates[0] if candidates else {
            "source":"UNRESOLVED","title":"","doi":"","abstract":"","id":""
        })
        cache[key] = rec

        if n % 25 == 0:
            cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(0.08)

    recovered_doi = norm_doi(rec.get("doi"))
    doi_disagreement = bool(doi and recovered_doi and doi != recovered_doi)
    title_score = SequenceMatcher(None, norm_title(title), norm_title(rec.get("title"))).ratio() if rec.get("title") else None
    abstract = clean_abstract(rec.get("abstract"))
    flags, priority = mechanism_flags(title + " " + abstract)

    d = r.to_dict()
    d.update({
        "recovered_abstract": abstract,
        "recovery_source": rec.get("source","UNRESOLVED"),
        "recovered_doi": recovered_doi,
        "recovered_title": rec.get("title",""),
        "title_similarity": title_score,
        "doi_disagreement": doi_disagreement,
        "abstract_resolved": bool(abstract),
        "recall_mechanism_flags": "; ".join(flags),
        "recall_priority": priority,
        "eligibility_decision": "",
        "eligibility_reason": "",
        "manual_screen_required": True
    })
    rows.append(d)

cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
master = pd.DataFrame(rows)

resolved = master[master["abstract_resolved"] == True].copy()
unresolved = master[master["abstract_resolved"] == False].copy()
high = resolved[resolved["recall_priority"].isin(["A_RECALL_HIGH","B_RECALL_MEDIUM"])].copy()

master_path = OUTDIR / "DV_Noncandidate_805_Abstract_Master_v10.csv"
resolved_path = OUTDIR / "DV_Noncandidate_805_Resolved_v10.csv"
unresolved_path = OUTDIR / "DV_Noncandidate_805_Unresolved_v10.csv"
high_path = OUTDIR / "DV_Noncandidate_805_HighPriority_v10.csv"
audit_path = OUTDIR / "DV_Noncandidate_Recall_Protection_Audit_v10.json"

master.to_csv(master_path, index=False)
resolved.to_csv(resolved_path, index=False)
unresolved.to_csv(unresolved_path, index=False)
high.to_csv(high_path, index=False)

audit = {
    "pipeline": "DV Noncandidate Recall Protection v10",
    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    "input_file": str(INPUT),
    "input_records": int(len(df)),
    "title_level_noncandidates": int(len(non)),
    "title_level_nonselection_is_exclusion": False,
    "records_with_recovered_abstract": int(len(resolved)),
    "records_still_unresolved": int(len(unresolved)),
    "abstract_recovery_rate": round(len(resolved)/len(non), 4),
    "source_counts": master["recovery_source"].value_counts(dropna=False).to_dict(),
    "doi_disagreements": int(master["doi_disagreement"].sum()),
    "priority_counts": master["recall_priority"].value_counts(dropna=False).to_dict(),
    "high_medium_manual_queue": int(len(high)),
    "synthetic_abstracts": False,
    "automatic_eligibility_decisions": 0,
    "manual_screen_required": True,
    "corpus_status": "NOT_FROZEN",
    "warning": "Recall priority is a screening aid only. D_NO_SIGNAL is not an exclusion. Unresolved records require later metadata/full-text handling."
}
audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

print("="*72)
print("DV NONCANDIDATE RECALL PROTECTION v10")
print("="*72)
print("Input records               :", len(df))
print("Title-level noncandidates   :", len(non))
print("Abstracts recovered         :", len(resolved))
print("Still unresolved            :", len(unresolved))
print("High/medium manual queue    :", len(high))
print("DOI disagreements           :", int(master["doi_disagreement"].sum()))
print("Priority counts             :", master["recall_priority"].value_counts().to_dict())
print("Eligibility decisions       : 0")
print("CORPUS STATUS               : NOT FROZEN")
print("\nOutputs:")
for p in (master_path, resolved_path, unresolved_path, high_path, audit_path, cache_path):
    print(" -", p)
