# Ardot MCP Tool Usage Guide — Complete Reference

This document provides end-to-end workflow examples. For design rules, property constraints, and troubleshooting, see `design-rules.md`.

## Ardot MCP Tool Usage Guide

## End-to-End Workflow Examples

### Example A: Creating a New Landing Page

```
Step 0: Ensure design file is open → create_design / open_design if needed, wait for ready
Step 1: fetch_editor_state(includeSchema: false) → understand the current canvas
Step 2: Load references/guidelines-landing-page.md → learn landing page design rules
Step 3: fetch_style_guide_tags → discover available style tags
Step 4: fetch_style_guide(tags: ["modern", "minimal", "website", ...]) → get style inspiration
Step 5: fetch_variables → read existing design tokens (always use these, never hardcode)
Step 6: locate_available_space(width: 1440, height: 3000) → locate placement area
Step 7: batch_edit → create the page frame and hero section (≤25 ops)
Step 8: capture_screenshot → verify hero section visually
Step 9: batch_edit → add features section and content (≤25 ops)
Step 10: capture_screenshot → verify features section
Step 11: batch_edit → add footer and CTA sections (≤25 ops)
Step 12: capture_screenshot → verify final design
Step 13: batch_edit → fix any detected issues
```

### Example B: Modifying an Existing Design

```
Step 0: Ensure design file is open → skip if editor already has a file loaded
Step 1: fetch_editor_state(includeSchema: false) → check current state and selection
Step 2: batch_read(patterns: [{name: "Header"}]) → find target elements
Step 3: capture_layout(parentId: "headerId", maxDepth: 2) → inspect current layout
Step 4: capture_screenshot(nodeIds: ["headerId"]) → visually check current state
Step 5: batch_edit → apply modifications (≤25 ops)
Step 6: capture_screenshot(nodeIds: [...]) → verify changes (batch all target nodes in one call)
```

### Example C: Global Style Update

```
Step 0: Ensure design file is open → skip if editor already has a file loaded
Step 1: fetch_editor_state(includeSchema: false) → check current state
Step 2: scan_all_unique_properties(parentIds: ["rootFrame"]) → audit existing styles
Step 3: substitute_all_matching_properties → bulk update matching properties
Step 4: capture_screenshot → verify the global changes
```

### Example D: Setting Up Design Tokens

```
Step 0: Ensure design file is open → skip if editor already has a file loaded
Step 1: fetch_editor_state(includeSchema: false) → check current state
Step 2: fetch_variables → inspect existing variables
Step 3: apply_variables → create or update variable sets with Light/Dark modes
Step 4: batch_read(patterns: [{reusable: true}]) → find components to bind variables to
Step 5: batch_edit → bind variable references to component properties
```

### Example E: Creating a Registration Form

```
Step 0: Ensure design file is open → create_design / open_design if needed, wait for ready
Step 1: fetch_editor_state(includeSchema: false) → get available components
Step 2: batch_edit → create container frame on document root
  container=I(document, {type: "frame", name: "Registration", layout: "vertical", width: 400, height: "hug_contents(600)"})
Step 3: batch_edit → add title, input fields using component refs
  title=I("containerId", {type: "text", name: "Title", content: "Create Account", fontSize: 28, fill: "#18191C"})
  input1=I("containerId", {type: "ref", ref: "InputComponentId"})
  U(input1+"/label", {content: "First Name"})
Step 4: capture_layout → check for spacing issues
Step 5: batch_edit → fix height to hug_contents if excessive space
Step 6: capture_screenshot → verify final form
```
