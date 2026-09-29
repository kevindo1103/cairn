from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path

import yaml
from yaml.events import AliasEvent
from yaml.nodes import MappingNode

from .common import Refused, read_bytes, safe_rel


class StrictLoader(yaml.SafeLoader):
    """No duplicate keys, aliases or YAML 1.1 on/off boolean coercion."""
    yaml_implicit_resolvers = {
        key: [(tag, regex) for tag, regex in value if tag != "tag:yaml.org,2002:bool"]
        for key, value in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }

    def compose_node(self, parent, index):
        if self.check_event(AliasEvent):
            raise Refused("YAML_ALIAS_UNSUPPORTED")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        if not isinstance(node, MappingNode):
            raise Refused("YAML_MAPPING_REQUIRED")
        result = {}
        for kn, vn in node.value:
            key = self.construct_object(kn, deep=deep)
            try:
                if key in result:
                    raise Refused("YAML_DUPLICATE_KEY")
                result[key] = self.construct_object(vn, deep=deep)
            except TypeError as exc:
                raise Refused("YAML_KEY_TYPE") from exc
        return result


StrictLoader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$", re.I), list("tTfF"))


def load_yaml(data: bytes | str):
    if len(data) > 4 * 1024 * 1024:
        raise Refused("YAML_TOO_LARGE")
    try:
        return yaml.load(data, Loader=StrictLoader)
    except (yaml.YAMLError, RecursionError, UnicodeError) as exc:
        raise Refused("YAML_INVALID") from exc


def default_config(repo: Path, output: Path) -> dict:
    cfg = load_yaml(files("iceflow_harness.data").joinpath("bingxue.yml").read_bytes())
    cfg["repo_path"] = str(repo.resolve())
    cfg["output_dir"] = str(output.resolve())
    return cfg


def load_config(path: Path) -> dict:
    cfg = load_yaml(read_bytes(path))
    required = {"version", "mode", "repository", "repository_id", "repo_path", "output_dir",
                "ref", "max_api_reads", "api_deadline_seconds", "model_path", "model_classes",
                "migration_dir", "canonical_router", "compatibility_router", "audio_required"}
    if not isinstance(cfg, dict) or set(cfg) != required:
        raise Refused("CONFIG_SHAPE")
    if type(cfg["version"]) is not int or cfg["version"] != 1 or cfg["mode"] != "observe":
        raise Refused("ONLY_OBSERVE_SUPPORTED")
    if not isinstance(cfg["repository"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", cfg["repository"]):
        raise Refused("CONFIG_REPOSITORY")
    if any(x in {".", ".."} for x in cfg["repository"].split("/")):
        raise Refused("CONFIG_REPOSITORY")
    if type(cfg["repository_id"]) is not int or cfg["repository_id"] <= 0:
        raise Refused("CONFIG_REPOSITORY_ID")
    for key, low, high in [("max_api_reads", 1, 20), ("api_deadline_seconds", 1, 120)]:
        if type(cfg[key]) is not int or not low <= cfg[key] <= high:
            raise Refused("CONFIG_BUDGET")
    for key in ["model_path", "migration_dir", "canonical_router", "compatibility_router"]:
        safe_rel(cfg[key])
    if (not isinstance(cfg["model_classes"], list) or not cfg["model_classes"] or
        not all(isinstance(x, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", x) for x in cfg["model_classes"])):
        raise Refused("CONFIG_MODELS")
    if type(cfg["audio_required"]) is not bool:
        raise Refused("CONFIG_AUDIO")
    if not isinstance(cfg["ref"], str) or not cfg["ref"]:
        raise Refused("CONFIG_REF")
    for key in ["repo_path", "output_dir"]:
        if not isinstance(cfg[key], str) or not cfg[key]:
            raise Refused("CONFIG_PATH")
        value = Path(cfg[key]).expanduser()
        if not value.is_absolute():
            value = path.resolve().parent / value
        cfg[key] = str(value)
    return cfg
