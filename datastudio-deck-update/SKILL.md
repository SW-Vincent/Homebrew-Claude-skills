---
name: datastudio-deck-update
description: Updates a deck or report (most often the previous COPIL deck, rolled over to the next period) with the figures of a Data Studio (Looker Studio) report. Maps each slide to its report chart, extracts with datastudio-reader, checks against the previous deliverable and rebuilds charts from raw values. Use for "mets à jour les slides sur le trimestre suivant", "exporte le Data Studio dans un deck".
---

# Update a deck or report from a Data Studio report

## What this skill does

It moves figures from a Data Studio report into a deliverable the user will present or send:
most often the deck of the previous period (a quarterly steering committee, a monthly report)
updated to the next period, sometimes new slides built from the report's charts. The figures are
read with the **datastudio-reader** skill (load it first; it needs Claude in Chrome), checked
against the previous deliverable, then turned into charts, tables and short factual statements by
code, never retyped by hand.

The output format follows the user's request: a house deck skill when the user asks for it (an
agency template, for instance), otherwise the session's own rules for decks, documents and
sheets. This skill decides what goes in the deliverable, not how it is styled.

## 1. Read the previous deliverable

When one is given, read its text (for a .pptx, the pptx skill's `slide_text.py`) and render its
slides as images to see the charts. Sort every slide:

- **Data slides**: figures, charts, tables. For each, note the metrics, dimensions, period,
  comparison and footnotes, and the benchmarks it quotes (sector averages and their sources).
- **Context slides**: the periods, dates and campaign lists to update.
- **Slides the report cannot update**: qualitative analysis, lessons learnt, roadmap, market
  watch, screenshots of ads. They are not rebuilt from the dashboard: list them for the user.

Look out for things that must not be copied blindly: credentials (an extranet login and password
in a footnote), footnotes that contradict the figures, a client's text that only needs its dates
changed.

## 2. Settle the periods

- **New period.** "Next quarter" after a deliverable on April to June is July to September. When
  the previous period was cut at a meeting date (1 April to 20 June), say which reading was taken
  (calendar quarter, or continuity from the day after), and carry on.
- **Comparisons, slide by slide.** Keep the comparison the previous deliverable used: the one the
  report computes itself (often the same period of the previous year), or the previous
  deliverable's period (for distributions such as age or device). Each comparison the report does
  not compute costs one more date change.
- Say the choices at the top of the work; ask first only if a wrong guess would be expensive (a long
  deck, many date changes).

## 3. Map and extract

Follow datastudio-reader. Then:

1. **Map.** Load the report's page in its default view, run `__DS.list()`, and match each data slide
   to its component (title, columns, chart type). When two components could fit, take the one whose
   figures match the previous deliverable.
2. **Validate on the previous period.** Set the date range to the previous deliverable's period and
   check several of its figures against the extraction (a cost, a count, a share, a change). They
   should match to the decimal. A mismatch means a wrong component, a filter, or data that changed
   since: stop and find out before going further. This one check is what makes the rest trustworthy.
3. **Extract the new period**, then each comparison period the report does not compute
   (datastudio-reader, step 5: drop the captured calls before each change, check `period:` after).
4. **Save** the components needed with `__DS.json([...])` into a file in the working directory, one
   file per period. The JSON is copied as it is; figures are never retyped.
5. **Reset** the report's view ("Réinitialiser") and close the tab. Each date change re-queries every
   component of the page (quotas, warehouse costs): two or three changes, not more.

## 4. Compute with code

A short script reads the JSON files and produces everything the deliverable shows:

- figures formatted the way the deliverable writes them (French: `3 275 311`, `0,82 €`, `1,96 %`,
  no-break spaces inside numbers);
- changes and shares computed from raw values (`(new - old) / old`), never from rounded ones;
- the chart data, in the target's chart format;
- consistency checks: rows add up to the totals, shares to about 100 %, the same figure is equal
  wherever it appears.

The deliverable's files then read these values (a JSON of formatted strings), so that rebuilding
after a correction does not mean editing figures by hand.

## 5. Build

- **Keep the previous deliverable's structure and texts.** Update periods, dates and figures; do not
  rewrite or condense the client's wording. Where the template forces a change (a title that no
  longer fits, a section name too long for the layout), make the smallest one and report it.
- **Rebuild charts from raw values**, not screenshots: same chart type as before unless it was hard
  to read (two units on one axis: split it; two pies to compare: grouped bars of shares; say so).
  Native, editable charts when the target supports them.
- **Each data slide states** its source, period, comparison and perimeter (a context band, a
  subtitle or a footnote, as the template allows).
- **Takeaways are factual**: figures, rankings, changes, against benchmarks. Causes, judgements and
  recommendations are another step (commentary), unless the user asks for them here.
- **Benchmarks** (sector averages) are taken from the previous deliverable with their sources and
  flagged as not refreshed.
- **What the report cannot provide** (campaign dates and objectives, qualitative slides) is listed
  for the user, or marked "à compléter" where a slide needs it. Never invented.
- **Credentials** found in the previous deliverable are not copied: say so.
- If the target's chart renderer cannot run here (a package it installs, no network), render the
  same chart specifications another way (same ids, sizes, fonts and colours) and say so.

## 6. Check, then report

- Run the consistency checks again on the final values; read the slide text back
  (`slide_text.py`) and compare a sample of figures with the JSON.
- Render the deliverable and look at every slide: overflow, overlaps, charts running into the
  takeaway box, labels cut at the edge of a chart.
- Report to the user, briefly:
  - the periods and comparisons used, and the reading taken for "next period";
  - the validation result on the previous period;
  - what was not updated, and why;
  - discrepancies found on the way: components of the report that disagree, a formula that looks
    wrong, a footnote of the previous deliverable that does not match what the report computes.
    These are worth fixing in the report itself;
  - template adjustments (shortened titles, a smaller font), and the number of date changes made.

## Limits

- Only what the report shows, in its filters and with its formulas. A figure the report does not
  compute is computed from extracted raw values, and labelled as such.
- The previous deliverable may have used a component, a filter or a period that the report no longer
  has: the validation step finds it; say what changed.
- The extraction limits of datastudio-reader apply: undocumented API, quotas, export disabled by the
  owner, paginated tables.
