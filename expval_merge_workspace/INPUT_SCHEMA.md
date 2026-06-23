# Input Schema

The CLI must accept heterogeneous CSV/Excel files and normalize them into canonical forms.

## Extracted Image Value Tables

Expected source root:

- `F:\내 드라이브\LNPDB_update_1\Supplementrays\expvals`

Accepted extensions:

- `.csv`
- `.xlsx`
- `.xlsm`
- `.xls`

### Barplot Extractor Columns

Current desktop barplot output:

```text
selected
figure_name
X_Label
Group
Value
Type
x_pixel
y_pixel
```

Legacy Streamlit barplot output:

```text
X_Label
Value
Type
x_pixel
y_pixel
```

### Heatmap Long Columns

Continuous colorbar:

```text
box_id
row_index
col_index
row_label
col_label
x_center
y_center
cell_rgb
cell_hex
extracted_value
colorbar_position
color_distance
```

Discrete colorbar:

```text
box_id
row_index
col_index
row_label
col_label
x_center
y_center
cell_rgb
cell_hex
matched_class_id
matched_class_label
matched_value
color_distance
```

Legacy heatmap long:

```text
row_index
col_index
row_label
col_label
x_center
y_center
value
```

### Heatmap Matrix Columns

Matrix tables have dynamic column labels. The row index is usually `row_label`; each matrix column represents a `col_label`.

The CLI must convert matrix tables to long form before matching:

```text
row_label
col_label
value
```

### Canonical Extracted-Value Columns

All extracted-value inputs must normalize to these columns:

```text
expval_id
source_file
source_sheet
paper_key
figure_key
partition_key
source_row
source_table_type
figure_name
item_id
panel_id
box_id
x_label
group_label
row_label
col_label
metric_type
value
value_text
unit
x_pixel
y_pixel
x_center
y_center
cell_rgb
cell_hex
color_distance
raw_columns_json
manual_required
normalization_warning
```

Rules:

- `value` is numeric when possible.
- `value_text` preserves the original cell exactly as text.
- `source_table_type` should be one of `barplot`, `heatmap_long`, `heatmap_matrix`, `unknown`.
- `item_id` should be inferred from `figure_name`, table labels, file path, file name, sheet name, column names, or explicit columns when present.
- `figure_key` and `partition_key` are used to split rows into figure/table matching groups before fallback matching.
- `paper_key` is retained only as a compatibility/provenance column and is not used for matching.
- If `figure_name` is absent, preserve blank and rely on file/sheet/path inference later.

## LNPDB-Like Tables

Expected search roots:

- `F:\내 드라이브\LNPDB_update_1\Supplementrays`
- `F:\내 드라이브\LNPDB_update_1\Source_head_tail_separated_f`
- `F:\내 드라이브\LNPDB_update_1\Source_DOI_added_f`

Accepted extensions:

- `.csv`
- `.xlsx`
- `.xlsm`
- `.xls`

### LNPDB-Like Required Handling

The CLI must not assume a single fixed schema. It must:

- preserve every original column
- add source provenance columns
- infer likely matching columns from names
- tolerate missing optional columns

Useful matching columns when present:

```text
Paper_ID
DOI
Title
Item_ID
figure_name
Figure
Panel
metric_type
Experiment_method
Model
Model_type
Model_target
Route_of_administration
Cargo
Cargo_type
formulation_id
Formulation_Name
condition_1_name
condition_1_value
condition_2_name
condition_2_value
condition_3_name
condition_3_value
condition_4_name
condition_4_value
Group
original_values
aggregated_value
Value
experimental_value
unit
```

### Canonical LNPDB Row Columns

After normalization, each row must include:

```text
lnpdb_row_id
source_file
source_sheet
paper_key
figure_key
partition_key
source_row
paper_id
doi
item_id
figure_name
panel_id
metric_type
formulation_id
formulation_name
group_label
condition_text
existing_value_text
existing_unit
raw_columns_json
```

`existing_value_text` must be read from `experimental_value` only. Other value-like columns may be preserved as original metadata, but they must not control whether the row is fillable.

Original columns must remain available in the merged output.
