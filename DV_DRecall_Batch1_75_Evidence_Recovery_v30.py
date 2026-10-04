#!/usr/bin/env python
"""
DV_DRecall_Batch1_75_Evidence_Recovery_v30.py

Evidence recovery for the 75 publication-level D_RECALL_PROTECTION records
prepared in v29.

Default input:
 D:\ACM\DV_DRecall_Publication_Batch1_v29.csv

Outputs:
 DV_DRecall_Batch1_75_Evidence_Master_v30.csv
 DV_DRecall_Batch1_75_Recovered_v30.csv
 DV_DRecall_Batch1_75_StillUnresolved_v30.csv
 DV_DRecall_Batch1_75_Evidence_Audit_v30.csv

Rules:
- No synthetic abstracts.
- No automatic eligibility decisions.
- No title-only exclusions.
- DOI match preferred.
- Title fallback requires strict near-exact matching.
"""
import os, re, sys, json, time, html, csv
from pathlib import Path
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import quote
import xml.etree.ElementTree as ET
import pandas as pd
import requests

INPUT = Path(sys.argv[1]) if len(sys.argv)>1 else Path(r"D:\ACM\DV_DRecall_Publication_Batch1_v29.csv")
OUT = INPUT.parent
EMAIL = os.getenv("OPENALEX_EMAIL","").strip()
S = requests.Session()
S.headers.update({"User-Agent": f"DV-systematic-review-v30 ({EMAIL or 'evidence-recovery'})"})

def st(x): return "" if pd.isna(x) else str(x)
def clean(x):
    x=html.unescape(st(x))
    x=re.sub(r"<[^>]+>"," ",x)
    return re.sub(r"\s+"," ",x).strip()
def norm_title(x):
    return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9]+"," ",clean(x).lower())).strip()
def sim(a,b): return SequenceMatcher(None,norm_title(a),norm_title(b)).ratio()
def norm_doi(x):
    x=st(x).strip().lower()
    x=re.sub(r"^https?://(dx\.)?doi\.org/","",x)
    return x
def inv_abs(x):
    if not x: return ""
    z=[]
    for word, positions in x.items():
        for pos in positions: z.append((pos,word))
    return " ".join(w for _,w in sorted(z))
def get(url,params=None,tries=4):
    for k in range(tries):
        try:
            r=S.get(url,params=params,timeout=35)
            if r.status_code==200: return r
            if r.status_code in (429,500,502,503,504):
                time.sleep(min(20,2**k)); continue
            return None
        except requests.RequestException:
            time.sleep(min(20,2**k))
    return None

def semantic(title,d):
    if d:
        r=get("https://api.semanticscholar.org/graph/v1/paper/DOI:"+quote(d,safe=""),
              {"fields":"title,abstract,externalIds,url,openAccessPdf"})
        if r:
            j=r.json(); ab=clean(j.get("abstract"))
            if ab:
                return ("SEMANTIC_SCHOLAR_DOI",j.get("title",""),
                        norm_doi((j.get("externalIds") or {}).get("DOI","")),
                        ab,1.0,((j.get("openAccessPdf") or {}).get("url") or j.get("url") or ""))
    r=get("https://api.semanticscholar.org/graph/v1/paper/search",
          {"query":title,"limit":10,"fields":"title,abstract,externalIds,url,openAccessPdf"})
    if not r:return None
    best=None
    for j in r.json().get("data",[]):
        sc=sim(title,j.get("title",""))
        z=("SEMANTIC_SCHOLAR_TITLE",j.get("title",""),
           norm_doi((j.get("externalIds") or {}).get("DOI","")),
           clean(j.get("abstract")),sc,
           ((j.get("openAccessPdf") or {}).get("url") or j.get("url") or ""))
        if best is None or sc>best[4]: best=z
    return best if best and best[4]>=.97 and best[3] else None

def openalex(title,d):
    if d:
        params={"mailto":EMAIL} if EMAIL else {}
        r=get("https://api.openalex.org/works/https://doi.org/"+quote(d,safe="/:"),params)
        if r:
            j=r.json(); ab=inv_abs(j.get("abstract_inverted_index"))
            if ab:
                loc=j.get("best_oa_location") or {}
                return ("OPENALEX_DOI",j.get("title",""),norm_doi(j.get("doi","")),ab,1.0,
                        loc.get("pdf_url") or loc.get("landing_page_url") or "")
    params={"search":title,"per-page":10}
    if EMAIL: params["mailto"]=EMAIL
    r=get("https://api.openalex.org/works",params)
    if not r:return None
    best=None
    for j in r.json().get("results",[]):
        sc=sim(title,j.get("title",""))
        loc=j.get("best_oa_location") or {}
        z=("OPENALEX_TITLE",j.get("title",""),norm_doi(j.get("doi","")),
           inv_abs(j.get("abstract_inverted_index")),sc,
           loc.get("pdf_url") or loc.get("landing_page_url") or "")
        if best is None or sc>best[4]:best=z
    return best if best and best[4]>=.97 and best[3] else None

