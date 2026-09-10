#!/bin/bash

# Usage: ./scripts/create-version.sh <new-version> [source-version]
# Example: ./scripts/create-version.sh 2.0.4dev
# Example: ./scripts/create-version.sh 2.0.4dev 2.0.3

set -e

NEW_VERSION="$1"
SOURCE_VERSION="$2"

if [ -z "$NEW_VERSION" ]; then
    echo "Usage: $0 <new-version> [source-version]"
    echo "Example: $0 2.0.4dev"
    echo "Example: $0 2.0.4dev 2.0.3"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DOCS_ROOT="$(dirname "$SCRIPT_DIR")"
VERSIONS_DIR="$DOCS_ROOT/versions"
DOCS_JSON="$DOCS_ROOT/docs.json"

# If source version not specified, find the latest version
if [ -z "$SOURCE_VERSION" ]; then
    # Get all version directories, sort by version number (descending), take the first
    SOURCE_VERSION=$(ls -1 "$VERSIONS_DIR" | sort -V -r | head -1)
    
    if [ -z "$SOURCE_VERSION" ]; then
        echo "Error: No existing versions found in $VERSIONS_DIR"
        exit 1
    fi
fi

SOURCE_DIR="$VERSIONS_DIR/$SOURCE_VERSION"
TARGET_DIR="$VERSIONS_DIR/$NEW_VERSION"

if [ ! -d "$SOURCE_DIR" ]; then
    echo "Error: Source version directory not found: $SOURCE_DIR"
    exit 1
fi

if [ -d "$TARGET_DIR" ]; then
    echo "Error: Target version already exists: $TARGET_DIR"
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is required to update docs.json but was not found."
    exit 1
fi

echo "Creating version $NEW_VERSION from $SOURCE_VERSION..."

# Copy the source version
cp -r "$SOURCE_DIR" "$TARGET_DIR"

# Replace version references in all mdx files
# GNU sed (Linux) and BSD sed (macOS) disagree on the -i argument, so branch on it
echo "Updating internal links in mdx files..."
if sed --version >/dev/null 2>&1; then
    SED_INPLACE=(sed -i)
else
    SED_INPLACE=(sed -i '')
fi
find "$TARGET_DIR" -name "*.mdx" -exec "${SED_INPLACE[@]}" "s|/versions/$SOURCE_VERSION/|/versions/$NEW_VERSION/|g" {} \;

# Count modified files
MODIFIED_COUNT=$(grep -r "/versions/$NEW_VERSION/" "$TARGET_DIR" --include="*.mdx" -l 2>/dev/null | wc -l | tr -d ' ')

