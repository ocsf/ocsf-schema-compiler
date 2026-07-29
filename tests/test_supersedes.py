# These tests exercise the individual reverse-reference passes directly, which are
# internal to SchemaCompiler.
# pyright: reportPrivateUsage=false

import unittest
from pathlib import Path

from ocsf_schema_compiler.compiler import SchemaCompiler
from ocsf_schema_compiler.jsonish import JObject, j_array, j_object, j_string

BASE_DIR = Path(__file__).parent


def _make_compiler(browser_mode: bool) -> SchemaCompiler:
    # The reverse-reference passes operate on the compiler's dictionary, classes, and
    # objects directly, so a schema path is only needed to satisfy the constructor;
    # compile() is never called.
    return SchemaCompiler(
        Path(BASE_DIR, "uncompiled-schemas/ocsf-schema-v1.6.0"),
        browser_mode=browser_mode,
    )


def _dictionary(attributes: JObject) -> JObject:
    return {"attributes": attributes, "types": {"attributes": {}}}


def _definition(container: JObject, name: str) -> JObject:
    return j_object(container[name])


def _attribute(item: JObject, name: str) -> JObject:
    return j_object(j_object(item["attributes"])[name])


def _supersedes(target: JObject) -> list[JObject]:
    return [j_object(entry) for entry in j_array(target["_supersedes"])]


def _superseded_names(target: JObject) -> list[str]:
    return [j_string(entry["type"]) for entry in _supersedes(target)]


