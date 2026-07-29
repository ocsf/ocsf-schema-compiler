# Compiled schema format

This document describes `compile_version` 1 of the normal compiled schema format produced by the OCSF Schema Compiler. It is intended as a human-readable guide for consumers of compiled schemas, rather than as a formal JSON Schema.

The examples and field inventory are based on modern OCSF schemas, including OCSF 1.8.0. Most properties described below are optional and are omitted when they do not apply. Consumers should tolerate properties added by future compiler format versions.

The compiler also supports a legacy output format, documented separately in [legacy_format.md](legacy_format.md), and a browser mode discussed briefly at the end of this document. The migration from the ocsf-server v3 compiler and its compatibility decisions are recorded in [diffs-historical.md](diffs-historical.md).

## Top-level structure

A normal compiled schema is one JSON object:

```json5
{
  "categories": {},
  "classes": {
    "<class-name>": {}
  },
  "compile_version": 1,
  "dictionary": {},
  "extensions": {
    "<extension-name>": {}
  },
  "objects": {
    "<object-name>": {}
  },
  "profiles": {
    "<profile-name>": {}
  },
  "version": "1.8.0"
}
```

`version` is the version of the source OCSF schema. `compile_version` identifies the compiled JSON format; the format documented here has compile version 1.

The other top-level properties are lookup tables or containers described below. Names introduced by an extension may be scoped as `<extension-name>/<item-name>`. The value's own `name` property remains the unscoped name.

## Common structures

### Descriptive properties

Many definitions share these properties:

```json5
{
  "name": "process_activity",      // Machine-readable name.
  "caption": "Process Activity",   // Short, human-readable name.
  "description": "..."             // Longer description; may contain HTML.
}
```

Descriptions and captions originate in the schema and should be treated as display content. Descriptions commonly contain HTML such as `<code>`, `<br>`, and links.

### Extension origin

Definitions originating in an extension may contain:

```json5
{
  "extension": "win",
  "extension_id": 2
}
```

These properties can occur on classes, objects, profiles, dictionary attributes, dictionary types, and compiled item attributes. They identify where a definition was introduced. They are not added merely because a base definition was patched by an extension.

Extension-defined keys are generally scoped in the top-level lookup tables. For example, the key for an extension object may be `win/reg_key`, while its `name` is `reg_key` and its `extension` is `win`.

### References

`references` is an array of external references:

```json5
{
  "references": [
    {
      "description": "RFC 3339",
      "url": "https://www.rfc-editor.org/rfc/rfc3339.html"
    }
  ]
}
```

References may occur on classes, objects, dictionary definitions, attributes, data types, and enumeration entries.

### Deprecation

Deprecated definitions contain an `@deprecated` object:

```json5
{
  "@deprecated": {
    "since": "1.5.0",
    "message": "Use the replacement definition instead.",
    "superseded_by": ["replacement"]
  }
}
```

`superseded_by` names the replacement definitions, if any. Entries are names rather than captions: an attribute or enumeration key in the same context, a class or object name, or a dotted path into one such as `email.uid`. An empty array means the definition was removed with no replacement.

Deprecation metadata may occur on classes, objects, attributes, dictionary attributes, profiles, and enumeration entries.

### Enumerations

An `enum` maps JSON string keys to enumeration details. Numeric values are represented as strings because they are JSON object keys.

```json5
{
  "enum": {
    "0": {
      "caption": "Unknown",
      "description": "The value is unknown."
    },
    "1": {
      "caption": "Allowed"
    },
    "99": {
      "caption": "Other"
    }
  }
}
```

An enumeration entry can contain `caption`, `description`, `source`, `references`, and `@deprecated`. Some compiler-generated enumerations, such as category enumerations, also include `uid`.

## Categories

`categories` contains descriptive metadata and an `attributes` lookup table. Despite the property name, these entries are category definitions, not event attributes.

```json5
{
  "categories": {
    "name": "category",
    "caption": "Categories",
    "description": "...",
    "attributes": {
      "system": {
        "uid": 1,
        "caption": "System Activity",
        "description": "System Activity events."
      }
    }
  }
}
```

Each category has a numeric `uid`, a `caption`, and normally a `description`. Extension categories also have `extension` and `extension_id`; their UIDs are extension-scoped by the compiler. The categories container may retain an `annotations` object from the base schema.

## Dictionary

The dictionary defines reusable attributes and non-object data types.

