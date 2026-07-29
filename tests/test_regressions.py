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
from ocsf_schema_compiler.exceptions import SchemaException
from ocsf_schema_compiler.jsonish import JObject, get_in
from ocsf_schema_compiler.structured_read import read_json_object_zstandard_file

BASE_DIR = Path(__file__).parent


class TestRegressions(unittest.TestCase):
    """Test cases where compilation should succeed."""

    @classmethod
    @override
    def setUpClass(cls):
        logging.basicConfig(
            format="%(levelname)s: %(message)s", style="%", stream=stderr, level="INFO"
        )

    @override
    def setUp(self):
        print(file=stderr)  # so logs start on new line

    def test_v1_6_0(self):
        compiler = SchemaCompiler(
            Path(BASE_DIR, "uncompiled-schemas/ocsf-schema-v1.6.0")
        )
        schema = compiler.compile()
        baseline_schema = read_json_object_zstandard_file(
            Path(BASE_DIR, "compiled-baselines/schema-v1.6.0.json.zst")
        )
        ok, diffs = diff_objects(schema, baseline_schema)
        self.assertTrue(
            ok,
            f"schema (left) should match baseline (right):\n{formatted_diffs(diffs)}",
        )
        # To make sure diff_objects is implemented correctly, also check with Python
        # equality
        self.assertEqual(schema, baseline_schema, "schema should match baseline")

    def test_v1_6_0_browser_mode(self):
        compiler = SchemaCompiler(
            Path(BASE_DIR, "uncompiled-schemas/ocsf-schema-v1.6.0"), browser_mode=True
        )
        schema = compiler.compile()
        baseline_schema = read_json_object_zstandard_file(
            Path(BASE_DIR, "compiled-baselines/browser-schema-v1.6.0.json.zst")
        )
        ok, diffs = diff_objects(schema, baseline_schema)
        self.assertTrue(
            ok,
            f"schema (left) should match baseline (right):\n{formatted_diffs(diffs)}",
        )
        # To make sure diff_objects is implemented correctly, also check with Python
        # equality
        self.assertEqual(schema, baseline_schema, "schema should match baseline")

    def test_v1_6_0_with_aws_v1_0_0(self):
        compiler = SchemaCompiler(
            Path(BASE_DIR, "uncompiled-schemas/ocsf-schema-v1.6.0"),
            extensions_paths=[Path(BASE_DIR, "uncompiled-schemas/aws-v1.0.0")],
            allow_shadowing=True,
        )
        schema = compiler.compile()
        baseline_schema = read_json_object_zstandard_file(
            Path(BASE_DIR, "compiled-baselines/schema-v1.6.0-aws-v1.0.0.json.zst")
        )
        ok, diffs = diff_objects(schema, baseline_schema)
        self.assertTrue(
            ok,
            f"schema (left) should match baseline (right):\n{formatted_diffs(diffs)}",
        )
        # To make sure diff_objects is implemented correctly, also check with Python
        # equality
        self.assertEqual(schema, baseline_schema, "schema should match baseline")

    def test_v1_6_0_with_aws_v1_0_0_browser_mode(self):
        compiler = SchemaCompiler(
            Path(BASE_DIR, "uncompiled-schemas/ocsf-schema-v1.6.0"),
            extensions_paths=[Path(BASE_DIR, "uncompiled-schemas/aws-v1.0.0")],
            allow_shadowing=True,
            browser_mode=True,
        )
        schema = compiler.compile()
        baseline_schema = read_json_object_zstandard_file(
            Path(
                BASE_DIR, "compiled-baselines/browser-schema-v1.6.0-aws-v1.0.0.json.zst"
            )
        )
        ok, diffs = diff_objects(schema, baseline_schema)
        self.assertTrue(
            ok,
            f"schema (left) should match baseline (right):\n{formatted_diffs(diffs)}",
        )
        # To make sure diff_objects is implemented correctly, also check with Python
        # equality
        self.assertEqual(schema, baseline_schema, "schema should match baseline")

    def test_v1_0_0_rc_2(self):
        compiler = SchemaCompiler(
            Path(BASE_DIR, "uncompiled-schemas/ocsf-schema-v1.0.0-rc.2"),
            ignore_platform_extensions=True,
        )
        schema = compiler.compile()
        baseline_schema = read_json_object_zstandard_file(
            Path(BASE_DIR, "compiled-baselines/schema-v1.0.0-rc.2.json.zst")
        )
        ok, diffs = diff_objects(schema, baseline_schema)
        self.assertTrue(
            ok,
            f"schema (left) should match baseline (right):\n{formatted_diffs(diffs)}",
        )
        # To make sure diff_objects is implemented correctly, also check with Python
        # equality
        self.assertEqual(schema, baseline_schema, "schema should match baseline")

    def test_v1_6_0_with_example_extensions(self):
        compiler = SchemaCompiler(
            Path(BASE_DIR, "uncompiled-schemas/ocsf-schema-v1.6.0"),
            extensions_paths=[Path(BASE_DIR, "uncompiled-schemas/example-extensions")],
            allow_shadowing=True,
        )
        schema = compiler.compile()

        self.assertEqual(
            "alpha/video_games",
            get_in(
                schema,
                "classes",
                "alpha/video_game_activity",
                "category",
            ),
            "Extension class using extension category should be extension-scoped",
        )

        self.assertEqual(
            "video_game_activity",
            get_in(
                schema,
                "classes",
                "alpha/video_game_activity",
                "name",
            ),
            "Extension class name should not be extension-scoped"
            " (consistent with old compiler)",
        )

        self.assertEqual(
            "system",
            get_in(
                schema,
                "classes",
                "alpha/system_comment",
                "category",
            ),
            "Extension class using base category should not be extension-scoped",
        )

        self.assertEqual(
            "system_comment",
            get_in(
                schema,
                "classes",
                "alpha/system_comment_plus",
                "extends",
            ),
            "Extension class extends of extension class should not be extension-scoped"
            " (consistent with old compiler)",
        )

        self.assertEqual(
            "alpha",
            get_in(
                schema,
                "objects",
                "alpha/alpha",
                "name",
            ),
            "Extension object name should not be extension-scoped"
            " (consistent with old compiler)",
        )

        self.assertEqual(
            "alpha",
            get_in(
                schema,
                "objects",
                "alpha/alpha_plus",
                "extends",
            ),
            "Extension object extends of extension object should not be"
            " extension-scoped (consistent with old compiler)",
        )

        # The default compile uses extension-scoped dictionary type names
        self.assertEqual(
            "alpha/video_game_name_t",
            get_in(
                schema,
                "classes",
                "alpha/video_game_activity",
                "attributes",
                "video_game_name",
                "type",
            ),
            "Dictionary type should be extension-scoped (new compiler default)",
        )

        baseline_schema = read_json_object_zstandard_file(
            Path(
                BASE_DIR,
                "compiled-baselines/schema-v1.6.0-example-extensions.json.zst",
            )
        )
        ok, diffs = diff_objects(schema, baseline_schema)
        self.assertTrue(
            ok,
            f"schema (left) should match baseline (right):\n{formatted_diffs(diffs)}",
        )
        # To make sure diff_objects is implemented correctly, also check with Python
        # equality
        self.assertEqual(schema, baseline_schema, "schema should match baseline")

    def test_v1_6_0_with_example_extensions_shadow(self):
        compiler = SchemaCompiler(
            Path(BASE_DIR, "uncompiled-schemas/ocsf-schema-v1.6.0"),
            extensions_paths=[
                Path(BASE_DIR, "uncompiled-schemas/example-extensions-shadow")
            ],
            allow_shadowing=True,
        )
        schema = compiler.compile()

        self.assertEqual(
            "alpha/video_games",
            get_in(
                schema,
                "classes",
                "alpha/video_game_activity",
                "category",
            ),
            "Category should be extension-scoped",
        )

        # The default compile uses extension-scoped dictionary type names
        self.assertEqual(
            "alpha/video_game_name_t",
            get_in(
                schema,
                "classes",
                "alpha/video_game_activity",
                "attributes",
                "video_game_name",
                "type",
            ),
            "Dictionary type should be extension-scoped",
        )

        baseline_schema = read_json_object_zstandard_file(
            Path(
                BASE_DIR,
                "compiled-baselines/schema-v1.6.0-example-extensions-shadow.json.zst",
            )
        )

        ok, diffs = diff_objects(schema, baseline_schema)
        self.assertTrue(
            ok,
            f"schema (left) should match baseline (right):\n{formatted_diffs(diffs)}",
        )
        # To make sure diff_objects is implemented correctly, also check with Python
        # equality
        self.assertEqual(schema, baseline_schema, "schema should match baseline")

    def test_v1_6_0_with_example_extensions_shadow_disabled(self):
        compiler = SchemaCompiler(
            Path(BASE_DIR, "uncompiled-schemas/ocsf-schema-v1.6.0"),
            extensions_paths=[
                Path(BASE_DIR, "uncompiled-schemas/example-extensions-shadow")
            ],
        )

        # The example-extensions-shadowing rely on shadowing
        with self.assertRaisesRegex(
            SchemaException,
            "shadows base schema",
        ):
            _ = compiler.compile()

    def test_v1_6_0_with_example_extensions_shadow_unscoped_dictionary_types(self):
        compiler = SchemaCompiler(
            Path(BASE_DIR, "uncompiled-schemas/ocsf-schema-v1.6.0"),
            extensions_paths=[
                Path(BASE_DIR, "uncompiled-schemas/example-extensions-shadow")
            ],
            allow_shadowing=True,
            unscoped_dictionary_types=True,
        )

        # The dictionary type name collision should fail
        with self.assertRaisesRegex(
            SchemaException,
            'Extension "alpha" dictionary type "ip_t" collides'
            " with base schema dictionary type",
        ):
            _ = compiler.compile()

    def test_legacy_v1_6_0_with_aws_v1_0_0(self):
        # The legacy schema export, even with v3 fixes, creates a slightly different
        # schema, however these differences are not material differences in actual
        # usage. The test uses a diff callback to ensure these differences are ones we
        # expect.

        # Compile using legacy mode to minimize the differences.
        compiler = SchemaCompiler(
            Path(BASE_DIR, "uncompiled-schemas/ocsf-schema-v1.6.0"),
            extensions_paths=[Path(BASE_DIR, "uncompiled-schemas/aws-v1.0.0")],
            allow_shadowing=True,
            legacy_mode=True,
        )
        schema = compiler.compile()
        baseline_schema = read_json_object_zstandard_file(
            Path(
                BASE_DIR,
                "compiled-baselines/server-v3-schema-v1.6.0-aws-v1.0.0.json.zst",
            )
        )
        ok, diffs = diff_objects(
            schema, baseline_schema, diff_callback=legacy_aws_diff_callback
        )
        self.assertTrue(
            ok,
            f"schema (left) should match baseline (right):\n{formatted_diffs(diffs)}",
        )
        # print("Diffs are all expected")
        # for diff in diffs:
        #     print(diff.formatted_string())


def legacy_aws_diff_callback(
    key: str,
    path: list[str],
    _left: JObject,
    _right: JObject,
    left_diff: DiffValue,
    right_diff: DiffValue,
) -> bool:
    if (
        len(path) == 2
        and path[0] == "objects"
        and isinstance(left_diff, DiffDictKeys)
        and left_diff.keys == []
        and isinstance(right_diff, DiffDictKeys)
        and right_diff.keys == ["profiles"]
    ):
        # This compiler does not needlessly set object and class "profiles" to null
        return True

    # Same as above but now we are at the "objects.<object-name>.profiles" level
    return (
        key == "profiles"
        and len(path) == 3
        and path[0] == "objects"
        and left_diff == MISSING
        and right_diff is None
    )


if __name__ == "__main__":
    _ = unittest.main()
