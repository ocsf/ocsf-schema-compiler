import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass

from ocsf_schema_compiler.jsonish import JObject, JValue


class Missing:
    pass


MISSING = Missing()


@dataclass
class DiffDictKeys:
    keys: list[str]
    other_name: str


type DiffValue = Missing | DiffDictKeys | JValue


@dataclass
class Difference:
    is_expected: bool
    path: list[str]
    left: DiffValue
    right: DiffValue

    def formatted_string(self) -> str:
        if self.is_expected:
            kind = "expected"
        else:
            kind = "unexpected"
        return (
            f'Diff at "{_path_to_string(self.path)}" ({kind}):'
            f"\n    left  : {_diff_value_to_string(self.left)}"
            f"\n    right : {_diff_value_to_string(self.right)}"
        )


def formatted_diffs(diffs: list[Difference]) -> str:
    # Show unexpected before expected
    unexpected_diffs: list[str] = []
    expected_diffs: list[str] = []
    for diff in diffs:
        if diff.is_expected:
            expected_diffs.append(diff.formatted_string())
        else:
            unexpected_diffs.append(diff.formatted_string())
    return "\n".join(unexpected_diffs + expected_diffs)


type DiffCallback = Callable[
    [str, list[str], JObject, JObject, DiffValue, DiffValue], bool
]


def diff_objects(
    left: JObject, right: JObject, diff_callback: DiffCallback | None = None
) -> tuple[bool, list[Difference]]:
    diffs: list[Difference] = []
    _diff_objects(left, right, diff_callback, [], diffs)
    ok = True
    for diff in diffs:
        if not diff.is_expected:
            ok = False
            break
    return ok, diffs


def _diff_objects(
    left_obj: JObject,
    right_obj: JObject,
    diff_callback: DiffCallback | None,
    base_path: list[str],
    diffs: list[Difference],
) -> None:
    for key in sorted(set(left_obj.keys()) | set(right_obj.keys())):
        path = deepcopy(base_path)
        path.append(key)
        left_dv = _diff_get(left_obj, key)
        right_dv = _diff_get(right_obj, key)
        if isinstance(left_dv, dict) and isinstance(right_dv, dict):
            has_equal_key, left_key_dv, right_key_dv = _is_equal_keys(left_dv, right_dv)
            if has_equal_key:
                _diff_objects(left_dv, right_dv, diff_callback, path, diffs)
            else:
                _callback_append(
                    key,
                    path,
                    left_obj,
                    right_obj,
                    left_key_dv,
                    right_key_dv,
                    diff_callback,
                    diffs,
                )
        elif left_dv != right_dv:
            _callback_append(
                key,
                path,
                left_obj,
                right_obj,
                left_dv,
                right_dv,
                diff_callback,
                diffs,
            )


def _callback_append(
    key: str,
    path: list[str],
    left_obj: JObject,
    right_obj: JObject,
    left_dv: DiffValue,
    right_dv: DiffValue,
    diff_callback: DiffCallback | None,
    diffs: list[Difference],
) -> None:
    if diff_callback:
        is_expected = diff_callback(key, path, left_obj, right_obj, left_dv, right_dv)
        diffs.append(Difference(is_expected, path, left_dv, right_dv))
    else:
        diffs.append(Difference(False, path, left_dv, right_dv))


def _is_equal_keys(
    left_obj: JObject, right_obj: JObject
) -> tuple[bool, DiffValue, DiffValue]:
    left_keys = set(left_obj.keys())
    right_keys = set(right_obj.keys())
    if left_keys == right_keys:
        return True, None, None
    else:
        return (
            False,
            DiffDictKeys(sorted(left_keys - right_keys), other_name="right"),
            DiffDictKeys(sorted(right_keys - left_keys), other_name="left"),
        )


def _diff_get(o: JObject, k: str) -> DiffValue:
    if k in o:
        return o[k]
    return MISSING


def _path_to_string(path: list[str]) -> str:
    return ".".join(path)


def _diff_value_to_string(dv: DiffValue) -> str:
    if isinstance(dv, Missing):
        return "missing"
    if isinstance(dv, DiffDictKeys):
        if dv.keys:
            return f"key(s) not in {dv.other_name} object: {', '.join(dv.keys)}"
        else:
            return f"key(s) not in {dv.other_name} object: none"
    return json.dumps(dv, sort_keys=True)
