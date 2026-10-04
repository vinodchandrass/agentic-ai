import os
import requests

API_KEY = os.getenv("SCOPUS_API_KEY")

if not API_KEY:
    raise RuntimeError("SCOPUS_API_KEY is not set.")

# Test using an EID from our retrieved sample.
# No API key is hard-coded.
EID = "2-s2.0-105050399526"

url = f"https://api.elsevier.com/content/abstract/eid/{EID}"

headers = {
    "X-ELS-APIKey": API_KEY,
    "Accept": "application/json"
}

params = {
    "view": "FULL"
}

print("Testing Scopus Abstract Retrieval API...")
print("EID:", EID)

r = requests.get(
    url,
    headers=headers,
    params=params,
    timeout=60
)

print("HTTP status:", r.status_code)

if r.status_code != 200:
    print("\nERROR RESPONSE")
    print(r.text[:4000])
    raise SystemExit(1)

data = r.json()

core = (
    data
    .get("abstracts-retrieval-response", {})
    .get("coredata", {})
)

print("\nSUCCESS")
print("Title:", core.get("dc:title"))
print("DOI:", core.get("prism:doi"))

description = core.get("dc:description")

print(
    "Abstract available:",
    bool(description)
)

if description:
    print(
        "Abstract characters:",
        len(description)
    )
    print("\nAbstract preview:")
    print(description[:1000])

print("\nTop-level coredata fields:")
for key in sorted(core.keys()):
    print(" ", key)

print("\nDONE")