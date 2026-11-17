# Data Studio internal API: what the script relies on

Observed on `datastudio.google.com` in 2026, signed in and anonymous. Undocumented: check here first
when the script breaks, then look at a fresh capture (`__DS.cap`) to see what changed.

## Endpoints

All are `POST /<name>?appVersion=<version>`, JSON body, JSON response prefixed with the anti-XSSI
string `)]}'` (removed by `unxssi()`).

| Endpoint | Body | Gives |
|---|---|---|
| `getReport` | `{reportId}` | Structure: pages, components, their field definitions (`conceptDefs`), text boxes, positions, blends, sharing settings |
| `getSchema` | `{datasourceId}` | Fields of a data source: `name`, `displayName`, `semanticInfo` (format) |
| `batchedDataV2` | `{dataRequest: [...]}` | The data, one request per component |

- **Headers.** Signed in, requests carry `X-RAP-XSRF-TOKEN` (plus `Content-Type`, `encoding: null`,
  `Accept`); anonymous sessions need no token. The hook keeps the headers of the last captured call
  in `__DS.headers` so that `getReport` and `getSchema` can be called the same way. Never print them.
- **appVersion** is read from a captured call in `performance` entries.
- `getReport` must be a POST (GET answers 405); a wrong body or a missing token answers 400.

## getReport

- `reportConfig.shareable`: `name`, `downloadable` (false = download disabled for viewers),
  `isOwner`, `editable`.
- `reportConfig.navigationInfo`: pages in menu order, `{pageId, displayName, hiddenFromViewer}`
  (nested for page groups).
- `publishedReportRevision.reportConfig` (fallback `reportConfig`): the published version, the one
  viewers see.
  - `page[].page.componentConfig[]`: components of a page. `type` (`kpi-metric`, `simple-table`,
    `simple-description` for text boxes...), `conceptDefs` (fields), `attributeConfig.componentAttribute`
    (left, top, width, height), `propertyConfig` (style, `chartTitleText`, text box HTML in
    `componentProperty.descriptionProperty.text`).
  - `page[].page.groupConfig[]`: grouped components.
  - `report.componentConfig[]`: components shown on every page (report-level).
  - `report.resource.dataViewResource.entry[].value.blockDatasource`: blends (see below).

## batchedDataV2

Request: `dataRequest[]`, each with
`requestContext.reportContext {reportId, pageId, componentId, displayType}` and
`datasetSpec {dataset[] (datasourceId per blended source), queryFields[], filters, dateRanges,
sortData, paginateInfo {startRow, rowsCount}, ...}`.

Response: `dataResponse[i]` matches `dataRequest[i]`; `errorStatus` when the query failed. Each
response holds several `dataSubset[]`, told apart by `viewTags`:

| viewTags | Meaning | Script |
|---|---|---|
| `role: "main"`, `compareIndex: 0` | The rows | `rows` |
| `compareIndex: 1` (or `isCompare`) | Comparison period | `compareRows` |
| `isTotals` | Summary row | `totals` |
| `isMin` / `isMax` | One-row helpers that scale bars and heatmaps | ignored (they used to overwrite the rows) |

`dataset.tableDataset`: `columnInfo[].name` (the `qt_…` id of a `conceptDef`),
`column[].<type>Column.values`, `totalCount` (rows of the full result, not of this page).

A column holds its **non-null values only**; `column[].nullIndex` lists the rows where the value is
null. Reading `values` as if they were aligned on the rows shifts every value after the first null (a
campaign with no purchase then shows the cost per purchase of the next one). The totals subset carries
the metric columns only: the script aligns it on the main columns by `columnInfo[].name`.

`dateRanges` holds the queried period, then the comparison period (`startDate`, `endDate`,
`YYYYMMDD`): shown as `period:` in the output.

Tables are paginated: `paginateInfo.startRow` is 1-based. The script merges pages of the same query
(same fields, filters, dates, sort) at their offset, and starts over when the query changes.

