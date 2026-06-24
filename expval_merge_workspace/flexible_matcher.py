from __future__ import annotations

import itertools
import json
import re
from collections import defaultdict
from typing import Any


SOURCE_VALUE_NAMES = [
    "experimental_value",
    "experiment_value",
    "aggregated_value",
    "extracted_value",
    "matched_value",
    "value",
]
TARGET_VALUE_NAMES = ["experimental_value", "experiment_value"]
IGNORED_SOURCE_COLUMNS = {
    "selected",
    "x_pixel",
    "y_pixel",
    "x_center",
    "y_center",
    "cell_rgb",
    "cell_hex",
    "color_distance",
}
INTERNAL_COLUMNS = {
    "expval_id",
    "lnpdb_row_id",
    "source_file",
    "source_sheet",
    "source_row",
    "paper_key",
    "figure_key",
    "partition_key",
    "raw_columns_json",
    "manual_required",
    "normalization_warning",
}
HEURISTIC_VALUE_LIMIT = 40
HEURISTIC_SOURCE_TUPLE_LIMIT = 250
HEURISTIC_MAX_SOURCE_COLUMNS = 12
HEURISTIC_MAX_TARGET_COLUMNS = 32
HEURISTIC_POSITIVE_COLUMN_HINTS = {
    "figure",
    "panel",
    "group",
    "condition",
    "treatment",
    "formulation",
    "experiment",
    "model",
    "cargo",
    "method",
    "type",
    "label",
    "row",
    "col",
}
HEURISTIC_NEGATIVE_COLUMN_HINTS = {
    "smiles",
    "descriptor",
    "debug",
    "publication",
    "pmid",
    "link",
    "numeric",
    "mean",
    "std",
    "median",
    "count",
    "atoms",
    "rings",
    "volume",
    "weight",
    "logp",
    "refractivity",
}


def text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def norm(value: Any) -> str:
    value = text(value).lower()
    value = value.replace("−", "-").replace("×", "x")
    value = re.sub(r"[_\-]+", " ", value)
    value = re.sub(r"[^\w\s.+/%()]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", norm(value))


def row_payload(row: dict[str, Any]) -> dict[str, str]:
    raw = row.get("raw_columns_json", "")
    payload: dict[str, Any] = {}
    if raw:
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                payload.update(loaded)
        except Exception:
            pass
    if not payload:
        payload = {key: value for key, value in row.items() if key != "raw_columns_json"}
    return {str(key): text(value) for key, value in payload.items()}


def column_values(rows: list[dict[str, Any]], limit: int = 80) -> dict[str, list[str]]:
    values: dict[str, list[str]] = defaultdict(list)
    seen: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        for column, value in row_payload(row).items():
            key = norm(value)
            if not key or key in seen[column] or len(values[column]) >= limit:
                continue
            seen[column].add(key)
            values[column].append(value)
    return dict(values)


def unique_column_values(rows: list[dict[str, Any]], column: str, limit: int = 80) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for row in rows:
        value = row_payload(row).get(column, "")
        key = norm(value)
        if not key or key in seen:
            continue
        seen.add(key)
        values.append(value)
        if len(values) >= limit:
            break
    return values


def schema_summary(rows: list[dict[str, Any]], sample_limit: int = 12, value_limit: int = 50) -> dict[str, Any]:
    payloads = [row_payload(row) for row in rows]
    columns: list[str] = []
    for row in payloads:
        for column in row:
            if column not in columns:
                columns.append(column)
    values = column_values(rows, value_limit)
    return {
        "row_count": len(rows),
        "columns": columns,
        "unique_values": {column: values.get(column, []) for column in columns},
        "sample_rows": payloads[:sample_limit],
    }


def _column_by_name(columns: list[str], candidates: list[str]) -> str:
    lookup = {compact(column): column for column in columns}
    for candidate in candidates:
        if compact(candidate) in lookup:
            return lookup[compact(candidate)]
    return ""


def infer_value_column(rows: list[dict[str, Any]], role: str) -> str:
    summary = schema_summary(rows, sample_limit=0, value_limit=5)
    columns = summary["columns"]
    candidates = TARGET_VALUE_NAMES if role == "target" else SOURCE_VALUE_NAMES
    selected = _column_by_name(columns, candidates)
    if selected:
        return selected
    if role == "target":
        value_like = [
            column
            for column in columns
            if "experimental" in compact(column) and "value" in compact(column)
        ]
        return value_like[0] if value_like else "experimental_value"
    numeric_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        for column, value in row_payload(row).items():
            try:
                float(text(value).replace(",", ""))
                numeric_counts[column] += 1
            except Exception:
                continue
    ignored = {compact(value) for value in IGNORED_SOURCE_COLUMNS | INTERNAL_COLUMNS}
    ranked = [
        (count, column)
        for column, count in numeric_counts.items()
        if compact(column) not in ignored
    ]
    ranked.sort(reverse=True)
    return ranked[0][1] if ranked else ""