class TestDictionaryAttributeSupersedes(unittest.TestCase):
    def test_reverse_marker_added_to_replacement(self) -> None:
        compiler = _make_compiler(browser_mode=True)
        compiler._dictionary = _dictionary(
            {
                "app": {
                    "caption": "Application",
                    "@deprecated": {
                        "message": "Use application instead.",
                        "since": "1.9.0",
                        "superseded_by": ["application"],
                    },
                },
                "application": {"caption": "Application"},
            }
        )

        compiler._add_dictionary_attribute_supersedes()

        attributes = j_object(compiler._dictionary["attributes"])
        # The deprecated attribute itself is not marked.
        self.assertNotIn("_supersedes", _definition(attributes, "app"))
        self.assertEqual(
            _supersedes(_definition(attributes, "application")),
            [{"type": "app", "since": "1.9.0"}],
        )

    def test_multiple_replacements(self) -> None:
        compiler = _make_compiler(browser_mode=True)
        compiler._dictionary = _dictionary(
            {
                "cpu_type": {
                    "caption": "Processor Type",
                    "@deprecated": {
                        "message": "Use model and vendor_name instead.",
                        "since": "1.9.0",
                        "superseded_by": ["model", "vendor_name"],
                    },
                },
                "model": {"caption": "Model"},
                "vendor_name": {"caption": "Vendor Name"},
            }
        )

        compiler._add_dictionary_attribute_supersedes()

        attributes = j_object(compiler._dictionary["attributes"])
        self.assertEqual(
            _supersedes(_definition(attributes, "model")),
            [{"type": "cpu_type", "since": "1.9.0"}],
        )
        self.assertEqual(
            _supersedes(_definition(attributes, "vendor_name")),
            [{"type": "cpu_type", "since": "1.9.0"}],
        )

    def test_aggregates_multiple_deprecated_onto_one_replacement(self) -> None:
        compiler = _make_compiler(browser_mode=True)
        compiler._dictionary = _dictionary(
            {
                "cwe_uid": {
                    "caption": "CWE UID",
                    "@deprecated": {
                        "message": "Use related_cwes instead.",
                        "since": "1.1.0",
                        "superseded_by": ["related_cwes"],
                    },
                },
                "cwe_url": {
                    "caption": "CWE URL",
                    "@deprecated": {
                        "message": "Use related_cwes instead.",
                        "since": "1.1.0",
                        "superseded_by": ["related_cwes"],
                    },
                },
                "related_cwes": {"caption": "Related CWEs"},
            }
        )

        compiler._add_dictionary_attribute_supersedes()

        attributes = j_object(compiler._dictionary["attributes"])
        # Sorted by deprecated attribute name.
        self.assertEqual(
            _superseded_names(_definition(attributes, "related_cwes")),
            ["cwe_uid", "cwe_url"],
        )

    def test_dotted_path_anchors_on_base_attribute(self) -> None:
        compiler = _make_compiler(browser_mode=True)
        compiler._dictionary = _dictionary(
            {
                "email_uid": {
                    "caption": "Email UID",
                    "@deprecated": {
                        "message": "Use email.uid instead.",
                        "since": "1.4.0",
                        "superseded_by": ["email.uid"],
                    },
                },
                "email": {"caption": "Email"},
            }
        )

        compiler._add_dictionary_attribute_supersedes()

        attributes = j_object(compiler._dictionary["attributes"])
        self.assertEqual(
            _superseded_names(_definition(attributes, "email")), ["email_uid"]
        )

    def test_unresolvable_replacement_is_skipped(self) -> None:
        compiler = _make_compiler(browser_mode=True)
        compiler._dictionary = _dictionary(
            {
                "finding": {
                    "caption": "Finding",
                    "@deprecated": {
                        "message": "Use the finding_info object instead.",
                        "since": "1.0.0",
                        "superseded_by": ["finding_info"],
                    },
                },
            }
        )

        # finding_info is not a dictionary attribute here, so there is nothing to
        # anchor the reverse marker on. This must not raise.
        compiler._add_dictionary_attribute_supersedes()

        attributes = j_object(compiler._dictionary["attributes"])
        self.assertNotIn("_supersedes", _definition(attributes, "finding"))

    def test_no_marker_without_browser_mode(self) -> None:
        compiler = _make_compiler(browser_mode=False)
        compiler._dictionary = _dictionary(
            {
                "app": {
                    "caption": "Application",
                    "@deprecated": {
                        "message": "Use application instead.",
                        "since": "1.9.0",
                        "superseded_by": ["application"],
                    },
                },
                "application": {"caption": "Application"},
            }
        )

        compiler._add_dictionary_attribute_supersedes()

        attributes = j_object(compiler._dictionary["attributes"])
        self.assertNotIn("_supersedes", _definition(attributes, "application"))

    def test_deprecated_without_superseded_by_is_ignored(self) -> None:
        compiler = _make_compiler(browser_mode=True)
        compiler._dictionary = _dictionary(
            {
                "legacy": {
                    "caption": "Legacy",
                    "@deprecated": {
                        "message": "No replacement.",
                        "since": "1.0.0",
                    },
                },
                "other": {"caption": "Other"},
            }
        )

        compiler._add_dictionary_attribute_supersedes()

        attributes = j_object(compiler._dictionary["attributes"])
        self.assertNotIn("_supersedes", _definition(attributes, "other"))

    def test_empty_superseded_by_creates_no_marker(self) -> None:
        # An empty superseded_by means "removed with no replacement": no reverse
        # marker is created anywhere.
        compiler = _make_compiler(browser_mode=True)
        compiler._dictionary = _dictionary(
            {
                "removed": {
                    "caption": "Removed",
                    "@deprecated": {
                        "message": "Removed with no replacement.",
                        "since": "1.0.0",
                        "superseded_by": [],
                    },
                },
                "other": {"caption": "Other"},
            }
        )

        compiler._add_dictionary_attribute_supersedes()

        attributes = j_object(compiler._dictionary["attributes"])
        self.assertNotIn("_supersedes", _definition(attributes, "other"))
        self.assertNotIn("_supersedes", _definition(attributes, "removed"))


