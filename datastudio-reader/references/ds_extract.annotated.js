// ds_extract.js — read what a Data Studio (Looker Studio) report shows, from inside the page.
// Two snippets, run with the browser's "execute JavaScript in page" tool:
//   HOOK    : right after the report URL starts loading (before its first data call, ~1-2 s).
//   EXTRACT : once the pages of interest have loaded (DS.goto() for the other pages, DS.nextPage() for more
//             rows of a paginated table), then DS.extract(), DS.dump(page) and the page-text tool, DS.clear().
// Read-only: the only calls it makes itself are getReport (if it was not captured) and getSchema.
// It never builds or alters a data request. Everything stays in window.__DS; nothing is sent elsewhere.
// Annotated source. The copy Claude runs is the pair of HOOK / EXTRACT blocks in ../SKILL.md (same code, comment lines
// and indentation removed): change both, tests/datastudio-reader checks that they still match.

// ---------------------------------------------------------------- HOOK
(function () {
  const DS = (window.__DS = window.__DS || {});
  if (DS.installed) return;
  DS.cap = [];
  DS.hookedAtMs = Math.round(performance.now());
  DS.callsBeforeHook = performance.getEntriesByType('resource').filter(r => /batchedDataV2/.test(r.name)).length;
  const P = XMLHttpRequest.prototype, setH = P.setRequestHeader, send = P.send;
  P.setRequestHeader = function (k, v) { (this.__dsH = this.__dsH || {})[k] = v; return setH.apply(this, arguments); };
  P.send = function (body) {
    const x = this, req = typeof body === 'string' ? body : '';
    x.addEventListener('loadend', () => {
      const m = (x.responseURL || '').match(/\/(getReport|batchedDataV2|getSchema)\b/);
      if (!m) return;
      let res = '';
      try {
        res = (x.responseType === '' || x.responseType === 'text') ? x.responseText
          : typeof x.response === 'string' ? x.response
          : x.response instanceof ArrayBuffer ? new TextDecoder().decode(x.response) : JSON.stringify(x.response);
      } catch (e) { res = ''; }
      DS.cap.push({ path: m[1], status: x.status, req, res, page: (location.pathname.split('/page/')[1] || '') });
      DS.headers = x.__dsH || {};
    });
    return send.apply(this, arguments);
  };
  DS.installed = true;
})();

