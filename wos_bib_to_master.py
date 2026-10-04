import re
import csv
import html
from pathlib import Path

INPUT_FILES = [
    str(p)
    for p in Path(".").glob("*.bib")
]

if not INPUT_FILES:
    raise FileNotFoundError(
        "No .bib files found in D:\\ACM"
    )

print("BibTeX files found:")
for f in INPUT_FILES:
    print("  ", f)
OUTPUT = "wos_v2_99_master.csv"


def split_entries(text):
    starts = [
        m.start()
        for m in re.finditer(
            r'@\w+\s*\{',
            text,
            flags=re.I
        )
    ]

    entries = []

    for i, start in enumerate(starts):
        end = (
            starts[i + 1]
            if i + 1 < len(starts)
            else len(text)
        )
        entries.append(text[start:end])

    return entries


def extract_field(entry, field):
    """
    Extract BibTeX fields enclosed by {...} or "...".
    Handles multiline fields conservatively.
    """

    pattern = (
        r'\b' + re.escape(field) +
        r'\s*=\s*'
        r'(?:\{((?:[^{}]|\{[^{}]*\})*)\}'
        r'|"([^"]*)")'
    )

    m = re.search(
        pattern,
        entry,
        flags=re.I | re.S
    )

    if not m:
        return ""

    value = (
        m.group(1)
        if m.group(1) is not None
        else m.group(2)
    )

    value = html.unescape(value)

    value = re.sub(
        r'\s+',
        ' ',
        value
    ).strip()

    # Remove simple BibTeX braces
    value = value.replace("{", "").replace("}", "")

    return value


def extract_key(entry):
    m = re.match(
        r'@\w+\s*\{\s*([^,\s]+)',
        entry,
        flags=re.I
    )

    return m.group(1) if m else ""


records = []

for filename in INPUT_FILES:

    path = Path(filename)

    if not path.exists():
        raise FileNotFoundError(
            f"Missing file: {filename}"
        )

    text = path.read_text(
        encoding="utf-8-sig",
        errors="replace"
    )

    entries = split_entries(text)

    print(
        f"{filename}: {len(entries)} entries"
    )

    for entry in entries:

        record = {
            "wos_key":
                extract_key(entry),

            "title":
                extract_field(entry, "title"),

            "abstract":
                extract_field(entry, "abstract"),

            "doi":
                extract_field(entry, "doi"),

            "year":
                extract_field(entry, "year"),

            "journal":
                extract_field(entry, "journal"),

            "booktitle":
                extract_field(entry, "booktitle"),

            "author":
                extract_field(entry, "author"),

            "keywords":
                extract_field(entry, "keywords"),

            "keywords_plus":
                extract_field(
                    entry,
                    "keywords-plus"
                ),

            "document_type":
                extract_field(
                    entry,
                    "type"
                ),

            "source_file":
                filename
        }

        records.append(record)


# ------------------------------------------------------
# DEDUPLICATION
# ------------------------------------------------------

unique = []
seen = set()

for r in records:

    doi = r["doi"].lower().strip()

    title_norm = re.sub(
        r'[^a-z0-9]+',
        '',
        r["title"].lower()
    )

    if doi:
        key = ("doi", doi)
    else:
        key = ("title", title_norm)

    if key not in seen:
        seen.add(key)
        unique.append(r)


print()
print("Raw records :", len(records))
print("Unique      :", len(unique))
print("Duplicates  :", len(records) - len(unique))


# ------------------------------------------------------
# ADD SCREENING FIELDS
# ------------------------------------------------------

for r in unique:

    r["screen_decision"] = ""
    r["exclusion_reason"] = ""

    r["STATE"] = ""
    r["INTENT"] = ""
    r["PLAN"] = ""
    r["AUTHORITY"] = ""
    r["ACTION"] = ""
    r["EFFECT"] = ""
    r["TEMPORAL"] = ""
    r["PROVENANCE"] = ""
    r["VERIFICATION"] = ""
    r["ENFORCEMENT"] = ""
    r["RECOVERY"] = ""

    r["evidence_excerpt"] = ""
    r["screening_notes"] = ""


# ------------------------------------------------------
# WRITE MASTER
# ------------------------------------------------------

fieldnames = list(unique[0].keys())

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
    writer.writerows(unique)


# ------------------------------------------------------
# QUALITY AUDIT
# ------------------------------------------------------

with_abstract = sum(
    bool(r["abstract"])
    for r in unique
)

with_doi = sum(
    bool(r["doi"])
    for r in unique
)

with_title = sum(
    bool(r["title"])
    for r in unique
)

print()
print("=" * 60)
print("WoS V2 MASTER CREATED")
print("=" * 60)

print("Unique records :", len(unique))
print("Titles         :", with_title)
print("Abstracts      :", with_abstract)
print("DOIs           :", with_doi)

print()
print("Output:", OUTPUT)

if len(unique) != 99:
    print()
    print(
        "WARNING: expected 99 unique WoS records."
    )
    print(
        "Do not proceed to screening until checked."
    )
else:
    print()
    print(
        "PASS: expected 99-record WoS V2 corpus recovered."
    )