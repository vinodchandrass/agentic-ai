# Decision Validity in Agentic AI

Reproducibility materials for the systematic survey:

**Decision Validity in Agentic AI: A Systematic Survey of Validity Mechanisms Across Consequential Action Boundaries**

**Author:** Vinod Chandra S. S.  
Department of Computer Science, University of Kerala, Thiruvananthapuram, Kerala, India

## Overview

This repository contains the data, coding outputs, analysis files, and
reproducibility materials supporting a systematic survey of decision validity
in agentic AI.

Decision validity concerns whether the grounds supporting an agentic decision
remain sufficient as the decision approaches and crosses a consequential
action boundary, and whether validity is subsequently verified or restored.

The review examines three analytical dimensions:

- mechanism;
- consequential boundary; and
- evidence maturity.

These dimensions are synthesized through an evidence-mapped
Decision-Validity Architecture (DVA).

## Frozen Evidence Base

The final recall-protection screening corpus contains **280 unique records**:

- **13 CORE**
- **45 CORE-REVIEW**
- **124 ADJACENT**
- **98 EXCLUDE**

The mechanism-focused evidence base therefore contains **58 records**
(13 CORE + 45 CORE-REVIEW).

Of these, **47 records** support an identifiable primary mechanism.
The remaining **11 records** are retained as explicit mechanism-evidence gaps
rather than being force-classified.

CORE denotes studies with demonstrated qualifying decision-validity
mechanisms. CORE-REVIEW denotes relevant architectural, conceptual,
review-based, or otherwise less directly demonstrated evidence.

## Decision-Validity Loci

The evidence is organized across five analytical loci:

- **L1 — Decision formation and validation**
- **L2 — Authority and permission**
- **L3 — Trusted context and capability**
- **L4 — Governed commit and execution**
- **L5 — Post-effect closure**

These loci are used for evidence synthesis and should not be interpreted as a
mandatory agent lifecycle or an ordinal maturity scale.

## Supplementary Evidence

`Table_S1_Frozen_58_Record_Evidence_Inventory.csv` contains the frozen
machine-readable evidence inventory for all 58 CORE and CORE-REVIEW records.

`Supplementary_Table_S1_Complete_58_Record_Evidence_Inventory.docx`
provides the corresponding human-readable supplementary table.

`Reference_Completeness_Audit_58_Studies.csv` records the bibliographic
completeness audit for the 58-study evidence base.

## Reproducibility

The repository preserves materials used during evidence identification,
screening, adjudication, taxonomy construction, quantitative synthesis,
robustness analysis, and evidence-architecture development.

Mechanism coding is multi-label. Consequently, mechanism counts are not
mutually exclusive and should not be expected to sum to the number of
included records.

Evidence-gap categories represent limitations in the evidence available for
classification and must not be interpreted as mechanism-prevalence
categories.

The frozen evidence files should be treated as the authoritative analytical
state underlying the reported manuscript results.

## Reuse and Citation

Please cite the associated article and the archived repository release when
using these data, coding outputs, or reproducibility materials.

A version-specific citation and archival DOI will be added to the final
public release.

## Repository Status

This repository currently contains the pre-publication reproducibility
materials. A frozen versioned release will be created for the submitted
manuscript.
