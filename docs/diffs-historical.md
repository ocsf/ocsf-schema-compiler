# Historical differences from the ocsf-server v3 compiler

This historical document records differences encountered while replacing the ocsf-server v3 compiler with the ocsf-schema-compiler. It is retained for migration details, compatibility decisions, and design rationale. The current `compile_version` 1 output is documented in [format.md](format.md).

This document refers to the ocsf-server v3 compiler as the "legacy compiler" and its output as the "legacy format". It refers to the ocsf-schema-compiler as the "new compiler" and its output as the "new format", reflecting the terminology used during the replacement project.

## Legacy exported schema vs new format
The ocsf-server's `/export/schema` format does not return all details, requiring use of various `/api` endpoints to retrieve the entire schema. The new format puts everything together.

This section focuses on how the current format differs from the legacy compiler output.

For reference, the legacy `/export/schema` API returns the following top-level structure:
```json5
{
  "base_event": {}, // note: this is broken in current version 3.1.0 (it is not fully processed)
  "classes": {},  // includes "base_event" (this version of base_event is not broken in v3.1.0)
  "object": {},
  "dictionary_attributes": {}, // equivalent to the new schema at dictionary.attributes
  "types": {},  // dictionary types; equivalent to the new schema at dictionary.types.attributes
  "version": "<major>.<minor>.<patch>"
}
```

The main differences at this level are:
- The addition of `compile_version` with value 1. The legacy schema has an implied version of 0.
- The addition of `categories`, `profiles`, and `extensions` information. The legacy schema requires separate API calls to retrieve this information.
- The dictionary is not split into `dictionary_attributes` and `types` but rather presented similar to the metaschema format.

The `/api/categories`, `/api/extensions`, and `/api/profiles` APIs are needed to get the remaining details of the schema.

## Potential extension class uid collision
Class UIDs are meant to be scoped by category. All UIDs in an extension are meant to be scoped by the extension. However there is one situation where this breaks down due to the math used to create the extension-scoped UIDs.

The colliding situation is the following:
1. An extension has a category with a UID that is the same a base schema category. Normally extension categories using the same UID as a base category is fine.
2. The extension has two classes, one of which uses the base schema category above and the other uses the extension category. Both of these classes use the same UID. Normally classes that use the same UID is fine so long as use different categories.

The problem that formula creating an extension-scoped category UID overlaps with the formula for creating an extension-scoped class UID.

These are the formulas.
- Extension-scoped category UID: (100 * category UID)
- Category-scoped class UID:
    - For base schema classes:
        - (1000 * category UID) + class UID
    - For extension classes that use base schema categories:
        - (1000 * ((100 * extension UID) + base category UID)) + class UID
    - For extension classes that use extension categories:
        - (1000 * ((100 * extension UID) + unscoped category UID)) + class UID

The flaw is that for extension classes, both base category UIDs and extension category UIDs are both treated as if they come from the extension.

The old compiler does not detect this situation and generates extension classes with the same UID values. The new compiler issues a warning when extension category UIDs match a base category UID, as well as an error for class UID collisions. Indeed, the new compiler checks for collisions with all UIDs: extension UIDs, categories (after extension-scoping), and class UIDs (after extension-scoping).

