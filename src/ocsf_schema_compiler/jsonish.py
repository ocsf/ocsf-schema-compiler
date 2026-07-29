from copy import deepcopy

from ocsf_schema_compiler.exceptions import (
    IncorrectTypeException,
    KeyNotMappedException,
)

# Type aliases for JSON-compatible types. See https://json.org.
# Yes, these are circular, and Python is OK with that.
# As with all Python type hints, these improve code readability and help IDEs identify
# type mismatches.

# JValue is type alias for types compatible with JSON values.
type JValue = JObject | JArray | str | int | float | bool | None
# JObject is a type alias for dictionary compatible with a JSON object.
type JObject = dict[str, JValue]
# JArray is a type alias for types compatible with a JSON array.
type JArray = list[JValue]  # if tuples are ever used, add | tuple[JValue]


def json_type_from_value(value: object) -> str:
    """
    Return JSON type for a Python value. See https://json.org.
    This is intended for error messages.
    """
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    # Test bool before int because it's a subtype of int
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "number (integer)"
    if isinstance(value, float):
        return "number (float)"
    if value is None:
        return "null"
    return f"non-JSON type: {type(value).__name__}"


# These j_* function are for type safety. They keep Pyright happy.
# The assertion error messages are given in terms of JSON types, mostly.
# JSON does not have a integer type, though we have j_integer rather than a more
# general j_number.


def j_object(v: JValue) -> JObject:
    """Ensures value v is a JObject (dict) and returns it."""
    assert isinstance(v, dict), (
        f"j_object: expected object but got {json_type_from_value(v)}: {v}"
    )
    return v


def j_object_optional(v: JValue) -> JObject | None:
    """Ensures value v is a JObject (dict) or None and returns it."""
    assert v is None or isinstance(v, dict), (
        f"j_object: expected object or null but got {json_type_from_value(v)}: {v}"
    )
    return v


def j_array(v: JValue) -> JArray:
    """Ensures value v is a JArray (list) and returns it."""
    assert isinstance(v, list), (
        f"j_array: expected array but got {json_type_from_value(v)}: {v}"
    )
    return v


def j_array_optional(v: JValue) -> JArray | None:
    """Ensures value v is a JArray (list) or None and returns it."""
    assert v is None or isinstance(v, list), (
        f"j_array: expected array or null but got {json_type_from_value(v)}: {v}"
    )
    return v


def j_string(v: JValue) -> str:
    """Ensures value v is a string and returns it."""
    assert isinstance(v, str), (
        f"j_string: expected string but got {json_type_from_value(v)}: {v}"
    )
    return v


def j_string_optional(v: JValue) -> str | None:
    """Ensures value v is a string or None and returns it."""
    assert v is None or isinstance(v, str), (
        f"j_string: expected string or null but got {json_type_from_value(v)}: {v}"
    )
    return v


def j_integer(v: JValue) -> int:
    """Ensures value v is an integer and returns it."""
    assert isinstance(v, int) and not isinstance(v, bool), (
        f"j_integer: expected integer number but got {json_type_from_value(v)}: {v}"
    )
    return v


def deep_copy_j_object(obj: JObject) -> JObject:
    """JObject typed flavor of copy.deepcopy. Returns deep copy of obj."""
    return deepcopy(obj)


def deep_copy_j_array(array: JArray) -> JArray:
    """JArray typed flavor of copy.deepcopy. Returns deep copy of array."""
    return deepcopy(array)


def deep_merge(dest: JObject, source: JObject) -> None:
    """
    In-place merge a source dictionary into a destination dictionary, modifying the
    destination dictionary.

    Note: this merge does not merge lists or deep merge dictionaries inside lists. List
    values are simply overwritten.
    """

    for source_key, source_value in source.items():
        if source_key in dest:
            dest_value = dest[source_key]
            if isinstance(dest_value, dict) and isinstance(source_value, dict):
                deep_merge(dest_value, source_value)
            else:
                # This replaces dest[source_key] with source_value
                dest[source_key] = source_value
        else:
            dest[source_key] = source_value


def get_in(o: JObject, *keys: str) -> JValue:
    v: JValue = None
    key_count = len(keys)
    # stop_i is the top index for current array slice of keys, so starts at 1
    for stop_i, k in enumerate(keys, 1):
        if k in o:
            v = o[k]
        else:
            raise KeyNotMappedException(
                f'Key "{".".join(keys[:stop_i])}" is not mapped'
            )
        if stop_i < key_count:
            if isinstance(v, dict):
                o = j_object(v)
            else:
                raise IncorrectTypeException(
                    f'Expected value of key "{".".join(keys[:stop_i])}" to be an object'
                    f" but got {json_type_from_value(v)}"
                )
    return v


def put_non_none(d: JObject, k: str, v: JValue) -> None:
    if v is not None:
        d[k] = v