def crossref(title,d):
    if d:
        r=get("https://api.crossref.org/works/"+quote(d,safe=""))
        if r:
            j=r.json().get("message",{})
            ab=clean(j.get("abstract",""))
            if ab:
                tt=(j.get("title") or [""])[0]
                return ("CROSSREF_DOI",tt,norm_doi(j.get("DOI","")),ab,1.0,j.get("URL",""))
    r=get("https://api.crossref.org/works",{"query.bibliographic":title,"rows":10})
    if not r:return None
    best=None
    for j in r.json().get("message",{}).get("items",[]):
        tt=(j.get("title") or [""])[0]; sc=sim(title,tt)
        z=("CROSSREF_TITLE",tt,norm_doi(j.get("DOI","")),clean(j.get("abstract","")),sc,j.get("URL",""))
        if best is None or sc>best[4]:best=z
    return best if best and best[4]>=.98 and best[3] else None

def arxiv(title):
    r=get("https://export.arxiv.org/api/query",
          {"search_query":'ti:"'+title.replace('"','')+'"',"start":0,"max_results":10})
    if not r:return None
    try:
        root=ET.fromstring(r.text); ns={"a":"http://www.w3.org/2005/Atom"}; best=None
        for e in root.findall("a:entry",ns):
            tt=clean(e.findtext("a:title","",ns)); ab=clean(e.findtext("a:summary","",ns))
            sc=sim(title,tt)
            z=("ARXIV_TITLE",tt,"",ab,sc,e.findtext("a:id","",ns))
            if best is None or sc>best[4]:best=z
        return best if best and best[4]>=.97 and best[3] else None
    except ET.ParseError:return None

if not INPUT.exists(): raise FileNotFoundError(INPUT)
df=pd.read_csv(INPUT)
if len(df)!=75: raise ValueError(f"Expected 75 records, found {len(df)}")

rows=[]
for n,(_,r) in enumerate(df.iterrows(),1):
    title=st(r.get("title")); d=norm_doi(r.get("doi")); found=None
    for fn in (lambda:semantic(title,d),lambda:openalex(title,d),
               lambda:crossref(title,d),lambda:arxiv(title)):
        found=fn()
        if found:break
        time.sleep(.10)
    rr=r.to_dict()
    if found:
        src,rt,rd,ab,score,url=found
        rr.update(V30_STATUS="RECOVERED_EVIDENCE",V30_SOURCE=src,
                  V30_RECOVERED_TITLE=rt,V30_RECOVERED_DOI=rd,
                  V30_TITLE_SIMILARITY=score,V30_ABSTRACT=ab,V30_EVIDENCE_URL=url,
                  V30_DOI_DISAGREEMENT=bool(d and rd and d!=rd))
    else:
        rr.update(V30_STATUS="STILL_UNRESOLVED",V30_SOURCE="",
                  V30_RECOVERED_TITLE="",V30_RECOVERED_DOI="",
                  V30_TITLE_SIMILARITY="",V30_ABSTRACT="",V30_EVIDENCE_URL="",
                  V30_DOI_DISAGREEMENT=False)
    rr["V30_ELIGIBILITY_DECISION"]=""
    rr["V30_TITLE_ONLY_EXCLUSION"]=False
    rr["V30_MANUAL_ADJUDICATION_REQUIRED"]=True
    rows.append(rr)
    print(f"{n:02d}/75 {rr['V30_STATUS']} | {title[:90]}")

m=pd.DataFrame(rows)
rec=m[m.V30_STATUS.eq("RECOVERED_EVIDENCE")].copy()
un=m[m.V30_STATUS.eq("STILL_UNRESOLVED")].copy()

master=OUT/"DV_DRecall_Batch1_75_Evidence_Master_v30.csv"
rp=OUT/"DV_DRecall_Batch1_75_Recovered_v30.csv"
up=OUT/"DV_DRecall_Batch1_75_StillUnresolved_v30.csv"
ap=OUT/"DV_DRecall_Batch1_75_Evidence_Audit_v30.csv"
m.to_csv(master,index=False); rec.to_csv(rp,index=False); un.to_csv(up,index=False)

audit={
 "pipeline":"DV D_RECALL_PROTECTION publication Batch1 evidence recovery v30",
 "timestamp_utc":datetime.now(timezone.utc).isoformat(),
 "input_records":len(m),
 "recovered_evidence":len(rec),
 "still_unresolved":len(un),
 "recovery_rate":round(len(rec)/len(m),4),
 "source_counts":m.V30_SOURCE.replace("","NO_EVIDENCE").value_counts().to_dict(),
 "doi_disagreements":int(m.V30_DOI_DISAGREEMENT.fillna(False).astype(bool).sum()),
 "synthetic_abstracts":False,
 "automatic_eligibility_decisions":0,
 "title_only_exclusions":0,
 "manual_adjudication_required":True,
 "corpus_status":"NOT_FROZEN"
}
with ap.open("w",newline="",encoding="utf-8-sig") as f:
    w=csv.writer(f); w.writerow(["field","value"])
    for k,v in audit.items():
        w.writerow([k,json.dumps(v) if isinstance(v,dict) else v])
print("\n"+json.dumps(audit,indent=2))
