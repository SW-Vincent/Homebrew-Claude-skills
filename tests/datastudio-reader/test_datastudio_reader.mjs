// Tests of the datastudio-reader script, without a browser: run with `node --test tests/datastudio-reader/`.
// The HOOK and EXTRACT blocks are read from datastudio-reader/SKILL.md (the copy Claude runs), executed against a
// minimal fake page, and fed a fake report and data response shaped like Data Studio's internal API.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const root = fileURLToPath(new URL('../../', import.meta.url));
const skill = readFileSync(root + 'datastudio-reader/SKILL.md', 'utf8');
const annotated = readFileSync(root + 'datastudio-reader/references/ds_extract.annotated.js', 'utf8');
const block = (title) => {
  const m = skill.match(new RegExp('### ' + title + '[^\\n]*\\n\\n```js\\n([\\s\\S]*?)```'));
  assert.ok(m, title + ' block not found in SKILL.md');
  return m[1];
};
const HOOK = block('HOOK'), EXTRACT = block('EXTRACT');

// Minimal page: the overlay element, the report URL, XMLHttpRequest and performance entries.
function fakePage() {
  const els = {};
  const document = {
    getElementById: (id) => els[id] || null,
    createElement: () => ({ setAttribute() {}, style: {}, remove() { delete els.__ds_out; } }),
    body: { appendChild(e) { e.id = '__ds_out'; els.__ds_out = e; } },
    querySelector: () => null, querySelectorAll: () => [],
  };
  function XMLHttpRequest() {}
  XMLHttpRequest.prototype.setRequestHeader = function () {};
  XMLHttpRequest.prototype.send = function () {};
  const window = {};
  const ctx = vm.createContext({ window, document, XMLHttpRequest, location: { pathname: '/reporting/R1/page/p1' },
    performance: { now: () => 1, getEntriesByType: () => [] }, console, URL, JSON, Math, Set, Object, Array, String, Promise, setTimeout });
  vm.runInContext(HOOK, ctx); vm.runInContext(EXTRACT, ctx);
  return { DS: window.__DS, overlay: () => (els.__ds_out ? els.__ds_out.textContent : null) };
}

// One page: a title text box above a table (campaign, CPA in EUR); data with a null CPA, a totals subset,
// a comparison subset and a min/max helper subset that must be ignored.
const report = {
  reportConfig: { shareable: { name: 'Test report', downloadable: true }, navigationInfo: [{ pageId: 'p1', displayName: 'Page 1' }] },
  publishedReportRevision: { reportConfig: { page: [{ pageId: 'p1', page: { componentConfig: [
    { componentId: 'c1', type: 'simple-table', attributeConfig: { componentAttribute: { left: 0, top: 100, width: 400, height: 200 } },
      conceptDefs: [
        { name: 'qt_a', queryTimeTransformation: { displayTransformation: { displayName: 'Campaign', outputSemanticInfo: { semanticConfig: [{ semanticType: 32 }] } } } },
        { name: 'qt_b', queryTimeTransformation: { dataTransformation: { textFormula: 'SUM(t0.cost) / SUM(t0.purchases)' },
          displayTransformation: { displayName: 'CPA', outputSemanticInfo: { semanticConfig: [{ semanticType: 12, currencyOptions: { currencyCode: 'EUR' } }] } } } }] },
    { componentId: 't1', type: 'simple-description', attributeConfig: { componentAttribute: { left: 0, top: 50, width: 400, height: 30 } },
      propertyConfig: { componentProperty: { descriptionProperty: { text: '<p>Cost&nbsp;per purchase &amp; lead</p>' } } } }] } }] } },
};
const table = (a, b, extra = {}) => ({ dataset: { tableDataset: { columnInfo: [{ name: 'qt_a' }, { name: 'qt_b' }],
  column: [{ stringColumn: { values: a }, nullIndex: [] }, { doubleColumn: { values: b.filter((v) => v !== null) }, nullIndex: b.flatMap((v, i) => (v === null ? [i] : [])) }],
  totalCount: a.length } }, ...extra });
const request = { dataRequest: [{ requestContext: { reportContext: { componentId: 'c1', pageId: 'p1' } },
  datasetSpec: { dataset: [{ datasourceId: 'd1' }], queryFields: [], dateRanges: [{ startDate: '20260701', endDate: '20260930' }, { startDate: '20250701', endDate: '20250930' }], paginateInfo: { startRow: 1, rowsCount: 10 } } }] };