class TestLocalAttributeSupersedes(unittest.TestCase):
    def test_replacement_in_same_item(self) -> None:
        compiler = _make_compiler(browser_mode=True)
        compiler._classes = {
            "user_access": {
                "attributes": {
                    "resource": {
                        "@deprecated": {
                            "message": "Use resources instead.",
                            "since": "1.5.0",
                            "superseded_by": ["resources"],
                        }
                    },
                    "resources": {"caption": "Resources"},
                }
            }
        }
        compiler._objects = {}
        compiler._profiles = {}

        compiler._add_local_attribute_supersedes()

        user_access = _definition(compiler._classes, "user_access")
        self.assertEqual(
            _supersedes(_attribute(user_access, "resources")),
            [{"type": "resource", "since": "1.5.0"}],
        )
        # The deprecated attribute itself is not marked.
        self.assertNotIn("_supersedes", _attribute(user_access, "resource"))

    def test_replacement_outside_the_item_is_skipped(self) -> None:
        compiler = _make_compiler(browser_mode=True)
        compiler._classes = {
            "email_activity": {
                "attributes": {
                    "email_uid": {
                        "@deprecated": {
                            "message": "Use email.uid instead.",
                            "since": "1.4.0",
                            "superseded_by": ["email.uid"],
                        }
                    }
                }
            }
        }
        compiler._objects = {}
        compiler._profiles = {}

        # email is not declared in this class, so there is nothing local to anchor on.
        # A local deprecation must not leak a marker into another context.
        compiler._add_local_attribute_supersedes()

        email_activity = _definition(compiler._classes, "email_activity")
        self.assertNotIn("_supersedes", _attribute(email_activity, "email_uid"))

    def test_no_marker_without_browser_mode(self) -> None:
        compiler = _make_compiler(browser_mode=False)
        compiler._classes = {
            "c": {
                "attributes": {
                    "old": {
                        "@deprecated": {
                            "message": "Use new_attr instead.",
                            "since": "1.0.0",
                            "superseded_by": ["new_attr"],
                        }
                    },
                    "new_attr": {"caption": "New"},
                }
            }
        }
        compiler._objects = {}
        compiler._profiles = {}

        compiler._add_local_attribute_supersedes()

        self.assertNotIn(
            "_supersedes", _attribute(_definition(compiler._classes, "c"), "new_attr")
        )


class TestItemSupersedes(unittest.TestCase):
    def test_class_supersedes_class(self) -> None:
        compiler = _make_compiler(browser_mode=True)
        compiler._classes = {
            "user_access": {
                "attributes": {},
                "@deprecated": {
                    "message": "Use user_management instead.",
                    "since": "1.6.0",
                    "superseded_by": ["user_management"],
                },
            },
            "user_management": {"attributes": {}},
        }
        compiler._objects = {}

        compiler._add_item_supersedes()

        self.assertEqual(
            _supersedes(_definition(compiler._classes, "user_management")),
            [{"type": "user_access", "since": "1.6.0"}],
        )

    def test_multiple_deprecated_classes_aggregate_on_replacement(self) -> None:
        compiler = _make_compiler(browser_mode=True)
        compiler._classes = {
            "file_query": {
                "attributes": {},
                "@deprecated": {
                    "message": "Use evidence_info instead.",
                    "since": "1.1.0",
                    "superseded_by": ["evidence_info"],
                },
            },
            "job_query": {
                "attributes": {},
                "@deprecated": {
                    "message": "Use evidence_info instead.",
                    "since": "1.1.0",
                    "superseded_by": ["evidence_info"],
                },
            },
            "evidence_info": {"attributes": {}},
        }
        compiler._objects = {}

        compiler._add_item_supersedes()

        self.assertEqual(
            _superseded_names(_definition(compiler._classes, "evidence_info")),
            ["file_query", "job_query"],
        )

    def test_object_supersedes_object(self) -> None:
        compiler = _make_compiler(browser_mode=True)
        compiler._classes = {}
        compiler._objects = {
            "finding": {
                "attributes": {},
                "@deprecated": {
                    "message": "Use finding_info instead.",
                    "since": "1.0.0",
                    "superseded_by": ["finding_info"],
                },
            },
            "finding_info": {"attributes": {}},
        }

        compiler._add_item_supersedes()

        self.assertEqual(
            _supersedes(_definition(compiler._objects, "finding_info")),
            [{"type": "finding", "since": "1.0.0"}],
        )

    def test_unresolvable_replacement_is_skipped(self) -> None:
        compiler = _make_compiler(browser_mode=True)
        compiler._classes = {
            "security_finding": {
                "attributes": {},
                "@deprecated": {
                    "message": "Use the specific finding classes instead.",
                    "since": "1.1.0",
                    "superseded_by": ["nonexistent_class"],
                },
            }
        }
        compiler._objects = {}

        # Must not raise; no marker created anywhere.
        compiler._add_item_supersedes()

        self.assertNotIn(
            "_supersedes", _definition(compiler._classes, "security_finding")
        )

    def test_no_marker_without_browser_mode(self) -> None:
        compiler = _make_compiler(browser_mode=False)
        compiler._classes = {
            "user_access": {
                "attributes": {},
                "@deprecated": {
                    "message": "Use user_management instead.",
                    "since": "1.6.0",
                    "superseded_by": ["user_management"],
                },
            },
            "user_management": {"attributes": {}},
        }
        compiler._objects = {}

        compiler._add_item_supersedes()

        self.assertNotIn(
            "_supersedes", _definition(compiler._classes, "user_management")
        )


