import unittest

from ocsf_schema_compiler.exceptions import SchemaException
from ocsf_schema_compiler.jsonish import JObject, j_object
from ocsf_schema_compiler.schema_structure import (
    category_definitions,
    dictionary_attribute_definitions,
    dictionary_type_definitions,
    item_attributes,
    normalize_categories,
    normalize_dictionary,
    normalize_item,
    normalize_items,
)


class TestSchemaStructure(unittest.TestCase):
    def test_normalize_missing_structural_objects(self):
        categories: JObject = {}
        dictionary: JObject = {}
        item: JObject = {}

        normalize_categories(categories, "categories")
        normalize_dictionary(dictionary, "dictionary")
        normalize_item(item, "item")

        self.assertEqual(category_definitions(categories), {})
        self.assertEqual(dictionary_attribute_definitions(dictionary), {})
        self.assertEqual(dictionary_type_definitions(dictionary), {})
        self.assertEqual(item_attributes(item), {})

    def test_normalize_preserves_existing_structural_objects(self):
        categories_attributes: JObject = {"category": {}}
        dictionary_attributes: JObject = {"attribute": {}}
        dictionary_type_attributes: JObject = {"string_t": {}}
        attributes: JObject = {"attribute": {}}
        categories: JObject = {"attributes": categories_attributes}
        dictionary: JObject = {
            "attributes": dictionary_attributes,
            "types": {"attributes": dictionary_type_attributes},
        }
        item: JObject = {"attributes": attributes}

        normalize_categories(categories, "categories")
        normalize_dictionary(dictionary, "dictionary")
        normalize_item(item, "item")

        self.assertIs(category_definitions(categories), categories_attributes)
        self.assertIs(
            dictionary_attribute_definitions(dictionary), dictionary_attributes
        )
        self.assertIs(
            dictionary_type_definitions(dictionary), dictionary_type_attributes
        )
        self.assertIs(item_attributes(item), attributes)

    def test_normalize_rejects_non_object_structural_property(self):
        dictionaries: list[JObject] = [
            {"attributes": None},
            {"types": []},
            {"types": {"attributes": "not an object"}},
        ]
        for dictionary in dictionaries:
            with (
                self.subTest(dictionary=dictionary),
                self.assertRaisesRegex(SchemaException, "to be an object"),
            ):
                normalize_dictionary(dictionary, "dictionary")

    def test_normalize_items_adds_attributes_to_every_item(self):
        items: JObject = {"first": {}, "second": {"attributes": {}}}

        normalize_items(items, "object")

        self.assertEqual(item_attributes(j_object(items["first"])), {})
        self.assertEqual(item_attributes(j_object(items["second"])), {})

    def test_path_helpers_do_not_normalize(self):
        dictionary: JObject = {}

        with self.assertRaises(KeyError):
            _ = dictionary_type_definitions(dictionary)

        self.assertEqual(dictionary, {})


if __name__ == "__main__":
    _ = unittest.main()
