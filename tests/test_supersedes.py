import unittest
from pathlib import Path

from ocsf_schema_compiler.compiler import SchemaCompiler
from ocsf_schema_compiler.jsonish import JObject

BASE_DIR = Path(__file__).parent


def _make_compiler(browser_mode: bool) -> SchemaCompiler:
    # The reverse-reference pass operates on self._dictionary directly, so a schema
    # path is only needed to satisfy the constructor; compile() is never called.
    return SchemaCompiler(
        Path(BASE_DIR, "uncompiled-schemas/ocsf-schema-v1.6.0"),
        browser_mode=browser_mode,
    )


def _dictionary(attributes: JObject) -> JObject:
    return {"attributes": attributes, "types": {"attributes": {}}}


class TestSupersedes(unittest.TestCase):
    def test_reverse_marker_added_to_replacement(self):
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

        attributes = compiler._dictionary["attributes"]
        self.assertNotIn("_supersedes", attributes["app"])
        self.assertEqual(
            attributes["application"]["_supersedes"],
            [{"type": "app", "since": "1.9.0"}],
        )

    def test_multiple_replacements(self):
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

        attributes = compiler._dictionary["attributes"]
        self.assertEqual(
            attributes["model"]["_supersedes"],
            [{"type": "cpu_type", "since": "1.9.0"}],
        )
        self.assertEqual(
            attributes["vendor_name"]["_supersedes"],
            [{"type": "cpu_type", "since": "1.9.0"}],
        )

    def test_aggregates_multiple_deprecated_onto_one_replacement(self):
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

        supersedes = compiler._dictionary["attributes"]["related_cwes"]["_supersedes"]
        # Sorted by deprecated attribute name.
        self.assertEqual([entry["type"] for entry in supersedes], ["cwe_uid", "cwe_url"])

    def test_dotted_path_anchors_on_base_attribute(self):
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

        self.assertIn("_supersedes", compiler._dictionary["attributes"]["email"])

    def test_unresolvable_replacement_is_skipped(self):
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

        # finding_info is not a dictionary attribute here, so there is nothing to anchor
        # the reverse marker on. This must not raise.
        compiler._add_dictionary_attribute_supersedes()

        self.assertNotIn(
            "_supersedes", compiler._dictionary["attributes"]["finding"]
        )

    def test_no_marker_without_browser_mode(self):
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

        self.assertNotIn(
            "_supersedes", compiler._dictionary["attributes"]["application"]
        )

    def test_deprecated_without_superseded_by_is_ignored(self):
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

        self.assertNotIn("_supersedes", compiler._dictionary["attributes"]["other"])

    def test_empty_superseded_by_creates_no_marker(self):
        # An empty superseded_by means "removed with no replacement": no reverse marker.
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

        self.assertNotIn("_supersedes", compiler._dictionary["attributes"]["other"])
        self.assertNotIn("_supersedes", compiler._dictionary["attributes"]["removed"])


class TestLocalAttributeSupersedes(unittest.TestCase):
    def test_sibling_replacement_in_same_item(self):
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

        resources = compiler._classes["user_access"]["attributes"]["resources"]
        self.assertEqual(
            resources["_supersedes"],
            [{"type": "resource", "since": "1.5.0"}],
        )
        # The deprecated attribute itself is not marked.
        self.assertNotIn(
            "_supersedes",
            compiler._classes["user_access"]["attributes"]["resource"],
        )

    def test_non_sibling_replacement_is_skipped(self):
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

        # email is not a sibling attribute here, so nothing local to anchor on.
        compiler._add_local_attribute_supersedes()

        self.assertNotIn(
            "_supersedes",
            compiler._classes["email_activity"]["attributes"]["email_uid"],
        )

    def test_no_marker_without_browser_mode(self):
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
            "_supersedes", compiler._classes["c"]["attributes"]["new_attr"]
        )


class TestItemSupersedes(unittest.TestCase):
    def test_class_supersedes_class(self):
        compiler = _make_compiler(browser_mode=True)
        compiler._classes = {
            "user_access": {
                "attributes": {},
                "@deprecated": {
                    "message": "Use User Management instead.",
                    "since": "1.6.0",
                    "superseded_by": ["user_management"],
                },
            },
            "user_management": {"attributes": {}},
        }
        compiler._objects = {}

        compiler._add_item_supersedes()

        self.assertEqual(
            compiler._classes["user_management"]["_supersedes"],
            [{"type": "user_access", "since": "1.6.0"}],
        )

    def test_multiple_deprecated_classes_aggregate_on_replacement(self):
        compiler = _make_compiler(browser_mode=True)
        compiler._classes = {
            "file_query": {
                "attributes": {},
                "@deprecated": {
                    "message": "Use Live Evidence Info.",
                    "since": "1.1.0",
                    "superseded_by": ["evidence_info"],
                },
            },
            "job_query": {
                "attributes": {},
                "@deprecated": {
                    "message": "Use Live Evidence Info.",
                    "since": "1.1.0",
                    "superseded_by": ["evidence_info"],
                },
            },
            "evidence_info": {"attributes": {}},
        }
        compiler._objects = {}

        compiler._add_item_supersedes()

        self.assertEqual(
            [e["type"] for e in compiler._classes["evidence_info"]["_supersedes"]],
            ["file_query", "job_query"],
        )

    def test_object_supersedes_object(self):
        compiler = _make_compiler(browser_mode=True)
        compiler._classes = {}
        compiler._objects = {
            "finding": {
                "attributes": {},
                "@deprecated": {
                    "message": "Use finding_info.",
                    "since": "1.0.0",
                    "superseded_by": ["finding_info"],
                },
            },
            "finding_info": {"attributes": {}},
        }

        compiler._add_item_supersedes()

        self.assertEqual(
            compiler._objects["finding_info"]["_supersedes"],
            [{"type": "finding", "since": "1.0.0"}],
        )

    def test_unresolvable_replacement_is_skipped(self):
        compiler = _make_compiler(browser_mode=True)
        compiler._classes = {
            "security_finding": {
                "attributes": {},
                "@deprecated": {
                    "message": "Use specific classes.",
                    "since": "1.1.0",
                    "superseded_by": ["nonexistent_class"],
                },
            }
        }
        compiler._objects = {}

        # Must not raise; no marker created anywhere.
        compiler._add_item_supersedes()

        self.assertNotIn("_supersedes", compiler._classes["security_finding"])


class TestEnumValueSupersedes(unittest.TestCase):
    def _compiler_with_enum(self, enum):
        compiler = _make_compiler(browser_mode=True)
        compiler._classes = {}
        compiler._objects = {
            "reg_value": {"attributes": {"type_id": {"enum": enum}}}
        }
        return compiler

    def test_sibling_enum_value_replacement(self):
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

        enum = compiler._objects["reg_value"]["attributes"]["type_id"]["enum"]
        self.assertEqual(enum["8"]["_supersedes"], [{"type": "9", "since": "1.6.0"}])
        # The deprecated value itself is not marked.
        self.assertNotIn("_supersedes", enum["9"])

    def test_non_sibling_reference_is_skipped(self):
        # superseded_by names an attribute, not a sibling enum key.
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

        enum = compiler._objects["reg_value"]["attributes"]["type_id"]["enum"]
        self.assertNotIn("_supersedes", enum["4"])

    def test_no_marker_without_browser_mode(self):
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
        compiler.browser_mode = False

        compiler._add_enum_value_supersedes()

        enum = compiler._objects["reg_value"]["attributes"]["type_id"]["enum"]
        self.assertNotIn("_supersedes", enum["8"])


if __name__ == "__main__":
    unittest.main()
