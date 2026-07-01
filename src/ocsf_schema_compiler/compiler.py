import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, override

from ocsf_schema_compiler.exceptions import SchemaException
from ocsf_schema_compiler.jsonish import (
    JValue,
    JObject,
    JArray,
    j_object,
    j_object_optional,
    j_array,
    j_array_optional,
    j_string,
    j_string_optional,
    j_integer,
    json_type_from_value,
    deep_copy_j_object,
    deep_copy_j_array,
    deep_merge,
    put_non_none,
)
from ocsf_schema_compiler.ocsf_utils import (
    is_hidden_class,
    is_hidden_object,
    requirement_to_rank,
    rank_to_requirement,
)
from ocsf_schema_compiler.scoping import (
    extension_scoped_category_uid,
    category_scoped_class_uid,
    class_uid_scoped_type_uid,
    to_extension_scoped_name,
    full_name,
)
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
from ocsf_schema_compiler.structured_read import (
    read_json_object_file,
    read_structured_items,
    read_patchable_structured_items,
)
from ocsf_schema_compiler.utils import pretty_json_encode


logger = logging.getLogger(__name__)


type PatchList = list[JObject]
"""
PatchList is a type alias for a list patches to an item (a class or object) held in a
JObject. A list is needed because multiple extensions can patch the same item.
"""

type PatchDict = dict[str, PatchList]
"""
PatchDict is a type alias for a dictionary from an item name (a class or object name)
to a list of patches for that item.
"""