def _usable_columns(rows: list[dict[str, Any]], value_column: str, role: str) -> list[str]:
    columns = schema_summary(rows, sample_limit=0, value_limit=1)["columns"]
    ignored_exact = {value.lower() for value in INTERNAL_COLUMNS}
    if role == "source":
        ignored_exact |= {value.lower() for value in IGNORED_SOURCE_COLUMNS}
    return [
        column
        for column in columns
        if compact(column) != compact(value_column) and column.lower() not in ignored_exact
    ]


def _exact_column_relations(source_columns: list[str], target_columns: list[str]) -> list[dict[str, Any]]:
    target_lookup = {compact(column): column for column in target_columns}
    relations = []
    for source_column in source_columns:
        target_column = target_lookup.get(compact(source_column))
        if not target_column:
            continue
        relations.append(
            {
                "source_columns": [source_column],
                "target_columns": [target_column],
                "mode": "exact",
                "required": True,
                "value_pairs": [],
                "reason": "normalized column names agree",
            }
        )
    return relations


def _looks_numeric(value: str) -> bool:
    try:
        float(text(value).replace(",", ""))
        return True
    except Exception:
        return False


def _rank_heuristic_columns(
    rows: list[dict[str, Any]],
    columns: list[str],
    limit: int,
) -> list[str]:
    scored: list[tuple[float, str]] = []
    sample_payloads = [row_payload(row) for row in rows[:300]]
    for column in columns:
        compact_name = compact(column)
        values = []
        seen = set()
        numeric_count = 0
        for payload in sample_payloads:
            value = text(payload.get(column, ""))
            if not value:
                continue
            key = norm(value)
            if key not in seen:
                seen.add(key)
                values.append(value)
            if _looks_numeric(value):
                numeric_count += 1
        if not values:
            continue
        numeric_ratio = numeric_count / max(1, len(sample_payloads))
        score = 0.0
        if any(hint in compact_name for hint in HEURISTIC_POSITIVE_COLUMN_HINTS):
            score += 4.0
        if any(hint in compact_name for hint in HEURISTIC_NEGATIVE_COLUMN_HINTS):
            score -= 6.0
        if 1 < len(values) <= 80:
            score += 2.0
        if len(values) > 120:
            score -= 2.0
        if numeric_ratio > 0.8 and len(values) > 20:
            score -= 4.0
        score -= len(compact_name) / 100.0
        scored.append((score, column))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [column for _, column in scored[:limit]]


def _value_overlap_relation(
    source_rows: list[dict[str, Any]],
    target_rows: list[dict[str, Any]],
    source_columns: list[str],
    target_column: str,
    target_values: list[str] | None = None,
) -> tuple[float, dict[str, Any] | None]:
    if target_values is None:
        target_values = unique_column_values(target_rows, target_column, limit=HEURISTIC_VALUE_LIMIT)
    if not target_values:
        return 0.0, None
    target_norms = [(target_value, norm(target_value)) for target_value in target_values]
    pairs: list[dict[str, Any]] = []
    matched = 0
    observed = 0
    seen_pairs: set[tuple[tuple[str, ...], str]] = set()
    seen_source_tuples: set[tuple[str, ...]] = set()
    for source_row in source_rows:
        payload = row_payload(source_row)
        source_values = [text(payload.get(column, "")) for column in source_columns]
        if any(not value for value in source_values):
            continue
        source_norms = [norm(value) for value in source_values]
        source_key = tuple(source_norms)
        if source_key in seen_source_tuples:
            continue
        seen_source_tuples.add(source_key)
        observed += 1
        if observed > HEURISTIC_SOURCE_TUPLE_LIMIT:
            break
        hits = [
            target_value
            for target_value, target_norm in target_norms
            if all(source_norm in target_norm for source_norm in source_norms)
        ]
        if len(hits) != 1:
            continue
        pair_key = (tuple(source_norms), norm(hits[0]))
        if pair_key not in seen_pairs:
            seen_pairs.add(pair_key)
            pairs.append({"source_values": source_values, "target_values": [hits[0]]})
        matched += 1
    coverage = matched / observed if observed else 0.0
    if coverage < 0.6 or not pairs:
        return coverage, None
    return coverage, {
        "source_columns": source_columns,
        "target_columns": [target_column],
        "mode": "value_map",
        "required": True,
        "value_pairs": pairs,
        "reason": f"{len(source_columns)} source column value(s) identify target values",
    }


