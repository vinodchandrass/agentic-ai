import pandas as pd
import json, re, sys
from pathlib import Path
from datetime import datetime, timezone

DEFAULT_V2 = Path(r'D:\ACM\Scopus_V2_Production_Candidate.csv')
DEFAULT_V2B = Path(r'D:\ACM\Scopus_V2B_StateCommit_Candidate.csv')
OUTDIR = Path(r'D:\ACM')


def norm_text(x):
    if pd.isna(x): return ''
    return re.sub(r'[^a-z0-9]+', ' ', str(x).lower()).strip()

def norm_doi(x):
    if pd.isna(x): return ''
    s=str(x).strip().lower()
    s=re.sub(r'^https?://(dx\.)?doi\.org/', '', s)
    return s

def pick_col(df, candidates):
    low={c.lower():c for c in df.columns}
    for cand in candidates:
        if cand.lower() in low: return low[cand.lower()]
    for c in df.columns:
        cl=c.lower()
        if any(cand.lower() in cl for cand in candidates): return c
    return None

def load(path, label):
    df=pd.read_csv(path, dtype=str, keep_default_na=False)
    df['search_family']=label
    return df

def main():
    v2 = Path(sys.argv[1]) if len(sys.argv)>1 else DEFAULT_V2
    v2b = Path(sys.argv[2]) if len(sys.argv)>2 else DEFAULT_V2B
    outdir = Path(sys.argv[3]) if len(sys.argv)>3 else OUTDIR
    outdir.mkdir(parents=True, exist_ok=True)

    a=load(v2,'V2')
    b=load(v2b,'V2B')
    cols=list(dict.fromkeys(list(a.columns)+list(b.columns)))
    a=a.reindex(columns=cols, fill_value='')
    b=b.reindex(columns=cols, fill_value='')
    raw=pd.concat([a,b], ignore_index=True)

    eid_col=pick_col(raw,['eid'])
    doi_col=pick_col(raw,['doi'])
    title_col=pick_col(raw,['title','dc:title'])
    if not title_col:
        raise RuntimeError('No title column detected.')

    raw['_eid']=raw[eid_col].str.strip().str.lower() if eid_col else ''
    raw['_doi']=raw[doi_col].map(norm_doi) if doi_col else ''
    raw['_title']=raw[title_col].map(norm_text)

    # Dedup hierarchy: EID -> DOI -> normalized title. Keep first occurrence (V2 first),
    # but preserve all source-family membership in search_families.
    groups={}
    for i,row in raw.iterrows():
        keys=[]
        if row['_eid']: keys.append(('eid',row['_eid']))
        if row['_doi']: keys.append(('doi',row['_doi']))
        if row['_title']: keys.append(('title',row['_title']))
        existing=None
        for k in keys:
            if k in groups:
                existing=groups[k]; break
        if existing is None:
            existing=i
        for k in keys: groups[k]=existing
        raw.at[i,'_master_idx']=existing

    # Transitive consolidation in case later identifiers bridge groups.
    changed=True
    while changed:
        changed=False
        mapping={}
        for i,row in raw.iterrows():
            root=int(row['_master_idx'])
            for val,typ in [(row['_eid'],'eid'),(row['_doi'],'doi'),(row['_title'],'title')]:
                if val:
                    k=(typ,val)
                    if k in mapping and mapping[k] != root:
                        new=min(root,mapping[k]); old=max(root,mapping[k])
                        raw.loc[raw['_master_idx']==old,'_master_idx']=new
                        root=new; changed=True
                    mapping[k]=root

    records=[]
    overlap_rows=[]
    for root,g in raw.groupby('_master_idx', sort=False):
        base=g.iloc[0].copy()
        fams=sorted(set(g['search_family']))
        base['search_families']=';'.join(fams)
        base['source_record_count']=len(g)
        records.append(base)
        if len(fams)>1 or len(g)>1:
            overlap_rows.append({
                'master_group': int(root),
                'search_families': ';'.join(fams),
                'source_record_count': len(g),
                'eid': base[eid_col] if eid_col else '',
                'doi': base[doi_col] if doi_col else '',
                'title': base[title_col]
            })

    master=pd.DataFrame(records).drop(columns=['_eid','_doi','_title','_master_idx'], errors='ignore')
    overlap=pd.DataFrame(overlap_rows)

    master_path=outdir/'DV_Scopus_Indexed_Discovery_Master_v9.csv'
    overlap_path=outdir/'DV_V2_V2B_Overlap_v9.csv'
    audit_path=outdir/'DV_V2_V2B_Merge_Audit_v9.json'
    master.to_csv(master_path,index=False,encoding='utf-8-sig')
    overlap.to_csv(overlap_path,index=False,encoding='utf-8-sig')

    # Sentinel audit is diagnostic only. Three arXiv frontier sentinels may be absent from Scopus.
    sentinels={
      'ATR':'From Version Conflicts to Decision Conflicts',
      'CORDON':'Cordon',
      'TOCTOU':'TOCTOU',
      'IEIB':'A Trusted Provenance and TEE-Based Reference Architecture for Intent-Execution Binding in LLM Agents',
      'IBBC':'IBBC-Guard',
      'VERIACT':'VeriAct-Agent',
      'AGENTGUARD':'AgentGuard: Runtime Verification of AI Agents'
    }
    titles=master[title_col].astype(str)
    sentinel_results={}
    for code,needle in sentinels.items():
        n=norm_text(needle)
        matches=[t for t in titles if n in norm_text(t) or norm_text(t) in n]
        sentinel_results[code]={'found':bool(matches),'matches':matches[:5]}

    audit={
      'pipeline':'DV Scopus V2 + V2B merge/dedup v9',
      'timestamp_utc':datetime.now(timezone.utc).isoformat(),
      'inputs':{'V2':str(v2),'V2B':str(v2b)},
      'input_counts':{'V2':len(a),'V2B':len(b),'combined_raw':len(raw)},
      'dedup_hierarchy':['EID','DOI','normalized_title'],
      'unique_master_records':len(master),
      'duplicates_removed':len(raw)-len(master),
      'overlap_rows_written':len(overlap),
      'sentinel_diagnostic':sentinel_results,
      'supplementary_frontier_sentinels':['ATR','CORDON','TOCTOU'],
      'automatic_eligibility_decisions':0,
      'corpus_status':'INDEXED_DISCOVERY_MASTER_NOT_ELIGIBILITY_FROZEN',
      'warning':'Merge/dedup only. Do not interpret title-level absence as exclusion and do not mix review papers with primary mechanism-frequency evidence.',
      'outputs':{'master':master_path.name,'overlap':overlap_path.name,'audit':audit_path.name}
    }
    audit_path.write_text(json.dumps(audit,indent=2,ensure_ascii=False),encoding='utf-8')

    print('='*72)
    print('DV SCOPUS V2 + V2B MERGE / DEDUP v9')
    print('='*72)
    print('V2 records          :',len(a))
    print('V2B records         :',len(b))
    print('Combined raw        :',len(raw))
    print('Unique master       :',len(master))
    print('Duplicates removed  :',len(raw)-len(master))
    print('Overlap rows        :',len(overlap))
    print('\nSentinel diagnostic:')
    for k,v in sentinel_results.items(): print(f'  {k:10s}:', 'FOUND' if v['found'] else 'NOT FOUND')
    print('\nSTATUS: INDEXED DISCOVERY MASTER CREATED; ELIGIBLE CORPUS NOT FROZEN')
    print('Master :',master_path)
    print('Overlap:',overlap_path)
    print('Audit  :',audit_path)

if __name__=='__main__':
    main()