# Update docs.json: clone navigation entry per language + update redirects
echo "Updating docs.json (navigation + redirects)..."
PY_OUTPUT=$(DOCS_JSON="$DOCS_JSON" SOURCE_VERSION="$SOURCE_VERSION" NEW_VERSION="$NEW_VERSION" python3 <<'PYEOF'
import copy
import json
import os

docs_json_path = os.environ["DOCS_JSON"]
source_version = os.environ["SOURCE_VERSION"]
new_version = os.environ["NEW_VERSION"]

with open(docs_json_path, "r", encoding="utf-8") as f:
    data = json.load(f)


def update_paths(obj):
    """Recursively rewrite any 'versions/<SOURCE_VERSION>/' substring."""
    src = f"versions/{source_version}/"
    dst = f"versions/{new_version}/"
    if isinstance(obj, str):
        return obj.replace(src, dst)
    if isinstance(obj, list):
        return [update_paths(x) for x in obj]
    if isinstance(obj, dict):
        return {k: update_paths(v) for k, v in obj.items()}
    return obj


added = []
skipped = []


def version_holders(lang_entry):
    """Yield every object that owns a 'versions' list for one language.

    Versions sit directly on the language entry in the old layout, and one
    level deeper (under each tab) once the site is split into tabs, so both
    shapes are collected here.
    """
    if isinstance(lang_entry.get("versions"), list):
        yield lang_entry
    for tab in lang_entry.get("tabs", []) or []:
        if isinstance(tab, dict) and isinstance(tab.get("versions"), list):
            yield tab


languages = data.get("navigation", {}).get("languages", []) or []
for lang_entry in languages:
    lang = lang_entry.get("language", "?")

    for holder in version_holders(lang_entry):
        versions = holder["versions"]
        # Name the holder after its tab so the log distinguishes the tabs
        label = lang
        if holder is not lang_entry:
            label = f"{lang}/{holder.get('tab', '?')}"

        # Skip if the new version already exists here
        if any(v.get("version") == new_version for v in versions):
            skipped.append(f"{label}(already exists)")
            continue

        # Locate the source version block
        source_idx = next(
            (i for i, v in enumerate(versions) if v.get("version") == source_version),
            None,
        )
        if source_idx is None:
            # Tabs of other products carry their own versions, so a miss here
            # is expected rather than an error
            continue

        # Deep-copy, update version field, then rewrite all internal paths
        new_entry = copy.deepcopy(versions[source_idx])
        new_entry["version"] = new_version
        new_entry.pop("default", None)
        new_entry.pop("tag", None)
        if new_version.endswith("dev"):
            new_entry["tag"] = "Development"
        else:
            for entry in versions:
                entry.pop("default", None)
            new_entry["default"] = True
        new_entry = update_paths(new_entry)

        # Insert right BEFORE the source version so newer versions appear higher
        versions.insert(source_idx, new_entry)
        added.append(label)

    if not any(a.startswith(lang) for a in added) and not any(
        s.startswith(lang) for s in skipped
    ):
        skipped.append(f"{lang}(source '{source_version}' not in navigation)")

# Update redirects (/latest/ for dev, /stable/ for release)
is_dev = new_version.endswith("dev")
target_source = "/latest/:slug*" if is_dev else "/stable/:slug*"
redirect_updated = ""
for redirect in data.get("redirects", []) or []:
    if redirect.get("source") == target_source:
        redirect["destination"] = f"/versions/{new_version}/:slug*"
        redirect_updated = f"{target_source} -> /versions/{new_version}/:slug*"
        break

# Write through a temporary file in the same directory, then rename it over
# the original. A plain "w" truncates the file first, so a running `mint dev`
# re-reads it mid-write and reports "docs.json has invalid JSON"
tmp_path = f"{docs_json_path}.tmp"
with open(tmp_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
os.replace(tmp_path, docs_json_path)

print(f"ADDED={','.join(added)}")
print(f"SKIPPED={','.join(skipped)}")
print(f"REDIRECT={redirect_updated}")
PYEOF
)

NAV_ADDED=$(echo "$PY_OUTPUT" | sed -n 's/^ADDED=//p')
NAV_SKIPPED=$(echo "$PY_OUTPUT" | sed -n 's/^SKIPPED=//p')
REDIRECT_UPDATED=$(echo "$PY_OUTPUT" | sed -n 's/^REDIRECT=//p')

echo ""
echo "✅ Created version $NEW_VERSION"
echo "   Source: $SOURCE_DIR"
echo "   Target: $TARGET_DIR"
echo "   Files with updated links: $MODIFIED_COUNT"
echo "   Navigation added for: ${NAV_ADDED:-<none>}"
if [ -n "$NAV_SKIPPED" ]; then
    echo "   Navigation skipped:    $NAV_SKIPPED"
fi
echo "   Redirect updated:      ${REDIRECT_UPDATED:-<no matching redirect found>}"

# Only *.mdx files are rewritten above, so generated artifacts still carry the
# source version. Point them out instead of patching them: an OpenAPI spec has
# to be regenerated from the matching AgentScope release, not string-replaced
STALE_FILES=$(grep -rl "$SOURCE_VERSION" "$TARGET_DIR" --include="*.json" 2>/dev/null || true)
if [ -n "$STALE_FILES" ]; then
    echo ""
    echo "⚠️  These generated files still reference $SOURCE_VERSION:"
    echo "$STALE_FILES" | sed 's|^|     |'
    echo "     Regenerate them from the AgentScope $NEW_VERSION release."
fi

echo ""
echo "Next steps:"
echo "  1. Review docs.json to confirm the new version block looks right"
echo "  2. Make your documentation changes in $TARGET_DIR"
echo "  3. Run 'mint dev' to preview"
echo ""
echo "When promoting a dev version to a release, drop the old dev version"
echo "afterwards: remove versions/<old-dev> and its navigation entries."
