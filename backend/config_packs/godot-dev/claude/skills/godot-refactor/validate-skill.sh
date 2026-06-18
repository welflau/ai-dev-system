#!/bin/bash
# Validation script for godot-refactoring skill

SKILL_DIR="${1:-.}"
# If not provided, use current directory
if [ ! -f "$SKILL_DIR/SKILL.md" ]; then
    SKILL_DIR="$HOME/.config/opencode/superpowers/skills/godot-refactoring"
fi
echo "Validating Godot Refactoring Skill..."
echo ""

# Check all required files exist
FILES=(
    "SKILL.md"
    "README.md"
    "INDEX.md"
    "EXAMPLES.md"
    "docs/anti-patterns-detection.md"
    "docs/tscn-generation-guide.md"
    "docs/godot-best-practices.md"
    "docs/refactoring-operations.md"
    "docs/verification-checklist.md"
    "docs/godot-node-reference.md"
    "docs/node-selection-guide.md"
    "docs/scene-reusability-patterns.md"
    "docs/conflicting-operations-detection.md"
    "docs/IMPLEMENTATION_SUMMARY.md"
)

echo "Checking required files..."
all_present=true
for file in "${FILES[@]}"; do
    if [ -f "$SKILL_DIR/$file" ]; then
        lines=$(wc -l < "$SKILL_DIR/$file")
        echo "  ✓ $file ($lines lines)"
    else
        echo "  ✗ $file MISSING"
        all_present=false
    fi
done
echo ""

# Check YAML frontmatter
echo "Checking YAML frontmatter..."
if head -5 "$SKILL_DIR/SKILL.md" | grep -q "^name: godot-refactoring"; then
    echo "  ✓ Skill name: godot-refactoring"
else
    echo "  ✗ Invalid skill name in frontmatter"
fi

if head -5 "$SKILL_DIR/SKILL.md" | grep -q "^description:"; then
    echo "  ✓ Description present"
else
    echo "  ✗ Description missing"
fi
echo ""

# Check file sizes
echo "File sizes:"
find "$SKILL_DIR" -name "*.md" | sort | xargs -I {} bash -c 'echo "{}" | sed "s|$SKILL_DIR/||"; du -h "{}"' | sort -k2h
echo ""

# Total line count
total=$(find "$SKILL_DIR" -name "*.md" -exec wc -l {} + | tail -1 | awk '{print $1}')
echo "Total lines: $total"
echo ""

if [ "$all_present" = true ]; then
    echo "✓ Skill validation PASSED"
    echo ""
    echo "The godot-refactoring skill is ready to use!"
    exit 0
else
    echo "✗ Skill validation FAILED"
    echo ""
    echo "Some files are missing. Please check the output above."
    exit 1
fi
