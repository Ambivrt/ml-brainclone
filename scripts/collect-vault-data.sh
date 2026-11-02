#!/bin/bash
# =============================================================================
# Larry Nightly — Vault Data Collector
# =============================================================================
# Collects raw vault data for analysis. Output: text files in .data/.
# The bulk-tier model analyzes these and writes reports to 00-inbox/.
#
# Usage: bash collect-vault-data.sh [vault-path]
#
# Needs gawk (BEGINFILE/ENDFILE/ARGIND). The per-file loops of the first
# version forked head/tr/sed/grep for every file and got slow on a big vault,
# so the heavy steps are one gawk pass each.
# =============================================================================

set -euo pipefail

# Same sort order in sort and comm no matter who starts the script. A scheduler
# runs without LANG, an interactive session with a locale. Lists sorted in one
# order and compared in the other gave false differences.
export LC_ALL=C

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
# CR and a UTF-8 BOM are stripped before the comparison. Without that every
# file saved with CRLF (most of them, on Windows) counts as missing frontmatter.
# One gawk pass instead of head/tr/sed per file. An unreadable or empty file
# counts as missing frontmatter.
xargs -d '\n' gawk -v vault="$VAULT/" '
    function rel(f) { return index(f, vault) == 1 ? substr(f, length(vault) + 1) : f }
    BEGINFILE { if (ERRNO != "") { print rel(FILENAME); nextfile } }
    FNR==1 {
        sub(/\r$/, ""); sub(/^\xef\xbb\xbf/, "")
        if ($0 != "---") print rel(FILENAME)
        nextfile
    }
    ENDFILE { if (FNR == 0) print rel(FILENAME) }
' < "$DATA_DIR/all-files.txt" > "$DATA_DIR/missing-frontmatter.txt" 2>/dev/null || true
echo "  Frontmatter: $(wc -l < "$DATA_DIR/missing-frontmatter.txt") files missing frontmatter"

# --- 3. All wikilinks in the vault ---
# Code fences (``` and ~~~) and inline code are skipped. They hold type hints
# (Callable[[dict, float], bool]) and examples of the syntax (`[[link]]`), not
# links. Without the filter they show up as broken every night.
xargs -d '\n' awk '
    FNR==1 { fence=0 }
    /^[[:space:]]*(```|~~~)/ { fence=!fence; next }
    fence { next }
    {
        line=$0
        gsub(/`[^`]*`/, "", line)
        while (match(line, /\[\[[^]|#]+/)) {
            print substr(line, RSTART, RLENGTH) "\t" FILENAME
            line=substr(line, RSTART+RLENGTH)
        }
    }
' < "$DATA_DIR/all-files.txt" 2>/dev/null \
    | sed 's/\[\[//' \
    | sort -u > "$DATA_DIR/wikilink-pairs.txt" || true
# Link target<TAB>source file. The pairs are needed in 3b to say where a broken target stands.
cut -f1 "$DATA_DIR/wikilink-pairs.txt" | sort -u > "$DATA_DIR/all-wikilinks.txt"
echo "  Wikilinks: $(wc -l < "$DATA_DIR/all-wikilinks.txt") unique link targets"

# All filenames (without path and .md), lowercase for comparison
sed 's|.*/||; s|\.md$||' "$DATA_DIR/all-files.txt" \
    | tr '[:upper:]' '[:lower:]' \
    | sort -u > "$DATA_DIR/all-filenames-lc.txt"

# Wikilink basenames, lowercase. The basename is taken in gawk (basename per
# link forked thousands of times) and treats \ as a separator too: a table link
# [[name\|alias]] gives the target "name\", which would be flagged as broken.
gawk '{ b = $0; sub(/[\/\\]+$/, "", b); if (b != "") sub(/.*[\/\\]/, "", b); else if ($0 != "") b = "/"; print b }' \
    "$DATA_DIR/all-wikilinks.txt" \
    | tr '[:upper:]' '[:lower:]' \
    | sort -u > "$DATA_DIR/wikilink-bases-lc.txt"

# --- 3b. Broken links via comm ---
comm -23 "$DATA_DIR/wikilink-bases-lc.txt" "$DATA_DIR/all-filenames-lc.txt" \
    > "$DATA_DIR/broken-links.txt" 2>/dev/null || true
echo "  Broken links: $(wc -l < "$DATA_DIR/broken-links.txt")"

# The source notes for each broken target, written in the same step:
# "target :: source | source". Without them a truncated link in two daily
# notes was reported for nights and misdiagnosed before a grep found it.
gawk -F'\t' -v vault="$VAULT/" '
    ARGIND==1 { broken[$0]=1; next }
    {
        base=$1
        sub(/\/+$/, "", base); sub(/.*\//, "", base)
        base=tolower(base)
        if (!(base in broken)) next
        src=$2
        if (index(src, vault) == 1) src=substr(src, length(vault) + 1)
        if (seen[base, src]++) next
        srcs[base]=(base in srcs ? srcs[base] " | " : "") src
    }
    END { for (b in srcs) print b " :: " srcs[b] }
' "$DATA_DIR/broken-links.txt" "$DATA_DIR/wikilink-pairs.txt" 2>/dev/null \
    | sort > "$DATA_DIR/bl-sources.txt" || true

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
    # Parameter expansion instead of basename|tr per file. With LC_ALL=C only
    # ASCII is lowered, exactly as tr did.
    base="${file##*/}"; base="${base%.md}"
    printf '%s\n' "${base,,}"
done < "$DATA_DIR/all-files.txt" | sort -u > "$DATA_DIR/candidate-orphans-lc.txt"

comm -23 "$DATA_DIR/candidate-orphans-lc.txt" "$DATA_DIR/wikilink-bases-lc.txt" \
    > "$DATA_DIR/orphans-lc.txt" 2>/dev/null || true

# Map back to real file names. One gawk pass instead of a grep over the whole
# list per orphan. Exact basename comparison: grep read dots in a name as regex.
gawk -v vault="$VAULT/" '
    ARGIND==1 { order[++n] = $0; next }
    {
        b = $0; sub(/.*\//, "", b)
        if (b !~ /\.[mM][dD]$/) next
        b = tolower(substr(b, 1, length(b) - 3))
        r = $0; if (index(r, vault) == 1) r = substr(r, length(vault) + 1)
        hits[b] = (b in hits ? hits[b] "\n" : "") r
    }
    END { for (i = 1; i <= n; i++) if (order[i] in hits) print hits[order[i]] }
' "$DATA_DIR/orphans-lc.txt" "$DATA_DIR/all-files.txt" > "$DATA_DIR/orphans.txt" 2>/dev/null || true
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
        # Anchored at the vault root. Without the anchor _private/01-personal/
        # counted into 01-personal. grep -c prints 0 itself when nothing matches.
        count=$(grep -c "^$VAULT/$dir/" "$DATA_DIR/all-files.txt" 2>/dev/null || true)
        echo "${dir}: $count"
    done
    new_files=$(cd "$VAULT" && git log --since="yesterday" --diff-filter=A --name-only --pretty=format: 2>/dev/null | grep -c ".md$" || true)
    echo "new_since_yesterday: $new_files"
} > "$DATA_DIR/vault-stats.txt"
echo "  Vault stats done"

echo ""
echo "All data collected in $DATA_DIR/"