class SchemaCompiler:
    def __init__(
        self,
        schema_path: Path,
        ignore_platform_extensions: bool = False,
        extensions_paths: list[Path] | None = None,
        unscoped_dictionary_types: bool = False,
        allow_shadowing: bool = False,
        browser_mode: bool = False,
        legacy_mode: bool = False,
    ) -> None:
        if browser_mode and legacy_mode:
            raise SchemaException("Browser mode and legacy mode are mutually exclusive")

        self.schema_path: Path = schema_path
        self.ignore_platform_extensions: bool = ignore_platform_extensions
        self.extensions_paths: list[Path] | None = extensions_paths
        self.unscoped_dictionary_types: bool = unscoped_dictionary_types
        self.allow_shadowing: bool = allow_shadowing
        self.browser_mode: bool = browser_mode
        self.legacy_mode: bool = legacy_mode

        logger.info("Schema path: %s", self.schema_path)
        if self.ignore_platform_extensions:
            logger.info(
                "Ignoring platform extensions (if any) at path: %s",
                self.schema_path / "extensions",
            )
        else:
            logger.info(
                "Including platform extensions (if any) at path: %s",
                self.schema_path / "extensions",
            )
        if self.extensions_paths:
            logger.info(
                "Including extensions path(s): %s",
                ", ".join(list(map(str, self.extensions_paths))),
            )
        if self.unscoped_dictionary_types:
            logger.info(
                "Extension defined dictionary types will be un-scoped."
                " A name collision with another dictionary type will cause an error."
            )
        else:
            logger.info(
                "Extension defined dictionary types will be extension-scoped, other"
                " than platform extension dictionary types, which will remain"
                " un-scoped for backwards compatibility."
            )
        if self.allow_shadowing:
            logger.info(
                "Allow shadowing enabled. Names in extension can shadow base schema"
                " names. Shadowed names block an extension ability to the base version"
                " of the named item. Warnings will be logged when shadowing occurs."
            )
        if self.browser_mode:
            logger.info(
                "Browser mode enabled."
                " Including extra information needed by the schema browser (the OCSF"
                " Server)."
            )
        if self.legacy_mode:
            logger.info(
                "Legacy mode enabled. Compiled output will be in legacy schema export"
                " format and layout."
            )

        self._is_compiled: bool = False
        self._warning_count: int = 0
        self._version: str = "0.0.0-undefined"
        self._categories: JObject = {}
        self._dictionary: JObject = {}
        self._classes: JObject = {}
        # class patches consolidated from all extensions
        self._class_patches: PatchDict = {}
        self._objects: JObject = {}
        # object patches consolidated from all extensions
        self._object_patches: PatchDict = {}
        self._profiles: JObject = {}
        # The extensions here are just the extension information as used by the schema
        # browser, not the complete data used during schema compilation. The values in
        # this JObject are thus a subset of the information in the Extension dataclass.
        self._extensions: JObject = {}
        self._platform_extension_id_set: frozenset[int] = frozenset()

        self._include_cache: dict[Path, JObject] = {}
        # Observable type_id values extracted from all observable sources
        # Used to detect collisions and populate the observable object's type_id enum
        self._observable_type_id_dict: JObject = {}
        # Slice of classes before removing "hidden" / abstract classes
        self._all_classes: JObject = {}
        # Slice of objects before removing "hidden" / abstract objects
        self._all_objects: JObject = {}

    def compile(self) -> JObject:
        if self._is_compiled:
            raise SchemaException(
                "Schema already compiled (compile can only be run once)"
            )
        self._is_compiled = True

        logger.info("Compiling schema")

        if not self.schema_path.is_dir():
            raise FileNotFoundError(
                f"Schema path is not a directory: {self.schema_path}"
            )

        self._read_base_schema()

        if self._version == "1.0.0-rc.2" and not self.ignore_platform_extensions:
            raise SchemaException(
                'Compiling the 1.0.0-rc.2 schema with its "dev" extension is not'
                " supported because it has overrides that are now considered errors."
                " Use the -i, --ignore-platform-extensions option."
            )

        self._read_and_merge_extensions()

        self._enrich_dictionary_object_types()

        self._process_classes()
        self._process_objects()

        self._validate_unique_ids(category_definitions(self._categories), "category")
        self._validate_unique_ids(self._classes, "class")

        self._enrich_and_validate_dictionary()
        self._observables_from_dictionary()

        self._validate_object_profiles_and_add_links()
        if self.browser_mode:
            self._add_object_links()
        self._update_observable_enum()
        self._consolidate_object_profiles()
        self._verify_object_attributes_and_add_datetime()

        self._validate_class_profiles_and_add_links()
        self._consolidate_class_profiles()
        self._verify_class_attributes_and_add_datetime()

        self._ensure_attributes_have_requirement()

        self._finish_attributes()

        output = self._create_compile_output()

        logger.info("Compiled schema base version: %s", self._version)
        if self._extensions:
            extensions = list(self._extensions.values())
            extensions.sort(key=_extension_j_value_key)
            logger.info(
                "Compiled schema includes the following extension(s):\n%s",
                pretty_json_encode(extensions),
            )

        if self._warning_count:
            logger.warning("Compile completed with %d warnings(s)", self._warning_count)
        else:
            logger.info("Compile completed successfully")

        return output

    def _warning(self, message: str, *args: JValue | Path) -> None:
        """Log a warning with count tracking."""
        self._warning_count += 1
        # NOTE: There should only be 2 direct calls to logger.warning in this
        #       SchemaCompiler class: here and the final warning count in the
        #       SchemaCompiler.compile method.
        logger.warning(message, *args)

    def _read_base_schema(self) -> None:
        self._read_version()
        self._categories = read_json_object_file(self.schema_path / "categories.json")
        self._dictionary = read_json_object_file(self.schema_path / "dictionary.json")
        self._classes = read_structured_items(
            self.schema_path,
            "events",
            item_callback_fn=self._upgrade_attribute_profiles,
        )
        self._objects = read_structured_items(
            self.schema_path,
            "objects",
            item_callback_fn=self._upgrade_attribute_profiles,
        )
        self._profiles = read_structured_items(
            self.schema_path, "profiles", item_callback_fn=self._cache_profile
        )
        self._normalize_base_schema()
        self._validate_base_profiles()

        self._resolve_includes()

    def _normalize_base_schema(self) -> None:
        normalize_categories(
            self._categories,
            f'base schema categories "{self.schema_path / "categories.json"}"',
        )
        normalize_dictionary(
            self._dictionary,
            f'base schema dictionary "{self.schema_path / "dictionary.json"}"',
        )
        normalize_items(self._classes, "base schema class")
        normalize_items(self._objects, "base schema object")
        normalize_items(self._profiles, "base schema profile")

    def _read_version(self) -> None:
        version_path = self.schema_path / "version.json"
        try:
            obj = read_json_object_file(version_path)
            self._version = j_string(obj["version"])
        except FileNotFoundError as e:
            raise SchemaException(
                "Schema version file does not exist (is this a schema directory?):"
                f" {version_path}"
            ) from e
        except KeyError as e:
            raise SchemaException(
                'The "version" key is missing in the schema version file:'
                f" {version_path}"
            ) from e

    def _upgrade_attribute_profiles(self, path: Path, item: JObject) -> None:
        normalize_item(item, f'schema item "{path}"')
        if not self.legacy_mode:
            # Upgrading class and object attributes with profile properties before
            # processing any "$include" pulling in profiles.
            # (Attributes in profiles cannot use "$include".)
            attributes = item_attributes(item)
            for attribute_name, attribute in attributes.items():
                if attribute_name != "$include":
                    attribute = j_object(attribute)
                    if "profiles" in attribute:
                        # This is a processing bug. The metaschema does not
                        # allow "profiles" in attributes.
                        raise SchemaException(
                            'Unexpectedly found "profiles" in attribute'
                            f" {attribute_name}: {path}"
                        )
                    if "profile" in attribute:
                        profile = attribute["profile"]
                        if profile is None:
                            attribute["profiles"] = None
                        else:
                            profile = j_string(profile)
                            attribute["profiles"] = [profile]
                        del attribute["profile"]

    def _cache_profile(self, path: Path, profile: JObject) -> None:
        normalize_item(profile, f'profile "{path}"')
        self._include_cache[path] = profile

    def _validate_base_profiles(self) -> None:
        # Before potentially resolving includes of profiles and then later finding
        # issues we will validate profiles early to identify the source of problems.
        dictionary_attributes = dictionary_attribute_definitions(self._dictionary)
        for profile_name, profile in self._profiles.items():
            profile = j_object(profile)
            profile_attributes = item_attributes(profile)
            for attribute_name in profile_attributes.keys():
                if attribute_name not in dictionary_attributes:
                    raise SchemaException(
                        f'Attribute "{attribute_name}" in base schema profile'
                        f' "{profile_name}" is not a defined dictionary attribute'
                    )

    @staticmethod
    def _add_attribute_annotations(annotations: JObject, attribute: JObject) -> None:
        for key, value in annotations.items():
            if key == "profiles":
                # This isn't covered by metaschema, but could cause trouble for
                # compilation.
                raise SchemaException(
                    'Unexpectedly found "profiles" in attribute annotations'
                )
            # Only add annotation mappings that do no exist already in annotation
            if key not in attribute:
                attribute[key] = value

    def _read_and_merge_extensions(self) -> None:
        extensions: list[Extension] = self._read_extensions()

        self._validate_extension_profiles(extensions)

        self._resolve_extension_includes(extensions)

        for extension in extensions:
            self._validate_extension_category_unique_ids(extension)
            # Add extension and extension_id values to most things in this extension
            extension.annotate()

        # Before merging to base schema, we need to add scope some of the names used
        # inside extension items.
        self._extension_scope_class_categories(extensions)
        self._extension_scope_types(extensions)
        self._extension_scope_all_profiles_uses(extensions)

        self._merge_extensions_categories(extensions)
        self._merge_extensions_classes(extensions)
        self._merge_extensions_objects(extensions)
        self._merge_extensions_dictionary(extensions)
        self._merge_extensions_profiles(extensions)
        self._append_extension_patches(extensions)

        # Create extension information. This information is needed for the
        # self._browser_mode output format, as well as the final information log showing
        # what was included in the compilation.
        platform_ids: list[int] = []
        for extension in extensions:
            if extension.is_platform_extension:
                platform_ids.append(extension.uid)

            self._extensions[extension.name] = {
                "uid": extension.uid,
                "name": extension.name,
                "platform_extension?": extension.is_platform_extension,
                "caption": extension.caption,
                "description": extension.description,
                "version": extension.version,
            }

        self._platform_extension_id_set = frozenset(platform_ids)

        self._validate_unique_ids(self._extensions, "extension")

    def _read_extensions(self) -> list[Extension]:
        extensions: list[Extension] = []
        if not self.ignore_platform_extensions:
            self._read_extensions_in_path(
                extensions, self.schema_path / "extensions", is_platform_extension=True
            )
        if self.extensions_paths:
            for extensions_path in self.extensions_paths:
                if not extensions_path.is_dir():
                    raise FileNotFoundError(
                        f"Extension path is not a directory: {extensions_path}"
                    )
                self._read_extensions_in_path(
                    extensions, extensions_path, is_platform_extension=False
                )

        # Ensure deterministic application of extensions.
        # This relies on sorting platform extensions before others
        # and then sorting by extension UID.
        extensions.sort()
        return extensions

    def _read_extensions_in_path(
        self, extensions: list[Extension], base_path: Path, is_platform_extension: bool
    ) -> None:
        for dir_path, _dir_names, file_names in os.walk(base_path, topdown=False):
            for file_name in file_names:
                if file_name == "extension.json":
                    # we found an extension at dir_path
                    extension = self._read_extension(
                        Path(dir_path), is_platform_extension
                    )
                    extensions.append(extension)
                    if is_platform_extension:
                        logger.info(
                            'Read platform extension "%s" from directory: %s',
                            extension.name,
                            dir_path,
                        )
                    else:
                        logger.info(
                            'Read extension "%s" from directory: %s',
                            extension.name,
                            dir_path,
                        )

    def _read_extension(
        self, base_path: Path, is_platform_extension: bool
    ) -> Extension:
        if is_platform_extension:
            logger.info("Reading platform extension directory: %s", base_path)
        else:
            logger.info("Reading extension directory: %s", base_path)
        # This should only be called after we know that extension.json exists in
        # base_path, so there's no need for extra error handling.
        extension_info_path = base_path / "extension.json"
        info = read_json_object_file(extension_info_path)

        # The extension "uid" and "name" values are essential, so we will make sure
        # they are set.
        uid = info.get("uid")
        name = info.get("name")
        if not isinstance(uid, int):
            t = json_type_from_value(uid)
            raise SchemaException(
                f'The extension "uid" must be an integer but got {t}:'
                f" {extension_info_path}"
            )
        if not isinstance(name, str):
            t = json_type_from_value(name)
            raise SchemaException(
                f'The extension "name" must be a string but got {t}:'
                f" {extension_info_path}"
            )

        categories_path = base_path / "categories.json"
        if categories_path.is_file():
            categories = read_json_object_file(categories_path)
        else:
            categories = {}

        classes, class_patches = read_patchable_structured_items(
            base_path, "events", item_callback_fn=self._upgrade_attribute_profiles
        )
        objects, object_patches = read_patchable_structured_items(
            base_path, "objects", item_callback_fn=self._upgrade_attribute_profiles
        )

        dictionary_path = base_path / "dictionary.json"
        if dictionary_path.is_file():
            dictionary = read_json_object_file(base_path / "dictionary.json")
        else:
            dictionary = {}

        profiles = read_structured_items(
            base_path, "profiles", item_callback_fn=self._cache_profile
        )

        if is_platform_extension and "version" not in info:
            # Fall back to overall schema version for platform extensions that do not
            # specify their own version
            version = self._version
        elif "version" in info:
            version = info["version"]
        else:
            raise SchemaException(
                f'Extension extension.json file is missing "version":'
                f" {extension_info_path}"
            )

        extension = Extension(
            base_path=base_path,
            uid=uid,
            name=name,
            is_platform_extension=is_platform_extension,
            caption=j_string_optional(info.get("caption")),
            description=j_string_optional(info.get("description")),
            version=j_string(version),
            categories=categories,
            classes=classes,
            class_patches=class_patches,
            objects=objects,
            object_patches=object_patches,
            dictionary=dictionary,
            profiles=profiles,
        )
        self._normalize_extension(extension)
        return extension

    @staticmethod
    def _normalize_extension(extension: Extension) -> None:
        context = f'extension "{extension.name}"'
        normalize_categories(extension.categories, f"{context} categories")
        normalize_dictionary(extension.dictionary, f"{context} dictionary")
        normalize_items(extension.classes, f"{context} class")
        normalize_items(extension.class_patches, f"{context} class patch")
        normalize_items(extension.objects, f"{context} object")
        normalize_items(extension.object_patches, f"{context} object patch")
        normalize_items(extension.profiles, f"{context} profile")

    def _validate_extension_profiles(self, extensions: list[Extension]) -> None:
        # Instead of resolving includes of profiles and then later finding issues, we
        # will validate profiles early so help identify the source of problems.
        base_dictionary_attributes = dictionary_attribute_definitions(self._dictionary)
        for extension in extensions:
            ext_dictionary_attributes = dictionary_attribute_definitions(
                extension.dictionary
            )
            for profile_name, profile in extension.profiles.items():
                profile = j_object(profile)
                profile_attributes = item_attributes(profile)
                for attribute_name in profile_attributes.keys():
                    if (
                        attribute_name not in base_dictionary_attributes
                        and attribute_name not in ext_dictionary_attributes
                    ):
                        raise SchemaException(
                            f'Attribute "{attribute_name}" in extension'
                            f' "{extension.name}" profile "{profile_name}" is not a'
                            " defined dictionary attribute"
                        )

    def _extension_scope_class_categories(self, extensions: list[Extension]) -> None:
        for extension in extensions:
            ext_cat_attributes = category_definitions(extension.categories)
            for cls in extension.classes.values():
                cls = j_object(cls)
                cat_name = j_string_optional(cls.get("category"))
                if cat_name and cat_name in ext_cat_attributes:
                    cls["category"] = to_extension_scoped_name(extension.name, cat_name)

    def _extension_scope_types(self, extensions: list[Extension]) -> None:
        for extension in extensions:
            for cls in extension.classes.values():
                cls = j_object(cls)
                self._extension_scope_attribute_types(
                    extension,
                    item_attributes(cls),
                )
            for cls_patch in extension.class_patches.values():
                cls_patch = j_object(cls_patch)
                self._extension_scope_attribute_types(
                    extension,
                    item_attributes(cls_patch),
                )
            for obj in extension.objects.values():
                obj = j_object(obj)
                self._extension_scope_attribute_types(
                    extension,
                    item_attributes(obj),
                )
            for obj_patch in extension.object_patches.values():
                obj_patch = j_object(obj_patch)
                self._extension_scope_attribute_types(
                    extension,
                    item_attributes(obj_patch),
                )
            self._extension_scope_attribute_types(
                extension,
                dictionary_attribute_definitions(extension.dictionary),
            )

    def _extension_scope_attribute_types(
        self,
        extension: Extension,
        attributes: JObject,
    ) -> None:
        use_scoped_dictionary_types = self._extension_uses_scoped_dictionary_types(
            extension
        )
        dictionary_types_attributes = dictionary_type_definitions(extension.dictionary)
        for attribute in attributes.values():
            attribute = j_object(attribute)
            if "type" in attribute:
                type_name = attribute["type"]
                if (
                    use_scoped_dictionary_types
                    and type_name in dictionary_types_attributes
                ) or type_name in extension.objects:
                    attribute["type"] = to_extension_scoped_name(
                        extension.name, type_name
                    )

    def _extension_scope_all_profiles_uses(self, extensions: list[Extension]) -> None:
        for extension in extensions:
            self._extension_scope_profile_in_items(
                extension, extension.classes, "class"
            )
            self._extension_scope_profile_in_items(
                extension, extension.class_patches, "class patch"
            )
            self._extension_scope_profile_in_items(
                extension, extension.objects, "object"
            )
            self._extension_scope_profile_in_items(
                extension, extension.object_patches, "object patch"
            )

    def _extension_scope_profile_in_items(
        self, extension: Extension, items: JObject, kind: str
    ) -> None:
        # Structured items can be classes, objects, class patches, or object patches
        for item_name, item in items.items():
            item_context = f'Extension "{extension.name}" {kind} "{item_name}"'
            item = j_object(item)
            item_profiles = j_array_optional(item.get("profiles"))
            if item_profiles:
                profiles_context = f'{item_context} "profiles"'
                fixed_item_profiles: JArray = []
                for profile_name in item_profiles:
                    fixed_item_profiles.append(
                        self._optionally_extension_scope_profile(
                            extension, j_string(profile_name), profiles_context
                        )
                    )
                item["profiles"] = fixed_item_profiles

            attributes = item_attributes(item)
            for attribute_name, attribute in attributes.items():
                attribute = j_object(attribute)
                if self.legacy_mode:
                    profile_name = j_string_optional(attribute.get("profile"))
                    if profile_name:
                        attribute_context = (
                            f'{item_context} attribute "{attribute_name}"'
                        )
                        attribute["profile"] = self._optionally_extension_scope_profile(
                            extension, profile_name, attribute_context
                        )
                else:
                    attribute_profiles = j_array_optional(attribute.get("profiles"))
                    if attribute_profiles:
                        attribute_context = (
                            f'{item_context} attribute "{attribute_name}"'
                        )
                        fixed_attribute_profiles: JArray = []
                        for profile_name in attribute_profiles:
                            fixed_attribute_profiles.append(
                                self._optionally_extension_scope_profile(
                                    extension, j_string(profile_name), attribute_context
                                )
                            )
                        attribute["profiles"] = fixed_attribute_profiles

    def _optionally_extension_scope_profile(
        self, extension: Extension, profile_name: str, context: str
    ) -> str:
        """
        Validates a profile reference used in an extension. Raises a SchemaException
        if validation fails.
        Returns fixed profile name, adding extension-scope to name if not already
        scoped.
        """
        if "/" in profile_name:
            split = profile_name.split("/")
            extension_name = split[0]
            if extension_name != extension.name:
                raise SchemaException(
                    f'{context} references profile "{profile_name}" that is scoped'
                    f' to a different extension: "{extension_name}"'
                )
            unscoped_profile_name = split[1]
            if unscoped_profile_name in extension.profiles:
                logger.debug('%s uses scoped profile "%s"', context, profile_name)
            else:
                raise SchemaException(
                    f'{context} references profile "{profile_name}" that is'
                    f" undefined in this extension and is not a platform extension"
                )
        else:
            if profile_name in extension.profiles:
                # This is normal - an extension's use of its own profiles are not
                # scoped. We will add the scope for the compiled schema.
                scoped_profile_name = to_extension_scoped_name(
                    extension.name, profile_name
                )
                logger.debug(
                    '%s references this extension\'s own profile "%s"; changing to'
                    ' "%s".',
                    context,
                    profile_name,
                    scoped_profile_name,
                )
                return scoped_profile_name

            elif profile_name in self._profiles:
                # This is fine
                logger.debug('%s uses base schema profile "%s"', context, profile_name)
            else:
                raise SchemaException(
                    f'{context} references profile "{profile_name}" that is not'
                    " defined in this extension or the base schema"
                )
        return profile_name

    def _resolve_includes(self) -> None:
        for cls in self._classes.values():
            cls = j_object(cls)
            self._resolve_item_includes(
                cls,
                f'class "{cls.get("name")}"',
                self._resolver_include_path,
            )
        for obj in self._objects.values():
            obj = j_object(obj)
            self._resolve_item_includes(
                obj,
                f'object "{obj.get("name")}"',
                self._resolver_include_path,
            )

    def _resolver_include_path(self, file_name: str) -> Path:
        return self.schema_path / file_name

    def _resolve_extension_includes(self, extensions: list[Extension]) -> None:
        for extension in extensions:

            def path_resolver(file_name: str) -> Path:
                return self._resolve_extension_include_path(extension, file_name)

            for cls in extension.classes.values():
                cls = j_object(cls)
                context = f'extension "{extension.name}" class "{cls.get("name")}"'
                self._resolve_item_includes(cls, context, path_resolver)

            for cls_patch in extension.class_patches.values():
                cls_patch = j_object(cls_patch)
                context = (
                    f'extension "{extension.name}" class patch'
                    f' "{cls_patch.get("name")}"'
                )
                self._resolve_item_includes(cls_patch, context, path_resolver)

            for obj in extension.objects.values():
                obj = j_object(obj)
                context = f'extension "{extension.name}" object "{obj.get("name")}"'
                self._resolve_item_includes(obj, context, path_resolver)

            for obj_patch in extension.object_patches.values():
                obj_patch = j_object(obj_patch)
                context = (
                    f'extension "{extension.name}" object patch'
                    f' "{obj_patch.get("name")}"'
                )
                self._resolve_item_includes(obj_patch, context, path_resolver)

    def _resolve_extension_include_path(
        self, extension: Extension, file_name: str
    ) -> Path:
        extension_path = extension.base_path / file_name
        if extension_path.is_file():
            return extension_path
        path = self.schema_path / file_name
        if path.is_file():
            return path
        raise FileNotFoundError(
            f'Extension "{extension.name}" "$include" {file_name} not found in'
            f" extension directory {extension.base_path} or schema directory"
            f" {self.schema_path}"
        )

    def _resolve_item_includes(
        self,
        item: JObject,
        context: str,
        path_resolver: Callable[[str], Path],
    ) -> None:
        attributes = item_attributes(item)

        # First, resolve $include at "attributes" level. These are commonly used for
        # profiles. An include at this level has the common item JSON object structure
        # with keys like "name", "caption", "description", and "attributes". Of these,
        # only the "attributes" are merged.
        #
        # This value of the "$include" key can be single string or an array of strings.
        # Each string is a path relative to the base directory of the schema, or for
        # extensions, the base directory of the extension OR the schema.
        #
        # The merge prefers existing values. The existing attributes details (if any)
        # are merged on top of (a copy of) the include contents.
        #
        # This example shows the array form of an $include:
        # {
        #    "name": "foo",
        #    ... other item details
        #    "attributes": {
        #       "$include": [
        #         "profiles/bar.json",
        #         "profiles/baz.json",
        #       ]
        #       "qux": {
        #          ... attribute details
        #       },
        #       ... other attributes
        #    }
        # }
        if "$include" in attributes:
            sub_context = f"{context} attributes.$include"
            # Get $include value and remove it from item attributes
            include_value = attributes.pop("$include")
            if isinstance(include_value, str):
                include_path = path_resolver(include_value)
                self._merge_attributes_include(item, sub_context, include_path)
            elif isinstance(include_value, list):
                for include_file_name in include_value:
                    include_path = path_resolver(j_string(include_file_name))
                    self._merge_attributes_include(item, sub_context, include_path)
            else:
                raise TypeError(
                    f"Illegal {sub_context} value type:"
                    f" expected string or array (list), but got"
                    f" {json_type_from_value(include_value)}"
                )

        # TODO: This is can easily overwrite existing information.
        #       Consider carefully determining if include is overwriting anything,
        #       perhaps with a new overwrite flag to utils.deep_merge.
        # Second, resolve $include in attribute details. An include at this level is a
        # JSON object containing exactly the information to merge in. These are (or
        # were) used to extract common enum values. The merge prefers existing values.
        # The existing attributes details (if any) are merged on top of the base.
        #
        # The value of the "$include" key must be a single string. The string is a path
        # relative to the base of the schema, or for extensions, the base directory of
        # the extension OR the schema.
        #
        # The merge prefers existing values. The existing attributes details (if any)
        # are merged on top of (a copy of) the include contents.
        #
        # Example:
        # {
        #    "name": "foo",
        #    ... other item details
        #    "attributes": {
        #       "baz_id": {
        #          "$include": "enum/baz.json"
        #           ... other attribute details (if any)
        #       },
        #       ... other attributes
        #    }
        # }
        #
        # attributes may have been modified, so we need to get them again, though now
        # we know they exist
        attributes = item_attributes(item)
        for attribute_name, attribute in attributes.items():
            if isinstance(attribute, dict) and "$include" in attribute:
                sub_context = f"{context} attributes.{attribute_name}.$include"
                # Get $include value and remove it from attribute
                include_value = attribute.pop("$include")
                if isinstance(include_value, str):
                    include_path = path_resolver(include_value)
                    self._merge_attribute_properties_include(
                        attributes,
                        attribute_name,
                        attribute,
                        sub_context,
                        include_path,
                    )
                else:
                    raise TypeError(
                        f"Illegal {sub_context} value type: expected string,"
                        f" but got {json_type_from_value(include_value)}"
                    )

    def _merge_attributes_include(
        self, item: JObject, context: str, include_path: Path
    ) -> None:
        include_item = self._get_include_contents(context, include_path)

        # Include file content should always have "attributes", but we will be
        # defensive.
        if "attributes" not in include_item:
            self._warning(
                "Include file suspiciously has no attributes: %s", include_path
            )
            # Nothing to merge. This should never happen (because it does nothing),
            # but is possible.
            return

        # Create merged attributes by merging item's attributes on top of included
        # attributes resulting in merge with base of included attributes, overridden by
        # item's.

        attributes = deep_copy_j_object(j_object(include_item["attributes"]))

        # First do profile-specific enrichment if include is a profile, and annotation
        # enrichment for all include cases (even though currently only profiles use
        # attributes includes)

        if include_item.get("meta") == "profile":
            if "name" not in include_item:
                raise SchemaException(f'Profile "name" is missing in {context}')
            profile_name = include_item["name"]
            for attribute_name, attribute in attributes.items():
                attribute = j_object(attribute)
                if "profile" in attribute:
                    raise SchemaException(
                        f'Profile "{profile_name}" attribute "{attribute_name}"'
                        f' unexpectedly has a "profile"'
                    )
                if self.legacy_mode:
                    attribute["profile"] = profile_name
                else:
                    attribute["profiles"] = [profile_name]

        if "annotations" in include_item:
            annotations = j_object(include_item["annotations"])
            for attribute in attributes.values():
                self._add_attribute_annotations(annotations, j_object(attribute))

        # item["attributes"] should exist at this point, so no need to double-check
        # Merge item's attributes on top of the copy of the include attribute,
        # preferring item's data
        self._merge_attributes(attributes, item_attributes(item), context)

        # replace item "attributes" with merged / resolved include attributes
        item["attributes"] = attributes

    def _merge_attribute_properties_include(
        self,
        attributes: JObject,
        attribute_name: str,
        attribute: JObject,
        context: str,
        include_path: Path,
    ) -> None:
        include_attribute = self._get_include_contents(context, include_path)

        # Create merged attribute detail for attributes.{attribute_name} by merging item
        # attribute's details on top of included attribute details resulting in merge
        # with base of included details overridden by item's.

        new_attribute = deep_copy_j_object(include_attribute)

        # Merge original attribute detail on top of the copy of the included
        # attribute_detail, preferring the original
        deep_merge(new_attribute, attribute)

        # replace existing attribute detail with the new merged detail
        attributes[attribute_name] = new_attribute

    def _get_include_contents(self, context: str, include_path: Path) -> JObject:
        if include_path in self._include_cache:
            return self._include_cache[include_path]

        try:
            include_item = read_json_object_file(include_path)
            self._include_cache[include_path] = include_item
            return include_item
        except FileNotFoundError as e:
            raise SchemaException(
                f"{context} file does not exist: {include_path}"
            ) from e

    def _merge_extensions_categories(self, extensions: list[Extension]) -> None:
        base_cat_attributes = category_definitions(self._categories)
        for extension in extensions:
            ext_cat_attributes = category_definitions(extension.categories)
            for cat_name, cat in ext_cat_attributes.items():
                self._check_shadowed_name(
                    extension.name,
                    "category",
                    cat_name,
                    base_cat_attributes,
                )
                scoped_cat_name = to_extension_scoped_name(extension.name, cat_name)
                base_cat_attributes[scoped_cat_name] = cat

    def _merge_extensions_classes(self, extensions: list[Extension]) -> None:
        for extension in extensions:
            if extension.classes:
                self._merge_extension_items(
                    extension.name, extension.classes, self._classes, "class"
                )

    def _merge_extensions_objects(self, extensions: list[Extension]) -> None:
        for extension in extensions:
            if extension.objects:
                self._merge_extension_items(
                    extension.name, extension.objects, self._objects, "object"
                )

    def _merge_extension_items(
        self,
        extension_name: str,
        extension_items: JObject,
        base_items: JObject,
        kind: str,
    ) -> None:
        """Merge extension class and objects."""
        for ext_item_name, ext_item in extension_items.items():
            self._check_shadowed_name(extension_name, kind, ext_item_name, base_items)
            scoped_name = to_extension_scoped_name(extension_name, ext_item_name)
            base_items[scoped_name] = ext_item

    def _merge_extensions_dictionary(self, extensions: list[Extension]) -> None:
        for extension in extensions:
            self._merge_extension_dictionary(extension)

    def _merge_extension_dictionary(self, extension: Extension) -> None:
        base_dict_attributes = dictionary_attribute_definitions(self._dictionary)
        ext_dict_attributes = dictionary_attribute_definitions(extension.dictionary)
        for ext_attribute_name, ext_attribute in ext_dict_attributes.items():
            self._check_shadowed_name(
                extension.name,
                "dictionary attribute",
                ext_attribute_name,
                base_dict_attributes,
            )

            ext_attribute = j_object(ext_attribute)
            if "overwrite" in ext_attribute:
                raise SchemaException(
                    f'Unsupported use of "overwrite" in extension "{extension.name}"'
                    f' dictionary attribute "{ext_attribute_name}"'
                )

            scoped_name = to_extension_scoped_name(extension.name, ext_attribute_name)
            base_dict_attributes[scoped_name] = ext_attribute

        use_scoped_types = self._extension_uses_scoped_dictionary_types(extension)

        base_types_attributes = dictionary_type_definitions(self._dictionary)
        ext_types_attributes = dictionary_type_definitions(extension.dictionary)
        for ext_type_name, ext_type in ext_types_attributes.items():
            ext_type = j_object(ext_type)
            if use_scoped_types:
                self._check_shadowed_name(
                    extension.name,
                    "dictionary type",
                    ext_type_name,
                    base_types_attributes,
                )
                scoped_name = to_extension_scoped_name(extension.name, ext_type_name)
                base_types_attributes[scoped_name] = ext_type
            else:
                if "/" in ext_type_name:
                    raise SchemaException(
                        f"Illegal use of extension-scope in extension"
                        f' "{extension.name}" dictionary type "{ext_type_name}";'
                        " shadowing or modifying a dictionary type"
                        " from another extension is not allowed"
                    )
                if ext_type_name in base_types_attributes:
                    base_attribute = j_object(base_types_attributes[ext_type_name])
                    if "extension" in base_attribute:
                        raise SchemaException(
                            "LOGIC BUG: base dictionary type with unscoped name"
                            f' "{ext_type_name}" unexpectedly has "extension" field'
                        )
                    raise SchemaException(
                        f'Extension "{extension.name}" dictionary type'
                        f' "{ext_type_name}" collides with'
                        " base schema dictionary type;"
                        " this is not supported as it would break compatibility"
                    )
                base_types_attributes[ext_type_name] = ext_type

    def _merge_extensions_profiles(self, extensions: list[Extension]) -> None:
        for extension in extensions:
            if extension.profiles:
                for profile_name, profile in extension.profiles.items():
                    self._check_shadowed_name(
                        extension.name,
                        "profile",
                        profile_name,
                        self._profiles,
                    )
                    scoped_name = to_extension_scoped_name(extension.name, profile_name)
                    self._profiles[scoped_name] = profile

    def _append_extension_patches(self, extensions: list[Extension]) -> None:
        for extension in extensions:
            for patch_name, patch in extension.class_patches.items():
                patches = self._class_patches.setdefault(patch_name, [])
                patches.append(j_object(patch))
            for patch_name, patch in extension.object_patches.items():
                patches = self._object_patches.setdefault(patch_name, [])
                patches.append(j_object(patch))

    def _enrich_dictionary_object_types(self) -> None:
        """
        Converts dictionary types not defined in dictionary's types to object types.
        """
        dictionary_attributes = dictionary_attribute_definitions(self._dictionary)
        for attribute_name, attribute in dictionary_attributes.items():
            attribute = j_object(attribute)
            attribute_type_name = j_string(attribute.get("type"))
            possible_dict_type = self._get_possible_dictionary_type(
                attribute_type_name, attribute
            )
            if possible_dict_type is None:
                attribute["type"] = "object_t"
                if attribute_type_name not in self._objects:
                    raise SchemaException(
                        self._dictionary_error_message(
                            attribute_name,
                            attribute,
                            f'uses undefined object "{attribute_type_name}"',
                        )
                    )
                attribute["object_type"] = attribute_type_name

    def _process_classes(self) -> None:
        # Extracting observables is easier to do before resolving (flattening) "extends"
        # inheritance since afterward the observable type_id enumerations will be
        # propagated to all children of event classes.
        self._observables_from_classes()

        if self.browser_mode:
            self._add_source_to_item_attributes(self._classes)
            self._add_source_to_patch_item_attributes(self._class_patches)
        self._resolve_patches(self._classes, self._class_patches, "class")
        self._resolve_extends(self._classes, "Class")

        if self.browser_mode:
            # Save informational complete class hierarchy (for schema browser)
            for cls_name, cls in self._classes.items():
                cls = j_object(cls)
                cls_slice = {}
                for k in ["name", "caption", "extends", "extension"]:
                    if k in cls:
                        cls_slice[k] = cls[k]
                cls_slice["hidden?"] = is_hidden_class(cls_name, cls)
                self._all_classes[cls_name] = cls_slice

        # Remove hidden classes
        self._classes = {
            name: cls
            for name, cls in self._classes.items()
            if not is_hidden_class(name, j_object(cls))
        }

        self._enrich_classes()

    def _enrich_classes(self) -> None:
        # enrich classes
        cat_attributes = category_definitions(self._categories)
        for cls_name, cls in self._classes.items():
            cls = j_object(cls)
            # update class uid
            category: JObject | None = None
            category_uid = 0
            category_key = j_string_optional(cls.get("category"))
            if category_key:
                category = j_object_optional(cat_attributes.get(category_key))
                if category:
                    cls["category_name"] = category.get("caption")
                    category_uid = j_integer(category.get("uid", 0))

            if "extension_id" in cls:
                if category and "extension_id" in category:
                    # The category_uid is already extension scoped
                    scoped_category_uid = category_uid
                else:
                    # Add extension scoping to base schema category
                    scoped_category_uid = extension_scoped_category_uid(
                        j_integer(cls["extension_id"]), category_uid
                    )
                cls_uid = category_scoped_class_uid(
                    scoped_category_uid, j_integer(cls.get("uid", 0))
                )
            else:
                cls_uid = category_scoped_class_uid(
                    category_uid, j_integer(cls.get("uid", 0))
                )

            cls["uid"] = cls_uid

            # add/update type_uid attribute
            cls_attributes = item_attributes(cls)
            cls_caption = cls.get("caption", "UNKNOWN")
            type_uid_attribute = j_object(cls_attributes.setdefault("type_uid", {}))
            type_uid_enum = {}
            if "activity_id" in cls_attributes and "enum" in j_object(
                cls_attributes["activity_id"]
            ):
                activity_id = j_object(cls_attributes["activity_id"])
                activity_enum = j_object(activity_id["enum"])
                for activity_enum_key, activity_enum_value in activity_enum.items():
                    activity_enum_value = j_object(activity_enum_value)
                    enum_key = str(
                        class_uid_scoped_type_uid(cls_uid, int(activity_enum_key))
                    )
                    enum_value = deep_copy_j_object(j_object(activity_enum_value))
                    enum_value["caption"] = (
                        f"{cls_caption}:"
                        f" {activity_enum_value.get('caption', '<unknown>')}"
                    )
                    type_uid_enum[enum_key] = enum_value
            else:
                raise SchemaException(
                    f'Class "{cls_name}" has invalid "activity_id" definition:'
                    ' "enum" not defined'
                )
            type_uid_enum[str(class_uid_scoped_type_uid(cls_uid, 0))] = {
                "caption": f"{cls_caption}: Unknown",
            }
            type_uid_attribute["enum"] = type_uid_enum

            if self.browser_mode:
                type_uid_attribute["_source"] = cls_name

            # add class_uid and class_name attributes
            cls_uid_attribute = j_object(cls_attributes.setdefault("class_uid", {}))
            cls_name_attribute = j_object(cls_attributes.setdefault("class_name", {}))
            cls_uid_key = str(cls_uid)
            enum: JObject = {
                cls_uid_key: {
                    "caption": cls_caption,
                    "description": cls.get("description", ""),
                }
            }
            cls_uid_attribute["enum"] = enum

            if self.browser_mode:
                cls_uid_attribute["_source"] = cls_name

            cls_name_attribute["description"] = (
                "The event class name, as defined by class_uid value:"
                f" <code>{cls_caption}</code>."
            )

            # add category_uid
            # add/update category_uid and category_name attributes
            if category:
                cls["category_uid"] = category_uid

                category_uid_attribute = j_object(
                    cls_attributes.setdefault("category_uid", {})
                )
                # Replace existing enum; leaf classes only include their one category
                # Doing ths prevents including base_event's 0 - Uncategorized enum.
                enum = {}
                category_uid_key = str(category_uid)
                enum[category_uid_key] = deep_copy_j_object(category)
                category_uid_attribute["enum"] = enum

                category_name_attribute = j_object(
                    cls_attributes.setdefault("category_name", {})
                )
                category_name_attribute["description"] = (
                    f"The event category name, as defined by category_uid value:"
                    f" <code>{category.get('caption', '')}</code>."
                )
            else:
                if category_key == "other":
                    logger.info(
                        'Class "%s" uses special undefined category "other"', cls_name
                    )
                    cls["category_uid"] = 0
                elif category_key is None:
                    raise SchemaException(f'Class "{cls_name}" has no category')
                else:
                    raise SchemaException(
                        f'Class "{cls_name}" has undefined category "{category_key}"'
                    )

    def _process_objects(self) -> None:
        # Extracting observables is easier to do before resolving (flattening) "extends"
        # inheritance since afterward the observable type_id enumerations will be
        # propagated to all children of objects.
        self._observables_from_objects()

        if self.browser_mode:
            self._add_source_to_item_attributes(self._objects)
            self._add_source_to_patch_item_attributes(self._object_patches)
        self._resolve_patches(self._objects, self._object_patches, "object")
        self._resolve_extends(self._objects, "Object")

        if self.browser_mode:
            # Save informational complete object hierarchy (for schema browser)
            for obj_name, obj in self._objects.items():
                obj = j_object(obj)
                obj_slice = {}
                for k in ["name", "caption", "extends", "extension"]:
                    if k in obj:
                        obj_slice[k] = obj[k]
                    obj_slice["hidden?"] = is_hidden_object(obj_name)
                self._all_objects[obj_name] = obj_slice

        # Remove hidden objects
        self._objects = {
            name: obj
            for name, obj in self._objects.items()
            if not is_hidden_object(name)
        }

    def _observables_from_classes(self) -> None:
        """Detect observable collisions and build up information for schema browser."""
        for cls_name, cls in self._classes.items():
            cls = j_object(cls)
            self._validate_class_observables(cls_name, cls, is_patch=False)
            self._observables_from_item_attributes(
                self._classes, cls_name, cls, "Class", is_patch=False
            )
            self._observables_from_item_observables(
                self._classes, cls_name, cls, "Class", is_patch=False
            )

        for patch_name, patch_list in self._class_patches.items():
            for patch in patch_list:
                self._validate_class_observables(patch_name, patch, is_patch=True)
                self._observables_from_item_attributes(
                    self._classes, patch_name, patch, "Class", is_patch=True
                )
                self._observables_from_item_observables(
                    self._classes, patch_name, patch, "Class", is_patch=True
                )

    @staticmethod
    def _validate_class_observables(
        cls_name: str, cls: JObject, is_patch: bool
    ) -> None:
        if "observable" in cls:
            raise SchemaException(
                'Illegal definition of one or more attributes with "observable" in'
                f' class "{cls_name}". Defining class-level observables is not'
                ' supported (this would be redundant). Instead use the "class_uid"'
                " attribute for querying, correlating, and reporting."
            )

        if not is_patch and is_hidden_class(cls_name, cls):
            attributes = item_attributes(cls)
            for attribute in attributes.values():
                if "observable" in j_object(attribute):
                    raise SchemaException(
                        'Illegal definition of one or more attributes with "observable"'
                        f' definition in hidden class "{cls_name}". This would cause'
                        " colliding definitions of the same observable type_id values"
                        " in all children of this class. Instead, define observables"
                        f' (of any kind) in non-hidden child classes of "{cls_name}".'
                    )

            if "observables" in cls:
                raise SchemaException(
                    f'Illegal "observables" definition in hidden class "{cls_name}".'
                    " This would cause colliding definitions of the same observable"
                    " type_id values in all children of this class. Instead, define"
                    " observables (of any kind) in non-hidden child classes of'"
                    f' "{cls_name}".'
                )

    def _observables_from_objects(self) -> None:
        """Detect observable collisions and build up information for schema browser."""
        for obj_name, obj in self._objects.items():
            obj = j_object(obj)
            self._validate_object_observables(obj_name, obj, is_patch=False)
            self._observables_from_object(obj_name, obj)
            self._observables_from_item_attributes(
                self._objects, obj_name, obj, "Object", is_patch=False
            )
            # Not supported:
            # self._observables_from_item_observables(self._objects, obj_name, obj,
            #     "Object", is_patch=False)

        for patch_name, patch_list in self._object_patches.items():
            for patch in patch_list:
                self._validate_object_observables(patch_name, patch, is_patch=True)
                self._observables_from_object(patch_name, patch)
                self._observables_from_item_attributes(
                    self._objects, patch_name, patch, "Object", is_patch=True
                )
                # Not supported:
                # self._observables_from_item_observables(self._objects, patch_name,
                #     patch, "Object", is_patch=True)

    @staticmethod
    def _validate_object_observables(
        obj_name: str, obj: JObject, is_patch: bool
    ) -> None:
        if "observables" in obj:
            # Attribute-path observables would be tricky to implement as a
            # machine-driven enrichment. It would require tracking the relative from the
            # point of the object down that tree of an overall OCSF event.
            raise SchemaException(
                f'Illegal "observables" definition in object "{obj_name}".'
                f" Object-specific attribute path observables are not supported."
                f" Please file an issue if you find this feature necessary."
            )

        if not is_patch and is_hidden_object(obj_name):
            attributes = item_attributes(obj)
            for attribute_detail in attributes.values():
                if "observable" in j_object(attribute_detail):
                    raise SchemaException(
                        f"Illegal definition of one or more attributes with"
                        f' "observable" definition in hidden object "{obj_name}".'
                        f" This would cause colliding definitions of the same"
                        f" observable type_id values in all children of this object."
                        f" Instead, define observables (of any kind) in non-hidden"
                        f' child objects of "{obj_name}".'
                    )

            if "observable" in obj:
                raise SchemaException(
                    f'Illegal "observable" definition in hidden object "{obj_name}".'
                    f" This would cause colliding definitions of the same observable"
                    f" type_id values in all children of this object. Instead, define"
                    f" observables (of any kind) in non-hidden child objects of"
                    f' "{obj_name}".'
                )

    def _observables_from_object(self, obj_name: str, obj: JObject) -> None:
        caption, description = self._find_item_caption_and_description(
            self._objects, obj_name, obj
        )
        if "observable" in obj:
            observable_type_id = str(obj["observable"])
            if observable_type_id in self._observable_type_id_dict:
                entry = j_object(self._observable_type_id_dict[observable_type_id])
                raise SchemaException(
                    f"Collision of observable type_id {observable_type_id} between"
                    f' "{caption}" object "observable" and'
                    f' "{entry["caption"]}": {entry["description"]}'
                )
            entry = self._make_observable_enum_entry(caption, description, "Object")
            self._observable_type_id_dict[observable_type_id] = entry

    def _observables_from_item_attributes(
        self,
        items: JObject,
        item_name: str,
        item: JObject,
        kind: str,
        is_patch: bool,
    ) -> None:
        # kind should be "Class" or "Object"
        if is_patch:
            caption, _ = self._find_parent_item_caption_and_description(
                items, item_name, item
            )
        else:
            caption, _ = self._find_item_caption_and_description(items, item_name, item)
        attributes = item_attributes(item)
        for attribute_name, attribute in attributes.items():
            attribute = j_object(attribute)
            if "observable" in attribute:
                observable_type_id = str(attribute["observable"])
                if observable_type_id in self._observable_type_id_dict:
                    entry = j_object(self._observable_type_id_dict[observable_type_id])
                    raise SchemaException(
                        f"Collision of observable type_id {observable_type_id}"
                        f' between {kind} "{item_name}" caption "{caption}"'
                        f' attribute "{attribute_name}" "observable" and'
                        f' "{entry["caption"]}": {entry["description"]}'
                    )
                self._observable_type_id_dict[observable_type_id] = (
                    self._make_observable_enum_entry(
                        f"{caption} {kind}: {attribute_name}",
                        f'{kind}-specific attribute "{attribute_name}" for the'
                        f" {caption} {kind}.",
                        f"{kind}-Specific Attribute",
                    )
                )

    def _observables_from_item_observables(
        self,
        items: JObject,
        item_name: str,
        item: JObject,
        kind: str,
        is_patch: bool,
    ) -> None:
        # kind should be title-case: "Class" or "Object"
        if "observables" in item:
            if is_patch:
                caption, _ = self._find_parent_item_caption_and_description(
                    items, item_name, item
                )
            else:
                caption, _ = self._find_item_caption_and_description(
                    items, item_name, item
                )
            observables = j_object(item["observables"])
            for attribute_path, observable_type_id_num in observables.items():
                observable_type_id = str(observable_type_id_num)
                if observable_type_id in self._observable_type_id_dict:
                    entry = j_object(self._observable_type_id_dict[observable_type_id])
                    raise SchemaException(
                        f"Collision of observable type_id {observable_type_id} between"
                        f' {kind} "{item_name}" caption "{caption}"'
                        f' "observables" attribute path "{attribute_path}" and'
                        f' "{entry["caption"]}": {entry["description"]}'
                    )
                self._observable_type_id_dict[observable_type_id] = (
                    self._make_observable_enum_entry(
                        f"{caption} {kind}: {attribute_path}",
                        f'{kind}-specific attribute "{attribute_path}" for the'
                        f" {caption} {kind}.",
                        f"{kind}-Specific Attribute",
                    )
                )

    def _make_observable_enum_entry(
        self, caption: str, description: str, observable_kind: str
    ) -> JObject:
        entry: JObject = {
            "caption": caption,
            "description": f"Observable by {observable_kind}.<br>{description}",
        }
        if self.browser_mode:
            entry["_observable_kind"] = observable_kind
        return entry

    @staticmethod
    def _find_item_caption_and_description(
        items: JObject, item_name: str, item: JObject
    ) -> tuple[str, str]:
        if "caption" in item:
            caption = j_string(item["caption"])
            description = j_string(item.get("description", caption))
            return caption, description
        return SchemaCompiler._find_parent_item_caption_and_description(
            items, item_name, item
        )

    @staticmethod
    def _find_parent_item_caption_and_description(
        items: JObject, item_name: str, item: JObject
    ) -> tuple[str, str]:
        current_item: JObject = item
        while True:
            if "extends" in item:
                parent_name = current_item["extends"]
                if parent_name in items:
                    parent_item = j_object(items[parent_name])
                    if "caption" in parent_item:
                        caption = j_string(parent_item["caption"])
                        description = j_string(parent_item.get("description", caption))
                        return caption, description
                    current_item = parent_item
                else:
                    raise SchemaException(
                        f'Ancestor "{parent_name}" of "{item_name}" is undefined.'
                    )
            else:
                break
        return item_name, item_name  # fallback

    @staticmethod
    def _add_source_to_item_attributes(items: JObject) -> None:
        for item_name, item in items.items():
            item = j_object(item)
            attributes = item_attributes(item)
            for attribute in attributes.values():
                attribute = j_object(attribute)
                attribute["_source"] = item_name

    @staticmethod
    def _add_source_to_patch_item_attributes(patch_dict: PatchDict) -> None:
        for patch_name, patches in patch_dict.items():
            for patch in patches:
                attributes = item_attributes(patch)
                for attribute in attributes.values():
                    attribute = j_object(attribute)
                    attribute["_source"] = patch_name

    def _resolve_patches(self, items: JObject, patches: PatchDict, kind: str) -> None:
        for patch_name, patch_list in patches.items():
            for patch in patch_list:
                # base_name will be the same as patch_name
                base_name = j_string(patch["extends"])
                assert patch_name == base_name, (
                    f'Patch name "{patch_name}" should match extends base name'
                    f' "{base_name}"'
                )

                context = (
                    f'Extension "{patch["extension"]}" {kind} patch "{patch_name}"'
                )
                if base_name not in items:
                    raise SchemaException(
                        f'{context} attempted to patch undefined {kind} "{base_name}"'
                    )

                base = j_object(items[base_name])

                if "extension" in base:
                    logger.info(
                        'Extension "%s" is patching "%s" from extension "%s"',
                        patch["extension"],
                        patch_name,
                        base["extension"],
                    )
                else:
                    logger.info(
                        'Extension "%s" is patching "%s" from base schema',
                        patch["extension"],
                        base_name,
                    )

                self._merge_profiles(base, patch)
                self._merge_attributes(
                    item_attributes(base),
                    item_attributes(patch),
                    context,
                )
                # Top-level observable.
                # Only occurs in objects, but is safe to do for classes too.
                put_non_none(base, "observable", patch.get("observable"))
                # Top-level path-based observables.
                # Only occurs in classes, but is safe to do for objects too.
                put_non_none(base, "observables", patch.get("observables"))
                put_non_none(base, "references", patch.get("references"))
                # Top-level attribute associations.
                # Only occurs in classes, but is safe to do for objects too.
                put_non_none(base, "associations", patch.get("associations"))
                self._patch_constraints(base, patch)

                self._patched_by_annotations(base, patch)

    @staticmethod
    def _patch_constraints(base: JObject, patch: JObject) -> None:
        if "constraints" in patch:
            constraints = patch["constraints"]
            if constraints:
                base["constraints"] = constraints
            else:
                # Remove base constraints if patch explicitly defines an empty
                # constraints list
                del base["constraints"]

    def _patched_by_annotations(self, base: JObject, patch: JObject) -> None:
        """
        Appends extension and extension_id from patch into _patched_by_extensions and
        _patched_by_extension_ids lists in base.
        """
        if not self.browser_mode:
            # Only added in browser-mode
            return

        ext_names = j_array(base.setdefault("_patched_by_extensions", []))
        ext_names.append(j_string(patch["extension"]))

        ext_ids = j_array(base.setdefault("_patched_by_extension_ids", []))
        ext_ids.append(j_integer(patch["extension_id"]))

    def _merge_attributes(
        self, dest_attributes: JObject, source_attributes: JObject, context: str
    ) -> None:
        if "$include" in source_attributes:
            # An included item's attributes should _not_ itself have an $include
            raise SchemaException(
                f'{context} illegally has an "$include"; this is not supported'
            )
        for source_attribute_name, source_attribute in source_attributes.items():
            source_attribute = j_object(source_attribute)
            if source_attribute_name in dest_attributes:
                dest_attribute = j_object(dest_attributes[source_attribute_name])
                self._merge_attribute_properties(
                    dest_attribute,
                    source_attribute,
                    f'{context} attribute "{source_attribute_name}"',
                )
            else:
                dest_attributes[source_attribute_name] = source_attribute

    def _merge_attribute_properties(
        self, dest_attribute: JObject, source_attribute: JObject, context: str
    ) -> None:
        for source_key, source_value in source_attribute.items():
            if source_key == "profile":
                if self.legacy_mode:
                    if source_value is None:
                        # Special meaning: attribute is not affected by profiles.
                        dest_attribute["profile"] = None
                    elif (
                        "profile" in dest_attribute
                        and dest_attribute["profile"] != source_value
                    ):
                        raise SchemaException(
                            f'{context} attempted merge of "profile" with different'
                            f' non-null value "{source_value}", existing:'
                            f" {dest_attribute} - this is not supported with legacy"
                            f" mode compilation since the output would be backwards"
                            f" incompatible with the legacy format"
                        )
                    else:
                        # OK... safe merge
                        dest_attribute["profile"] = j_string(source_value)
                else:
                    raise SchemaException(
                        f'LOGIC BUG: {context} "profile" should not exist while merging'
                        f" attributes"
                    )
            elif source_key not in dest_attribute:
                # this is always OK - safe merge, including "profiles"
                dest_attribute[source_key] = source_value
            elif source_value == dest_attribute[source_key]:
                pass  # No change - nothing to do
            elif source_key == "profiles":
                # Special merge:
                # set to None if source is None, otherwise merge set of both
                if source_value is None:
                    dest_attribute["profiles"] = None
                elif "profiles" in dest_attribute:
                    dest_profiles = j_array(dest_attribute["profiles"])
                    source_profiles = j_array(source_value)
                    merged = set(dest_profiles) | set(source_profiles)
                    dest_attribute["profiles"] = j_array(
                        sorted(merged, key=lambda v: j_string(v))
                    )
                else:
                    dest_attribute["profiles"] = j_array(source_value)
            elif (
                source_key == "requirement"
                and source_attribute.get("profiles") is not None
                and "profiles" in dest_attribute
            ):
                # Special merge of attribute affected by two profiles:
                # requirement becomes max of both
                dest_rank = requirement_to_rank(
                    j_string_optional(dest_attribute.get("requirement"))
                )
                source_rank = requirement_to_rank(
                    j_string(source_attribute["requirement"])
                )
                dest_attribute["requirement"] = rank_to_requirement(
                    max(dest_rank, source_rank)
                )
            else:
                # Hopefully a safe merge; deep merge if dicts, otherwise overwrite
                # TODO: This will add "extension" and "extension_id" if they exist in
                #       source attribute, possibly overwriting dest values.
                if isinstance(dest_attribute[source_key], dict) and isinstance(
                    source_value, dict
                ):
                    # TODO: Detect collisions? Perhaps with overwrite flag in
                    #       utils.deep_merge?
                    deep_merge(j_object(dest_attribute[source_key]), source_value)
                else:
                    dest_attribute[source_key] = source_value

    @staticmethod
    def _merge_profiles(dest: JObject, source: JObject) -> None:
        dest_profiles = set(j_array(dest.get("profiles", [])))
        source_profiles = set(j_array(source.get("profiles", [])))
        merged = dest_profiles.union(source_profiles)
        if merged:  # avoid adding "profiles" if neither base nor patch had any
            # sorts and converts to list (otherwise profiles are randomly sorted)
            dest["profiles"] = sorted(merged, key=lambda v: j_string(v))

    def _resolve_extends(self, items: JObject, kind: str) -> None:
        for item_name, item in items.items():
            self._resolve_item_extends(items, item_name, j_object(item), kind)

    def _get_extends_parent(
        self, items: JObject, item_name: str, item: JObject, kind: str
    ) -> tuple[str, JObject]:
        parent_name = j_string(item["extends"])
        if "extension" in item:
            ext_parent_name = to_extension_scoped_name(
                j_string(item["extension"]), parent_name
            )
            if ext_parent_name in items:
                return ext_parent_name, j_object(items[ext_parent_name])
        if parent_name in items:
            return parent_name, j_object(items[parent_name])
        raise SchemaException(
            f'{kind} "{item_name}" extends undefined {kind} "{parent_name}"'
        )

    def _resolve_item_extends(
        self, items: JObject, item_name: str, item: JObject, kind: str
    ) -> None:
        if "extends" not in item:
            return

        original_parent_name, original_parent = self._get_extends_parent(
            items, item_name, item, kind
        )
        # Extends resolution is recursive... resolve parent first
        self._resolve_item_extends(items, original_parent_name, original_parent, kind)

        # Get parent again in case extends resolution has changed it
        parent_name, parent = self._get_extends_parent(items, item_name, item, kind)
        assert parent_name == original_parent_name, (
            f'{kind} "{item_name}" "extends" value should not change after'
            f' recursively processing parent: original value: "{original_parent_name}",'
            f' current value: "{parent_name}"'
        )

        # Create flattened item by merging item on top of a copy of it's parent
        # with the result that new and overlapping things in item _win_ over
        # those in parent. This new item replaces the existing one.
        new_item = deep_copy_j_object(parent)
        # The values of most keys simply replace what is in the parent, except
        # for attributes and profiles
        for source_key, source_value in item.items():
            if source_key == "attributes":
                new_attributes = item_attributes(new_item)
                self._merge_attributes(
                    new_attributes,
                    j_object(source_value),
                    f'{kind} "{item_name}" extending "{parent_name}"',
                )
                new_item["attributes"] = new_attributes
            elif source_key == "profiles":
                self._merge_profiles(new_item, item)
            else:
                new_item[source_key] = source_value

        items[item_name] = new_item

    def _enrich_and_validate_dictionary(self) -> None:
        if self.browser_mode:
            self._add_common_dictionary_attribute_links()
            self._add_class_dictionary_attribute_links()
            self._add_object_dictionary_attribute_links()
        self._enrich_and_validate_dictionary_types()
        self._add_datetime_sibling_dictionary_attributes()

    def _add_common_dictionary_attribute_links(self) -> None:
        if not self.browser_mode:
            return
        if "base_event" not in self._classes:
            raise SchemaException('Schema has not defined a "base_event" class')
        base_event = j_object(self._classes["base_event"])
        link = self._make_link("common", "base_event", base_event)
        self._add_links_to_dictionary_attributes(base_event, link)

    def _add_class_dictionary_attribute_links(self) -> None:
        if not self.browser_mode:
            return
        for cls_name, cls in self._classes.items():
            cls = j_object(cls)
            link = self._make_link("class", cls_name, cls)
            self._add_links_to_dictionary_attributes(cls, link)

    def _add_object_dictionary_attribute_links(self) -> None:
        if not self.browser_mode:
            return
        for obj_name, obj in self._objects.items():
            obj = j_object(obj)
            link = self._make_link("object", obj_name, obj)
            self._add_links_to_dictionary_attributes(obj, link)

    @staticmethod
    def _make_link(group: str, item_name: str, item: JObject) -> JObject:
        """
        Create link reference. The group value should be "common", "class", or "object",
        with "common" being a group holding the "base_event" class, which is treated
        specially.
        """
        link: JObject = {
            "group": group,
            "type": item_name,
            "caption": item.get("caption", "*No name*"),
        }
        if "extension" in item:
            link["extension"] = item["extension"]
        if item.get("@deprecated"):
            link["deprecated?"] = True
        return link

    @staticmethod
    def _sort_links(links: JArray) -> None:
        def link_to_key(link: JValue) -> tuple[str, str]:
            link = j_object(link)
            return j_string(link["group"]), j_string(link["type"])

        links.sort(key=link_to_key)

    def _add_links_to_dictionary_attributes(self, item: JObject, link: JObject) -> None:
        if not self.browser_mode:
            return

        attributes = item_attributes(item)
        for item_attribute_name, item_attribute in attributes.items():
            dictionary_attribute = self._get_dictionary_attribute(
                item,
                item_attribute_name,
                j_object(item_attribute),
            )

            # Create copy of link to avoid polluting original in case at least one
            # attribute is an object type.
            attribute_link = deep_copy_j_object(link)
            # attribute_keys is only used to track the different attribute name uses
            # of object types. We don't track the various attribute names that use
            # dictionary types.
            if "object_type" in dictionary_attribute:
                attribute_link["attribute_keys"] = [item_attribute_name]
            links = j_array(dictionary_attribute.setdefault("_links", []))
            links.append(attribute_link)
            self._sort_links(links)

    def _enrich_and_validate_dictionary_types(self) -> None:
        dictionary_types_attributes = dictionary_type_definitions(self._dictionary)
        dictionary_attributes = dictionary_attribute_definitions(self._dictionary)

        # Make sure dictionary types are OK. These are specifically checked as these
        # keys are used later in the compile, and verifying early leads to better
        # error messages. Plus we can fix a known issue with 1.0.0-rc.2.
        for type_name, type_detail in dictionary_types_attributes.items():
            type_detail = j_object(type_detail)
            if "caption" not in type_detail:
                raise SchemaException(
                    self._dictionary_type_error_message(
                        type_name, type_detail, 'does not define "caption"'
                    )
                )
            # Check type and type_name, which are used in dictionary subtype definitions
            # to specify the base type and base type name.
            # (These should really be "base_type" and "base_type_caption".)
            if "type" in type_detail:
                # This is a subtype
                base_type = type_detail["type"]
                if base_type not in dictionary_types_attributes:
                    raise SchemaException(
                        self._dictionary_type_error_message(
                            type_name,
                            type_detail,
                            f'uses undefined dictionary type "{base_type}"',
                        )
                    )
                if "type_name" not in type_detail:
                    raise SchemaException(
                        self._dictionary_type_error_message(
                            type_name,
                            type_detail,
                            'defines "type" without "type_name"; both are required'
                            " to define a dictionary subtype",
                        )
                    )
            if "type_name" in type_detail and "type" not in type_detail:
                if self._version == "1.0.0-rc.2":
                    # 1.0.0-rc.2 left out "type" for some subtypes. The legacy compiler
                    # defaulted to "string_t". However, some of the 1.0.0-rc.2 subtypes
                    # defined "type_name", so we can fix these, a more complicated
                    # compensation later in the compile process.
                    logger.info(
                        'Fixing known issue with 1.0.0-rc.2: dictionary type "%s"'
                        ' is a subtype with base "type_name" of "%s", but does not'
                        ' define "type"; assuming "string_t"',
                        type_name,
                        type_detail["type_name"],
                    )
                    type_detail["type"] = "string_t"
                else:
                    # For later schemas, "type_name" without "type" is an error.
                    raise SchemaException(
                        self._dictionary_type_error_message(
                            type_name,
                            type_detail,
                            'defines "type_name" without "type"; both are required to'
                            " define a dictionary subtype",
                        )
                    )

        for attribute_name, attribute in dictionary_attributes.items():
            attribute = j_object(attribute)
            if "type" in attribute:
                attribute_type_name = j_string(attribute["type"])
            else:
                raise SchemaException(
                    self._dictionary_error_message(
                        attribute_name, attribute, 'does not define "type"'
                    )
                )
            if attribute_type_name == "object_t":
                # Object dictionary type
                # Add "object_name" to attribute details based on caption.
                # NOTE: This must be done after resolving patches and extends so caption
                # is resolved.
                object_type = attribute["object_type"]
                if object_type in self._objects:
                    obj = j_object(self._objects[object_type])
                    attribute["object_name"] = obj.get("caption", "")
                else:
                    raise SchemaException(
                        self._dictionary_error_message(
                            attribute_name,
                            attribute,
                            f'uses undefined object type "{object_type}"',
                        )
                    )
            else:
                # Normal dictionary type
                dictionary_type = self._get_possible_dictionary_type(
                    attribute_type_name, attribute
                )
                if dictionary_type:
                    attribute["type_name"] = dictionary_type.get("caption", "")
                else:
                    raise SchemaException(
                        self._dictionary_error_message(
                            attribute_name,
                            attribute,
                            f'uses undefined "type" "{attribute_type_name}"',
                        )
                    )

    @staticmethod
    def _dictionary_type_error_message(
        type_name: str, type_detail: JObject, problem: str
    ) -> str:
        if "extension" in type_detail:
            return (
                f'Dictionary type "{type_name}" from extension'
                f' "{type_detail["extension"]}" {problem}'
            )
        return f'Dictionary type "{type_name}" {problem}'

    @staticmethod
    def _dictionary_error_message(
        attribute_name: str, attribute: JObject, problem: str
    ) -> str:
        if "extension" in attribute:
            return (
                f'Dictionary attribute "{attribute_name}" from extension'
                f' "{attribute["extension"]}" {problem}'
            )
        return f'Dictionary attribute "{attribute_name}" {problem}'

    def _add_datetime_sibling_dictionary_attributes(self) -> None:
        """
        Magic datetime dictionary attribute siblings with type "timestamp_t" are added
        when the following are defined in the schema:
            - The "datetime" profile
            - The "datetime_t" dictionary type
            - The "timestamp_t" dictionary type
        """
        got_datetime_profile = "datetime" in self._profiles
        dictionary_types_attributes = dictionary_type_definitions(self._dictionary)
        got_datetime_t = "datetime_t" in dictionary_types_attributes
        got_timestamp_t = "timestamp_t" in dictionary_types_attributes
        if got_datetime_profile and got_datetime_t and got_timestamp_t:
            logger.info(
                'Datetime siblings of attributes with the "timestamp_t" type will be'
                " added because the following are defined in the schema: the"
                ' "datetime" profile, the "datetime_t" dictionary type, and the'
                ' "timestamp_t" dictionary type.'
            )
            # Add datetime siblings
            dictionary_attributes = dictionary_attribute_definitions(self._dictionary)
            # We can't add dictionary_attributes while iterating, so instead add to
            # another dict and then merge
            additions: JObject = {}
            for attribute_name, attribute in dictionary_attributes.items():
                attribute = j_object(attribute)
                if attribute.get("type") == "timestamp_t":
                    sibling = deep_copy_j_object(attribute)
                    # No need to fix up attribute_keys as they are not used for
                    # dictionary types
                    sibling["type"] = "datetime_t"
                    sibling["type_name"] = "Datetime"
                    additions[self._make_datetime_attribute_name(attribute_name)] = (
                        sibling
                    )
            dictionary_attributes.update(additions)
        elif got_datetime_profile:
            raise SchemaException(
                'Schema defines "datetime" profile but does not define "datetime_t"'
                " dictionary type"
            )
        elif got_datetime_t:
            raise SchemaException(
                'Schema defines "datetime_t" dictionary type but does not define'
                ' "datetime" profile'
            )
        else:
            logger.info(
                'This schema does not define the "datetime" profile or the "datetime_t"'
                ' dictionary type, so datetime siblings of "timestamp_t" attributes'
                " will not be added."
            )

    @staticmethod
    def _make_datetime_attribute_name(timestamp_name: str) -> str:
        return f"{timestamp_name}_dt"

    def _observables_from_dictionary(self) -> None:
        dictionary_types_attributes = dictionary_type_definitions(self._dictionary)
        dictionary_attributes = dictionary_attribute_definitions(self._dictionary)
        self._observables_from_dictionary_items(
            dictionary_types_attributes, "Dictionary Type"
        )
        self._observables_from_dictionary_items(
            dictionary_attributes, "Dictionary Attribute"
        )

    def _observables_from_dictionary_items(self, items: JObject, kind: str) -> None:
        for key, detail in items.items():
            detail = j_object(detail)
            if "observable" in detail:
                observable_type_id = str(detail["observable"])
                if observable_type_id in self._observable_type_id_dict:
                    entry = j_object(self._observable_type_id_dict[observable_type_id])
                    if "extension" in detail:
                        kind = f'extension "{detail["extension"]}" {kind}'
                    raise SchemaException(
                        f"Collision of observable type_id {observable_type_id} between"
                        f' {kind} "{key}" caption "{detail.get("caption")}"'
                        f' "observable" and "{entry["caption"]}":'
                        f" {entry['description']}"
                    )
                else:
                    entry = self._make_observable_enum_entry(
                        j_string(detail.get("caption", "")),
                        j_string(detail.get("description", "")),
                        kind,
                    )
                    self._observable_type_id_dict[observable_type_id] = entry

    def _validate_object_profiles_and_add_links(self) -> None:
        self._validate_item_profiles_and_add_links("object", self._objects)

    def _validate_class_profiles_and_add_links(self) -> None:
        self._validate_item_profiles_and_add_links("class", self._classes)

    def _validate_item_profiles_and_add_links(self, group: str, items: JObject) -> None:
        for item_name, item in items.items():
            item = j_object(item)
            if "profiles" in item:
                for profile_name in j_array(item["profiles"]):
                    profile_name = j_string(profile_name)
                    if profile_name in self._profiles:
                        profile = j_object(self._profiles[profile_name])
                    else:
                        if "extension" in item:
                            full_group = f'extension "{item["extension"]}" {group}'
                        else:
                            full_group = group
                        raise SchemaException(
                            f'Undefined profile "{profile_name}" used in'
                            f' {full_group} "{item_name}"'
                        )

                    if self.browser_mode:
                        link = self._make_link(group, item_name, item)
                        links = j_array(profile.setdefault("_links", []))
                        links.append(link)
                        self._sort_links(links)

    def _add_object_links(self) -> None:
        if not self.browser_mode:
            return

        dictionary_attributes = dictionary_attribute_definitions(self._dictionary)
        for obj_name, obj in self._objects.items():
            obj = j_object(obj)
            links: JArray = []
            for attribute in dictionary_attributes.values():
                attribute = j_object(attribute)
                if attribute.get("object_type") == obj_name and "_links" in attribute:
                    attribute_links = deep_copy_j_array(j_array(attribute["_links"]))
                    links.extend(attribute_links)

            # Group by group and type and merge attribute_keys
            grouped_links: JObject = {}
            for link in links:
                link = j_object(link)
                group_key = f"{link['group']}:{link['type']}"
                if group_key in grouped_links:
                    group = j_object(grouped_links[group_key])
                    group_attribute_keys = j_array(group["attribute_keys"])
                    for key in j_array(link["attribute_keys"]):
                        if key not in group_attribute_keys:
                            group_attribute_keys.append(key)
                else:
                    grouped_links[group_key] = link

            # The final result is the values of the grouped_link dict
            links = list(grouped_links.values())
            self._sort_links(links)
            obj["_links"] = links

    def _update_observable_enum(self) -> None:
        if "observable" in self._objects:
            observable = j_object(self._objects["observable"])
            observable_attributes = item_attributes(observable)
            observable_type_id = j_object(
                observable_attributes.setdefault("type_id", {})
            )
            dest_enum_dict = j_object(observable_type_id.setdefault("enum", {}))
            for (
                source_type_id_key,
                source_enum_detail,
            ) in self._observable_type_id_dict.items():
                if source_type_id_key in dest_enum_dict:
                    # This is a defensive coding check - we should have already detected
                    # the collision
                    raise SchemaException(
                        f"Collision of observable type_id {source_type_id_key} detected"
                        f" while building observable object enum values."
                        f" This a bug. Please file an issue at"
                        f" https://github.com/ocsf/ocsf-schema-compiler/issues."
                    )
                else:
                    dest_enum_dict[source_type_id_key] = source_enum_detail

    def _consolidate_object_profiles(self) -> None:
        """
        Update object profiles to includes profile from all attributes with object
        types.
        """
        self._consolidate_profiles("object", self._objects)

    def _consolidate_class_profiles(self) -> None:
        """
        Update class profiles to include profiles from all attributes with object
        types.
        """
        self._consolidate_profiles("class", self._classes)

    # ProfilesDict is a mapping from class or object name to list of profiles or None
    # We really prefer to list[str] rather than JArray (list[JValue]), however JArray
    # works better with the types used here, and keeps Pyright happy.
    type ProfilesDict = dict[str, JArray | None]

    def _consolidate_profiles(self, group: str, items: JObject) -> None:
        for item_name, item in items.items():
            item = j_object(item)
            profiles_dict: SchemaCompiler.ProfilesDict = {}
            try:
                if group == "class":
                    # The recursive step is for objects. For classes, we need to do the
                    # first step here.
                    if "profiles" in item:
                        # Use prefix for class so it does not collide with object names
                        item_profiles = j_array(item["profiles"])
                        profiles_dict[f"class:{item_name}"] = item_profiles

                    attributes = item_attributes(item)
                    for attribute_name, attribute in attributes.items():
                        # This happens before enriching attributes with dictionary
                        # information, so we need to do extra work to determine actual
                        # type
                        object_type = self._find_object_type(
                            item, attribute_name, j_object(attribute)
                        )
                        if object_type:
                            self._gather_profiles(object_type, profiles_dict)

                else:
                    # for object, we can jump straight to _gather_profiles
                    self._gather_profiles(item_name, profiles_dict)
            except SchemaException as e:
                raise SchemaException(
                    f'Consolidating profiles of {group} "{item_name}" failed: {e}'
                ) from e

            all_profiles: set[JValue] = set()
            for profile_list in profiles_dict.values():
                if profile_list:
                    all_profiles.update(profile_list)

            if all_profiles:
                sorted_profiles = sorted(all_profiles, key=lambda v: j_string(v))
                if logger.isEnabledFor(logging.DEBUG):
                    items_with_profiles: JArray = []
                    for profile_name, profile_list in profiles_dict.items():
                        if profile_list:
                            items_with_profiles.append(profile_name)
                    items_with_profiles.sort(key=lambda v: j_string(v))
                    original_profiles = item.get("profiles")
                    if sorted_profiles == original_profiles:
                        logger.debug(
                            'Consolidated profiles of %s "%s": profiles unchanged.',
                            group,
                            item_name,
                        )
                    else:
                        logger.debug(
                            'Consolidated profiles of %s "%s".'
                            "\n    Original profiles: %s."
                            "\n    Consolidated from: %s."
                            "\n    Consolidated profiles: %s.",
                            group,
                            item_name,
                            original_profiles,
                            items_with_profiles,
                            sorted_profiles,
                        )
                item["profiles"] = j_array(sorted_profiles)
            else:
                logger.debug(
                    'Consolidated profiles of %s "%s": no profiles.', group, item_name
                )

    def _gather_profiles(
        self, obj_name: str, profiles_dict: SchemaCompiler.ProfilesDict
    ) -> None:
        """
        Gather profiles from obj_name object (if any) and its attributes that are object
        types, recursively.
        """
        if obj_name in profiles_dict:
            return  # obj_name already processed

        if obj_name not in self._objects:
            raise SchemaException(f'Object "{obj_name}" is not defined')
        obj = j_object(self._objects[obj_name])

        # We specifically want actual and None values since profiles_dict is doing both
        # gathering profiles and marking things that have been processed.
        profiles_dict[obj_name] = j_array_optional(obj.get("profiles"))

        obj_attributes = item_attributes(obj)
        for attr_name, attr in obj_attributes.items():
            try:
                object_type = self._find_object_type(obj, attr_name, j_object(attr))
            except SchemaException as e:
                raise SchemaException(
                    f'Error finding type of attribute "{attr_name}"'
                    f' in object "{obj_name}": {e}'
                ) from e
            if object_type:
                self._gather_profiles(object_type, profiles_dict)

    def _find_object_type(
        self, item: JObject, attribute_name: str, attribute: JObject
    ) -> str | None:
        """
        Determine object type of unprocessed object or class attribute
        (an attribute not yet merged with dictionary attribute information).
        Returns None is if attribute is not an object type (it's a dictionary type).
        """
        # We haven't merged dictionary attributes in class and object attributes yet,
        # so "object_type" should not yet be present. The logic in this method depends
        # on the unprocessed "type", and will not work if "type" has already been
        # changed to "object_t" and "object_type" added for object types.
        assert "object_type" not in attribute, (
            f'Object attribute "{attribute_name}" unexpectedly already has'
            ' "object_type"'
        )
        dictionary_attribute = self._get_dictionary_attribute(
            item, attribute_name, attribute
        )
        # will return None if "object_type" is not present
        return j_string_optional(dictionary_attribute.get("object_type"))

    def _verify_object_attributes_and_add_datetime(self) -> None:
        self._verify_item_attributes_and_add_datetime(self._objects, "object")

    def _verify_class_attributes_and_add_datetime(self) -> None:
        self._verify_item_attributes_and_add_datetime(self._classes, "class")

    def _verify_item_attributes_and_add_datetime(
        self, items: JObject, kind: str
    ) -> None:
        dictionary_types_attributes = dictionary_type_definitions(self._dictionary)

        got_datetime_profile = "datetime" in self._profiles
        got_datetime_t = "datetime_t" in dictionary_types_attributes
        got_timestamp_t = "timestamp_t" in dictionary_types_attributes
        add_datetime = got_datetime_profile and got_datetime_t and got_timestamp_t

        for item_name, item in items.items():
            item = j_object(item)
            # We cannot add attributes while iterating attributes, so track additions
            dt_attribute_additions: JObject = {}
            attributes = item_attributes(item)
            for attribute_name, attribute in attributes.items():
                attribute = j_object(attribute)
                dictionary_attribute = self._get_dictionary_attribute(
                    item, attribute_name, attribute
                )
                if "description" not in attribute:
                    # No description. Make sure fallback dictionary description isn't
                    # meant to be overridden.
                    dictionary_description = j_string(
                        dictionary_attribute.get("description", "")
                    )
                    if "See specific usage" in dictionary_description:
                        self._warning(
                            'Please update the "description" of %s "%s" attribute "%s":'
                            ' "%s"',
                            kind,
                            item_name,
                            attribute_name,
                            dictionary_description,
                        )

                if add_datetime:
                    attribute_type: str | None = None
                    if "type" in attribute:
                        attribute_type = j_string(attribute["type"])
                    elif dictionary_attribute:
                        attribute_type = j_string(dictionary_attribute.get("type"))
                    if attribute_type and attribute_type == "timestamp_t":
                        dt_attribute = deep_copy_j_object(attribute)
                        if self.legacy_mode:
                            dt_attribute["profile"] = "datetime"
                        else:
                            dt_attribute["profiles"] = ["datetime"]
                        dt_attribute["requirement"] = "optional"
                        dt_attribute_additions[
                            self._make_datetime_attribute_name(attribute_name)
                        ] = dt_attribute

            if dt_attribute_additions:
                attributes.update(dt_attribute_additions)
                profiles = j_array(item.setdefault("profiles", []))
                if "datetime" not in profiles:
                    profiles.append("datetime")
                    # keep profiles sorted
                    profiles.sort(key=lambda v: j_string(v))

    def _ensure_attributes_have_requirement(self) -> None:
        # Track attributes in profiles, classes, and objects that incorrectly do _not_
        # have a "requirement"
        missing_requirements: list[str] = []
        self._ensure_item_attributes_have_requirement(
            self._profiles, "profile", missing_requirements
        )
        self._ensure_item_attributes_have_requirement(
            self._classes, "class", missing_requirements
        )
        self._ensure_item_attributes_have_requirement(
            self._objects, "object", missing_requirements
        )
        if missing_requirements:
            missing_requirements.sort()
            self._warning(
                'The following attributes do not have a "requirement" property and a'
                ' value of "optional" will be used:\n    %s',
                "\n    ".join(missing_requirements),
            )

    @staticmethod
    def _ensure_item_attributes_have_requirement(
        items: JObject, kind: str, missing_requirements: list[str]
    ) -> None:
        for item_name, item in items.items():
            item = j_object(item)
            fixed: list[str] = []
            attributes = item_attributes(item)
            for attribute_name, attribute in attributes.items():
                attribute = j_object(attribute)
                if attribute.get("requirement") is None:
                    attribute["requirement"] = "optional"
                    fixed.append(f'"{attribute_name}"')
            if fixed:
                fixed.sort()
                if "extension" in item:
                    name = f'extension "{item["extension"]}" {kind} "{item_name}"'
                else:
                    name = f'{kind} "{item_name}"'
                missing_requirements.append(f"{name} attribute(s): {', '.join(fixed)}")

    def _finish_attributes(self):
        self._finish_item_attributes(self._classes, "class")
        self._finish_item_attributes(self._objects, "object")

        # Profile attributes are only used for schema browser UI of profiles. They are
        # not needed for event validation as the attribute details are merged into the
        # classes and objects that use them.
        if self.browser_mode:
            # Do "annotations" processing so profile attributes match work done when
            # including profiles
            for item in self._profiles.values():
                item = j_object(item)
                if "annotations" in item:
                    annotations = j_object(item["annotations"])
                    attributes = item_attributes(item)
                    for attribute in attributes.values():
                        attribute = j_object(attribute)
                        self._add_attribute_annotations(annotations, attribute)
            # Finish the attributes, enriching with dictionary attribute information
            self._finish_item_attributes(self._profiles, "profile")
        else:
            for profile in self._profiles.values():
                profile = j_object(profile)
                del profile["attributes"]

    def _finish_item_attributes(self, items: JObject, kind: str) -> None:
        for item_name, item in items.items():
            item = j_object(item)
            attributes = item_attributes(item)
            new_attributes: JObject = {}
            for attribute_name, attribute in attributes.items():
                new_attribute = self._finish_item_attribute(
                    item_name,
                    item,
                    kind,
                    attribute_name,
                    j_object(attribute),
                )
                new_attributes[attribute_name] = new_attribute
            item["attributes"] = new_attributes
            if self.browser_mode:
                self._add_sibling_of_to_attributes(new_attributes)

    def _finish_item_attribute(
        self,
        item_name: str,
        item: JObject,
        kind: str,
        attribute_name: str,
        attribute: JObject,
    ) -> JObject:
        dict_attribute = self._get_dictionary_attribute(item, attribute_name, attribute)
        new_attribute = deep_copy_j_object(dict_attribute)
        deep_merge(new_attribute, attribute)

        # Check if the item attribute's type has been changed, because if so,
        # we need make sure the type_name ends up with the correct value.

        if "type" in attribute:
            attribute_type_name = j_string(attribute["type"])
            if attribute_type_name != dict_attribute["type"]:
                # This item attribute's type has been changed.
                # We only allow a compatible subtype in this case.
                # In general, a subtype could be a dictionary subtype or an object
                # that inherits from a parent object (a derived object).
                # Currently this compiler only supports dictionary subtypes, not
                # object subtypes, though object subtypes are possible.

                # Make sure subtype of this attribute matches the original
                # attribute's type
                original_type = dict_attribute["type"]
                dictionary_type = self._get_dictionary_type(
                    item, attribute_type_name, attribute
                )
                subtype = dictionary_type.get("type")
                if subtype != original_type:
                    raise SchemaException(
                        f'Attribute "{attribute_name}" in {kind} "{item_name}" has'
                        f' refined type "{attribute_type_name}", however this is'
                        f" not a subtype of dictionary attribute type"
                        f' "{original_type}"'
                    )

                # Checks are OK... we just need to fix up "type_name", which
                # currently has the type from the dictionary type
                new_attribute["type_name"] = dictionary_type["caption"]
                logger.debug(
                    '_finish_item_attribute - attribute "%s" in %s "%s" is using'
                    ' refined type "%s"',
                    attribute_name,
                    kind,
                    item_name,
                    attribute_type_name,
                )

        if "is_array" in attribute:
            if attribute["is_array"] != dict_attribute.get("is_array"):
                raise SchemaException(
                    f'Attribute "{attribute_name}" in {kind} "{item_name}"'
                    f' has "is_array" with value {attribute.get("is_array")} that does'
                    f" not match dictionary attribute value of"
                    f" {dict_attribute.get('is_array')}"
                )

        # TODO: could also check other type constraints

        return new_attribute

    @staticmethod
    def _add_sibling_of_to_attributes(attributes: JObject) -> None:
        # This must be done after finalizing attributes so full enum attribute details
        # are present. Specifically the enum attribute "sibling" key.

        sibling_of_dict: dict[str, str] = {}
        # Enum attributes point to their enum sibling through the :sibling attribute,
        # however the siblings do _not_ refer back to their related enum attribute,
        # so let's build that.
        # First pass, iterate attributes to find enum attributes and create mapping to
        # their siblings.
        for attribute_name, attribute in attributes.items():
            attribute = j_object(attribute)
            if "sibling" in attribute:
                # This is an enum attribute
                sibling_of_dict[j_string(attribute["sibling"])] = attribute_name

        if not sibling_of_dict:
            # no enum attributes present in attributes, so nothing to do
            return  # skip iterating attributes again uselessly

        # Second pass, look for enum attributes and add "_sibling_of" mapping
        for attribute_name, attribute in attributes.items():
            attribute = j_object(attribute)
            if attribute_name in sibling_of_dict:
                # This is an enum sibling. Add "_sibling_of" pointing back to its
                # related enum attribute.
                attribute["_sibling_of"] = sibling_of_dict[attribute_name]

    def _validate_extension_category_unique_ids(self, extension: Extension) -> None:
        base_cats = category_definitions(self._categories)
        base_uid_to_name: dict[int, str] = {}
        for base_cat_name, base_cat in base_cats.items():
            base_cat = j_object(base_cat)
            base_uid_to_name[j_integer(base_cat["uid"])] = base_cat_name

        ext_cats = category_definitions(extension.categories)
        for ext_cat_name, ext_cat in ext_cats.items():
            ext_cat = j_object(ext_cat)
            ext_cat_uid = j_integer(ext_cat["uid"])
            if ext_cat_uid in base_uid_to_name:
                base_cat_name = base_uid_to_name[ext_cat_uid]
                self._warning(
                    'Category unique ID collision: extension "%s" category "%s" with'
                    ' "uid" %d collides with base category "%s" with "uid" %d.'
                    '\n    The category "uid" values will not collide once the'
                    ' extension category "uid" becomes extension-scoped, however this'
                    ' can lead to class "uid" collisions in this extension.'
                    '\n    If a class in extension "%s" uses base category "%s" and'
                    ' another class in extension "%s" uses extension category "%s", the'
                    ' resulting extension-scoped class "uid" values will be the same.'
                    '\n    This is a known design flaw in the extension class "uid"'
                    " calculation."
                    '\n    If this is a newly defined category, its "uid" should be'
                    " changed."
                    "\n    Otherwise, if a collision between extension-scoped class"
                    ' "uid" occurs, one of them must be changed.',
                    extension.name,
                    ext_cat_name,
                    ext_cat_uid,
                    base_cat_name,
                    ext_cat_uid,
                    extension.name,
                    base_cat_name,
                    extension.name,
                    ext_cat_name,
                )

    @staticmethod
    def _validate_unique_ids(items: JObject, kind: str) -> None:
        """
        Validate that items do not have a unique ID collisions.
        Note that for class "uid" values are scoped by category and (for extensions) by
        category, so this check must be done _after_ they are processed.
        """
        names_by_uids: dict[int, str] = {}
        for item_name, item in items.items():
            item = j_object(item)
            uid = j_integer(item["uid"])
            if uid in names_by_uids:
                other_item_name = names_by_uids[uid]
                raise SchemaException(
                    f'Unique ID collision: both {kind} "{item_name}"'
                    f' and "{other_item_name}" have "uid" {uid}'
                )
            names_by_uids[uid] = item_name

    def _check_shadowed_name(
        self,
        extension_name: str,
        kind: str,
        ext_item_unscoped_name: str,
        base_items: JObject,
    ) -> None:
        if "/" in ext_item_unscoped_name:
            raise SchemaException(
                f'Illegal use of extension-scope in extension "{extension_name}"'
                f' {kind} "{ext_item_unscoped_name}"; shadowing or modifying a {kind}'
                " from another extension is not allowed"
            )

        if ext_item_unscoped_name not in base_items:
            return

        base_item = j_object(base_items[ext_item_unscoped_name])
        if "extension" in base_item:
            raise SchemaException(
                f'LOGIC BUG: base {kind} with unscoped name "{ext_item_unscoped_name}"'
                ' unexpectedly has "extension" field'
            )
        if self.allow_shadowing:
            self._warning(
                'Extension "%s" %s "%s" shadows base schema %s with same name;'
                " this name should be changed if this is a newly added %s",
                extension_name,
                kind,
                ext_item_unscoped_name,
                kind,
                kind,
            )
        else:
            raise SchemaException(
                f'Extension "{extension_name}" {kind} "{ext_item_unscoped_name}"'
                f" shadows base schema {kind} with same name."
                f" For an extension that has never allowed shadowed names, including"
                " new extensions, this name should be changed."
                " If this is an existing name in an extension in active use, fixing can"
                " lead to backwards incompatibility."
                " Use the -a, --allow-shadowing option to enable shadowing."
            )

    def _extension_uses_scoped_dictionary_types(self, extension: Extension) -> bool:
        if extension.is_platform_extension:
            return False
        return not self.unscoped_dictionary_types

    def _extension_id_uses_scoped_dictionary_types(self, extension_id: int) -> bool:
        if extension_id in self._platform_extension_id_set:
            return False
        return not self.unscoped_dictionary_types

    def _get_dictionary_attribute(
        self, item: JObject, attribute_name: str, attribute: JObject
    ) -> JObject:
        """
        Dictionary attributes are used without extension-scope in classes, objects,
        and profiles. This returns the correct dictionary attribute whether or not it
        is being used from an extension context.
        """
        dictionary_attributes = dictionary_attribute_definitions(self._dictionary)
        if "extension" in attribute:
            ext_name = j_string(attribute["extension"])
            scoped_name = to_extension_scoped_name(ext_name, attribute_name)
            # No need to fall back in this case... the item should exist
            if scoped_name not in dictionary_attributes:
                raise SchemaException(
                    f'Attribute "{scoped_name}" from "{full_name(item)}"'
                    " is not a defined dictionary attribute"
                )
            return j_object(dictionary_attributes[scoped_name])

        if attribute_name not in dictionary_attributes:
            raise SchemaException(
                f'Attribute "{attribute_name}" from "{full_name(item)}"'
                " is not a defined dictionary attribute"
            )
        return j_object(dictionary_attributes[attribute_name])

    def _get_dictionary_type(
        self, item: JObject, type_name: str, attribute: JObject
    ) -> JObject:
        """
        Dictionary types are used without extension-scope in classes, objects,
        and profiles. This returns the correct dictionary attribute whether or not it
        is being used from an extension context.
        """
        dictionary_types_attributes = dictionary_type_definitions(self._dictionary)

        if "extension" in attribute:
            ext_name = j_string(attribute["extension"])
            scoped_name = to_extension_scoped_name(ext_name, type_name)
            if scoped_name in dictionary_types_attributes:
                return j_object(dictionary_types_attributes[scoped_name])
            # If not an extension dictionary type, it should be a base dictionary type

        if type_name not in dictionary_types_attributes:
            raise SchemaException(
                f'Dictionary type "{type_name}" from "{full_name(item)}"'
                " is not a defined dictionary type"
            )
        return j_object(dictionary_types_attributes[type_name])

    def _get_possible_dictionary_type(
        self, type_name: str, attribute: JObject
    ) -> JObject | None:
        """
        Dictionary types are used without extension-scope in classes, objects,
        and profiles. This returns the correct dictionary attribute whether or not it
        is being used from an extension context, or None if it isn't a dictionary type.
        """
        dictionary_types_attributes = dictionary_type_definitions(self._dictionary)

        if "extension" in attribute:
            ext_name = j_string(attribute["extension"])
            scoped_name = to_extension_scoped_name(ext_name, type_name)
            if scoped_name in dictionary_types_attributes:
                return j_object(dictionary_types_attributes.get(scoped_name))
            # If not an extension dictionary type, it could be a base dictionary type

        return j_object_optional(dictionary_types_attributes.get(type_name))

    def _create_compile_output(self) -> JObject:
        if self.legacy_mode:
            dictionary_types = dictionary_type_definitions(self._dictionary)
            return {
                "base_event": self._classes.get("base_event"),
                "classes": self._classes,
                "objects": self._objects,
                "dictionary_attributes": dictionary_attribute_definitions(
                    self._dictionary
                ),
                "types": dictionary_types,
                "version": self._version,
            }

        output: JObject = {
            "categories": self._categories,
            "dictionary": self._dictionary,
            "classes": self._classes,
            "objects": self._objects,
            "profiles": self._profiles,
            "extensions": self._extensions,
            "version": self._version,
            "compile_version": 1,
        }

        if self.browser_mode:
            output["browser_mode?"] = True
            output["all_classes"] = self._all_classes
            output["all_objects"] = self._all_objects
        return output


