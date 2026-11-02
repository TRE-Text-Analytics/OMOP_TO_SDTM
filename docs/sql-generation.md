# SQL Generation from Structural Mapping

This document describes how the system generates SQL queries from `structural-mapping.yaml` and how semantic mapping is applied to the results.

## Overview

For each field in a bridge the system generates an individual SQL query used for **value discovery** — counting unique participants per distinct value. These queries are stored in `structures.json` under `lastCohortRequest.sqlQuery`. The same logic is used to assemble the final domain SELECT.

---

## Query Template

```sql
WITH <cte_name> AS (
  <cte_sql>
)
SELECT
    <field_sql> AS "c.<SDTM_FIELD>",
    <bridge_id>  AS "__bridge_id",
    count(distinct omop.person."person_id") AS count_uniq_participants
FROM omop.person
[JOIN <cte_name> AS <alias> ON omop.person.person_id = <alias>.person_id]
WHERE true
GROUP BY "c.<SDTM_FIELD>"
HAVING COUNT(distinct omop.person."person_id") >= 1
LIMIT <n>
```

The `WITH` block is included only when at least one JOIN to the CTE is needed by the query.

---

## `$table` Substitution

`$table` is a placeholder in the `sql` expressions in `structural-mapping.yaml`. It is replaced at generation time depending on whether a JOIN is present for the field:

| Context | `$table` replaced with |
|---------|------------------------|
| Field uses a JOIN to a CTE | CTE alias, e.g. `c_69d636c8a4e99` |
| No JOIN (base participant table) | `omop.person` |

### Examples

**`AESTDTC`** — bridge `ae_mapping` uses `conditions_join`, so `$table` → CTE alias:
```yaml
# YAML
AESTDTC:
  sql: "to_char($table.condition_start_date, 'YYYY-MM-DD')"
  type: plain
```
```sql
-- Generated
to_char(c_69cd0a5ed4895.condition_start_date, 'YYYY-MM-DD') AS "c.AESTDTC"
```

**`RACE`** — bridge `dm_mapping` has `join: null`, so `$table` → `omop.person`:
```yaml
# YAML
RACE:
  sql: $table.race_source_value
  type: conceptId
```
```sql
-- Generated
omop.person.race_source_value AS "c.RACE"
```

---

## JOIN Resolution

JOIN is controlled at two levels. The field level overrides the bridge level.

```
bridge.join: <join_name>      ← default for all fields in this bridge
    field.join: null          ← removes JOIN for this specific field
    field.join: <join_name>   ← adds JOIN for this field even if bridge.join is null
```

### Bridge-level join

Set in the bridge definition:
```yaml
bridges:
  - name: ae_mapping
    join: conditions_join     # all fields inherit this JOIN
    ...
  - name: dm_mapping
    join: null                # base table only by default
    ...
```

### Field-level join override

A field can declare its own `join:` key to diverge from the bridge default.

**`AEENRF`** in `ae_mapping` — bridge uses `conditions_join`, field overrides with `join: null`:
```yaml
AEENRF:
  sql: "''"
  type: plain
  join: null          # override: no JOIN for this field
```
```sql
-- No CTE, no JOIN:
SELECT '' AS "c.AEENRF", 3938 AS "__bridge_id",
    count(distinct omop.person."person_id") AS count_uniq_participants
FROM omop.person
WHERE true
GROUP BY "c.AEENRF"
```

**`AGE`** in `dm_mapping` — bridge has `join: null`, field overrides with `join: conditions_join`:
```yaml
AGE:
  sql: "(EXTRACT(YEAR FROM $table.condition_start_date) - omop.person.year_of_birth)::int"
  type: plain
  join: conditions_join   # override: add JOIN despite bridge.join being null
```
```sql
-- CTE and JOIN are added just for this field:
WITH conditions_cte AS (
  SELECT co.person_id, co.condition_start_date, c.concept_name, c.concept_code, c.concept_id, c.domain_id
  FROM omop.condition_occurrence co JOIN omop.concept c ON co.condition_concept_id = c.concept_id
)
SELECT
    (EXTRACT(YEAR FROM c_69d636c8a4e99.condition_start_date) - omop.person.year_of_birth)::int AS "c.AGE",
    c_69d636c8a4e99.condition_start_date::text AS "c.__variable__tableCondition_start_date",
    3936 AS "__bridge_id",
    count(distinct omop.person."person_id") AS count_uniq_participants
FROM omop.person
JOIN conditions_cte AS c_69d636c8a4e99 ON omop.person.person_id = c_69d636c8a4e99.person_id
WHERE true
GROUP BY "c.AGE", "c.__variable__tableCondition_start_date"
HAVING COUNT(distinct omop.person."person_id") >= 1
LIMIT 1001
```

### CTE aliasing

Each CTE reference gets a unique hash-based alias (e.g. `c_69d636c8a4e99`). This prevents name collisions when the same CTE is joined in multiple places.

---

## Field Types and Their Effect on Generation

### `plain`

No post-processing. The SQL value is used as-is in the final output.
- LIMIT: **1001**

### `conceptId`

The raw SQL value is fetched and then replaced by a CDISC concept name via `semantic-mapping.csv` (see below).
- LIMIT: **100 000 000** — all distinct values must be loaded to build the complete mapping

### `serial`

