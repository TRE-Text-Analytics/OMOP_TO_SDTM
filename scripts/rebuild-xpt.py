#!/usr/bin/env python3
"""Rebuild XPT files from CSVs. Most logic now in structural-mapping.yaml SQL."""

import pandas as pd
import pyreadstat
import os
import sys

# Usage: python3 rebuild-xpt.py <dir with exported <DOMAIN>.csv files>
os.chdir(sys.argv[1] if len(sys.argv) > 1 else '.')

NUMERIC_COLS = {
    'AESEQ','AELLTCD','AEPTCD','AEHLTCD','AEHLGTCD','AEBDSYCD','AESOCCD',
    'TAETORD','AESTDY','AEENDY','AGE','DMDY','MHSEQ','MHDY','TSSEQ',
    'LBSEQ','LBSTRESN','LBSTNRLO','LBSTNRHI','LBDY','LBENDY',
    'LBTPTNUM','VISITNUM','VISITDY',
    'SCSEQ','SCSTRESN','SCDY',
    'PRSEQ','PRSTDY','PRENDY','PRDOSE','PRTPTNUM',
    'BSSEQ','BSSTRESN','BSDY','BSTPTNUM',
    'VSSEQ','VSSTRESN','VSDY','VSTPTNUM',
}

def write_xpt(domain, df):
    df = df.replace('', None)
    if len(df) > 0:
        # Drop entirely-null permissible columns (SD1078).
        # Protect *DY columns only when the paired *DTC column has actual values —
        # otherwise dropping *DTC but keeping *DY triggers SD2270 (inverse dependency).
        def paired_dtc(dy):
            if dy.endswith('STDY'): return dy[:-4] + 'STDTC'
            if dy.endswith('ENDY'): return dy[:-4] + 'ENDTC'
            return dy[:-2] + 'DTC'
        keep = set()
        for col in df.columns:
            if col.endswith('DY'):
                dtc = paired_dtc(col)
                if dtc in df.columns and not df[dtc].isna().all():
                    keep.add(col)
        drop = [c for c in df.columns if c not in keep and df[c].isna().all()]
        df = df.drop(columns=drop)
    for col in df.columns:
        if col in NUMERIC_COLS:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    pyreadstat.write_xport(df, f'{domain}.xpt', file_format_version=5, table_name=domain)
    print(f'  {domain}.xpt: {len(df)} rows')

# Simple domains: read CSV, write XPT (10K limit)
for domain in ['AE', 'MH', 'DM', 'TS']:
    print(f'{domain}...')
    limit = None if domain in ('DM', 'TS') else 10000
    df = pd.read_csv(f'{domain}.csv', dtype=str, keep_default_na=False, nrows=limit)
    write_xpt(domain, df)

# BS: add EPOCH (server CDM model doesn't support it, P21 SD1077 requires it)
print('BS...')
bs = pd.read_csv('BS.csv', dtype=str, keep_default_na=False, nrows=10000)
bs['EPOCH'] = 'BASELINE'
write_xpt('BS', bs)

# LB/VS: server casts STRESN to bigint, losing decimals. Align with STRESC.
for domain in ['LB', 'VS']:
    print(f'{domain}...')
    df = pd.read_csv(f'{domain}.csv', dtype=str, keep_default_na=False, nrows=10000)
    stresn = f'{domain}STRESN'
    stresc = f'{domain}STRESC'
    if stresn in df.columns and stresc in df.columns:
        df[stresn] = df[stresc]
    write_xpt(domain, df)

# SC: filter null rows
print('SC...')
sc = pd.read_csv('SC.csv', dtype=str, keep_default_na=False, nrows=10000)
sc = sc[sc['USUBJID'] != '']
write_xpt('SC', sc)

# PR: fix PRSEQ to be unique per USUBJID (server generates global sequence)
print('PR...')
pr = pd.read_csv('PR.csv', dtype=str, keep_default_na=False, nrows=10000)
pr['PRSEQ'] = pr.groupby('USUBJID').cumcount() + 1
pr['PRSEQ'] = pr['PRSEQ'].astype(str)
write_xpt('PR', pr)

print('Done!')