// ---------------------------------------------------------------- EXTRACT
(function () {
  const DS = window.__DS;
  const unxssi = s => JSON.parse(String(s).replace(/^\)\]\}'\s*/, ''));
  const plain = s => String(s || '').replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim();
  DS.reportId = location.pathname.split('/')[2];

  DS.post = async (path, obj) => {
    const e = performance.getEntriesByType('resource').find(r => /\/(batchedDataV2|getReport)/.test(r.name));
    const av = e ? new URL(e.name).searchParams.get('appVersion') : '';
    const r = await fetch('/' + path + '?appVersion=' + encodeURIComponent(av), {
      method: 'POST', credentials: 'include', headers: DS.headers || { 'Content-Type': 'application/json' }, body: JSON.stringify(obj)
    });
    const t = await r.text();
    return { status: r.status, json: r.status === 200 ? unxssi(t) : null };
  };

  // Page change without reload (keeps the hook), then scroll so lazy components load.
  DS.goto = async (pageId, waitMs) => {
    const before = DS.cap.length;
    history.pushState({}, '', '/reporting/' + DS.reportId + '/page/' + pageId);
    window.dispatchEvent(new PopStateEvent('popstate', { state: {} }));
    await new Promise(r => setTimeout(r, waitMs || 7000));
    await DS.scroll();
    return { page: pageId, newCalls: DS.cap.length - before };
  };
  // Scroll the report down and back up, so components below the fold load (they load when shown).
  DS.scroll = async () => {
    const before = DS.cap.length;
    const sc = [...document.querySelectorAll('*')]
      .filter(e => e.scrollHeight > e.clientHeight + 50 && /auto|scroll/.test(getComputedStyle(e).overflowY))
      .sort((a, b) => b.scrollHeight - a.scrollHeight)[0];
    if (sc) {
      for (let y = 0; y <= sc.scrollHeight; y += 500) { sc.scrollTop = y; await new Promise(r => setTimeout(r, 400)); }
      sc.scrollTop = 0; await new Promise(r => setTimeout(r, 2000));
    }
    return { scrolled: !!sc, newCalls: DS.cap.length - before };
  };

  // Next pages of a paginated table, clicked as a viewer would: the app sends its own request (captured by HOOK),
  // nothing is built here. One request per page, counted in the data source's quota (GA4 tokens, warehouse
  // queries): load only the pages needed, then run DS.extract() again (rows are placed at their offset).
  DS.nextPage = async (componentId, pages, waitMs) => {
    const fwd = () => document.querySelector('[class*="' + componentId + '"] .pageForward');
    if (!fwd()) return 'no pager for this component on the current page';
    let n = 0;
    for (; n < (pages || 1); n++) {
      const b = fwd();
      if (!b || /disabled/.test(b.className)) break;
      const before = DS.cap.length;
      ['mousedown', 'mouseup', 'click'].forEach(t => b.dispatchEvent(new MouseEvent(t, { bubbles: true })));
      for (let w = 0; w < 30 && DS.cap.length === before; w++) await new Promise(r => setTimeout(r, 500));
      await new Promise(r => setTimeout(r, waitMs || 1500));
    }
    return n + ' page(s) loaded';
  };

  DS.extract = async () => {
    // 1. Structure
    const capRep = DS.cap.find(c => c.path === 'getReport' && c.status === 200 && c.res);
    DS.report = capRep ? unxssi(capRep.res) : (await DS.post('getReport', { reportId: DS.reportId })).json;
    if (!DS.report) return { error: 'getReport unavailable' };
    const share = DS.report.reportConfig.shareable || {};
    const R = (DS.report.publishedReportRevision || {}).reportConfig || DS.report.reportConfig;
    const result = {
      reportId: DS.reportId, name: share.name, exportAllowed: share.downloadable !== false,
      viewer: share.isOwner ? 'owner' : share.editable ? 'editor' : 'viewer', pages: [], warnings: []
    };
    if (!result.exportAllowed) { result.warnings.push('Export disabled by the owner: data not extracted.'); DS.result = result; return result; }

    // 2. Pages (navigation order, hidden flag)
    const navPages = [];
    (function walk(o) {
      if (Array.isArray(o)) return o.forEach(walk);
      if (o && typeof o === 'object') {
        if (o.pageId && o.displayName !== undefined) navPages.push({ id: o.pageId, name: o.displayName, hidden: !!o.hiddenFromViewer });
        Object.values(o).forEach(walk);
      }
    })(DS.report.reportConfig.navigationInfo || {});

    // 3. Field dictionaries: data source schemas + blend output names
    const dsIds = new Set();
    DS.cap.forEach(c => { try { JSON.parse(c.req).dataRequest.forEach(d => d.datasetSpec.dataset.forEach(x => dsIds.add(x.datasourceId))); } catch (e) {} });
    DS.schemas = DS.schemas || {};
    for (const id of dsIds) {
      if (DS.schemas[id]) continue;
      const r = await DS.post('getSchema', { datasourceId: id });
      if (r.json) { const m = {}; [...(r.json.schema.dimensions || []), ...(r.json.schema.metrics || [])].forEach(f => { m[f.name] = f; }); DS.schemas[id] = m; }
    }
    const allFields = Object.assign({}, ...Object.values(DS.schemas));
    // Blends: output fields (outputName) point to concepts of the blend's input queries, which carry the display
    // name, the format and, for blend-level calculated fields, the formula. Keep both, with the input's data source.
    const blendFields = {}, blendInner = {};
    ((((R.report || {}).resource || {}).dataViewResource || {}).entry || []).forEach(e => {
      const b = e.value && e.value.blockDatasource;
      if (!b) return;
      ((b.datasourceBlock && b.datasourceBlock.fields) || []).forEach(f => { if (f.field) blendFields[f.field.name] = f; });
      (function walk(o, dsId) {
        if (Array.isArray(o)) return o.forEach(x => walk(x, dsId));
        if (!o || typeof o !== 'object') return;
        const id = o.datasourceId || dsId;
        if (Array.isArray(o.concepts)) o.concepts.forEach(c => { const n = (c.id && c.id.name) || c.name; if (n) blendInner[n] = { c, datasourceId: id }; });
        Object.values(o).forEach(v => walk(v, id));
      })(b.blocks, null);
    });
    // Formula with internal field ids (t0._n123_ / _dvN suffix) rewritten with the fields' names
    const readable = (f, dsId) => f ? f.replace(/t\d+\.([A-Za-z0-9_]+)/g, (m, n) => {
      const dv = n.match(/^(.*)_dv(\d+)$/), base = dv ? dv[1] : n;
      const fld = (dsId && DS.schemas[dsId] && DS.schemas[dsId][base]) || allFields[base];
      return fld ? fld.displayName : m;
    }).replace(/\s+/g, ' ') : null;

    // 4. Components by id, with page and all concept definitions (fallback for concepts defined elsewhere)
    const comp = {}, allConcepts = {};
    const pageOf = {};
    R.page.forEach(p => p.page.componentConfig.forEach(c => { comp[c.componentId] = c; pageOf[c.componentId] = p.pageId; (c.conceptDefs || []).forEach(d => { allConcepts[d.name] = d; }); }));
    ((R.report || {}).componentConfig || []).forEach(c => { comp[c.componentId] = c; pageOf[c.componentId] = '(all pages)'; });

    const stats = { custom: 0, blend: 0, schema: 0, formula: 0, unresolved: 0 };
    const semanticOf = sc => {
      const s = (sc || [])[0] || {};
      if (s.semanticType === 12) return 'currency:' + ((s.currencyOptions || {}).currencyCode || '');
      if (s.semanticType === 14) return 'percent';
      if (s.semanticType === 2) return 'date';
      if (s.semanticType === 32 || s.semanticType === 16 || s.semanticType === 17) return 'text';
      if (s.semanticType === 41) return 'url';
      if (s.semanticType === 42) return 'link'; // HYPERLINK() field
      if (s.semanticType === 33) return 'number';
      if (s.semanticType === 28) return 'duration'; // seconds, shown as hh:mm:ss (104.15 -> 00:01:44)
      return s.semanticType != null ? 'type' + s.semanticType : '';
    };
    const describe = (c, qt, dataset) => {
      const d = ((c && c.conceptDefs) || []).find(x => x.name === qt || (x.id || '').endsWith('.' + qt)) || allConcepts[qt];
      const q = (d && d.queryTimeTransformation) || {}, dt = q.dataTransformation || {}, disp = q.displayTransformation || {};
      const sf = dt.sourceFieldName || '';
      const dv = sf.match(/^(.*)_dv(\d+)$/);
      const part = dv && dataset && dataset[+dv[2]];
      const srcField = (part && DS.schemas[part.datasourceId] && DS.schemas[part.datasourceId][dv[1]]) || allFields[dv ? dv[1] : sf];
      const bf = blendFields[sf];
      let label, how;
      if (disp.displayName) { label = disp.displayName; how = 'custom'; }
      else if (bf && bf.outputName) { label = bf.outputName; how = 'blend'; }
      else if (srcField) { label = srcField.displayName; how = 'schema'; }
      else if (dt.textFormula) { label = 'ƒ ' + readable(dt.textFormula, part && part.datasourceId).slice(0, 60); how = 'formula'; }
      else { label = sf || qt; how = 'unresolved'; }
      stats[how]++;
      const af = d && d.resultTransformation ? d.resultTransformation.analyticalFunction : 0;
      // Format: the component's own setting > the blend input concept > that concept's source field > the field
      const inner = bf && blendInner[((bf.queryTimeTransformation || {}).dataTransformation || {}).sourceFieldName];
      const iq = (inner && inner.c.queryTimeTransformation) || {}, idt = iq.dataTransformation || {};
      const innerSrc = inner && DS.schemas[inner.datasourceId] && DS.schemas[inner.datasourceId][idt.sourceFieldName];
      let format = semanticOf((disp.outputSemanticInfo || {}).semanticConfig)
        || (inner ? semanticOf(((iq.displayTransformation || {}).outputSemanticInfo || {}).semanticConfig) : '')
        || (innerSrc ? semanticOf((innerSrc.semanticInfo || {}).semanticConfig) : '')
        || (srcField ? semanticOf((srcField.semanticInfo || {}).semanticConfig) : '');
      if (af === 1) format = 'percent'; // percent of total, already computed by the backend
      const formula = dt.textFormula ? readable(dt.textFormula, part && part.datasourceId) : (idt.textFormula ? readable(idt.textFormula, inner.datasourceId) : null);
      return { label, format: format || 'number', formula };
    };

    // 5. Titles: explicit chart title > text in same group > text inside > nearest text above; plus section heading
    const titles = {};
    R.page.forEach(p => {
      const cs = p.page.componentConfig.concat((R.report || {}).componentConfig || []);
      const box = c => { const a = ((c.attributeConfig || {}).componentAttribute) || {}; return { l: a.left || 0, t: a.top || 0, w: a.width || 0, h: a.height || 0 }; };
      const texts = cs.filter(c => c.type === 'simple-description' && !(c.conceptDefs || []).length)
        .map(c => ({ id: c.componentId, b: box(c), text: plain((((c.propertyConfig || {}).componentProperty || {}).descriptionProperty || {}).text) }))
        .filter(t => t.text);
      const groupOf = {};
      (p.page.groupConfig || []).forEach(g => (g.componentId || []).forEach(id => { groupOf[id] = g.groupId; }));
      p.page.componentConfig.filter(c => (c.conceptDefs || []).length && !/description|image|shape/.test(c.type)).forEach(c => {
        const b = box(c);
        const ov = t => Math.max(0, Math.min(b.l + b.w, t.b.l + t.b.w) - Math.max(b.l, t.b.l)) / Math.max(1, Math.min(b.w, t.b.w));
        const explicit = (JSON.stringify(c.propertyConfig || {}).match(/"chartTitleText":"([^"]*)"/) || [])[1];
        const same = texts.filter(t => groupOf[t.id] && groupOf[t.id] === groupOf[c.componentId]);
        const inside = texts.filter(t => t.b.t >= b.t - 5 && t.b.t + t.b.h <= b.t + b.h + 5 && t.b.l >= b.l - 5 && t.b.l + t.b.w <= b.l + b.w + 5);
        const above = texts.filter(t => ov(t) >= 0.4 && t.b.t + t.b.h <= b.t + 15 && b.t - (t.b.t + t.b.h) <= 140).sort((x, y) => y.b.t - x.b.t);
        const section = texts.filter(t => t.b.w >= 300 && t.b.t + t.b.h <= b.t && b.t - t.b.t <= 700 && ov(t) >= 0.3).sort((x, y) => y.b.t - x.b.t)[0];
        let title = explicit, how = 'explicit';
        if (!title && same.length) { title = same.map(t => t.text).join(' — '); how = 'group'; }
        if (!title && inside.length) { title = inside.map(t => t.text).join(' — '); how = 'inside'; }
        if (!title && above.length) { title = above.slice(0, 2).reverse().map(t => t.text).join(' — '); how = 'above'; }
        titles[c.componentId] = { title: title || '', titleSource: title ? how : 'none', section: section ? section.text : '', top: b.t, left: b.l };
      });
    });

    // 6. Data: one entry per component, main subset + comparison + totals
    const out = {};
    DS.cap.filter(c => c.path === 'batchedDataV2' && c.status === 200 && c.res).forEach(c => {
      let rq, rs;
      try { rq = JSON.parse(c.req); rs = unxssi(c.res); } catch (e) { return; }
      rq.dataRequest.forEach((dq, i) => {
        const ctx = dq.requestContext.reportContext, cid = ctx.componentId, cc = comp[cid];
        const resp = rs.dataResponse[i];
        if (!resp) return;
        if (resp.errorStatus) { result.warnings.push('Data error on component ' + cid); return; }
        // A response holds several subsets, told apart by viewTags: role "main" (the rows), compareIndex > 0
        // (comparison period), isTotals (summary row), isMin / isMax (one-row helpers used to scale bars and
        // heatmaps: never data to report). Only "main" fills rows/columns.
        const spec = dq.datasetSpec, start = ((spec.paginateInfo && spec.paginateInfo.startRow) || 1) - 1;
        const key = JSON.stringify([spec.queryFields, spec.filters, spec.dateRanges, spec.sortData]);
        // Periods queried (main, then comparison): any {startDate, endDate} pair found in dateRanges
        const periods = [];
        (function w(x) { if (Array.isArray(x)) return x.forEach(w); if (x && typeof x === 'object') { if (x.startDate && x.endDate) periods.push(x.startDate + '..' + x.endDate); Object.values(x).forEach(w); } })(spec.dateRanges);
        (resp.dataSubset || []).forEach(ds => {
          const td = ds.dataset && ds.dataset.tableDataset;
          if (!td) return;
          const tags = ds.viewTags || {};
          if (tags.isMin || tags.isMax) return;
          const cols = td.columnInfo.map(ci => describe(cc, ci.name, dq.datasetSpec.dataset));
          // A column holds its non-null values only; nullIndex lists the rows where the value is null
          const vals = td.column.map(col => {
            const k = Object.keys(col).find(x => /Column$/.test(x)), v = (k && col[k].values) || [], nulls = new Set(col.nullIndex || []);
            const full = []; let j = 0;
            for (let r = 0; r < v.length + nulls.size; r++) full.push(nulls.has(r) ? null : v[j++]);
            return full;
          });
          const names = td.columnInfo.map(ci => ci.name);
          const rows = (vals[0] || []).map((_, r) => vals.map(v => v[r]));
          const o = out[cid] = out[cid] || { componentId: cid, type: cc ? cc.type : ctx.displayType, page: pageOf[cid] || ctx.pageId, ...(titles[cid] || {}), columns: cols, colNames: names, rows: null, compareRows: null, totals: null, rowCount: null, rowsLoaded: 0 };
          if (!o.periods && periods.length) o.periods = [...new Set(periods)];
          const isTotals = ds.isTotals || tags.isTotals, isCompare = ds.isCompare || (tags.compareIndex || 0) > 0;
          // Totals carry the metric columns only: kept with their names, aligned on the columns at the end
          if (isTotals) { if (!isCompare && rows[0]) o.totalsRaw = { names, row: rows[0] }; return; }
          // Tables are paginated (paginateInfo.startRow / rowsCount): each page the viewer opens is a separate
          // request of the same query. Same query -> place the rows at their offset; another query (other sort,
          // other fields) -> start over, unless it carries fewer columns.
          const k = isCompare ? 'compareRows' : 'rows', kk = isCompare ? 'compareKey' : 'key';
          if (!o[k] || (o[kk] !== key && cols.length >= o.columns.length)) { o[k] = []; o[kk] = key; if (!isCompare) { o.columns = cols; o.colNames = names; } }
          if (o[kk] !== key) return;
          rows.forEach((r, j) => { o[k][start + j] = r; });
          if (!isCompare) { o.rowCount = td.totalCount != null ? td.totalCount : o.rows.length; o.rowsLoaded = o.rows.filter(Boolean).length; }
        });
      });
    });

    // 7. Assemble per page. A component shown on a page reached by DS.goto() may have no request of its own:
    //    the app reused a cached response of another component. Do NOT guess which one (same fields can carry
    //    different filters or comparison settings). Flag it; the fix is to load that page directly with HOOK.
    Object.values(out).forEach(o => {
      if (o.totalsRaw && o.colNames) o.totals = o.colNames.map(n => { const j = o.totalsRaw.names.indexOf(n); return j < 0 ? null : o.totalsRaw.row[j]; });
      delete o.totalsRaw;
    });
    navPages.forEach(np => {
      const p = R.page.find(x => x.pageId === np.id); if (!p) return;
      const loaded = DS.cap.some(c => c.page === np.id && c.path === 'batchedDataV2') || Object.values(out).some(o => o.page === np.id);
      const comps = p.page.componentConfig.filter(c => (c.conceptDefs || []).length && !/description|image|shape|filter/.test(c.type));
      const page = { id: np.id, name: np.name, hidden: np.hidden, loaded, components: [] };
      comps.forEach(c => {
        let o = out[c.componentId];
        if (o && !o.title && o.columns) {
          // Fallback: "<metrics> par <dimensions>", flagged as generated so it is never mistaken for the report's own title
          const dims = o.columns.filter(x => /text|date|url|link/.test(x.format)).map(x => x.label);
          const mets = o.columns.filter(x => !/text|date|url|link/.test(x.format)).map(x => x.label);
          o = Object.assign({}, o, { title: mets.join(', ') + (dims.length ? ' par ' + dims.join(', ') : ''), titleSource: 'generated' });
        }
        page.components.push(o || { componentId: c.componentId, type: c.type, ...(titles[c.componentId] || {}),
          missing: loaded ? 'no request of its own (cached or lazy): load this page directly with HOOK' : 'page not loaded' });
      });
      page.components.sort((a, b) => (a.top || 0) - (b.top || 0) || (a.left || 0) - (b.left || 0));
      result.pages.push(page);
    });
    result.labelResolution = stats;
    DS.result = result;
    return result;
  };

  // Formatting for display (approximation of the report's own formatting)
  DS.fmt = (v, format) => {
    if (v == null) return '';
    // HYPERLINK() values come as "label" + two no-break spaces + "url"
    if (format === 'link' && typeof v === 'string' && v.includes('\u00a0\u00a0')) { const [l, u] = v.split('\u00a0\u00a0'); return l + ' <' + u + '>'; }
    if (typeof v !== 'number') return String(v);
    if (format === 'percent') return (v * 100).toLocaleString('fr-FR', { maximumFractionDigits: 2 }) + ' %';
    if (format === 'duration') { const s = Math.floor(Math.abs(v)), p = n => String(n).padStart(2, '0'); return (v < 0 ? '-' : '') + p(Math.floor(s / 3600)) + ':' + p(Math.floor(s % 3600 / 60)) + ':' + p(s % 60); }
    if (format && format.startsWith('currency:')) return v.toLocaleString('fr-FR', { style: 'currency', currency: format.split(':')[1] || 'EUR' });
    return v.toLocaleString('fr-FR', { maximumFractionDigits: 2 });
  };
  DS.toMarkdown = (o, maxRows) => {
    if (!o || !o.rows) return '';
    const head = '| ' + o.columns.map(c => c.label).join(' | ') + ' |\n|' + o.columns.map(() => '---').join('|') + '|\n';
    const body = o.rows.slice(0, maxRows || 20).map(r => '| ' + r.map((v, i) => DS.fmt(v, o.columns[i].format)).join(' | ') + ' |').join('\n');
    return '**' + (o.title || o.type) + '**' + (o.section ? ' (' + o.section + ')' : '') + '\n\n' + head + body;
  };
  // Query strings can carry personal data (e-mail, ids, tokens): drop them from any text value before output.
  DS.safe = v => typeof v === 'string' ? v.replace(/(https?:\/\/[^\s?#]+|\/[^\s?#]*)[?#][^\s]*/g, '$1') : v;
  // Output channel: the JavaScript tool returns ~2 KB and blocks text that looks like query strings. Write one page's
  // result as text into an overlay <pre id="__ds_out"> and read it with the page-text tool. Remove it with DS.clear().
  // raw = true: unformatted values (numbers as sent by the backend, ratios as 0.52), for calculations and charts.
  DS.dump = (pageName, maxRows, raw) => {
    const p = (DS.result.pages || []).find(x => x.name === pageName || x.id === pageName);
    if (!p) return 'unknown page';
    const f = (v, format) => !raw ? DS.fmt(v, format) : v == null ? '' : (format === 'link' ? DS.fmt(v, format) : String(v));
    const row = (r, o) => r.map((v, i) => DS.safe(f(v, o.columns[i].format))).join(' | ');
    const lines = ['# ' + DS.safe(DS.result.name) + ' — ' + p.name + (raw ? ' (raw values)' : '')];
    p.components.forEach(o => {
      if (o.missing) { lines.push('\n## ' + (o.title || o.type) + '\n(missing: ' + o.missing + ')'); return; }
      lines.push('\n## ' + DS.safe(o.title) + (o.titleSource === 'generated' ? ' [generated title]' : '') + (o.section ? ' — section: ' + DS.safe(o.section) : '') + ' [' + o.type + ', ' + o.rowCount + ' rows' + (o.rowsLoaded < o.rowCount ? ', ' + o.rowsLoaded + ' loaded' : '') + ']');
      if (o.periods) lines.push('period: ' + o.periods[0] + (o.periods.length > 1 ? ' — compared with ' + o.periods.slice(1).join(', ') : ''));
      lines.push(o.columns.map(c => c.label + ' (' + c.format + ')').join(' | '));
      // Calculated fields: the formula lets the reader check a label (a scorecard renamed by mistake, for instance)
      o.columns.filter(c => c.formula).forEach(c => lines.push('  ' + c.label + ' = ' + c.formula));
      (o.rows || []).filter(Boolean).slice(0, maxRows || 1000).forEach(r => lines.push(row(r, o)));
      if (o.totals) lines.push('totals: ' + row(o.totals, o));
      // Comparison rows came in the same order as the main rows, with the same dimension values (seen on tables): check
      // the dimension columns match before computing a change
      if (o.compareRows) { lines.push('compare:'); o.compareRows.filter(Boolean).slice(0, maxRows || 1000).forEach(r => lines.push(row(r, o))); }
    });
    return DS.show(lines.join('\n'));
  };
  // Visible full-screen overlay with role=article: the page-text tool reads it whole (a hidden element or an
  // aria-label is not read). DS.clear() removes it.
  DS.show = (text) => {
    let el = document.getElementById('__ds_out');
    if (!el) { el = document.createElement('pre'); el.id = '__ds_out'; el.setAttribute('role', 'article'); el.style.cssText = 'position:fixed;inset:0;margin:0;padding:16px;background:#fff;color:#000;font:12px monospace;white-space:pre-wrap;overflow:auto;z-index:2147483647'; document.body.appendChild(el); }
    el.textContent = text;
    return text.length + ' chars written';
  };
  // One line per component with data: n° | type | title | columns | rows | period. To map deliverable slides to components.
  DS.list = () => DS.show(DS.result.pages.flatMap(p => p.components.filter(c => c.rows).map(c => [p.name, c.type, DS.safe(c.title) + (c.titleSource === 'generated' ? ' [generated]' : ''),
    c.columns.map(k => k.label).join(', '), c.rowsLoaded + '/' + c.rowCount + ' rows', (c.periods || []).join(' vs '), c.componentId].join(' | '))).map((l, i) => (i + 1) + '. ' + l).join('\n'));
  // Raw values of chosen components as JSON (between JSONSTART and JSONEND), to save as a file: pick = list of
  // componentIds or titles, or a filter function; none = all components with data.
  DS.json = (pick) => {
    const keep = c => !pick || (typeof pick === 'function' ? pick(c) : pick.includes(c.componentId) || pick.includes(c.title));
    const cs = DS.result.pages.flatMap(p => p.components.filter(c => c.rows && keep(c)).map(c => ({ page: p.name, componentId: c.componentId, type: c.type,
      title: DS.safe(c.title), titleSource: c.titleSource, section: DS.safe(c.section), periods: c.periods || null,
      columns: c.columns.map(k => ({ label: k.label, format: k.format, formula: k.formula })), rows: c.rows.filter(Boolean).map(r => r.map(DS.safe)),
      compare: c.compareRows ? c.compareRows.filter(Boolean).map(r => r.map(DS.safe)) : null, totals: c.totals || null, rowCount: c.rowCount, rowsLoaded: c.rowsLoaded })));
    DS.show('JSONSTART' + JSON.stringify({ report: DS.result.name, reportId: DS.result.reportId, components: cs }) + 'JSONEND');
    return cs.length + ' components';
  };
  DS.clear = () => { const el = document.getElementById('__ds_out'); if (el) el.remove(); return 'cleared'; };
  DS.summary = () => {
    const r = DS.result; if (!r) return 'run DS.extract() first';
    const comps = r.pages.flatMap(p => p.components);
    return {
      report: r.name, viewer: r.viewer, exportAllowed: r.exportAllowed,
      pages: r.pages.map(p => ({ name: p.name, hidden: p.hidden, loaded: p.loaded, components: p.components.length,
        withData: p.components.filter(c => c.rows).length, missing: p.components.filter(c => c.missing).length,
        titled: p.components.filter(c => c.title && c.titleSource !== 'generated').length,
        generatedTitles: p.components.filter(c => c.titleSource === 'generated').length })),
      totals: { components: comps.length, withData: comps.filter(c => c.rows).length, missing: comps.filter(c => c.missing).length },
      labelResolution: r.labelResolution, warnings: r.warnings
    };
  };
})();