## Other differences
This section cover a laundry list of other differences. Many of these are addressed in the ocsf-server [Bug fixes](https://github.com/ocsf/ocsf-server/pull/169) pull request, created as a way to more easily compare file differences during development of the new compiler.

### Difference 1: broken top-level base_event
The the base event class at legacy output's `base_event` key is not fully processed. This is a longstanding regression bug. Note that the base event class in the legacy schema's `classes` at `classes.base_event` is not fully processed.

### Difference 2: profiles are sorted
The new compiler sorts the various `profiles` string arrays. With the legacy compiler, the order was non-deterministic.

### Difference 3: reverse merging of extension class and object attributes to dictionary
The legacy compiler reverse merged details of extension class and object attributes to the base dictionary. It is unclear why this was done. The new compiler does not do this.

Quirks and bugs I've seen caused by this weirdness:
- The `caption`, `description`, `group`, `profile`, and `requirement` values from classes and/or objects propagated back to dictionary attributes. I did not notice these cases propagated onward to other classes and objects.
- The `group` values propagated from a class or object to the dictionary and then to another class or object.

These should be be non-issues. The cases above do not affect encodings or event validation. However, due to weirdness of this bug, there may well be a private extension out there that propagates a material change.

### Difference 4: profile consolidation in classes and objects
The `profiles` attribute in classes and objects is a consolidation of all its own profiles and all child objects. The legacy compiler implementation did not fully consolidate the profiles of all objects. Interestingly, this did not affect the consolidation of profiles in `classes`.

With the new compiler, `profiles` field in objects includes those of all children. The following objects are affected: `actor`, `affected_package`, `application`, `cis_benchmark_result`, `idp`, `metadata`, `remediation`, `startup_item`, and `vulnerability`.

### Difference 5: dictionary data type extension information
The new compiler adds `extension` and `extension_id` attributes to dictionary data types coming from extensions. This is done for consistency with dictionary attributes.

### Difference 6: type_name set properly for class and object refined types
In dictionary types that are subtypes, `type` refers to the base type's name (e.g., `string_t`), and `type_name` refers to the base type's caption (e.g., "String").

Class and object attributes are allowed to refine the type of their attributes to a subtype or the original. In these cases, legacy compiler was incorrectly populating the attribute details with the dictionary attribute's original base type and caption, rather than the refined type's base type and caption.

### Difference 7: handling of extension-scoped names
As of v0.9.8, the new compiler now uses extension-scoped names the same way as the old compiler with two differences: extension defined dictionary types and other extension names that collide with base schema names.

First, dictionary types are handled different. The old compiler uses unscoped names for dictionary data types defined in extensions. This opens up the possibility new collisions should a future base schema version also add a dictionary data type with the same name. By default, the new compiler uses extension-scoped names for dictionary types defined in extensions other than platform extensions. The dictionary types added in platform extensions remain unscoped for backwards compatibility.

This behavior can be changed with the `-u, --unscoped-dictionary-types` option. Developers of existing extensions that define dictionary types will want to use this option to avoid a breaking change when using the new compiler.

Second, extension items with names that collide with base schema names cause an error by default, since this causes uses in the extension to _shadow_ the same item in the base schema, preventing the extension from using the base schema version of this item. (Remember that extensions refer to both base schema names and their own item names without a scope.) This behavior can be changed with the `-a, --allow-shadowing` option. When shadowed names are enabled, the new compiler will still issue a warning since additions to existing schema should still avoid these name collisions.

### Difference 8: class and object attribute profile change
The new compiler uses `profiles` in class and object attributes. The allows multiple profiles to affect the same attribute. This amounts to design flaw in the legacy compiler output format since it was always possible to define multiple profiles that affect the same attribute.

### Difference 9: extension are processed deterministically
The new compiler processes extensions in a deterministic manner. This is useful in cases where extensions extend or patch items in other extensions.

Processing order:
1. Platform extensions — those in the base schema's `extensions` directory — are processed first, in ascending extension UID order.
2. Other extensions are processed in ascending extension UID order.

By contract, the old compiler processed extension in a partial order. Each paths in the `SCHEMA_EXTENSION` environment variable was considered in order, however the extensions inside each path were not processed in any sort order.

### Difference 10: undocumented dictionary attribute overwrite flag
The new compiler removes support for the undocumented `overwrite` property of dictionary attributes.

Note that the dictionary attribute `overwrite` property has never been supported by the metaschema. I suspect that the "overwrite" property has never been actively used.

The old compiler allowed modification of dictionary attributes with this property. However, this creates the possibility of incompatible schemas.

### Difference 11: extension names that shadow base schema names
Extension names that that can shadow base schema names are an error by default.

Shadowing can occur with the following kinds of extension defined items:
- Category names
- Class names
- Object names
- Dictionary attribute names
- Dictionary type names
    - This applies to non-platform (_private_) extension when the `-u`, `--unscoped-dictionary-types` option is _not_ enabled (the default). Dictionary type names that collide with the base schema are always an error for platform extensions, and are an error for non-platform (_private_) extensions when the `-u`, `--unscoped-dictionary-types` is enabled.
- Profile names

With the definition of an extension all names are unscoped. There is no way to distinguish between the base schema version of a name and an extension version of with the same name. When shadowing is enabled, the extension can _only_ use their version of the named item.

This behavior can be changed with the `-a`, `--allow-shadowing` compiler option. This option is only recommended for existing extensions to maintain backwards compatibility. When enabled, shadowed names become a warning. These warnings should be examined since newly defined names should avoid colliding with base schema names to allow current or future uses of the base schema name.

**TODO:** Should class names be checked for shadowing? These don't seem to be used anywhere. This check will be left for now pending feedback from the community.

### Difference 12: extension profiles without extension-scope
Most extension-defined items are referenced without an extension-scope, however when profile names are referenced in the extension class and object top-level `profiles` attribute, they are typically referenced _with_ an extension-scope.

When an extension-define profile is referenced _without_ a scope, things get messy. The old compiler simply keeps the unscoped profile name, causing a mismatch between the profile's name in attributes that are enabled by the profile, and the name of the profile in the top-level class or object `profiles` property.

When the new compiler encounters an unscoped profile name that is defined in the extension, it adds the extension-scope to the name. This fix-up avoids the name mismatch caused by the old compiler.

#### Include files and extension-scoped profiles
Profile are also typically implemented using the magic `$include` attribute name in class and object definition with a value that is a relative path. For extensions, the include file handling always looks for this file _first_ relative to the extension's base directory (where the `extension.json` file is at), and next in the base schema directory. (Both the old and new compilers share this behavior.)

The old compiler's extension-define profile name mismatch above is further compounded by always pulling in the extension-define include file. In other words, if an extension tried to define a shadowed, extension-specific version of a profile with the same name as a base class, but one in one case wanted an extension class or object to use the base schema profile, it wouldn't work. Although class or object would have the base schema's profile name in its top-level `profiles` attribute, the details included with the `$include` directive would pull in the extension-specific attributes.

In short, the old compiler's approach is broken in this case. The new compiler tries to do something sensible, allowing unscoped extension-define profile name references to work like every other extension item name reference: unscoped.

### Difference 13: patched class and object top-level `profiles` property with `null` value
In patched classes and objects that end up with no profiles (the top-level profiles), the new compiler leaves out the `profiles` top-level property, while the old compiler emits `"profiles": null`. This is only a textual difference as there is no logical difference between a `null` value and a missing property.

## Errors detected by new compiler
The new compiler is stricter than the legacy compiler. Below are the more notable errors.

### Error: extension dictionary type name collision with base schema dictionary type
Dictionary types defined in extensions other than platform extension are now extension-scoped by default. Dictionary types defined in platform extension remain unscoped for backwards compatibility. When the unscoped dictionary types option is enabled, name collisions with the base dictionary types is an error.

If you are maintaining an extension, and this error occurs when compiling with a new version of the base schema, this means your extension is no longer compatible with the base schema from that version and forward. Your only options are to use a different dictionary type name in your extensions (a backwards incompatible change that _might_ be tolerable in your organization's specific usage), or create your own incompatible fork of the base schema. In other words, you're stuck and there is no good path forward.

This is new behavior with v0.9.8. The old compiler allowed modifying base schema dictionary types, silently allowing the possibility to create a schema incompatible with a schema compiled without your extension.

### Error: unique ID collision
The new compiler checks for unique ID collisions in categories, classes, and extensions.
