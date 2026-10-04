#!/usr/bin/env python
"""
DV_Final_Unresolved_Recovery_v20.py
Final evidence-recovery pass for the 309 records still unresolved after v13.

Default input:
  D:\ACM\DV_Unresolved_Still_Unresolved_v13.csv

Sources:
  1. Semantic Scholar DOI/title retry
  2. OpenAlex DOI/title retry
  3. Crossref DOI/title metadata/abstract retry
  4. arXiv title retry
  5. Unpaywall OA-location lookup (when OPENALEX_EMAIL is set)

No synthetic abstracts. No eligibility decisions.
"""
import os, re, sys, json, time, html
from pathlib import Path
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import quote
import xml.etree.ElementTree as ET
import pandas as pd
import requests

INPUT=Path(sys.argv[1]) if len(sys.argv)>1 else Path(r"D:\ACM\DV_Unresolved_Still_Unresolved_v13.csv")
OUT=INPUT.parent
EMAIL=os.getenv("OPENALEX_EMAIL","").strip()
S=requests.Session()
S.headers.update({"User-Agent":f"DV-final-recovery/20.0 ({EMAIL or 'systematic-review'})"})

def st(x): return "" if pd.isna(x) else str(x)
def c(x):
    x=html.unescape(st(x)); x=re.sub(r"<[^>]+>"," ",x)
    return re.sub(r"\s+"," ",x).strip()
def nd(x):
    x=st(x).strip().lower()
    return re.sub(r"^https?://(dx\.)?doi\.org/","",x)
def nt(x):
    x=c(x).lower(); x=re.sub(r"[^a-z0-9]+"," ",x)
    return re.sub(r"\s+"," ",x).strip()
def sim(a,b): return SequenceMatcher(None,nt(a),nt(b)).ratio()
def inv(x):
    if not x:return ""
    z=[]
    for w,ps in x.items():
        for p in ps:z.append((p,w))
    return " ".join(w for _,w in sorted(z))
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

def semantic(title,doi):
    if doi:
        r=get("https://api.semanticscholar.org/graph/v1/paper/DOI:"+quote(doi,safe=""),
              {"fields":"title,abstract,externalIds,url,openAccessPdf"})
        if r:
            j=r.json()
            if c(j.get("abstract")):
                return ("SEMANTIC_SCHOLAR_DOI",j.get("title",""),
                        nd((j.get("externalIds") or {}).get("DOI","")),
                        c(j.get("abstract")),1.0,
                        ((j.get("openAccessPdf") or {}).get("url") or ""))
    r=get("https://api.semanticscholar.org/graph/v1/paper/search",
          {"query":title,"limit":10,"fields":"title,abstract,externalIds,url,openAccessPdf"})
    if not r:return None
    best=None
    for j in r.json().get("data",[]):
        sc=sim(title,j.get("title",""))
        z=("SEMANTIC_SCHOLAR_TITLE",j.get("title",""),
           nd((j.get("externalIds") or {}).get("DOI","")),
           c(j.get("abstract")),sc,((j.get("openAccessPdf") or {}).get("url") or ""))
        if best is None or sc>best[4]:best=z
    return best if best and best[4]>=.96 and best[3] else None

def openalex(title,doi):
    params={"mailto":EMAIL} if EMAIL else {}
    if doi:
        r=get("https://api.openalex.org/works/https://doi.org/"+quote(doi,safe="/:"),params)
        if r:
            j=r.json(); ab=inv(j.get("abstract_inverted_index"))
            if ab:
                oa=((j.get("best_oa_location") or {}).get("pdf_url") or
                    (j.get("best_oa_location") or {}).get("landing_page_url") or "")
                return ("OPENALEX_DOI",j.get("title",""),nd(j.get("doi","")),ab,1.0,oa)
    p={"search":title,"per-page":10}
    if EMAIL:p["mailto"]=EMAIL
    r=get("https://api.openalex.org/works",p)
    if not r:return None
    best=None
    for j in r.json().get("results",[]):
        sc=sim(title,j.get("title","")); ab=inv(j.get("abstract_inverted_index"))
        oa=((j.get("best_oa_location") or {}).get("pdf_url") or
            (j.get("best_oa_location") or {}).get("landing_page_url") or "")
        z=("OPENALEX_TITLE",j.get("title",""),nd(j.get("doi","")),ab,sc,oa)
        if best is None or sc>best[4]:best=z
    return best if best and best[4]>=.96 and best[3] else None

