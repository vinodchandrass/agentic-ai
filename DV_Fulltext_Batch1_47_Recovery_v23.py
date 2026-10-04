#!/usr/bin/env python
"""
DV_Fulltext_Batch1_47_Recovery_v23.py
Evidence recovery for the 47 highest-priority records from v22.

Default input:
 D:\ACM\DV_241_Fulltext_Retrieval_Batch1_v22.csv

Goal:
 Recover legitimate abstract/full-text evidence where possible.
 No synthetic abstracts. No eligibility decisions. No title-only exclusions.
"""
import os,re,sys,json,time,html,csv
from pathlib import Path
from datetime import datetime,timezone
from difflib import SequenceMatcher
from urllib.parse import quote
import xml.etree.ElementTree as ET
import pandas as pd, requests

INPUT=Path(sys.argv[1]) if len(sys.argv)>1 else Path(r"D:\ACM\DV_241_Fulltext_Retrieval_Batch1_v22.csv")
OUT=INPUT.parent
EMAIL=os.getenv("OPENALEX_EMAIL","").strip()
S=requests.Session(); S.headers.update({"User-Agent":f"DV-fulltext-recovery/23 ({EMAIL or 'systematic-review'})"})

def st(x): return "" if pd.isna(x) else str(x)
def clean(x):
    x=html.unescape(st(x)); x=re.sub(r"<[^>]+>"," ",x)
    return re.sub(r"\s+"," ",x).strip()
def doi(x): return re.sub(r"^https?://(dx\.)?doi\.org/","",st(x).strip().lower())
def nt(x):
    return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9]+"," ",clean(x).lower())).strip()
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

def semantic(title,d):
    if d:
        r=get("https://api.semanticscholar.org/graph/v1/paper/DOI:"+quote(d,safe=""),
              {"fields":"title,abstract,externalIds,url,openAccessPdf"})
        if r:
            j=r.json(); ab=clean(j.get("abstract"))
            if ab:
                return ("SEMANTIC_SCHOLAR_DOI",j.get("title",""),
                        doi((j.get("externalIds") or {}).get("DOI","")),ab,1.0,
                        ((j.get("openAccessPdf") or {}).get("url") or j.get("url") or ""))
    r=get("https://api.semanticscholar.org/graph/v1/paper/search",
          {"query":title,"limit":10,"fields":"title,abstract,externalIds,url,openAccessPdf"})
    if not r:return None
    best=None
    for j in r.json().get("data",[]):
        sc=sim(title,j.get("title",""))
        z=("SEMANTIC_SCHOLAR_TITLE",j.get("title",""),
           doi((j.get("externalIds") or {}).get("DOI","")),clean(j.get("abstract")),sc,
           ((j.get("openAccessPdf") or {}).get("url") or j.get("url") or ""))
        if best is None or sc>best[4]:best=z
    return best if best and best[4]>=.97 and best[3] else None

def openalex(title,d):
    if d:
        p={"mailto":EMAIL} if EMAIL else {}
        r=get("https://api.openalex.org/works/https://doi.org/"+quote(d,safe="/:"),p)
        if r:
            j=r.json(); ab=inv(j.get("abstract_inverted_index"))
            if ab:
                loc=j.get("best_oa_location") or {}
                return ("OPENALEX_DOI",j.get("title",""),doi(j.get("doi","")),ab,1.0,
                        loc.get("pdf_url") or loc.get("landing_page_url") or "")
    p={"search":title,"per-page":10}
    if EMAIL:p["mailto"]=EMAIL
    r=get("https://api.openalex.org/works",p)
    if not r:return None
    best=None
    for j in r.json().get("results",[]):
        sc=sim(title,j.get("title","")); loc=j.get("best_oa_location") or {}
        z=("OPENALEX_TITLE",j.get("title",""),doi(j.get("doi","")),
           inv(j.get("abstract_inverted_index")),sc,
           loc.get("pdf_url") or loc.get("landing_page_url") or "")
        if best is None or sc>best[4]:best=z
    return best if best and best[4]>=.97 and best[3] else None