## Labels

For a column `qt_x`, find its `conceptDef` (in the component, else anywhere in the report), then:

1. `queryTimeTransformation.displayTransformation.displayName`: name set by the report author.
2. Blend output name: `datasourceBlock.fields[]` whose `field.name` is the column's
   `sourceFieldName`, `outputName`.
3. Data source field: `displayName` from `getSchema`. A `_dvN` suffix on the source field name points
   to the N-th source of the blend (`datasetSpec.dataset[N]`).
4. Formula (`textFormula`), shown as `ƒ …`.

Blend output fields point, through `queryTimeTransformation.dataTransformation.sourceFieldName`, to a
concept of the blend's input query (`blocks[].treeQueryBlockConfig…query.concepts[]`, name in
`concept.id.name`, data source in the sibling `datasourceId`). That concept carries the display name,
the format (`displayTransformation.outputSemanticInfo`) and, for blend-level calculated fields, the
formula.

Formulas use `t0._n123_` style ids; `readable()` replaces them with field names.

## Formats

`semanticConfig[0].semanticType`, from the component's own setting, else the blend input concept,
else its source field, else the data source field:

| Code | Format | Notes |
|---|---|---|
| 12 | `currency:<code>` | `currencyOptions.currencyCode` |
| 14 | `percent` | value is a ratio |
| 28 | `duration` | seconds, shown hh:mm:ss |
| 33 | `number` | |
| 2 | `date` | |
| 32, 16, 17 | `text` | |
| 41 | `url` | |
| 42 | `link` | HYPERLINK(): value is label + two no-break spaces + URL |

`resultTransformation.analyticalFunction: 1` = percent of total, already computed by the backend.
Unknown codes come out as `typeN`: look at the screen, then add them to `semanticOf()`.

## Titles

Text boxes (`simple-description` without fields), HTML stripped. For each data component: explicit
`chartTitleText`; else text boxes of the same group; else text boxes inside its box; else the
nearest text box above (horizontal overlap ≥ 40 %, gap ≤ 140 px). Section: the nearest wide text box
(≥ 300 px) above, within 700 px. A component with none of these gets a generated title, flagged.

## The hook and its timing

`fetch` is not used for these calls: they go through `XMLHttpRequest` in the main thread. The hook
wraps `setRequestHeader` and `send` and reads the response on `loadend` via `responseURL`. Replacing
`fetch` or `send` after the first calls changes nothing, and loading the report in an iframe to hook
it is blocked. Install the hook right after `navigate` returns; `callsBeforeHook` counts data calls
already sent.

Page changes inside the app: `history.pushState` + a `popstate` event changes page without
reloading (the hook stays). Components with the same query as one already loaded reuse its response:
no request, so `missing`. Only a direct load of the page fixes it.

Components below the fold load when scrolled into view.

## Browser tool constraints

- `javascript_tool` returns about 2,000 characters, blocks output that looks like query strings
  (`[BLOCKED: Cookie/query string data]`: avoid `=`, `?`, `&` in returned text) and times out after
  about 45 s. Long loops run in the background with a flag polled afterwards.
- `read_page` on an element with an `aria-label` returns the label only. `get_page_text` reads a
  visible element with `role=article`, hence the full-screen overlay of `DS.dump`.

## When something breaks

| Symptom | Likely cause | Check |
|---|---|---|
| `cap` empty | Hook installed too late, or calls moved off XHR | `callsBeforeHook`, `performance` entries for `batchedDataV2` |
| `getReport unavailable` | Not captured and replay refused (token, body) | `__DS.cap` paths and statuses |
| Many `unresolved` labels | Structure moved | a `conceptDef` and the matching `getSchema` field |
| Rows overwritten / 1 row, values in the wrong rows | New subset type, or nulls | `viewTags` and `nullIndex` of each subset |
| Values differ from screen | Format code unknown, or a subset misread | the raw values against the screen |