class TestEnumValueSupersedes(unittest.TestCase):
    def _compiler_with_enum(
        self, enum: JObject, browser_mode: bool = True
    ) -> SchemaCompiler:
        compiler = _make_compiler(browser_mode=browser_mode)
        compiler._classes = {}
        compiler._objects = {"reg_value": {"attributes": {"type_id": {"enum": enum}}}}
        return compiler

    def _enum(self, compiler: SchemaCompiler) -> JObject:
        reg_value = _definition(compiler._objects, "reg_value")
        return j_object(_attribute(reg_value, "type_id")["enum"])

    def test_replacement_value_in_same_enum(self) -> None:
        compiler = self._compiler_with_enum(
            {
                "8": {"caption": "REG_QWORD"},
                "9": {
                    "caption": "REG_QWORD_LITTLE_ENDIAN",
                    "@deprecated": {
                        "message": "Use REG_QWORD instead.",
                        "since": "1.6.0",
                        "superseded_by": ["8"],
                    },
                },
            }
        )

        compiler._add_enum_value_supersedes()

        enum = self._enum(compiler)
        self.assertEqual(
            _supersedes(_definition(enum, "8")), [{"type": "9", "since": "1.6.0"}]
        )
        # The deprecated value itself is not marked.
        self.assertNotIn("_supersedes", _definition(enum, "9"))

    def test_reference_outside_the_enum_is_skipped(self) -> None:
        # superseded_by names an attribute rather than a value in the same enum.
        compiler = self._compiler_with_enum(
            {
                "4": {
                    "caption": "Suppressed",
                    "@deprecated": {
                        "message": "Use status_id instead.",
                        "since": "1.4.0",
                        "superseded_by": ["status_id"],
                    },
                },
            }
        )

        compiler._add_enum_value_supersedes()

        self.assertNotIn("_supersedes", _definition(self._enum(compiler), "4"))

    def test_no_marker_without_browser_mode(self) -> None:
        compiler = self._compiler_with_enum(
            {
                "8": {"caption": "REG_QWORD"},
                "9": {
                    "caption": "REG_QWORD_LITTLE_ENDIAN",
                    "@deprecated": {
                        "message": "Use REG_QWORD instead.",
                        "since": "1.6.0",
                        "superseded_by": ["8"],
                    },
                },
            },
            browser_mode=False,
        )

        compiler._add_enum_value_supersedes()

        self.assertNotIn("_supersedes", _definition(self._enum(compiler), "8"))


if __name__ == "__main__":
    _ = unittest.main()
