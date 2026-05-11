# Slide Scene Injection Prompt

This file is the Agent injection prompt for the **Slides / Presentation** scene. When the Agent receives requests involving slides, presentations, PPTs, decks, reporting pages, pitch decks, proposals, or speech materials, it **MUST** strictly follow the instructions in this file without skipping any stage.

---

## 1. Scene Definition

**Scene Name**: Slides (Presentation)
**`fetch_guidelines` topic**: `slides`
**Canvas Size (Strict)**: Each slide is **1920 × 1080** (16:9), and MUST NOT be changed.
**Multi-Page Layout**: At most 5 slides per row; row and column spacing is 100px.

**Trigger Keywords** (entering this scene if any is matched):
- English: slide, slides, deck, pitch deck, presentation, keynote, ppt, slide deck, design a presentation, create a deck
- Chinese: 幻灯片、演示稿、演示文稿、PPT、汇报、路演、路演 PPT、提案稿、宣讲稿、Keynote、翻页效果、幻灯片转网页

---

## 2. Required Skill to Load

When the Agent enters this scene, it MUST first invoke:

```
use_skill("ardot-design-assistant")
```
> This Skill defines the standard workflow of the entire ardot MCP; in this scene, it **MUST** be executed under the **Slides / Presentation Creation Workflow** (5 phases).

---

## 3. Required Rules / References to Load

The core reference of this scene is **`references/slides-workflow.md`**, which **MUST** be read in Phase 0; the rest are loaded as needed.

| Reference File                         | When to Load                                              |
|----------------------------------------|-----------------------------------------------------------|
| `references/slides-workflow.md`        | **Core. Required in Phase 0** — 5-phase workflow + three mandatory rules. |
| `rules/design-rules.md`                | **Required in Phase 0** — flexbox, text, property specs, troubleshooting. |
| `references/ardot-workflow.md`         | **Required in Phase 0** — end-to-end MCP invocation paradigm. |
| `rules/style-guide.md`                 | Creative aid for Phase 0–1 — layout inspiration, bento grid, anti-patterns. |

**Required guidelines / style fetches** (within Phase 0):
```
fetch_guidelines(topic: "slides")
fetch_style_guide_tags
fetch_style_guide(tags including "slides" or "presentation")
```

## 4. MCP Tool Whitelist (Strictly Limited)

**Core Tools**:
- `fetch_editor_state`
- `fetch_guidelines` (topic fixed to `slides`)
- `fetch_style_guide_tags`
- `fetch_style_guide` (tags MUST include `slides`)
- `fetch_variables`
- `apply_variables`
- `locate_available_space`
- `batch_read`
- `batch_edit` (≤ 25 ops / call)
- `capture_screenshot`
- `capture_layout`
- `upload_images`

---

## 5. Scene-Specific Additional Constraints

1. **Strict Size Rule**: Each slide is strictly **1920×1080**; rows and columns are arranged according to Phase 1 planning with 100px spacing, and **MUST NOT overlap**.
2. **Cover (Homepage) Required**: Main title (≥72px, recommended 80–120px), subtitle (optional, 40–48px), brand identity slot, visual focal point.
3. **Layout Variety**: Three consecutive slides MUST NOT use the same layout; recommended options include bento grid / comparison layout / image-and-text two-column / full-bleed image / data feature (see `rules/style-guide.md`).
4. **Contrast**: All text MUST pass WCAG AA; on dark backgrounds, body `fill` is explicitly set to a light color.
6. **Image Retrieval**: Prefer `G(nodeId, "ai", prompt)`; do NOT manually fill any URL into `fills`.
7. **After each slide is completed, `capture_screenshot` + `capture_layout` double verification MUST be performed** before moving on to the next slide.

---

## 6. Acceptance Checklist (Agent Self-Check — every item MUST pass)

- [ ] All Phase 0 documents have been read; `fetch_guidelines("slides")` / `fetch_style_guide` have been called
- [ ] In Phase 1, the slide count N, roles, and chart slots have been clearly planned
- [ ] In Phase 2, all N empty 1920×1080 frames have been **created in a single pass**, with 100px spacing and at most 5 per row
- [ ] Each slide is completed **in sequence** and has passed both `capture_screenshot` + `capture_layout`
- [ ] All slide sizes are strictly 1920×1080, with no overlap
- [ ] Any text ≥ 22px; Title ≥ 56px; Body ≥ 28px; data numerics 56–96px
- [ ] The entire deck has a unified design style
- [ ] Each slide contains at least 2–3 decorative elements
- [ ] All data is presented as SVG charts rather than plain text lists
