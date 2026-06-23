# Troubleshooting

## No Extracted-Value Files Found

Check:

- `F:\내 드라이브\LNPDB_update_1\Supplementrays\expvals`
- supported extensions: `.csv`, `.xlsx`, `.xlsm`, `.xls`
- file permissions and synced-drive availability

Action:

- Re-run observe.
- Record missing root in `observe_report.json`.

## No LNPDB-Like Files Found

Check:

- `F:\내 드라이브\LNPDB_update_1\Supplementrays`
- `F:\내 드라이브\LNPDB_update_1\Source_head_tail_separated_f`
- `F:\내 드라이브\LNPDB_update_1\Source_DOI_added_f`

Action:

- Confirm whether output files are nested more deeply.
- Exclude extracted-value output folders from LNPDB-like search if needed.

## Excel Sheet Cannot Be Read

Cause:

- unsupported format
- password-protected workbook
- broken workbook
- missing engine such as `openpyxl`

Action:

- Log file and sheet in `input_inventory.csv`.
- Continue with other readable files.
- Do not delete or repair original workbook in place.

## Extracted Value Column Not Detected

Accepted value-like columns include:

- `Value`
- `value`
- `extracted_value`
- `matched_value`
- matrix cell values after long conversion

Action:

- Write rows to `normalized_expvals_warnings.csv`.
- Require manual column mapping if no value-like column exists.

## Figure ID Missing

Cause:

- extracted image table lacks `figure_name`
- filename does not encode figure/panel

Action:

- Keep `figure_name` blank.
- Try file/sheet-based inference only if the pattern is clear.
- Set low confidence or unmatched when no stable item ID exists.

## Too Many Candidate Matches

Cause:

- LNPDB-like row is figure-level while extracted table is group-level
- labels are repeated across formulations or conditions

Action:

- Use `long_expand` if row expansion is scientifically intended.
- Otherwise write to `merge_conflicts.csv`.

## Existing Target Value Conflicts

Cause:

- LNPDB-like table already has a different value
- unit mismatch
- wrong candidate match

Action:

- Do not overwrite.
- Write conflict with both existing and extracted values.
- Require human review.

## Units Are Missing Or Different

Action:

- Do not convert automatically.
- Preserve extracted value text.
- Set `manual_required=true` unless unit agreement is evident from the target row or metric.

## Korean Or Space-Containing Paths Fail On Windows

Action:

- Always quote paths.
- Prefer `-LiteralPath` in PowerShell tooling.
- Avoid shell glob expansion for user-provided paths.
- Store paths as UTF-8 in CSV/JSON outputs.

## Duplicate Source Rows

Cause:

- same workbook discovered from multiple roots
- same CSV copied into multiple locations

Action:

- Generate stable IDs from absolute path + sheet + row.
- Do not deduplicate silently unless content hash and path policy are documented.

## Validation Report Does Not Balance

Check:

- accepted matches
- merged rows
- row expansion count
- conflicts
- unmatched rows

Action:

- The QC report must explain every extracted-value row as merged, conflict, unmatched, or intentionally skipped.