Placeholder `sql: '1'` in the YAML. In the final domain SELECT this is replaced with a `ROW_NUMBER()` window function to produce a per-participant sequence number (e.g. `AESEQ`, `MHSEQ`).

---

## Two-Stage Processing for `conceptId` Fields

### Stage 1 — SQL execution

The query fetches raw values from the source column:

```
$table.race_source_value  →  "WHITE", "BLACK/AFRICAN AMERICAN", "ASIAN - CHINESE", ...
$table.gender_source_value →  "F", "M", ...
'UNKNOWN'                  →  "UNKNOWN"    (single literal value)
'YEARS'                    →  "YEARS"
```

### Stage 2 — Semantic mapping via `semantic-mapping.csv`

Each raw value is looked up by `sourceCode`. The row provides:
- `conceptId` — the target CDISC concept (`{classId}-{conceptId}`)
- `conceptName` — the CDISC-standard name that replaces the raw value in the output
- `sqlExpression` — the SQL expression that produced this value (mirrors the `sql` field from the YAML; stored here for reference)

**Example — RACE:**

| sourceCode | conceptName | conceptId |
|------------|-------------|-----------|
| `WHITE` | `WHITE` | C74457-C41261 |
| `WHITE - EASTERN EUROPEAN` | `WHITE` | C74457-C41261 |
| `BLACK/AFRICAN AMERICAN` | `BLACK OR AFRICAN AMERICAN` | C74457-C16352 |
| `ASIAN - CHINESE` | `ASIAN` | C74457-C41260 |
| `UNABLE TO OBTAIN` | `UNKNOWN` | C74457-C17998 |

Many source sub-values collapse to a single CDISC concept name. This normalisation is what semantic mapping provides.

**Example — SEX:**

| sourceCode | conceptName | conceptId |
|------------|-------------|-----------|
| `F` | `F` | C66731-C16576 |
| `M` | `M` | C66731-C20197 |

**Example — literal fields (`AGEU`, `EPOCH`, `AESEV`):**

For fields whose SQL is a literal (`'YEARS'`, `'BASELINE'`, `'MODERATE'`), only one source value is ever produced, so `semantic-mapping.csv` has exactly one entry for it:

| sourceCode | sqlExpression | conceptName | conceptId |
|------------|---------------|-------------|-----------|
| `YEARS` | `'YEARS'` | `YEARS` | C66781-C29848 |
| `BASELINE` | `'BASELINE'` | `BASELINE` | C99079-C125938 |
| `MODERATE` | `'MODERATE'` | `MODERATE` | C66769-C41339 |

---

## Final Domain SELECT Assembly

When generating the complete output for a domain (e.g. DM, AE, MH):

1. For each field in the bridge, take `sql` from the YAML.
2. Resolve JOIN: apply field-level override if present, otherwise use bridge-level.
3. Replace `$table` with the CTE alias (if JOIN present) or `omop.person` (if not).
4. Assemble all fields into a single `SELECT` list.
5. Include `WITH <cte> AS (...)` only if at least one field references it via JOIN.
6. For `serial` fields, substitute `ROW_NUMBER() OVER (...)` in place of the literal `1`.
7. Execute the query to obtain raw rows.
8. Post-process each row: for every `conceptId` field, look up the raw value in `semantic-mapping.csv` by `sourceCode` and replace it with the corresponding `conceptName`.

### Resulting query structure (example for AE domain)

```sql
WITH conditions_cte AS (
  SELECT
    co.person_id,
    co.condition_start_date,
    c.concept_name,
    c.concept_code,
    c.concept_id,
    c.domain_id
  FROM omop.condition_occurrence co
  JOIN omop.concept c ON co.condition_concept_id = c.concept_id
)
SELECT
    'UNKNOWN'                                                         AS "AEACN",      -- conceptId → semantic mapping
    NULL                                                              AS "AEBODSYS",
    c_<hash>.domain_id                                                AS "AECAT",
    c_<hash>.concept_name                                             AS "AEDECOD",
    NULL                                                              AS "AEDUR",
    NULL                                                              AS "AEENDTC",
    NULL                                                              AS "AEENDY",
    ''                                                                AS "AEENRF",     -- join: null override
    NULL                                                              AS "AEOUT",      -- conceptId → semantic mapping
    NULL                                                              AS "AEREL",
    NULL                                                              AS "AESCAT",
    ROW_NUMBER() OVER (PARTITION BY omop.person.person_id ORDER BY c_<hash>.condition_start_date) AS "AESEQ",  -- serial
    NULL                                                              AS "AESER",      -- conceptId → semantic mapping
    'MODERATE'                                                        AS "AESEV",      -- conceptId → semantic mapping
    to_char(c_<hash>.condition_start_date, 'YYYY-MM-DD')              AS "AESTDTC",
    NULL                                                              AS "AESTDY",
    c_<hash>.concept_code                                             AS "AETERM",
    'AE'                                                              AS "DOMAIN",
    'BASELINE'                                                        AS "EPOCH",      -- conceptId → semantic mapping
    'STUDY-1'                                                         AS "STUDYID",
    CAST(omop.person.person_id AS TEXT)                               AS "USUBJID"
FROM omop.person
JOIN conditions_cte AS c_<hash> ON omop.person.person_id = c_<hash>.person_id
```
