# Legacy compiled schema format

This is not a comprehensive document. It was created during development of this project to help understand the existing layout and formatting details, some of which are (were) quite unintuitive.

Top level structure:

```json5
{
  "base_event": {},  // "item" format
  "classes": {},  // includes "base_event"
  "object": {},
  "dictionary_attributes": {},
  "types": {},  // non-object types
  "version": "<major>.<minor>.<patch>"
}
```

## Extension names that are scoped

Extensions create names (JSON object keys) that are sometimes (but annoyingly, not always) scoped by the extension name with the pattern `extension-name/item-name`.

Of these, the only one that must be maintained in any future schema format are extension profile names.

### Extension profiles in classes and dictionary attributes

Extension profiles are scoped when they appear a class `profiles` array and dictionary attributes.

This needs to be maintained. These scopes names DO appear in concrete events.

### Extension class and object names

Extension classes use a scoped name for keys under `classes`, but _not_ for their own `name` attributes.

Extension scoped class names are visible in the browser UI on the classes pages (URL path `/classes`). However, concrete events do not use this form of class names. The closest concrete event attribute would be `class_name`, the enum sibling of `class_uid`, however `class_name` is populated with a class's `caption`.

Similarly, extension scoped object names are visible in the browser UI on the objects page (URL path `/objects`).

This does not seem like it needs to be maintained in a future format. These scoped names do not appear in concrete events.

### Extension object types in class attributes and dictionary attributes

Extension object type names in class and dictionary attributes values are scoped. These are class attribute `object_type` values.

This does not seem like it needs to be maintained in a future format, unless we really want extension items to have their own namespaces (though this isn't always the case in the current format).

NOTE: This does not apply extension patched objects.

These scoped names do not appear in the browser UI.

These scoped names do not appear in concrete events.

This does not seem like it needs to be maintained in a future format.

### Extension dictionary attributes in dictionary

Extension dictionary attributes are scoped in the dictionary itself.

These scoped names do not appear in the browser UI.

These scoped names do not appear in concrete events.

This does not seem like it needs to be maintained in a future format.

## Extension names that are not scoped

# Extension dictionary attributes in classes and objects

Extension dictionary attributes in classes and objects are not scoped when used in classes and objects. These names occur in `attributes` and `constraints`.

NOTE: Due to extension patching of classes and objects, these extension attributes can occur both in extension defined classes and object _and_ base schema classes and objects.

This means that dictionary attributes are not scoped. They must be unique everywhere.

# Extension dictionary types

Dictionary types (types that not objects) defined in extensions are not scoped for any usage.

(Further, these types are not annotated with `extension` and `extension_id` as with other extension defined things.)
