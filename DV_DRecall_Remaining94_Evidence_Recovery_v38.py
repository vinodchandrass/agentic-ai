#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DV D_RECALL publication remaining-94 evidence recovery v38.

Purpose:
  Recover source-backed abstracts/evidence for the remaining 94 publication-level
  D_RECALL_PROTECTION records. This script NEVER makes eligibility decisions.

Default input:
  D:\ACM\DV_DRecall_Publication_Remaining_v29.csv

Outputs:
  DV_DRecall_Remaining94_Evidence_Master_v38.csv
  DV_DRecall_Remaining94_Recovered_v38.csv
  DV_DRecall_Remaining94_StillUnresolved_v38.csv
  DV_DRecall_Remaining94_Evidence_Audit_v38.csv
"""

import os, re, time, html, json, csv
from pathlib import Path
from difflib import SequenceMatcher
import pandas as pd
import requests

INPUT = Path(r"D:\ACM\DV_DRecall_Publication_Remaining_v29.csv")
OUTDIR = INPUT.parent
UA = {"User-Agent": "DecisionValidityEvidenceRecovery/38 (systematic-review; scholarly metadata recovery)"}
TIMEOUT = 25

def norm_title(s):
    s = html.unescape(str(s or "")).lower()
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def sim(a,b):
    a,b=norm_title(a),norm_title(b)
    return SequenceMatcher(None,a,b).ratio() if a and b else 0.0

def clean_abstract(s):
    if not s: return ""
    s=html.unescape(str(s))
    s=re.sub(r"<jats:[^>]+>|</jats:[^>]+>|<[^>]+>"," ",s)
    return re.sub(r"\s+"," ",s).strip()

def doi_norm(x):
    x=str(x or "").strip()
    x=re.sub(r"^https?://(dx\.)?doi\.org/","",x,flags=re.I)
    return x.lower()

def get_json(url, params=None):
    try:
        r=requests.get(url,params=params,headers=UA,timeout=TIMEOUT)
        if r.status_code==200:
            return r.json()
    except Exception:
        pass
    return None

def semantic_by_doi(doi):
    if not doi: return None
    url="https://api.semanticscholar.org/graph/v1/paper/DOI:"+doi
    j=get_json(url,{"fields":"title,abstract,externalIds,url"})
    if j and j.get("abstract"):
        ext=j.get("externalIds") or {}
        return {"source":"SEMANTIC_SCHOLAR_DOI","title":j.get("title",""),
                "doi":ext.get("DOI",""),"abstract":clean_abstract(j.get("abstract")),
                "url":j.get("url",""),"similarity":1.0}
    return None

def openalex_by_doi(doi):
    if not doi: return None
    j=get_json("https://api.openalex.org/works/https://doi.org/"+doi)
    if not j: return None
    inv=j.get("abstract_inverted_index")
    if not inv: return None
    words=[]
    for w,poss in inv.items():
        for p in poss: words.append((p,w))
    abstract=" ".join(w for _,w in sorted(words))
    if not abstract: return None
    return {"source":"OPENALEX_DOI","title":j.get("title",""),
            "doi":((j.get("doi") or "").replace("https://doi.org/","")),
            "abstract":clean_abstract(abstract),"url":j.get("id",""),"similarity":1.0}

def crossref_by_doi(doi):
    if not doi: return None
    j=get_json("https://api.crossref.org/works/"+doi)
    if not j or "message" not in j: return None
    m=j["message"]; ab=clean_abstract(m.get("abstract",""))
    if not ab: return None
    title=(m.get("title") or [""])[0]
    return {"source":"CROSSREF_DOI","title":title,"doi":m.get("DOI",""),
            "abstract":ab,"url":m.get("URL",""),"similarity":1.0}

def semantic_title(title):
    j=get_json("https://api.semanticscholar.org/graph/v1/paper/search",
               {"query":title,"limit":5,"fields":"title,abstract,externalIds,url"})
    best=None
    for x in (j or {}).get("data",[]):
        s=sim(title,x.get("title",""))
        if s>=0.97 and x.get("abstract") and (best is None or s>best["similarity"]):
            ext=x.get("externalIds") or {}
            best={"source":"SEMANTIC_SCHOLAR_TITLE","title":x.get("title",""),
                  "doi":ext.get("DOI",""),"abstract":clean_abstract(x.get("abstract")),
                  "url":x.get("url",""),"similarity":s}
    return best

def openalex_title(title):
    j=get_json("https://api.openalex.org/works",{"search":title,"per-page":5})
    best=None
    for x in (j or {}).get("results",[]):
        s=sim(title,x.get("title",""))
        inv=x.get("abstract_inverted_index")
        if s>=0.97 and inv:
            words=[]
            for w,poss in inv.items():
                for p in poss: words.append((p,w))
            ab=clean_abstract(" ".join(w for _,w in sorted(words)))
            if ab and (best is None or s>best["similarity"]):
                best={"source":"OPENALEX_TITLE","title":x.get("title",""),
                      "doi":((x.get("doi") or "").replace("https://doi.org/","")),
                      "abstract":ab,"url":x.get("id",""),"similarity":s}
    return best

def crossref_title(title):
    j=get_json("https://api.crossref.org/works",{"query.title":title,"rows":5})
    best=None
    for x in ((j or {}).get("message") or {}).get("items",[]):
        rt=(x.get("title") or [""])[0]; s=sim(title,rt)
        ab=clean_abstract(x.get("abstract",""))
        if s>=0.98 and ab and (best is None or s>best["similarity"]):
            best={"source":"CROSSREF_TITLE","title":rt,"doi":x.get("DOI",""),
                  "abstract":ab,"url":x.get("URL",""),"similarity":s}
    return best

def arxiv_title(title):
    # Export API is used only as strict title fallback.
    try:
        import urllib.parse, xml.etree.ElementTree as ET
        q=urllib.parse.quote('ti:"'+title.replace('"',"")+'"')
        r=requests.get("https://export.arxiv.org/api/query?search_query="+q+"&start=0&max_results=5",
                       headers=UA,timeout=TIMEOUT)
        if r.status_code!=200: return None
        root=ET.fromstring(r.text)
        ns={"a":"http://www.w3.org/2005/Atom"}
        best=None
        for e in root.findall("a:entry",ns):
            rt=(e.findtext("a:title",default="",namespaces=ns) or "").replace("\n"," ")
            ab=clean_abstract(e.findtext("a:summary",default="",namespaces=ns))
            s=sim(title,rt)
            if s>=0.97 and ab and (best is None or s>best["similarity"]):
                best={"source":"ARXIV_TITLE","title":rt,"doi":"","abstract":ab,
                      "url":e.findtext("a:id",default="",namespaces=ns),"similarity":s}
        return best
    except Exception:
        return None

def recover(row):
    title=str(row.get("title","") or "")
    doi=doi_norm(row.get("doi",""))
    funcs=[]
    if doi: funcs=[semantic_by_doi,openalex_by_doi,crossref_by_doi]
    for fn in funcs:
        z=fn(doi); time.sleep(0.12)
        if z: return z
    for fn in [semantic_title,openalex_title,crossref_title,arxiv_title]:
        z=fn(title); time.sleep(0.12)
        if z: return z
    return None

def main():
    if not INPUT.exists():
        raise SystemExit(f"Missing input: {INPUT}")
    df=pd.read_csv(INPUT)
    if len(df)!=94:
        raise SystemExit(f"Expected exactly 94 records; found {len(df)}")
    rows=[]
    for n,(_,r) in enumerate(df.iterrows(),1):
        z=recover(r)
        o=r.to_dict()
        if z:
            o.update(V38_STATUS="EVIDENCE_RECOVERED",V38_SOURCE=z["source"],
                     V38_RECOVERED_TITLE=z["title"],V38_RECOVERED_DOI=z["doi"],
                     V38_TITLE_SIMILARITY=z["similarity"],V38_ABSTRACT=z["abstract"],
                     V38_EVIDENCE_URL=z["url"])
        else:
            o.update(V38_STATUS="STILL_UNRESOLVED",V38_SOURCE="NO_EVIDENCE",
                     V38_RECOVERED_TITLE="",V38_RECOVERED_DOI="",
                     V38_TITLE_SIMILARITY="",V38_ABSTRACT="",V38_EVIDENCE_URL="")
        orig=doi_norm(r.get("doi","")); got=doi_norm(o["V38_RECOVERED_DOI"])
        o["V38_DOI_DISAGREEMENT"]=bool(orig and got and orig!=got)
        o["V38_ELIGIBILITY_DECISION"]=""
        o["V38_TITLE_ONLY_EXCLUSION"]=False
        o["V38_MANUAL_ADJUDICATION_REQUIRED"]=True
        rows.append(o)
        print(f"{n:02d}/94 {o['V38_STATUS']} {o['V38_SOURCE']} | {str(r.get('title',''))[:90]}")
    out=pd.DataFrame(rows)
    master=OUTDIR/"DV_DRecall_Remaining94_Evidence_Master_v38.csv"
    recovered=OUTDIR/"DV_DRecall_Remaining94_Recovered_v38.csv"
    unresolved=OUTDIR/"DV_DRecall_Remaining94_StillUnresolved_v38.csv"
    audit=OUTDIR/"DV_DRecall_Remaining94_Evidence_Audit_v38.csv"
    out.to_csv(master,index=False)
    out[out.V38_STATUS=="EVIDENCE_RECOVERED"].to_csv(recovered,index=False)
    out[out.V38_STATUS=="STILL_UNRESOLVED"].to_csv(unresolved,index=False)
    stats={
      "input_records":94,
      "recovered_evidence":int((out.V38_STATUS=="EVIDENCE_RECOVERED").sum()),
      "still_unresolved":int((out.V38_STATUS=="STILL_UNRESOLVED").sum()),
      "recovery_rate":round(float((out.V38_STATUS=="EVIDENCE_RECOVERED").mean()),4),
      "source_counts":out.V38_SOURCE.value_counts().to_dict(),
      "doi_disagreements":int(out.V38_DOI_DISAGREEMENT.sum()),
      "synthetic_abstracts":0,
      "automatic_eligibility_decisions":0,
      "title_only_exclusions":0,
      "manual_adjudication_required":94,
      "corpus_status":"NOT_FROZEN"
    }
    with open(audit,"w",newline="",encoding="utf-8-sig") as f:
        w=csv.writer(f); w.writerow(["field","value"])
        for k,v in stats.items(): w.writerow([k,json.dumps(v) if isinstance(v,dict) else v])
    print(json.dumps(stats,indent=2))

if __name__=="__main__":
    main()