def crossref(title,d):
    r=get("https://api.crossref.org/works",{"query.bibliographic":title,"rows":10})
    if not r:return None
    best=None
    for j in r.json().get("message",{}).get("items",[]):
        tt=(j.get("title") or [""])[0]; sc=sim(title,tt)
        z=("CROSSREF_TITLE",tt,doi(j.get("DOI","")),clean(j.get("abstract","")),sc,
           j.get("URL",""))
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
            sc=sim(title,tt); z=("ARXIV_TITLE",tt,"",ab,sc,e.findtext("a:id","",ns))
            if best is None or sc>best[4]:best=z
        return best if best and best[4]>=.97 and best[3] else None
    except ET.ParseError:return None

if not INPUT.exists(): raise FileNotFoundError(INPUT)
df=pd.read_csv(INPUT)
if len(df)!=47: print(f"WARNING expected 47, found {len(df)}")

rows=[]
for n,(_,r) in enumerate(df.iterrows(),1):
    title=st(r.get("title")); d=doi(r.get("doi")); found=None
    for fn in (lambda:semantic(title,d),lambda:openalex(title,d),
               lambda:crossref(title,d),lambda:arxiv(title)):
        found=fn()
        if found:break
        time.sleep(.12)
    rr=r.to_dict()
    if found:
        src,rt,rd,ab,score,url=found
        rr.update(v23_status="RECOVERED_EVIDENCE",v23_source=src,
                  v23_recovered_title=rt,v23_recovered_doi=rd,
                  v23_title_similarity=score,v23_abstract=ab,v23_evidence_url=url,
                  v23_doi_disagreement=bool(d and rd and d!=rd))
    else:
        rr.update(v23_status="FULLTEXT_STILL_REQUIRED",v23_source="",
                  v23_recovered_title="",v23_recovered_doi="",
                  v23_title_similarity="",v23_abstract="",v23_evidence_url="",
                  v23_doi_disagreement=False)
    rr["v23_eligibility_decision"]=""
    rr["v23_manual_adjudication_required"]=True
    rows.append(rr)
    print(f"{n}/{len(df)} {rr['v23_status']}")

m=pd.DataFrame(rows); rec=m[m.v23_status=="RECOVERED_EVIDENCE"].copy()
un=m[m.v23_status=="FULLTEXT_STILL_REQUIRED"].copy()
mp=OUT/"DV_Batch1_47_Evidence_Recovery_Master_v23.csv"
rp=OUT/"DV_Batch1_47_Recovered_Evidence_v23.csv"
up=OUT/"DV_Batch1_47_Still_Fulltext_v23.csv"
ap=OUT/"DV_Batch1_47_Evidence_Recovery_Audit_v23.csv"
m.to_csv(mp,index=False);rec.to_csv(rp,index=False);un.to_csv(up,index=False)
audit={
 "pipeline":"DV Batch1 47 evidence recovery v23","timestamp_utc":datetime.now(timezone.utc).isoformat(),
 "input_records":len(m),"recovered_evidence":len(rec),"still_fulltext_required":len(un),
 "recovery_rate":round(len(rec)/len(m),4) if len(m) else 0,
 "source_counts":m.v23_source.replace("","NO_EVIDENCE").value_counts().to_dict(),
 "doi_disagreements":int(m.v23_doi_disagreement.sum()),
 "synthetic_abstracts":False,"automatic_eligibility_decisions":0,
 "title_only_exclusions":0,"corpus_status":"NOT_FROZEN"
}
with ap.open("w",newline="",encoding="utf-8-sig") as f:
    w=csv.writer(f);w.writerow(["field","value"])
    for k,v in audit.items():w.writerow([k,json.dumps(v) if isinstance(v,dict) else v])
print("\n",json.dumps(audit,indent=2))
