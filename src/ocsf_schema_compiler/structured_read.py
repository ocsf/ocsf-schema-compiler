import json
import os
from collections.abc import Callable
from compression import zstd
from pathlib import Path
from typing import Any

from ocsf_schema_compiler.exceptions import SchemaException
from ocsf_schema_compiler.jsonish import (
    JObject,
    j_object,
    j_string,
    json_type_from_value,
)


# _load_json_object_file loads a JSON file an ensure the result is a JSON object.
# It also has all of the ugly Pyright annotations to deal with the loose typing of
# open() and json.load().
def _load_json_object_file(
    path: Path,
    f: Any,  # pyright: ignore[reportAny, reportExplicitAny]
) -> JObject:
    try:
        v: Any = json.load(f)  # pyright: ignore[reportAny, reportExplicitAny]
    except json.JSONDecodeError as e:
        raise SchemaException(f'Failed to decode schema file "{path}": {e}') from e
    if not isinstance(v, dict):
        t = json_type_from_value(v)  # pyright: ignore[reportAny]
        raise TypeError(
            f"Schema file contains a JSON {t} value, but should contain an object:"
            f" {path}"
        )
    return v  # pyright: ignore[reportUnknownVariableType]


def read_json_object_file(path: Path) -> JObject:
    with open(path) as f:
        return _load_json_object_file(path, f)


def read_json_object_zstandard_file(path: Path) -> JObject:
    with zstd.open(path) as f:
        return _load_json_object_file(path, f)


def read_structured_items(
    base_path: Path,
    kind: str,
    item_callback_fn: Callable[[Path, JObject], None] | None = None,
) -> JObject:
    """
    Read schema structured items found in `kind` directory under `base_path`,
    recursively, and returns dict with unprocessed items, each keyed by their name
    attribute.
    """
    # event classes can be organized in subdirectories, so we must walk to find all the
    # event class JSON files
    item_path = base_path / kind
    items: JObject = {}
    for dir_path, _dir_names, file_names in os.walk(item_path, topdown=False):
        for file_name in file_names:
            if file_name.endswith(".json"):
                file_path = Path(dir_path, file_name)
                obj = read_json_object_file(file_path)
                name = obj.get("name")

                # The way this is tested, "no value" happens when attribute is missing,
                # JSON null (Python None), or an empty value (an empty string, JSON
                # array, JSON object, or even a numeric zero).
                if not name:
                    raise SchemaException(
                        f'The "name" value in {kind} file must have a value:'
                        f" {file_path}"
                    )

                # Ensure name is a string
                if not isinstance(name, str):
                    raise SchemaException(
                        f'The "name" value in {kind} file must be a string,'
                        f" but got {json_type_from_value(name)}: {file_path}"
                    )

                if name in items:
                    existing = j_object(items[name])
                    raise SchemaException(
                        f'Collision of "name" in {kind} file: "{name}" with caption'
                        f' "{obj.get("caption", "")}", collides with {kind} with'
                        f' caption "{existing.get("caption", "")}", file: {file_path}'
                    )
                else:
                    items[name] = obj
                    if item_callback_fn:
                        item_callback_fn(file_path, obj)

    return items


def read_patchable_structured_items(
    base_path: Path,
    kind: str,
    item_callback_fn: Callable[[Path, JObject], None] | None = None,
) -> tuple[JObject, JObject]:
    """
    Read schema "patchable" structured items found in `kind` directory under
    `base_path`, recursively, and returns dataclass with unprocessed items and patches.
    Extension classes and objects are patchable structured items. Items are each keyed
    by their name attribute and patches are keyed by the name of the item to patch.

    Returns tuple of items dictionary and patches dictionary.
    """
    # event classes can be organized in subdirectories, so we must walk to find all the
    # event class JSON files
    item_path = base_path / kind
    items: JObject = {}
    patches: JObject = {}
    for dir_path, _dir_names, file_names in os.walk(item_path, topdown=False):
        for file_name in file_names:
            if file_name.endswith(".json"):
                file_path = Path(dir_path, file_name)
                obj = read_json_object_file(file_path)
                # An extension "patch" occurs in two cases:
                #   1. The item has an "extends" key but no "name" key. This is the
                #      common case in practice.
                #   2. The item has both the "name" and "extends" keys, and both have
                #      the same value.
                name = obj.get("name")
                extends = obj.get("extends")

                # A structured item (a class, object, etc.) must have a name OR an
                # extends value. The way this is tested, "no value" happens when
                # attribute is missing, JSON null (Python None), or an empty value (an
                # empty string, JSON array, JSON object, or even a numeric zero).
                if not name and not extends:
                    raise SchemaException(
                        f'Extension {kind} file does not have a "name" or "extends"'
                        f" value: {file_path}"
                    )

                # Ensure values are strings
                if name is not None and not isinstance(name, str):
                    raise SchemaException(
                        f'The "name" value in extension {kind} file must be a string,'
                        f" but got {json_type_from_value(name)}: {file_path}"
                    )
                if extends is not None and not isinstance(extends, str):
                    raise SchemaException(
                        f'The "extends" value in extension {kind} file must be a'
                        f" string, but got {json_type_from_value(extends)}: {file_path}"
                    )

                if not name or name == extends:
                    # This is a patch definition.
                    # An extension event class or object is a patch when it only defines
                    # "extends" or when "name" and "extends" have the same value. This
                    patch_name = j_string(extends)  # use patch_name for clarity
                    if patch_name in patches:
                        existing = j_object(patches[patch_name])
                        raise SchemaException(
                            f'Collision of patch name ("extends" key) in extension'
                            f' {kind} file: "{patch_name}" with caption'
                            f' "{obj.get("caption", "")}", collides with existing'
                            f' {kind} with caption "{existing.get("caption", "")}",'
                            f" file: {file_path}"
                        )
                    else:
                        patches[patch_name] = obj
                        if item_callback_fn:
                            item_callback_fn(file_path, obj)
                else:
                    # This is a normal definition.
                    if name in items:
                        existing = j_object(items[name])
                        raise SchemaException(
                            f'Collision of "name" in extension {kind} file: "{name}"'
                            f' with caption "{obj.get("caption", "")}", collides with'
                            f' {kind} with caption "{existing.get("caption", "")}",'
                            f" file: {file_path}"
                        )
                    else:
                        items[name] = obj
                        if item_callback_fn:
                            item_callback_fn(file_path, obj)

    return items, patches
