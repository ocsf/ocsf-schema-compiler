from ocsf_schema_compiler.exceptions import SchemaException
from ocsf_schema_compiler.jsonish import JObject, j_object, json_type_from_value


def category_definitions(categories: JObject) -> JObject:
    """Return the normalized category definitions."""
    return j_object(categories["attributes"])


def dictionary_attribute_definitions(dictionary: JObject) -> JObject:
    """Return the normalized dictionary attribute definitions."""
    return j_object(dictionary["attributes"])


def dictionary_type_definitions(dictionary: JObject) -> JObject:
    """Return the normalized dictionary type definitions."""
    types = j_object(dictionary["types"])
    return j_object(types["attributes"])


def item_attributes(item: JObject) -> JObject:
    """Return the normalized attributes of a class, object, profile, or patch."""
    return j_object(item["attributes"])


def _normalize_object(parent: JObject, key: str, context: str) -> JObject:
    """Add a missing object property or return an existing object property."""
    if key not in parent:
        new_value: JObject = {}
        parent[key] = new_value
        return new_value

    value = parent[key]
    if not isinstance(value, dict):
        raise SchemaException(
            f'Expected {context} property "{key}" to be an object, but got'
            f" {json_type_from_value(value)}"
        )
    return value


def normalize_categories(categories: JObject, context: str) -> None:
    """Normalize the structural containers in a categories document."""
    _ = _normalize_object(categories, "attributes", context)


def normalize_dictionary(dictionary: JObject, context: str) -> None:
    """Normalize the structural containers in a dictionary document."""
    _ = _normalize_object(dictionary, "attributes", context)
    types = _normalize_object(dictionary, "types", context)
    _ = _normalize_object(types, "attributes", f"{context}.types")


def normalize_item(item: JObject, context: str) -> None:
    """Normalize attributes in a class, object, profile, or patch."""
    _ = _normalize_object(item, "attributes", context)


def normalize_items(items: JObject, context: str) -> None:
    """Normalize attributes in classes, objects, profiles, or patches."""
    for item_name, item in items.items():
        if not isinstance(item, dict):
            raise SchemaException(
                f'Expected {context} "{item_name}" to be an object, but got'
                f" {json_type_from_value(item)}"
            )
        normalize_item(item, f'{context} "{item_name}"')
