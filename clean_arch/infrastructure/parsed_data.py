"""Lazy lookups over the parsed element and task JSON exports."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass
class ParsedData:
    elements_root: str | None = None
    tasks_root: str | None = None

    def __post_init__(self) -> None:
        self._element_names: dict[int, str] | None = None
        self._task_index: dict[int, dict] | None = None

    def _load_element_names(self) -> dict[int, str]:
        if self._element_names is not None:
            return self._element_names
        result: dict[int, str] = {}
        if self.elements_root and os.path.isdir(self.elements_root):
            for filename in ("058 - NPC_ESSENCE.json",
                             "004 - WEAPON_ESSENCE.json",
                             "007 - ARMOR_ESSENCE.json",
                             "010 - DECORATION_ESSENCE.json",
                             "013 - MEDICINE_ESSENCE.json",
                             "016 - MATERIAL_ESSENCE.json",
                             "039 - MONSTER_ESSENCE.json"):
                path = os.path.join(self.elements_root, filename)
                try:
                    with open(path, "r", encoding="utf-8") as file:
                        document = json.load(file)
                except (OSError, UnicodeError, json.JSONDecodeError):
                    continue
                for item in document.get("items", []):
                    if isinstance(item.get("ID"), int) and item.get("Name"):
                        result.setdefault(item["ID"], str(item["Name"]))
        self._element_names = result
        return result

    def _load_tasks(self) -> dict[int, dict]:
        if self._task_index is not None:
            return self._task_index
        result: dict[int, dict] = {}
        index_path = os.path.join(self.tasks_root or "", "_index.json")
        try:
            with open(index_path, "r", encoding="utf-8") as file:
                rows = json.load(file)
        except (OSError, UnicodeError, json.JSONDecodeError):
            rows = []
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("id"), int):
                result[row["id"]] = row
        self._task_index = result
        return result

    def element_name(self, value: int) -> str | None:
        return self._load_element_names().get(value)

    def task_name(self, value: int) -> str | None:
        row = self._load_tasks().get(value)
        return str(row["name"]) if row and row.get("name") else None