```json5
{
  "dictionary": {
    "name": "dictionary",
    "caption": "Attribute Dictionary",
    "description": "...",
    "attributes": {
      "<attribute-name>": {}
    },
    "types": {
      "caption": "Data Types",
      "description": "...",
      "attributes": {
        "<type-name>": {}
      }
    }
  }
}
```

### Dictionary attributes

`dictionary.attributes` is the authoritative lookup table for reusable OCSF attributes. A definition can contain:

```json5
{
  "caption": "Source IP",
  "description": "The source IP address.",
  "type": "ip_t",
  "type_name": "IP Address",
  "is_array": true,
  "enum": {},
  "sibling": "status",
  "observable": 2,
  "source": "...",
  "references": [],
  "suppress_checks": ["enum_convention"],
  "@deprecated": {},
  "extension": "example",
  "extension_id": 100
}
```

The properties have these meanings:

- `type` is the dictionary data type used by the attribute. Object-valued attributes use `object_t`.
- `type_name` is the human-readable caption of the data type. It is added by the compiler for non-object types.
- `is_array` indicates that the event value is an array of the declared type rather than one value.
- `enum` defines the permitted or standardized values, as described above.
- `sibling` names the human-readable sibling paired with an enumerated attribute, commonly the non-`_id` form of the attribute name.
- `observable` is the numeric OCSF observable type ID associated with the value.
- `source` records the external or original source of the definition.
- `suppress_checks` records schema convention checks intentionally suppressed by the definition. Modern schemas use values such as `enum_convention` and `sibling_convention`.

An object-valued dictionary attribute additionally contains:

```json5
{
  "type": "object_t",
  "object_type": "user",
  "object_name": "User"
}
```

`object_type` is the key of the object definition in `objects`; `object_name` is its human-readable caption. An extension object type may use a scoped name such as `win/win_service`.

Dictionary attributes do not have a `requirement`. Requirements belong to a specific use of an attribute in a class or object.

### Dictionary data types

`dictionary.types.attributes` maps type names such as `string_t`, `integer_t`, and `ip_t` to type definitions.

```json5
{
  "caption": "IP Address",
  "description": "Internet Protocol address.",
  "type": "string_t",
  "type_name": "String",
  "max_len": 64,
  "range": [0, 65535],
  "regex": "...",
  "values": [false, true],
  "observable": 2,
  "references": [],
  "extension": "example",
  "extension_id": 100
}
```

All types have a `caption` and normally a `description`. The remaining properties are present only when applicable:

- `type` and `type_name` identify the base type and its caption for a subtype. Root types do not have a base type.
- `max_len` limits the length of a value.
- `range` gives the inclusive minimum and maximum numeric values.
- `regex` gives the regular expression a string value must match.
- `values` gives a fixed set of allowed JSON values.
- `observable` associates values of the type with an OCSF observable type ID.

## Classes and objects

`classes` and `objects` are lookup tables containing fully compiled event-class and object definitions. Their attributes have already been merged from dictionary definitions, includes, profiles, patches, and inheritance.

The compiler retains `extends` as useful ancestry information, but consumers do not need to walk the inheritance hierarchy to collect attributes. The `attributes` object on each compiled class or object is already flattened and complete.

The normal format omits hidden or abstract classes and objects, except that the special `base_event` class remains in `classes`. Hidden classes are source definitions without a UID; hidden objects have names beginning with `_`.

### Shared item properties

Classes and objects can contain:

```json5
{
  "name": "authentication",
  "caption": "Authentication",
  "description": "...",
  "extends": "iam",
  "attributes": {
    "<attribute-name>": {}
  },
  "profiles": ["cloud", "example/custom_profile"],
  "constraints": {
    "at_least_one": ["service", "dst_endpoint"],
    "just_one": ["user", "account"]
  },
  "references": [],
  "@deprecated": {},
  "extension": "example",
  "extension_id": 100
}
```

`profiles` is the consolidated, sorted set of profiles used by the item and any nested object types reachable from its attributes. Extension profile names are scoped.

`constraints` expresses relationships between attributes:

- `at_least_one` requires at least one named attribute to be present.
- `just_one` requires exactly one named attribute to be present.

An empty constraints object can occur and has no effect.

### Classes

A class additionally contains:

```json5
{
  "uid": 3002,
  "category": "iam",
  "category_uid": 3,
  "category_name": "Identity & Access Management",
  "associations": {
    "actor.user": ["src_endpoint"]
  },
  "observables": {
    "actor.user.uid": 42
  }
}
```

