import json
import os
import unittest
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

from ocsf_schema_compiler.compiler import SchemaCompiler

BASE_DIR = Path(__file__).parent

_os_walk = os.walk


def _reversed_walk(
    top: str | os.PathLike[str], topdown: bool = True
) -> Iterator[tuple[str, list[str], list[str]]]:
    """
    Simulate a filesystem that lists directory entries in a different order by
    reversing the order of the real os.walk results and of each file list.
    """
    for dir_path, dir_names, file_names in reversed(list(_os_walk(top, topdown))):
        yield dir_path, dir_names, list(reversed(file_names))


def _compile_to_json(extensions_paths: list[Path] | None = None) -> str:
    compiler = SchemaCompiler(
        Path(BASE_DIR, "uncompiled-schemas/ocsf-schema-v1.6.0"),
        extensions_paths=extensions_paths,
    )
    return json.dumps(compiler.compile())


class TestDeterministicOutput(unittest.TestCase):
    """Compiled output must not depend on the filesystem's directory order."""

    def test_base_schema(self):
        expected = _compile_to_json()
        with patch("os.walk", _reversed_walk):
            actual = _compile_to_json()
        self.assertEqual(actual, expected, "output should be byte-identical")

    def test_with_extension(self):
        extensions = [Path(BASE_DIR, "uncompiled-schemas/example-extensions")]
        expected = _compile_to_json(extensions)
        with patch("os.walk", _reversed_walk):
            actual = _compile_to_json(extensions)
        self.assertEqual(actual, expected, "output should be byte-identical")
