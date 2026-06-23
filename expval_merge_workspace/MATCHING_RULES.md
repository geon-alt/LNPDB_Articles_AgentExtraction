# Matching Rules

The merge CLI must prefer transparent deterministic matching over broad fuzzy matching.

## Normalization

Normalize comparison text before matching:

- lowercase
- trim whitespace
- collapse repeated spaces
- convert `Fig.` to `figure`
- convert `Supplementary Fig.` and `Suppl. Fig.` to `supplementary figure`
- normalize panel IDs such as `2B`, `Fig 2b`, `figure 2 b` to `figure 2b`
- remove harmless punctuation for comparison but preserve original text in output
- normalize Unicode minus and multiplication signs when comparing numbers or ratios

## Match Priority

Use the highest reliable tier available.

### Tier 0: Figure/Table Partition Match

Before broad matching, split both extracted-value rows and LNPDB-like rows by:

```text
figure_key
partition_key = figure_key
```

Match order:

```text
same figure_key/table_key
same item_id
item_id partial match
remaining global fallback
```

`paper_key`, DOI, and paper title are not used to split or score rows. The CLI assumes all supplied inputs for a run belong to the same paper.

The CLI must write these grouped rows under `partitioned/` and list them in `partition_inventory.csv`.

### Tier 1: Explicit Identifier Match

Accept when these fields agree:

- same `Item_ID`, `figure_name`, table label, or normalized figure/table/panel ID
- same formulation/group/condition or only one possible extracted value exists for the item

### Tier 2: Figure/Panel + Label Match

Accept when:

- normalized figure or panel identifier agrees
- extracted `X_Label`, `Group`, `row_label`, or `col_label` maps to LNPDB-like formulation, group, metric, or condition fields
- only one candidate remains after filtering

### Tier 3: File/Sheet Context Match

Accept with medium confidence when:

- source file or sheet names encode the same figure/panel/table identifier
- label/group context is consistent
- no stronger match is available

### Tier 4: Conservative Fuzzy Match

Allowed only when:

- deterministic tiers fail
- fuzzy score is high
- there is exactly one candidate above threshold
- match reason records the fields and score

Do not use fuzzy matching to resolve scientific ambiguity.

## Fields Used For Matching

The target value column is strict, but all other target columns are flexible matching context.

Extracted-value side:

```text
figure_name
item_id
panel_id
box_id
x_label
group_label
row_label
col_label
metric_type
unit
source_file
source_sheet
```

LNPDB-like side:

```text
Paper_ID
DOI
Item_ID
figure_name
Panel
metric_type
Experiment_method
Formulation_Name
formulation_id
Group
condition_*_name
condition_*_value
unit
source_file
source_sheet
```

In addition to the named fields above, every non-empty original LNPDB-like cell except `experimental_value` should be available as match context. This allows target files with different column names to match when the values themselves contain figure IDs, formulation names, group names, treatment names, model names, condition labels, or metric labels.

## Value Column

The CLI may insert extracted values into one target column only:

```text
experimental_value
```

If `experimental_value` does not exist in the LNPDB-like input, the merged output may create it. Other value-like columns such as `original_values`, `aggregated_value`, `Value`, or `value` must not be filled by this merge workflow.

Rows are eligible for insertion only when `experimental_value` is blank after trimming whitespace. If `experimental_value` already has a non-empty value, do not overwrite it and do not write extracted-value provenance into that row.

Always add provenance columns:

```text
expval_source_file
expval_source_sheet
expval_source_row
expval_source_table_type
expval_value_column
expval_value_text
expval_x_pixel
expval_y_pixel
expval_x_center
expval_y_center
expval_match_score
expval_match_confidence
expval_match_reason
expval_manual_required
```

## Conflict Rules

Do not silently merge when:

- two or more extracted rows map to one target row in `fill_existing` mode
- one extracted row maps equally to multiple target rows
- target `experimental_value` is already non-empty
- unit differs and no conversion rule exists
- metric labels disagree
- group/formulation labels disagree

Conflicts must go to `merge_conflicts.csv` and `merge_review_flags.csv`.

## Numeric Comparison

For conflict detection:

- Parse numbers with optional scientific notation.
- Treat blank and missing as missing, not zero.
- Default tolerance: exact text match or numeric absolute difference <= `1e-9`.
- Do not convert units unless an explicit conversion table is implemented and logged.

## Confidence Labels

Use:

- `high`: explicit identifier plus label/group agreement.
- `medium`: figure/panel plus unique contextual label match.
- `low`: weak context but still unique; should usually set `manual_required=true`.
- `conflict`: ambiguous or contradictory; do not merge.

## Forbidden Matching Behavior

- Do not match based only on equal numeric values.
- Do not infer missing labels from memory.
- Do not use file modification time as scientific evidence.
- Do not drop unmatched extracted values.
- Do not drop unmatched LNPDB-like rows.
