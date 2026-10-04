#!/usr/bin/env python
"""
DV_Unresolved_Secondary_Recovery_v13.py

Second-pass evidence recovery for the v10 unresolved/non-resolved recall population.
Sources: Semantic Scholar, OpenAlex (bibliographic/title retry), Crossref (bibliographic/title retry),
and arXiv Atom search. No synthetic abstracts and no automatic eligibility decisions.

INPUT (default)
  D:\ACM\DV_Noncandidate_805_Abstract_Master_v10.csv

OUTPUTS
  DV_Unresolved_Secondary_Recovery_Master_v13.csv
  DV_Unresolved_Secondary_Recovered_v13.csv
  DV_Unresolved_Still_Unresolved_v13.csv
  DV_Unresolved_Secondary_Recovery_Audit_v13.json
  DV_Unresolved_Secondary_Recovery_Cache_v13.json
"""
import os, re, sys, json, time, html
from pathlib import Path
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import quote
import xml.etree.ElementTree as ET
import pandas as pd
import requests

INPUT=Path(sys.argv[1]) if len(sys.argv)>1 else Path(r"D:\ACM\DV_Noncandidate_805_Abstract_Master_v10.csv")
OUT=INPUT.parent
EMAIL=os.getenv("OPENALEX_EMAIL","").strip()
S=requests.Session()
S.headers.update({"User-Agent":f"DV-secondary-recovery/13.0 ({EMAIL or 'systematic-review'})"})

def s(x): return "" if pd.isna(x) else str(x)
def doi(x):
    x=s(x).strip().lower()
    return re.sub(r"^https?://(dx\.)?doi\.org/","",x)
def nt(x):
    x=html.unescape(s(x)).lower()
    x=re.sub(r"<[^>]+>"," ",x); x=re.sub(r"[^a-z0-9]+"," ",x)
    return re.sub(r"\s+"," ",x).strip()
def sim(a,b): return SequenceMatcher(None,nt(a),nt(b)).ratio()
def clean(x):
    x=html.unescape(s(x)); x=re.sub(r"<[^>]+>"," ",x)
    return re.sub(r"\s+"," ",x).strip()
def inv(inv):
    if not inv:return ""
    p=[]
    for w,ps in inv.items():
        for z in ps:p.append((z,w))
    return " ".join(w for _,w in sorted(p))
def get(url,params=None,tries=4):
    for k in range(tries):
        try:
            r=S.get(url,params=params,timeout=35)
            if r.status_code==200:return r
            if r.status_code in (429,500,502,503,504):
                time.sleep(min(20,2**k)); continue
            return None
        except requests.RequestException: time.sleep(min(20,2**k))
    return None

def semscholar(title, d):
    # DOI first
    if d:
        r=get("https://api.semanticscholar.org/graph/v1/paper/DOI:"+quote(d,safe=""),
              {"fields":"title,abstract,externalIds,url"})
        if r:
            j=r.json()
            if j.get("abstract"):
                return {"source":"SEMANTIC_SCHOLAR_DOI","title":j.get("title",""),
                        "doi":doi((j.get("externalIds") or {}).get("DOI","")),
                        "abstract":clean(j.get("abstract")),"score":1.0}
    r=get("https://api.semanticscholar.org/graph/v1/paper/search",
          {"query":title,"limit":5,"fields":"title,abstract,externalIds,url"})
    if not r:return None
    best=None
    for j in r.json().get("data",[]):
        sc=sim(title,j.get("title",""))
        if (best is None or sc>best["score"]):
            best={"source":"SEMANTIC_SCHOLAR_TITLE","title":j.get("title",""),
                  "doi":doi((j.get("externalIds") or {}).get("DOI","")),
                  "abstract":clean(j.get("abstract")),"score":sc}
    return best if best and best["score"]>=.94 and best["abstract"] else None

def openalex_title(title):
    p={"search":title,"per-page":5}
    if EMAIL:p["mailto"]=EMAIL
    r=get("https://api.openalex.org/works",p)
    if not r:return None
    best=None
    for j in r.json().get("results",[]):
        sc=sim(title,j.get("title",""))
        x={"source":"OPENALEX_TITLE_RETRY","title":j.get("title",""),
           "doi":doi(j.get("doi","")),"abstract":inv(j.get("abstract_inverted_index")),"score":sc}
        if best is None or sc>best["score"]:best=x
    return best if best and best["score"]>=.94 and best["abstract"] else None

def crossref_title(title):
    r=get("https://api.crossref.org/works",{"query.bibliographic":title,"rows":5})
    if not r:return None
    best=None
    for j in r.json().get("message",{}).get("items",[]):
        tt=(j.get("title") or [""])[0]; sc=sim(title,tt)
        x={"source":"CROSSREF_BIBLIO_RETRY","title":tt,"doi":doi(j.get("DOI","")),
           "abstract":clean(j.get("abstract","")),"score":sc}
        if best is None or sc>best["score"]:best=x
    return best if best and best["score"]>=.96 and best["abstract"] else None

