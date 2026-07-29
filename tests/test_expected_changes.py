import logging
import unittest
from pathlib import Path
from sys import stderr
from typing import override

from diff import (  # pyright: ignore[reportImplicitRelativeImport]
    MISSING,
    DiffDictKeys,
    DiffValue,
    diff_objects,
    formatted_diffs,
)

from ocsf_schema_compiler.compiler import SchemaCompiler
from ocsf_schema_compiler.jsonish import JObject
from ocsf_schema_compiler.structured_read import read_json_object_zstandard_file

BASE_DIR = Path(__file__).parent


# This module shows how to make a change to the compiler output and test against an
# existing baseline. In this example, we've added support for multiple profiles to
# affect a class or object attribute, changing class and attributes that used to have a
# "profile" property with null or a string to a "profiles" attribute with a null or a
# list of strings.
@unittest.skip("skip example expected changes test")
class TestExpectedChanges(unittest.TestCase):
    """
    Example test cases showing how to use diff_callback to handle expected changes.
    """

    @classmethod
    @override
    def setUpClass(cls):
        logging.basicConfig(
            format="%(levelname)s: %(message)s", style="%", stream=stderr, level="INFO"
        )

    @override
    def setUp(self):
        print(file=stderr)  # so logs start on new line

    def test_current(self):
        compiler = SchemaCompiler(
            Path(BASE_DIR, "uncompiled-schemas/ocsf-schema-v1.6.0")
        )
        schema = compiler.compile()
        baseline_schema = read_json_object_zstandard_file(
            Path(BASE_DIR, "compiled-baselines/schema-v1.6.0.json.zst")
        )
        ok, diffs = diff_objects(schema, baseline_schema, diff_callback=diff_callback)
        self.assertTrue(
            ok,
            f"schema (left) should match baseline (right):\n{formatted_diffs(diffs)}",
        )
        print("Diffs are all expected")
        for diff in diffs:
            print(diff.formatted_string())


def diff_callback(
    key: str,
    path: list[str],
    left: JObject,
    right: JObject,
    left_diff: DiffValue,
    right_diff: DiffValue,
) -> bool:
    # We are expecting attribute profile to change from profile to profiles
    # with values changing from string to array of strings.

    # Check if we are at the attribute property level and are seeing left profiles or
    # right profile
    if (
        len(path) >= 2
        and path[-2] == "attributes"
        and isinstance(left_diff, DiffDictKeys)
        and left_diff.keys == ["profiles"]
        and isinstance(right_diff, DiffDictKeys)
        and right_diff.keys == ["profile"]
    ):
        return True

    # Check if we are at an attribute "profile" property with left missing and right
    # has a value
    if (
        key == "profile"
        and len(path) > 3
        and path[-3] == "attributes"
        and left_diff == MISSING
        and right_diff != MISSING
    ):
        # Check if left object has attribute with "profiles" with list of 1 element that
        # the same as the right value
        left_profiles = left.get("profiles")
        if left_profiles is None and right_diff is None:
            return True
        if (
            isinstance(left_profiles, list)
            and len(left_profiles) == 1
            and left_profiles[0] == right_diff
        ):
            return True

    # Check if we are at an attribute with left is missing right is profiles
    if (
        key == "profiles"
        and len(path) > 3
        and path[-3] == "attributes"
        and left_diff != MISSING
        and right_diff == MISSING
    ):
        # Check if right object has attribute with "profile" that is the same as the 1
        # element in left "profiles" list
        right_profile = right.get("profile")
        if left_diff is None and right_profile is None:
            return True
        if (
            isinstance(left_diff, list)
            and len(left_diff) == 1
            and left_diff[0] == right_profile
        ):
            return True

    return False


if __name__ == "__main__":
    _ = unittest.main()