def heuristic_mapping_plan(
    partition_key: str,
    source_rows: list[dict[str, Any]],
    target_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    source_value_column = infer_value_column(source_rows, "source")
    target_value_column = infer_value_column(target_rows, "target")
    source_columns = _usable_columns(source_rows, source_value_column, "source")
    target_columns = _usable_columns(target_rows, target_value_column, "target")
    relations = _exact_column_relations(source_columns, target_columns)
    used_source = {column for relation in relations for column in relation["source_columns"]}
    used_target = {column for relation in relations for column in relation["target_columns"]}

    candidates: list[tuple[float, dict[str, Any]]] = []
    source_pool = [column for column in source_columns if column not in used_source]
    target_pool = [column for column in target_columns if column not in used_target]
    ranked_source = set(_rank_heuristic_columns(source_rows, source_pool, HEURISTIC_MAX_SOURCE_COLUMNS))
    ranked_target = set(_rank_heuristic_columns(target_rows, target_pool, HEURISTIC_MAX_TARGET_COLUMNS))
    remaining_source = [column for column in source_pool if column in ranked_source]
    remaining_target = [column for column in target_pool if column in ranked_target]
    for target_column in remaining_target:
        target_values = unique_column_values(target_rows, target_column, limit=HEURISTIC_VALUE_LIMIT)
        for size in (1, 2):
            for source_combo in itertools.combinations(remaining_source, size):
                coverage, relation = _value_overlap_relation(
                    source_rows,
                    target_rows,
                    list(source_combo),
                    target_column,
                    target_values,
                )
                if relation:
                    candidates.append((coverage + size * 0.01, relation))
    candidates.sort(key=lambda item: item[0], reverse=True)
    for _, relation in candidates:
        source_set = set(relation["source_columns"])
        target_set = set(relation["target_columns"])
        if source_set & used_source or target_set & used_target:
            continue
        relations.append(relation)
        used_source |= source_set
        used_target |= target_set

    confidence = "high" if source_value_column and target_value_column and relations else "low"
    return {
        "partition_key": partition_key,
        "source_value_column": source_value_column,
        "target_value_column": target_value_column,
        "relations": relations,
        "fixed_target_values": {},
        "confidence": confidence,
        "needs_review": confidence != "high",
        "reason": "heuristic schema/value mapping",
    }


def validate_mapping_plan(
    plan: dict[str, Any],
    partition_key: str,
    source_rows: list[dict[str, Any]],
    target_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    source_columns = set(schema_summary(source_rows, sample_limit=0, value_limit=0)["columns"])
    target_columns = set(schema_summary(target_rows, sample_limit=0, value_limit=0)["columns"])
    source_value_column = text(plan.get("source_value_column")) or infer_value_column(source_rows, "source")
    target_value_column = text(plan.get("target_value_column")) or infer_value_column(target_rows, "target")
    relations: list[dict[str, Any]] = []
    for raw_relation in plan.get("relations", []) or []:
        if not isinstance(raw_relation, dict):
            continue
        source_cols = [text(value) for value in raw_relation.get("source_columns", []) or [] if text(value)]
        target_cols = [text(value) for value in raw_relation.get("target_columns", []) or [] if text(value)]
        if not source_cols or not target_cols:
            continue
        if any(column not in source_columns for column in source_cols):
            continue
        if any(column not in target_columns for column in target_cols):
            continue
        value_pairs = []
        for raw_pair in raw_relation.get("value_pairs", []) or []:
            if not isinstance(raw_pair, dict):
                continue
            source_values = [text(value) for value in raw_pair.get("source_values", []) or []]
            target_values = [text(value) for value in raw_pair.get("target_values", []) or []]
            if len(source_values) == len(source_cols) and len(target_values) == len(target_cols):
                value_pairs.append({"source_values": source_values, "target_values": target_values})
        mode = text(raw_relation.get("mode")) or ("value_map" if value_pairs else "exact")
        if mode not in {"exact", "value_map", "contains", "token_overlap"}:
            mode = "value_map" if value_pairs else "exact"
        relations.append(
            {
                "source_columns": source_cols,
                "target_columns": target_cols,
                "mode": mode,
                "required": bool(raw_relation.get("required", True)),
                "value_pairs": value_pairs,
                "reason": text(raw_relation.get("reason")),
            }
        )
    raw_fixed_values = plan.get("fixed_target_values", {}) or {}
    if isinstance(raw_fixed_values, list):
        fixed_items = [
            (item.get("target_column", ""), item.get("target_value", ""))
            for item in raw_fixed_values
            if isinstance(item, dict)
        ]
    elif isinstance(raw_fixed_values, dict):
        fixed_items = list(raw_fixed_values.items())
    else:
        fixed_items = []
    fixed_target_values = {
        text(column): text(value)
        for column, value in fixed_items
        if text(column) in target_columns and text(value)
    }
    needs_review = bool(plan.get("needs_review", False))
    target_can_be_created = compact(target_value_column) == compact("experimental_value")
    if (
        source_value_column not in source_columns
        or (target_value_column not in target_columns and not target_can_be_created)
        or not relations
    ):
        needs_review = True
    return {
        "partition_key": partition_key,
        "source_value_column": source_value_column,
        "target_value_column": target_value_column,
        "relations": relations,
        "fixed_target_values": fixed_target_values,
        "confidence": text(plan.get("confidence")) or "low",
        "needs_review": needs_review,
        "reason": text(plan.get("reason")),
    }


def _tuple_norm(payload: dict[str, str], columns: list[str]) -> tuple[str, ...]:
    return tuple(norm(payload.get(column, "")) for column in columns)


def _relation_matches(
    source_payload: dict[str, str],
    target_payload: dict[str, str],
    relation: dict[str, Any],
) -> tuple[bool, str]:
    source_columns = relation["source_columns"]
    target_columns = relation["target_columns"]
    source_values = _tuple_norm(source_payload, source_columns)
    target_values = _tuple_norm(target_payload, target_columns)
    if any(not value for value in source_values) or any(not value for value in target_values):
        return False, "missing mapped value"
    for pair in relation.get("value_pairs", []) or []:
        if tuple(norm(value) for value in pair["source_values"]) != source_values:
            continue
        expected_target = tuple(norm(value) for value in pair["target_values"])
        return expected_target == target_values, "explicit value mapping"
    mode = relation.get("mode", "exact")
    if mode == "exact":
        return source_values == target_values, "exact normalized values"
    source_joined = " ".join(source_values)
    target_joined = " ".join(target_values)
    if mode == "contains":
        return (
            all(value in target_joined for value in source_values)
            or all(value in source_joined for value in target_values)
        ), "cross-column containment"
    if mode == "token_overlap":
        source_tokens = set(source_joined.split())
        target_tokens = set(target_joined.split())
        union = source_tokens | target_tokens
        score = len(source_tokens & target_tokens) / len(union) if union else 0.0
        return score >= 0.8, f"token overlap={score:.3f}"
    return False, "no applicable mapping"


def evaluate_pair(
    source_row: dict[str, Any],
    target_row: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    source_payload = row_payload(source_row)
    target_payload = row_payload(target_row)
    reasons: list[str] = []
    matched_relations = 0
    required_relations = 0
    for relation in plan.get("relations", []) or []:
        required = bool(relation.get("required", True))
        if required:
            required_relations += 1
        matched, detail = _relation_matches(source_payload, target_payload, relation)
        label = (
            f"{'+'.join(relation['source_columns'])}"
            f" -> {'+'.join(relation['target_columns'])}: {detail}"
        )
        if matched:
            matched_relations += 1
            reasons.append(label)
        elif required:
            return {
                "matched": False,
                "score": 0,
                "matched_fields": [],
                "reason": label,
            }
    for target_column, expected in (plan.get("fixed_target_values", {}) or {}).items():
        required_relations += 1
        if norm(target_payload.get(target_column, "")) != norm(expected):
            return {
                "matched": False,
                "score": 0,
                "matched_fields": [],
                "reason": f"fixed target mismatch: {target_column}",
            }
        matched_relations += 1
        reasons.append(f"fixed target {target_column}={expected}")
    if required_relations == 0:
        return {"matched": False, "score": 0, "matched_fields": [], "reason": "mapping plan has no required relations"}
    score = round(100 * matched_relations / required_relations)
    return {
        "matched": matched_relations == required_relations,
        "score": score,
        "matched_fields": [
            f"{'+'.join(relation['source_columns'])}->{'+'.join(relation['target_columns'])}"
            for relation in plan.get("relations", []) or []
        ],
        "reason": "; ".join(reasons),
    }
