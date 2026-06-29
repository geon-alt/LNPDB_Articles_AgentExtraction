from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable


def normalize_ft_item_id(value: object) -> str:
    """Normalize figure/table identifiers to a stable lowercase form."""
    text = str(value or "").strip().lower()
    text = text.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    text = re.sub(r"\s+", " ", text)
    replacements = [
        (r"\bextended\s+data\s+fig\.?\b", "extended data figure"),
        (r"\bextended\s+data\s+figure\b", "extended data figure"),
        (r"\bextended\s+data\s+table\b", "extended data table"),
        (r"\bsupplementary\s+fig\.?\b", "supplementary figure"),
        (r"\bsupp\.?\s+fig\.?\b", "supplementary figure"),
        (r"\bsupplementary\s+table\b", "supplementary table"),
        (r"\bsupp\.?\s+table\.?\b", "supplementary table"),
        (r"\bfig\.?\b", "figure"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"\s+", " ", text).strip(" .;,")
    return text


def classify_item(item_id: str) -> str:
    text = normalize_ft_item_id(item_id)
    if "table" in text:
        return "table"
    if "figure" in text:
        return "figure"
    return "unknown"


def is_supplementary(item_id: str) -> bool:
    text = normalize_ft_item_id(item_id)
    return (
        "supplementary" in text
        or bool(re.search(r"\bfigure\s+s\d+", text))
        or bool(re.search(r"\btable\s+s\d+", text))
    )


def _child_suffix(parent: str, child: str) -> str:
    if not child.startswith(parent):
        return ""
    return child[len(parent):].strip()


def filter_hierarchy(items: Iterable[object]) -> list[str]:
    """Drop parent identifiers when more specific panel identifiers exist."""
    normalized = sorted({normalize_ft_item_id(item) for item in items if str(item or "").strip()})
    keep = set(normalized)
    for item in normalized:
        for other in normalized:
            suffix = _child_suffix(item, other)
            if suffix and re.fullmatch(r"[a-z]", suffix):
                keep.discard(item)
                break
    return sorted(keep)


def group_by_base_figure(items: Iterable[object]) -> dict[str, list[str]]:
    """Group panel IDs by their base figure/table ID."""
    groups: dict[str, list[str]] = defaultdict(list)
    pattern = re.compile(r"^((?:supplementary|extended data)\s+)?(figure|table)\s+[a-z]?\d+", re.I)
    for raw_item in items:
        item = normalize_ft_item_id(raw_item)
        if not item:
            continue
        match = pattern.match(item)
        base = match.group(0).strip().lower() if match else item
        groups[base].append(item)
    return {key: sorted(set(values)) for key, values in groups.items()}


def infer_candidates(text: str) -> list[str]:
    """Infer figure/table IDs from free text using regex only."""
    patterns = [
        r"(extended\s+data\s+(?:fig\.?|figure)\s+\d+[a-z]?)",
        r"(extended\s+data\s+table\s+\d+[a-z]?)",
        r"(supplementary\s+figure\s+\d+[a-z]?)",
        r"(supplementary\s+table\s+\d+[a-z]?)",
        r"(figure\s+\d+[a-z]?)",
        r"(fig\.?\s*\d+[a-z]?)",
        r"(table\s+\d+[a-z]?)",
    ]
    candidates: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, str(text or ""), flags=re.I):
            value = normalize_ft_item_id(match)
            if value and value not in candidates:
                candidates.append(value)
    return candidates