def crossref(title,doi):
    if doi:
        r=get("https://api.crossref.org/works/"+quote(doi,safe=""))
        if r:
            j=r.json().get("message",{}); ab=c(j.get("abstract",""))
            if ab:
                return ("CROSSREF_DOI",(j.get("title") or [""])[0],nd(j.get("DOI","")),ab,1.0,"")
    r=get("https://api.crossref.org/works",{"query.bibliographic":title,"rows":10})
    if not r:return None
    best=None
    for j in r.json().get("message",{}).get("items",[]):
        tt=(j.get("title") or [""])[0]; sc=sim(title,tt); ab=c(j.get("abstract",""))
        z=("CROSSREF_TITLE",tt,nd(j.get("DOI","")),ab,sc,"")
        if best is None or sc>best[4]:best=z
    return best if best and best[4]>=.97 and best[3] else None

def arxiv(title):
    r=get("https://export.arxiv.org/api/query",
          {"search_query":'ti:"'+title.replace('"','')+'"',"start":0,"max_results":10})
    if not r:return None
    try:
        root=ET.fromstring(r.text); ns={"a":"http://www.w3.org/2005/Atom"}
        best=None
        for e in root.findall("a:entry",ns):
            tt=c(e.findtext("a:title","",ns)); ab=c(e.findtext("a:summary","",ns))
            sc=sim(title,tt); url=e.findtext("a:id","",ns)
            z=("ARXIV_TITLE",tt,"",ab,sc,url)
            if best is None or sc>best[4]:best=z
        return best if best and best[4]>=.96 and best[3] else None
    except ET.ParseError:return None

def unpaywall(doi):
    if not doi or not EMAIL:return ""
    r=get("https://api.unpaywall.org/v2/"+quote(doi,safe=""),{"email":EMAIL})
    if not r:return ""
    j=r.json(); b=j.get("best_oa_location") or {}
    return b.get("url_for_pdf") or b.get("url") or ""

if not INPUT.exists(): raise FileNotFoundError(INPUT)
df=pd.read_csv(INPUT)
if len(df)!=309:
    print(f"WARNING expected 309 rows; found {len(df)}. Continuing with actual rows.")

rows=[]; cache={}
for n,(_,r) in enumerate(df.iterrows(),1):
    title=st(r.get("title")); doi=nd(r.get("doi"))
    found=None
    for fn in (lambda:semantic(title,doi),lambda:openalex(title,doi),
               lambda:crossref(title,doi),lambda:arxiv(title)):
        found=fn()
        if found:break
        time.sleep(.10)
    oa=unpaywall(doi)
    rr=r.to_dict()
    if found:
        source,rt,rd,ab,score,url=found
        rr.update({"v20_status":"RECOVERED_ABSTRACT","v20_source":source,
                   "v20_recovered_title":rt,"v20_recovered_doi":rd,
                   "v20_title_similarity":score,"v20_abstract":ab,
                   "v20_evidence_url":url or oa,
                   "v20_doi_disagreement":bool(doi and rd and doi!=rd)})
    else:
        rr.update({"v20_status":"METADATA_OR_FULLTEXT_REQUIRED","v20_source":"",
                   "v20_recovered_title":"","v20_recovered_doi":"",
                   "v20_title_similarity":"","v20_abstract":"",
                   "v20_evidence_url":oa,
                   "v20_doi_disagreement":False})
    rr["v20_eligibility_decision"]=""
    rr["v20_manual_screen_required"]=True
    rows.append(rr)
    if n%25==0: print(f"{n}/{len(df)} processed")

m=pd.DataFrame(rows)
rec=m[m.v20_status=="RECOVERED_ABSTRACT"].copy()
still=m[m.v20_status!="RECOVERED_ABSTRACT"].copy()

mp=OUT/"DV_Final_Unresolved_Recovery_Master_v20.csv"
rp=OUT/"DV_Final_Unresolved_Recovered_v20.csv"
up=OUT/"DV_Final_Unresolved_FulltextQueue_v20.csv"
ap=OUT/"DV_Final_Unresolved_Recovery_Audit_v20.json"
m.to_csv(mp,index=False); rec.to_csv(rp,index=False); still.to_csv(up,index=False)
audit={
 "pipeline":"DV final unresolved evidence recovery v20",
 "timestamp_utc":datetime.now(timezone.utc).isoformat(),
 "input_records":len(df),
 "recovered_abstracts":len(rec),
 "fulltext_or_metadata_queue":len(still),
 "recovery_rate":round(len(rec)/len(df),4) if len(df) else 0,
 "source_counts":m.v20_source.replace("", "NO_ABSTRACT").value_counts().to_dict(),
 "oa_evidence_urls_for_remaining":int(still.v20_evidence_url.fillna("").str.len().gt(0).sum()),
 "doi_disagreements":int(m.v20_doi_disagreement.sum()),
 "synthetic_abstracts":False,
 "automatic_eligibility_decisions":0,
 "title_only_exclusion":False,
 "corpus_status":"NOT_FROZEN",
 "warning":"No unresolved record is excluded. Recovered abstracts require semantic adjudication; remaining records require metadata/full-text review."
}
ap.write_text(json.dumps(audit,indent=2),encoding="utf-8")
print(json.dumps(audit,indent=2))