def arxiv_title(title):
    q='"'+title.replace('"','')+'"'
    r=get("https://export.arxiv.org/api/query",
          {"search_query":"ti:"+q,"start":0,"max_results":5})
    if not r:return None
    try:
        root=ET.fromstring(r.text)
        ns={"a":"http://www.w3.org/2005/Atom"}
        best=None
        for e in root.findall("a:entry",ns):
            tt=clean(e.findtext("a:title","",ns)); ab=clean(e.findtext("a:summary","",ns))
            sc=sim(title,tt)
            x={"source":"ARXIV_TITLE","title":tt,"doi":"","abstract":ab,"score":sc}
            if best is None or sc>best["score"]:best=x
        return best if best and best["score"]>=.94 and best["abstract"] else None
    except ET.ParseError:return None

if not INPUT.exists(): raise FileNotFoundError(INPUT)
df=pd.read_csv(INPUT)
if len(df)!=805: raise RuntimeError(f"Expected 805 rows, got {len(df)}")

# v10 unresolved means no recovered abstract. This includes title-signal queues if abstract recovery failed.
abscol="recovered_abstract"
un=df[df[abscol].fillna("").astype(str).str.strip().eq("")].copy()
if len(un)!=648:
    print(f"WARNING: expected 648 v10 unresolved; found {len(un)}. Continuing with actual unresolved set.")

cachep=OUT/"DV_Unresolved_Secondary_Recovery_Cache_v13.json"
try: cache=json.loads(cachep.read_text(encoding="utf-8")) if cachep.exists() else {}
except Exception: cache={}

rows=[]
for n,(_,r) in enumerate(un.iterrows(),1):
    title=s(r.get("title")); d=doi(r.get("doi")); key=d or "TITLE::"+nt(title)
    rec=cache.get(key)
    if rec is None:
        rec=None
        for fn in (lambda:semscholar(title,d),lambda:openalex_title(title),
                   lambda:crossref_title(title),lambda:arxiv_title(title)):
            x=fn()
            if x and x.get("abstract"): rec=x; break
            time.sleep(.12)
        if rec is None: rec={"source":"UNRESOLVED","title":"","doi":"","abstract":"","score":None}
        cache[key]=rec
        if n%20==0: cachep.write_text(json.dumps(cache,ensure_ascii=False,indent=2),encoding="utf-8")
    rr=r.to_dict()
    rd=doi(rec.get("doi"))
    rr.update({
      "v13_abstract":clean(rec.get("abstract")),
      "v13_source":rec.get("source","UNRESOLVED"),
      "v13_recovered_title":rec.get("title",""),
      "v13_recovered_doi":rd,
      "v13_title_similarity":rec.get("score"),
      "v13_doi_disagreement":bool(d and rd and d!=rd),
      "v13_status":"RECOVERED" if clean(rec.get("abstract")) else "UNRESOLVED",
      "v13_eligibility_decision":"",
      "v13_manual_screen_required":True
    })
    rows.append(rr)
cachep.write_text(json.dumps(cache,ensure_ascii=False,indent=2),encoding="utf-8")

m=pd.DataFrame(rows)
rec=m[m.v13_status=="RECOVERED"].copy()
still=m[m.v13_status=="UNRESOLVED"].copy()
mp=OUT/"DV_Unresolved_Secondary_Recovery_Master_v13.csv"
rp=OUT/"DV_Unresolved_Secondary_Recovered_v13.csv"
up=OUT/"DV_Unresolved_Still_Unresolved_v13.csv"
ap=OUT/"DV_Unresolved_Secondary_Recovery_Audit_v13.json"
m.to_csv(mp,index=False);rec.to_csv(rp,index=False);still.to_csv(up,index=False)
audit={
 "pipeline":"DV unresolved secondary recovery v13",
 "timestamp_utc":datetime.now(timezone.utc).isoformat(),
 "input_file":str(INPUT),"input_total":int(len(df)),
 "v10_unresolved_input":int(len(un)),
 "recovered_v13":int(len(rec)),"still_unresolved_v13":int(len(still)),
 "recovery_rate":round(len(rec)/len(un),4) if len(un) else 0,
 "source_counts":m.v13_source.value_counts(dropna=False).to_dict(),
 "doi_disagreements":int(m.v13_doi_disagreement.sum()),
 "synthetic_abstracts":False,"automatic_eligibility_decisions":0,
 "title_only_exclusion":False,"corpus_status":"NOT_FROZEN",
 "warning":"Recovered records require manual abstract adjudication. Still-unresolved records require metadata/full-text handling; they are not exclusions."
}
ap.write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding="utf-8")
print("="*70)
print("DV UNRESOLVED SECONDARY RECOVERY v13")
print("="*70)
print("v10 unresolved input :",len(un))
print("Recovered v13       :",len(rec))
print("Still unresolved     :",len(still))
print("DOI disagreements   :",int(m.v13_doi_disagreement.sum()))
print("Eligibility decisions: 0")
print("CORPUS STATUS        : NOT FROZEN")
print("\nOutputs:")
for p in (mp,rp,up,ap,cachep):print(" -",p)
