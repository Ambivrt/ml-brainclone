#!/bin/bash
# =============================================================================
# Larry Nightly — Vault Data Collector
# =============================================================================
# Collects raw vault data for analysis. Output: text files in .data/.
# The bulk-tier model analyzes these and writes reports to 00-inbox/.
#
# Usage: bash collect-vault-data.sh [vault-path]
# =============================================================================

set -euo pipefail

VAULT="${1:-$VAULT_PATH}"
DATA_DIR="$VAULT/03-projects/ml-brainclone/operations/nattskift/.data"
TODAY=$(date +%Y-%m-%d)

if [ -z "$VAULT" ] || [ ! -d "$VAULT" ]; then
    echo "Error: VAULT_PATH not set or directory not found."
    echo "Usage: bash collect-vault-data.sh /path/to/vault"
    exit 1
fi

mkdir -p "$DATA_DIR"

echo "Collecting vault data..."

# --- 1. All markdown files (excluding system directories) ---
find "$VAULT" \
    -name "*.md" \
    -not -path "*/.obsidian/*" \
    -not -path "*/.trash/*" \
    -not -path "*/.claude/*" \
    -not -path "*/.playwright-mcp/*" \
    -not -path "*/.git/*" \
    -not -path "*/node_modules/*" \
    2>/dev/null | sort > "$DATA_DIR/all-files.txt"

FILE_COUNT=$(wc -l < "$DATA_DIR/all-files.txt")
echo "  Found $FILE_COUNT markdown files"

# --- 2. Frontmatter analysis ---
> "$DATA_DIR/missing-frontmatter.txt"
while IFS= read -r file; do
    first_line=$(head -1 "$file" 2>/dev/null || echo "")
    if [ "$first_line" != "---" ]; then
        rel="${file#$VAULT/}"
        echo "$rel" >> "$DATA_DIR/missing-frontmatter.txt"
    fi
done < "$DATA_DIR/all-files.txt"
echo "  Frontmatter: $(wc -l < "$DATA_DIR/missing-frontmatter.txt") files missing frontmatter"

# --- 3. All wikilinks in the vault ---
xargs -d '\n' grep -ohE '\[\[[^]|#]+' < "$DATA_DIR/all-files.txt" 2>/dev/null \
    | sed 's/\[\[//' \
    | sort -u > "$DATA_DIR/all-wikilinks.txt" || true
echo "  Wikilinks: $(wc -l < "$DATA_DIR/all-wikilinks.txt") unique link targets"

# All filenames (without path and .md), lowercase for comparison
sed 's|.*/||; s|\.md$||' "$DATA_DIR/all-files.txt" \
    | tr '[:upper:]' '[:lower:]' \
    | sort -u > "$DATA_DIR/all-filenames-lc.txt"

# Wikilink basenames, lowercase
while IFS= read -r link; do
    basename "$link" 2>/dev/null || echo "$link"
done < "$DATA_DIR/all-wikilinks.txt" \
    | tr '[:upper:]' '[:lower:]' \
    | sort -u > "$DATA_DIR/wikilink-bases-lc.txt"

# --- 3b. Broken links via comm ---
comm -23 "$DATA_DIR/wikilink-bases-lc.txt" "$DATA_DIR/all-filenames-lc.txt" \
    > "$DATA_DIR/broken-links.txt" 2>/dev/null || true
echo "  Broken links: $(wc -l < "$DATA_DIR/broken-links.txt")"

# --- 4. All tags (from frontmatter) ---
{
    # Inline format: tags: [foo, bar]
    xargs -d '\n' grep -h "^tags:" < "$DATA_DIR/all-files.txt" 2>/dev/null \
        | sed 's/tags: *\[//; s/\]//; s/,/\n/g' \
        | sed 's/^ *//; s/ *$//' \
        | grep -v '^$' || true

    # YAML list format:   - foo
    xargs -d '\n' grep -hA 20 "^tags:" < "$DATA_DIR/all-files.txt" 2>/dev/null \
        | grep "^  - " \
        | sed 's/^  - //' || true
} | sort | uniq -c | sort -rn > "$DATA_DIR/tag-counts.txt" 2>/dev/null || true

echo "  Tags: $(wc -l < "$DATA_DIR/tag-counts.txt") entries"

# --- 5. Orphan notes (via comm) ---
> "$DATA_DIR/candidate-orphans-lc.txt"
while IFS= read -r file; do
    rel="${file#$VAULT/}"
    case "$rel" in
        _private/*|05-templates/*|.claude/*) continue ;;
        HOME.md|CLAUDE.md|README.md|QUICK-START.md|ARCHITECTURE.md|CONTRIBUTING.md|SETUP.md|_active-context.md) continue ;;
        00-inbox/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md) continue ;;
    esac
    basename "$file" .md | tr '[:upper:]' '[:lower:]'
done < "$DATA_DIR/all-files.txt" | sort -u > "$DATA_DIR/candidate-orphans-lc.txt"

comm -23 "$DATA_DIR/candidate-orphans-lc.txt" "$DATA_DIR/wikilink-bases-lc.txt" \
    > "$DATA_DIR/orphans-lc.txt" 2>/dev/null || true

> "$DATA_DIR/orphans.txt"
while IFS= read -r orphan_lc; do
    grep -i "/${orphan_lc}\\.md$" "$DATA_DIR/all-files.txt" 2>/dev/null \
        | sed "s|^$VAULT/||" >> "$DATA_DIR/orphans.txt" || true
done < "$DATA_DIR/orphans-lc.txt"
echo "  Orphans: $(wc -l < "$DATA_DIR/orphans.txt")"

# --- 6. Inbox files (for triage) ---
find "$VAULT/00-inbox" -name "*.md" \
    -not -name "nightly-*" \
    -not -name "morning-*" \
    -not -name "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md" \
    2>/dev/null | sed "s|^$VAULT/||" | sort > "$DATA_DIR/inbox-files.txt"
echo "  Inbox files to triage: $(wc -l < "$DATA_DIR/inbox-files.txt")"

# --- 7. Vault stats ---
{
    echo "date: $TODAY"
    echo "total_files: $FILE_COUNT"
    for dir in 00-inbox 01-personal 02-work 03-projects 04-knowledge 05-templates 06-archive _private; do
        count=$(grep -c "/$dir/" "$DATA_DIR/all-files.txt" 2>/dev/null || echo "0")
        echo "${dir}: $count"
    done
    new_files=$(cd "$VAULT" && git log --since="yesterday" --diff-filter=A --name-only --pretty=format: 2>/dev/null | grep -c ".md$" || echo "0")
    echo "new_since_yesterday: $new_files"
} > "$DATA_DIR/vault-stats.txt"
echo "  Vault stats done"

echo ""
echo "All data collected in $DATA_DIR/"
