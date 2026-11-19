"""Strict, deterministic loading of autoLoop's declarative contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]


class _UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys instead of silently replacing earlier values."""


def _construct_unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode) -> dict:
    loader.flatten_mapping(node)
    result: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in result:
            raise ValueError(f"duplicate YAML key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.load(handle, Loader=_UniqueKeyLoader)
    if not isinstance(loaded, dict):
        raise ValueError(f"expected a YAML mapping: {path}")
    return loaded


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return loaded


def load_contracts(root: Path = ROOT) -> dict[str, dict[str, Any]]:
    contract_dir = root / "contracts"
    return {
        "states": load_yaml(contract_dir / "states.yaml"),
        "limits": load_yaml(contract_dir / "limits.yaml"),
        "protected_paths": load_yaml(contract_dir / "protected_paths.yaml"),
        "policies": load_yaml(contract_dir / "policies.yaml"),
        "task": load_json(contract_dir / "task.schema.json"),
        "runner_events": load_json(contract_dir / "runner-events.json"),
        "evidence": load_json(contract_dir / "evidence.schema.json"),
        "report": load_json(contract_dir / "report.schema.json"),
    }