@dataclass
class Extension:
    base_path: Path
    uid: int
    name: str
    is_platform_extension: bool
    caption: str | None
    description: str | None
    version: str
    categories: JObject
    classes: JObject
    class_patches: JObject
    objects: JObject
    object_patches: JObject
    dictionary: JObject
    profiles: JObject

    @override
    def __eq__(self, other: object) -> bool:
        if isinstance(other, Extension):
            return (
                self.is_platform_extension == other.is_platform_extension
                and self.uid == other.uid
            )
        return False

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Extension):
            return False
        if self.is_platform_extension and other.is_platform_extension:
            return self.uid < other.uid
        if self.is_platform_extension and not other.is_platform_extension:
            return True
        if not self.is_platform_extension and other.is_platform_extension:
            return False
        return self.uid < other.uid

    def _annotate_object(self, o: JObject) -> None:
        """Annotate o adding extension and extension_id fields for this extension."""
        o["extension"] = self.name
        o["extension_id"] = self.uid

    def _annotate_object_children(self, o: JObject) -> None:
        """
        Annotate children of o (o's values) adding extension and extension_id fields
        for this extension.
        """
        for child in o.values():
            self._annotate_object(j_object(child))

    def _annotate_item_with_attributes(self, o: JObject) -> None:
        """
        Annotate class, object, or profile, and their attributes.
        """
        dictionary_attributes = dictionary_attribute_definitions(self.dictionary)
        for item in o.values():
            item = j_object(item)
            self._annotate_object(j_object(item))
            attributes = item_attributes(item)
            for attribute_name, attribute in attributes.items():
                if attribute_name in dictionary_attributes:
                    self._annotate_object(j_object(attribute))

    def _annotate_patches(self, patches: JObject) -> None:
        """
        Annotate patches. This is similar to _enrich_object_children, but also annotates
        attributes of the the patched items (classes and objects) that are defined in
        this extension.

        This is needed because patched items are not defined in this extension, so
        when the patched class or object attribute details are enriched with
        dictionary attribute information, we cannot use where these class or object
        is defined (base schema or other extension) to determine whether the
        attribute is from an extension or from the base schema. That is, whether
        we need to look it up with an extension prefix or not.
        """
        dictionary_attributes = dictionary_attribute_definitions(self.dictionary)
        for patch in patches.values():
            patch = j_object(patch)
            self._annotate_object(patch)
            attributes = item_attributes(patch)
            for attribute_name, attribute in attributes.items():
                if attribute_name in dictionary_attributes:
                    self._annotate_object(j_object(attribute))

    def annotate(self) -> None:
        """
        Annotate all items in extension with extension information.
        Change category attribute "uid" values to extension-scoped values.
        This must be done after processing includes.
        """
        category_attributes = category_definitions(self.categories)
        for category_detail in category_attributes.values():
            category_detail = j_object(category_detail)
            category_detail["uid"] = extension_scoped_category_uid(
                self.uid, j_integer(category_detail["uid"])
            )
            self._annotate_object(category_detail)

        # self._annotate_object_children(self.classes)
        self._annotate_item_with_attributes(self.classes)

        self._annotate_patches(self.class_patches)

        # self._annotate_object_children(self.objects)
        self._annotate_item_with_attributes(self.objects)

        self._annotate_patches(self.object_patches)
        self._annotate_object_children(
            dictionary_attribute_definitions(self.dictionary)
        )
        dictionary_types_attributes = dictionary_type_definitions(self.dictionary)
        self._annotate_object_children(dictionary_types_attributes)

        # self._annotate_object_children(self.profiles)
        self._annotate_item_with_attributes(self.profiles)


def _extension_j_value_key(v: JValue):
    """
    Helper key function to sort values of SchemaCompiler._extensions consistent
    with Extension dataclass.
    """
    o = j_object(v)
    return (not o["platform_extension?"], o["uid"])