- `uid` is the fully scoped class UID used as `class_uid` in events. It incorporates category and, where applicable, extension scoping.
- `category` is the category's machine-readable name.
- `category_uid` is the category UID.
- `category_name` is the category caption.
- `associations` maps an attribute path to related attribute paths. Associations show which values belong together when an event contains multiple actors, endpoints, or similar entities.
- `observables`, when present in a source schema, maps class-relative attribute paths to observable type IDs. The compiler also incorporates these definitions into the `observable.type_id` enumeration.

### Objects

An object may have a top-level `observable` property:

```json5
{
  "name": "file",
  "observable": 24
}
```

This associates instances of the object with an OCSF observable type ID. Object names are used by `object_type` in attribute definitions.

## Compiled item attributes

The `attributes` objects inside classes and objects map event attribute names to their complete definitions. The compiler starts with the corresponding dictionary attribute and overlays details specific to that class or object.

```json5
{
  "caption": "Actor",
  "description": "...",
  "type": "object_t",
  "object_type": "actor",
  "object_name": "Actor",
  "is_array": false,
  "requirement": "recommended",
  "group": "context",
  "profiles": ["cloud"],
  "enum": {},
  "sibling": "status",
  "observable": 42,
  "source": "...",
  "references": [],
  "suppress_checks": [],
  "@deprecated": {},
  "extension": "example",
  "extension_id": 100
}
```

In addition to the dictionary properties described earlier, item attributes use:

- `requirement`: `required`, `recommended`, or `optional`.
- `group`: the semantic grouping `primary`, `context`, `classification`, or `occurrence`.
- `profiles`: the profiles that enable or affect this use of the attribute. A JSON `null` value explicitly means the attribute is not profile-dependent. A missing or empty value is likewise treated as having no profile dependency by typical consumers.

The compiler ensures every class and object attribute has a requirement, defaulting a missing requirement to `optional` with a compilation warning.

## Profiles

`profiles` maps profile names to descriptive definitions:

```json5
{
  "profiles": {
    "host": {
      "name": "host",
      "caption": "Host",
      "description": "...",
      "meta": "profile",
      "annotations": {
        "group": "primary"
      }
    },
    "example/custom_profile": {
      "name": "custom_profile",
      "caption": "Custom Profile",
      "description": "...",
      "meta": "profile",
      "extends": "another_profile",
      "extension": "example",
      "extension_id": 100
    }
  }
}
```

`meta` identifies the definition as a profile. `extends`, when present, identifies a parent profile. `annotations` contains properties that the profile applies to its attributes during compilation. In normal output, profile attributes are not repeated here: they have already been incorporated into the compiled class and object attributes.

## Extensions

`extensions` describes every included platform or separately supplied extension:

```json5
{
  "extensions": {
    "win": {
      "uid": 2,
      "name": "win",
      "caption": "Windows",
      "description": "...",
      "version": "1.8.0",
      "platform_extension?": true
    }
  }
}
```

`platform_extension?` is true for an extension discovered in the base schema's `extensions` directory and false for an extension supplied separately to the compiler. `uid` is the extension's numeric identifier.

## Browser mode

Browser mode is enabled with `-b` or `--browser-mode`. It is intended for the [OCSF Server](https://github.com/ocsf/ocsf-server) schema browser and is substantially larger than the normal format. General compiled-schema consumers should use normal mode unless they specifically need the browser's navigation and provenance data.

Browser mode keeps the complete normal format and adds information in these broad categories:

- Top-level `browser_mode?`, `all_classes`, and `all_objects` properties. The `all_*` tables contain concise entries for all definitions, including hidden and abstract definitions that normal output omits.
- Reverse `_links` from dictionary attributes, objects, and profiles to the classes or objects that use them. Link entries carry display and navigation details such as group, type, caption, attribute keys, extension, and deprecation status.
- Attribute provenance such as `_source`, patch provenance such as `_patched_by_extensions` and `_patched_by_extension_ids`, observable-kind metadata in `_observable_kind`, and reverse enum-sibling information in `_sibling_of`.
- Reverse `_supersedes` from a replacement definition back to the deprecated definitions that name it in their `@deprecated.superseded_by`. Each entry carries the deprecated definition's name in `type` and its `since` version, so the browser can show on a live definition which deprecated definition it replaces. Entries are sorted by `type` and are scoped to the context holding the deprecation, so a class- or object-local deprecation does not mark a replacement elsewhere.
- Fully compiled profile attributes, which normal mode intentionally removes after merging them into classes and objects.

Properties beginning with `_` and the browser-specific lookup tables are compiler UI metadata, not part of the event schema needed for ordinary validation, enrichment, or schema inspection.
