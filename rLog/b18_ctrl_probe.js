// CTRL앱 시험 — 가짜 Google Drive 커넥터로 화면·신호 파일을 확인. 실행: npm i jsdom && node tests/test_ctrl_app.js apps/ctrl/index.html
const { JSDOM } = require("jsdom");
const fs = require('fs');
const html = fs.readFileSync(process.argv[2] || 'apps/ctrl/index.html', 'utf8');
const NOW = Date.now() / 1000;
const files = {};   // id -> {title, parent, mime, content}
let n = 0;
const mk = (parent, title, content, folder) => { const id = 'f' + (++n); files[id] = { id, title, parent, folder: !!folder, content, modifiedTime: new Date().toISOString() }; return id; };
const root = mk('', 'eggplant_yolo', null, true), adm = mk('', 'eggplant_admin', null, true);
const arb = mk(root, 'arb', null, true), jobs = mk(root, 'jobs', null, true), status = mk(root, 'status', null, true), workers = mk(root, 'workers', null, true);
const cfg = mk(adm, 'config', null, true), holds = mk(arb, 'holds', null, true), alerts = mk(arb, 'alerts', null, true), locks = mk(arb, 'locks', null, true);
const signals = mk(jobs, 'signals', null, true), wd = mk(jobs, 'wake_done', null, true), sdone = mk(arb, 'signal_done', null, true);
mk(arb, 'ARBITER.json', { epoch: 2, round: 40, session: 'kgl-1', at: NOW - 30, protect: [{ path: 'arb/holds/stop__M1__1.json', why: 'active' }], unknown: [],
  check: { needs_check: ['mgmt'], executor_wait: ['d1'], orphans: [] }, wake: { runnable: 1, busy: 2, gpu_needed: 0 } });
mk(jobs, 'ARBITER_GRANT.json', { epoch: 2, session: 'kgl-1' });
mk(jobs, 'keeper.json', { at: NOW - 40, version: '4.33.0j' });
mk(status, 'collector.json', { version: '4.33.0', last: { time: new Date().toISOString(), ok: true } });
mk(cfg, 'people.json', [{ id: 'M1', name: '재웅', account: 'a0@x', role: 'admin', perms: ['request', 'wake', 'release'], status: 'active' }]);
mk(workers, 'kgl-1__fp.json', { session: 'kgl-1', caps: ['master'], hb: NOW - 20, status: { gpu_status_unknown_since: NOW - 900, config: { rejected: null } } });
mk(workers, 'kgw-1__fp.json', { session: 'kgw-1', caps: ['cpu', 'agg'], hb: NOW - 10 });
mk(holds, 'stop__M1__1.json', { stop_id: 'stop__M1__1', active: true, until: null });
mk(alerts, 'a1.json', { kind: 'protect', path: 'arb/holds/stop__M1__1.json' });
mk(locks, 'mgmt.json', { state: 'needs_check', run: 'mgmt_x', rid: 'd1', stop_reported: true });
mk(signals, 'wake__M1__2026.json', {}); mk(wd, 'wake__M1__2026.json', { state: 'rejected', reason: 'hold' });
const created = [];
let FAIL = false;
const DL_FAIL = new Set(); let LIST_FAIL = null, DELAY = 0;
const mcp = { callTool: async (srv, tool, input) => {
  if (DELAY) await new Promise((r) => setTimeout(r, DELAY));
  if (tool === 'search_files') {
    const qy = input.query;
    if (LIST_FAIL && qy.includes(`parentId = '${LIST_FAIL}'`) && /mimeType != /.test(qy)) throw { message: 'fake list failure' }; let out = Object.values(files);
    const m1 = /parentId = '([^']+)'/.exec(qy); if (m1) out = out.filter((f) => f.parent === m1[1]); else out = out.filter((f) => !f.parent);
    const m2 = /title = '([^']+)'/.exec(qy); if (m2) out = out.filter((f) => f.title === m2[1]);
    if (/mimeType = /.test(qy)) out = out.filter((f) => f.folder); if (/mimeType != /.test(qy)) out = out.filter((f) => !f.folder);
    return { payload: { files: out.map((f) => ({ id: f.id, title: f.title, modifiedTime: f.modifiedTime })) } };
  }
  if (tool === 'download_file_content' && DL_FAIL.has(input.fileId)) throw { message: 'fake download failure' };
  if (tool === 'download_file_content') return { payload: { content: Buffer.from(JSON.stringify(files[input.fileId].content)).toString('base64') } };
  if (tool === 'create_file') { created.push(input); mk(input.parentId, input.title, JSON.parse(input.textContent)); return { payload: { id: 'new' } }; }
} };
const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, beforeParse(w) {
  w.claude = { use: async () => mcp }; w.HTMLDialogElement.prototype.showModal = function () { this.open = true; }; w.HTMLDialogElement.prototype.close = function () { this.open = false; };
  w.TextDecoder = TextDecoder; w.atob = (b) => Buffer.from(b, 'base64').toString('binary'); } });
const w = dom.window, d = w.document;
setTimeout(async()=>{
const ar=Object.values(files).find(f=>f.title==='ARBITER.json');ar.content.protect=[];ar.content.at=NOW-900;
d.querySelector('#reload').click();await new Promise(r=>setTimeout(r,150));
d.querySelector('[data-rel]').click();
const hf=Object.values(files).find(f=>f.parent===holds);DL_FAIL.add(hf.id);
d.querySelector('#reload').click();await new Promise(r=>setTimeout(r,150));
console.log('after_reload_hold_unknown',d.querySelector('#holds').textContent,'release_disabled',d.querySelector('[data-rel]')?.disabled,'modal_open',d.querySelector('#dlg').open);
d.querySelector('#dlg-ok').click();await new Promise(r=>setTimeout(r,100));console.log('sent_despite_unknown',created.map(x=>({title:x.title,body:JSON.parse(x.textContent)})));
process.exit(0);
},800);
