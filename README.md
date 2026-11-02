# OMOP_TO_SDTM

OMOP CDM v5.4 → CDISC SDTM (SDTMIG 3.4) mapping for the [TRExt](https://github.com/TRE-Text-Analytics) pipeline, using the Unison platform (Hyper Unison Ltd). The repository contains the structural and semantic mapping configuration, the script that builds SAS XPT files from the exported SDTM tables, and documentation of how Unison turns the mapping into SQL.

## Overview

Unison maps the unified OMOP CDM database (NLP-derived plus structured MIMIC-IV data) to SDTM. The results are available in two forms:

1. **Virtual SDTM views.** SDTM domains can be queried through the Unison platform using the [Unison Query Language (UQL)](https://unison.usetiful.help/article/0195ec52-3083-0442-6741-d9d32441712a), with no copy of the data. Only aggregated results above a minimum count threshold are returned.
2. **Materialised SDTM tables.** Unison generates a separate PostgreSQL schema holding the final SDTM tables, structured to the SDTMIG 3.4 specification and validated with Pinnacle 21.

The Unison agent runs in a Docker container alongside the OMOP database inside the TRE. All SQL runs locally within the secure environment.

## Repository contents

| Path | Description |
|---|---|
| `mapping/structural-mapping.yaml` | OMOP → SDTM structural mapping: CTEs, joins, and one bridge per SDTM domain |
| `mapping/semantic-mapping-cdisc-ct.csv` | Source value → CDISC Controlled Terminology assignments for `conceptId` variables |
| `scripts/rebuild-xpt.py` | Converts exported SDTM tables (CSV) to SAS XPT v5 for Pinnacle 21 validation |
| `docs/sql-generation.md` | How Unison generates SQL from the structural mapping and applies semantic mapping |

## Structural mapping

`structural-mapping.yaml` has three sections:

- **`cte`**: SQL common table expressions that join OMOP clinical tables with the `concept` vocabulary and prepare the source data.
- **`joins`**: link the person table to each CTE via `person_id`.
- **`bridges`**: one per SDTM domain (`cdmTable`). Each SDTM variable is a SQL expression of one of three types:
  - `plain`: a direct value or expression. `$table` refers to the joined CTE.
  - `conceptId`: a categorical value resolved against a vocabulary (`vocabularyId` + `conceptClassId`), either CDISC Controlled Terminology or MedDRA.
  - `serial`: a per-subject sequence number (`--SEQ`).

The source schema is set by `participantTable` and the table references in the CTEs (`omop_combined` in this deployment). Change these to match your OMOP schema.

| Domain | OMOP source |
|---|---|
| DM (Demographics) | `person`, `death` |
| AE (Adverse Events) | `condition_occurrence` |
| MH (Medical History) | `condition_occurrence` |
| PR (Procedures) | `procedure_occurrence` |
| SC (Subject Characteristics) | `observation` |
| BS (Biospecimen) | `specimen` |
| LB (Laboratory), VS (Vital Signs) | `measurement` |
| TS (Trial Summary) | study-level parameters (static CTE) |

## Semantic mapping

For `conceptId` variables, Unison collects the distinct source values and suggests matching concepts, which a domain expert reviews and approves. `semantic-mapping-cdisc-ct.csv` lists the approved CDISC Controlled Terminology assignments. `conceptId` is in `{codelist}-{term}` format, e.g. `C74457-C41260` = RACE / ASIAN.

AE and MH diagnoses (SNOMED CT) are mapped to MedDRA 29.0 across the full hierarchy (LLT → PT → HLT → HLGT → SOC). MedDRA is licensed by the MSSO, so the MedDRA dictionary and term mappings are not included in this repository.

## Validation

Requirements: Python 3 with `pandas` and `pyreadstat`, and [Pinnacle 21 Community](https://www.certara.com/software/pinnacle-21-community/).

```bash
pip install pandas pyreadstat
python3 scripts/rebuild-xpt.py /path/to/exported/csv   # writes <DOMAIN>.xpt next to the CSVs
```

Then validate the XPT files in Pinnacle 21 Community with the SDTMIG 3.4 (FDA) configuration and MedDRA 29.0.

`rebuild-xpt.py` also:

- restores decimal precision of `--STRESN` from `--STRESC`
- adds `EPOCH` to BS
- renumbers `PRSEQ` per subject
- drops empty permissible variables
- caps domains at 10,000 rows, to keep Pinnacle 21 memory use manageable

## Results

Validation of the materialised tables with Pinnacle 21 reported no MedDRA or controlled terminology errors. The only rejection was DD0101, raised because no define.xml was generated. The remaining findings come from the observational nature of MIMIC-IV:

- no treatment arm assignment
- no trial design, exposure or disposition domains
- no causality or specimen unit information in OMOP

## Limitations

- MIMIC-IV is an observational dataset, so trial-specific variables and domains (ARM, EX, DS, Trial Design) cannot be populated.
- The source OMOP `drug_exposure` table is empty, so the EX and CM domains were not generated.
