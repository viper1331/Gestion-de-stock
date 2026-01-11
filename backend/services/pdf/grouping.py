"""Shared grouping helpers for PDF exports."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")


@dataclass
class GroupNode:
    key: str
    value: object
    rows: list[T]
    children: list["GroupNode"]


@dataclass
class GroupStats:
    row_count: int
    child_count: int
    subtotals: dict[str, float]


def _group_sort_value(value: object) -> tuple[int, object]:
    if value is None:
        return (1, "")
    if isinstance(value, (int, float)):
        return (0, value)
    return (0, str(value).lower())


def _stable_sort_rows(
    rows: Iterable[T],
    keys: list[str],
    *,
    key_fn: Callable[[T, str], object],
) -> list[T]:
    sorted_rows = list(rows)
    for key in reversed(keys):
        sorted_rows = sorted(sorted_rows, key=lambda row: _group_sort_value(key_fn(row, key)))
    return sorted_rows


def build_group_tree(
    rows: Iterable[T],
    keys: list[str],
    *,
    key_fn: Callable[[T, str], object],
) -> list[GroupNode]:
    if not keys:
        return []
    sorted_rows = _stable_sort_rows(rows, keys, key_fn=key_fn)
    return _build_group_tree_sorted(sorted_rows, keys, key_fn=key_fn)


def _build_group_tree_sorted(
    rows: list[T],
    keys: list[str],
    *,
    key_fn: Callable[[T, str], object],
) -> list[GroupNode]:
    key = keys[0]
    grouped: list[GroupNode] = []
    for value, group_iter in groupby(rows, key=lambda row: key_fn(row, key)):
        grouped_rows = list(group_iter)
        children = _build_group_tree_sorted(grouped_rows, keys[1:], key_fn=key_fn) if len(keys) > 1 else []
        grouped.append(GroupNode(key=key, value=value, rows=grouped_rows, children=children))
    return grouped


def flatten_groups(groups: Iterable[GroupNode]) -> list[GroupNode]:
    flattened: list[GroupNode] = []
    for group in groups:
        flattened.append(group)
        if group.children:
            flattened.extend(flatten_groups(group.children))
    return flattened


def compute_group_stats(
    group: GroupNode,
    *,
    subtotal_columns: Iterable[str] = (),
    value_fn: Callable[[T, str], object],
) -> GroupStats:
    subtotal_keys = list(subtotal_columns)
    subtotals: dict[str, float] = {key: 0.0 for key in subtotal_keys}
    if subtotal_keys:
        for row in group.rows:
            for key in subtotal_keys:
                value = value_fn(row, key)
                if isinstance(value, (int, float)):
                    subtotals[key] += float(value)
    return GroupStats(row_count=len(group.rows), child_count=len(group.children), subtotals=subtotals)
