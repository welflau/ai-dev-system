---
name: perf-report
description: "Generate and compare Unreal performance reports from .utrace / Unreal Insights exports. Use for frame-time analysis, GameThread/RenderThread/GPU hotspot summaries, jank clustering, archive management, and regression comparison."
---

# Unreal Perf Report Skill

## Purpose

Turn Unreal `.utrace` or Unreal Insights-derived data into a concise Markdown performance report with supporting charts and an optional archived history.

This skill is project-neutral. Discover helper scripts, trace paths, report paths, and custom scope names from the current repository and trace data.

## Inputs

- `.utrace` files, usually from a packaged build or editor trace.
- Optional converted SQLite `.db` / `.insights.db`.
- Optional exported hotpath text, JSON summaries, or GPU flamegraph images.
- Optional archive index for comparing historical reports.

## Discovery

Before analysis:

1. Search the repo for existing helpers such as `generate_perf_report.*`, `dump_perf_data.py`, `Tools/UTrace/`, or `Saved/PerfReports/`.
2. If no helper exists, use Unreal Insights/utrace CLI or Python SQLite queries directly.
3. Do not assume executable names, packaged game names, device IDs, or custom scope prefixes.

## Report Workflow

1. Locate or request the `.utrace` source.
2. Convert/export raw data when needed: summary, frame stats, jank frames, global timers, and per-frame hotpaths.
3. Prefer structured JSON/CSV/SQLite tables over parsing free text.
4. Analyze GameThread, RenderThread, and GPU separately when data exists.
5. Cluster jank frames by repeated hotspot/root scope, phase, or frame range.
6. Generate Markdown report and charts under the repository's discovered report directory, commonly `Saved/PerfReports/`.
7. Archive results by device/time when the repo already has an archive convention or the user asks for history.

## Minimum Report Sections

- Trace metadata: source file, duration, frame count, channels available, generated time.
- Frame summary: average, max, p95/p99, distribution buckets.
- Worst frames: top frame table with thread, duration, likely root.
- Hotspots: top cumulative timers per available thread.
- Jank clusters: grouped cause, affected frames, evidence, confidence.
- GPU status: analyzed if data exists; otherwise state the missing channel/export.
- Recommendations: data-backed and ranked by expected impact/risk.

## GPU Notes

GPU detail availability varies by engine version and trace channels. SQLite events may not contain full GPU pass timing. If data is missing, ask for or point to an Unreal Insights GPU track export rather than inventing pass-level conclusions.

## Comparison Workflow

When asked to compare reports:

1. Discover archive index or list report directories.
2. Select the requested baseline/target; if ambiguous, ask for the two report IDs.
3. Extract common metrics: FPS/frame times, p95/p99, jank count, top timers, new/disappeared hotspots.
4. Produce a comparison Markdown file near the archive or report directory.
5. Call out device/build differences separately from performance regressions.

## Charting

Use Python with a non-GUI backend such as matplotlib `Agg`. Keep chart generation reproducible and write image files next to the report. Use fonts available on the machine; if CJK labels fail, fall back to ASCII labels rather than blocking the analysis.

## Constraints

- Do not make subjective claims without measured evidence.
- Do not delete trace files or old reports unless the user explicitly asks.
- For huge databases, use bounded SQL queries and timeouts; fall back to top-N or sampled frames.
- Keep custom scope interpretation generic until the current project defines the meaning.

## Delivery

Report output path, source trace, generated charts, archive path if any, key bottlenecks, confidence level, and data gaps.