const response = { dataResponse: [{ dataSubset: [
  table(['A', 'B', 'C'], [null, 2.5, 4], { viewTags: { role: 'main', compareIndex: 0 } }),
  table(['A', 'B', 'C'], [1, 2, 3], { viewTags: { role: 'main', compareIndex: 1 } }),
  table(['X'], [99], { viewTags: { isMax: true } }),
  { viewTags: { isTotals: true }, isTotals: true, dataset: { tableDataset: { columnInfo: [{ name: 'qt_b' }], column: [{ doubleColumn: { values: [3.2] }, nullIndex: [] }] } } }] }] };

async function extracted() {
  const page = fakePage();
  page.DS.cap = [{ path: 'getReport', status: 200, req: '', res: JSON.stringify(report) },
    { path: 'batchedDataV2', status: 200, req: JSON.stringify(request), res: ")]}'\n" + JSON.stringify(response), page: 'p1' }];
  page.DS.schemas = { d1: {} };
  const result = await page.DS.extract();
  // values built inside the vm context have that context's prototypes: compare plain copies
  return { ...page, result, c: JSON.parse(JSON.stringify(result.pages[0].components[0])) };
}

test('null values stay in their row (nullIndex)', async () => {
  const { c } = await extracted();
  assert.deepEqual(c.rows, [['A', null], ['B', 2.5], ['C', 4]]);
});

test('comparison rows are kept, min/max helpers ignored', async () => {
  const { c } = await extracted();
  assert.deepEqual(c.compareRows, [['A', 1], ['B', 2], ['C', 3]]);
  assert.equal(c.rowCount, 3);
});

test('totals are aligned on the metric columns', async () => {
  const { c } = await extracted();
  assert.deepEqual(c.totals, [null, 3.2]);
});

test('title, labels, formats, periods', async () => {
  const { c } = await extracted();
  assert.equal(c.title, 'Cost per purchase & lead'); // HTML entities decoded
  assert.deepEqual(c.columns.map((k) => [k.label, k.format]), [['Campaign', 'text'], ['CPA', 'currency:EUR']]);
  assert.deepEqual(c.periods, ['20260701..20260930', '20250701..20250930']);
});

test('dump, list and json write to the overlay', async () => {
  const { DS, overlay } = await extracted();
  DS.dump('Page 1', 10);
  assert.match(overlay(), /## Cost per purchase & lead/);
  assert.match(overlay(), /period: 20260701\.\.20260930 — compared with 20250701\.\.20250930/);
  assert.match(overlay(), /B \| 2,50\s€/);
  DS.list();
  assert.match(overlay(), /^1\. Page 1 \| simple-table \| Cost per purchase & lead \| Campaign, CPA \| 3\/3 rows/);
  DS.json(['c1']);
  const json = JSON.parse(overlay().replace(/^JSONSTART/, '').replace(/JSONEND$/, ''));
  assert.equal(json.components.length, 1);
  assert.deepEqual(json.components[0].rows[0], ['A', null]);
  DS.clear();
  assert.equal(overlay(), null);
});

test('export disabled by the owner: nothing extracted', async () => {
  const page = fakePage();
  const locked = structuredClone(report); locked.reportConfig.shareable.downloadable = false;
  page.DS.cap = [{ path: 'getReport', status: 200, req: '', res: JSON.stringify(locked) }];
  const result = await page.DS.extract();
  assert.equal(result.exportAllowed, false);
  assert.equal(result.pages.length, 0);
});

test('annotated source and SKILL.md blocks hold the same code', () => {
  const norm = (code) => code.split('\n').map((l) => l.trim()).filter((l) => l && !l.startsWith('//')).join('\n');
  const parts = annotated.split(/^\/\/ -+ (?:HOOK|EXTRACT)\s*$/m);
  assert.equal(parts.length, 3, 'annotated file should have a HOOK and an EXTRACT section');
  assert.equal(norm(parts[1]), norm(HOOK), 'HOOK differs between SKILL.md and references/ds_extract.annotated.js');
  assert.equal(norm(parts[2]), norm(EXTRACT), 'EXTRACT differs between SKILL.md and references/ds_extract.annotated.js');
});
