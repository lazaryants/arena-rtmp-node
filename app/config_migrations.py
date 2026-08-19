"""Explicit, ordered migrations for restream-config.json."""

import copy

from .config_store import (
    CURRENT_SCHEMA_VERSION,
    FIELD_ID_RE,
    ConfigValidationError,
    validate_config,
    validate_field,
    validate_rtmp_url,
)


LEGACY_FIELD_KEYS = {
    "emoji",
    "enabled",
    "hls_url",
    "key",
    "name",
    "publish_auth_enabled",
    "restream_url",
    "restream_urls",
    "rtmp_url",
    "stream_key",
}


class ConfigMigrationError(ConfigValidationError):
    """Configuration cannot be safely migrated to the current schema."""


def schema_version(config):
    if not isinstance(config, dict):
        raise ConfigMigrationError("configuration root must be an object")
    version = config.get("schema_version", 0)
    if type(version) is not int or version < 0:
        raise ConfigMigrationError("schema_version must be a non-negative integer")
    if version > CURRENT_SCHEMA_VERSION:
        raise ConfigMigrationError(
            f"configuration schema {version} is newer than supported "
            f"schema {CURRENT_SCHEMA_VERSION}"
        )
    return version


def validate_v1_field(field_id, field):
    """Validate the string destination format used by schema v1."""
    normalized = copy.deepcopy(field)
    destinations = normalized.get("restream_urls", [])
    if not isinstance(destinations, list):
        raise ConfigMigrationError(
            f"field {field_id}.restream_urls must be a list"
        )
    if len(destinations) > 32:
        raise ConfigMigrationError(
            f"field {field_id}.restream_urls has too many entries"
        )
    normalized["restream_urls"] = []
    validate_field(field_id, normalized)
    for index, destination in enumerate(destinations):
        validate_rtmp_url(
            destination,
            f"field {field_id}.restream_urls[{index}]",
        )


def validate_legacy_v0(config):
    allowed_root_keys = {"fields"} if "schema_version" not in config else {
        "schema_version",
        "fields",
    }
    if set(config) != allowed_root_keys or config.get("schema_version", 0) != 0:
        raise ConfigMigrationError(
            "legacy configuration must contain only schema_version=0 and fields"
        )
    fields = config["fields"]
    if not isinstance(fields, dict) or len(fields) > 16:
        raise ConfigMigrationError("legacy fields must contain no more than 16 entries")

    for field_id, field in fields.items():
        if not isinstance(field_id, str) or not FIELD_ID_RE.fullmatch(field_id):
            raise ConfigMigrationError(f"invalid field ID: {field_id!r}")
        if not isinstance(field, dict):
            raise ConfigMigrationError(f"field {field_id} must be an object")
        unknown = set(field) - LEGACY_FIELD_KEYS
        if unknown:
            raise ConfigMigrationError(
                f"field {field_id} contains unsupported keys: {sorted(unknown)}"
            )
        normalized = {
            key: value
            for key, value in field.items()
            if key not in {"hls_url", "restream_url", "rtmp_url"}
        }
        try:
            validate_v1_field(field_id, normalized)
            if "restream_url" in field:
                validate_rtmp_url(
                    field["restream_url"],
                    f"field {field_id}.restream_url",
                )
        except ConfigValidationError as error:
            raise ConfigMigrationError(str(error)) from error


def migrate_v0_to_v1(config):
    validate_legacy_v0(config)
    migrated = copy.deepcopy(config)
    for field in migrated["fields"].values():
        destinations = list(field.get("restream_urls", []))
        legacy_destination = field.pop("restream_url", None)
        if legacy_destination and legacy_destination not in destinations:
            destinations.append(legacy_destination)
        field["restream_urls"] = destinations
        field.pop("rtmp_url", None)
        field.pop("hls_url", None)
        field.setdefault("publish_auth_enabled", False)
    migrated["schema_version"] = 1
    return migrated


def migrate_v1_to_v2(config):
    if (
        not isinstance(config, dict)
        or set(config) != {"schema_version", "fields"}
        or config.get("schema_version") != 1
    ):
        raise ConfigMigrationError(
            "schema v1 configuration must contain only schema_version=1 and fields"
        )
    fields = config.get("fields")
    if not isinstance(fields, dict) or len(fields) > 16:
        raise ConfigMigrationError(
            "schema v1 fields must contain no more than 16 entries"
        )

    migrated = copy.deepcopy(config)
    for field_id, field in migrated["fields"].items():
        if not isinstance(field_id, str) or not FIELD_ID_RE.fullmatch(field_id):
            raise ConfigMigrationError(f"invalid field ID: {field_id!r}")
        if not isinstance(field, dict):
            raise ConfigMigrationError(f"field {field_id} must be an object")
        validate_v1_field(field_id, field)
        field["restream_urls"] = [
            {"url": url, "audio_mode": "source"}
            for url in field.get("restream_urls", [])
        ]
    migrated["schema_version"] = 2
    return migrated


MIGRATIONS = {
    0: migrate_v0_to_v1,
    1: migrate_v1_to_v2,
}


def migrate_config(config):
    migrated = copy.deepcopy(config)
    original_version = schema_version(migrated)
    version = original_version
    while version < CURRENT_SCHEMA_VERSION:
        migration = MIGRATIONS.get(version)
        if migration is None:
            raise ConfigMigrationError(f"missing migration from schema {version}")
        migrated = migration(migrated)
        new_version = schema_version(migrated)
        if new_version != version + 1:
            raise ConfigMigrationError("migration did not advance exactly one schema")
        version = new_version
    validate_config(migrated)
    return migrated, original_version
