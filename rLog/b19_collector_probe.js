// Collector.gs (v4.33 수집기) 시험 — 가짜 Drive·CVAT에서 collect()를 실제로 돌림. 실제 서비스에 접속하지 않음.
// 실행: node tests/test_collector.js apps_script/G_collector/Collector.gs [apps_script/G_collector/Uld.gs]
const fs = require('fs'), vm = require('vm');
let NOW = Date.parse('2026-11-15T02:00:00Z');
class F { constructor(name, text, owner) { this.name = name; this.text = text; this.owner = owner || 'g@x'; this.trashed = false; }
  getName() { return this.name; } getId() { return this.id || (this.id = 'id' + Math.random().toString(36).slice(2, 9)); } getBlob() { const t = this.text; return { getDataAsString: () => t }; }
  setContent(t) { failIf(this.name); this.text = t; WRITES.push(this.path); } setTrashed(v) { this.trashed = v; } }
class D { constructor(name, path) { this.name = name; this.path = path || name; this.files = []; this.dirs = []; }
  live() { return this.files.filter((f) => !f.trashed); }
  getFoldersByName(n) { return it(this.dirs.filter((d) => d.name === n)); } getFolders() { return it(this.dirs); }
  createFolder(n) { const d = new D(n, this.path + '/' + n); this.dirs.push(d); return d; }
  getFilesByName(n) { return it(this.live().filter((f) => f.name === n)); } getFiles() { return it(this.live()); }
  searchFiles(qy) { if (SEARCH_LAG) return it([]); const m = /title contains '([^']+)'/.exec(qy); return it(this.live().filter((f) => !m || f.name.includes(m[1]))); }
  createFile(n, t) { failIf(n); const f = new F(n, t); f.path = this.path + '/' + n; this.files.push(f); WRITES.push(f.path); return f; }
  sub(p) { return p.split('/').reduce((d, x) => d.getFoldersByName(x).hasNext() ? d.getFoldersByName(x).next() : d.createFolder(x), this); }
  put(p, name, obj) { const d = this.sub(p); const f = new F(name, typeof obj === 'string' ? obj : JSON.stringify(obj)); f.path = d.path + '/' + name; d.files.push(f); return f; }
  get(p, name) { const x = this.sub(p).live().find((f) => f.name === name); return x && JSON.parse(x.text); } }
const FAIL_ONCE = []; let SEARCH_LAG = false;   // 이름이 이 글자로 시작하는 파일 쓰기를 한 번 실패시킴
function failIf(n) { const i = FAIL_ONCE.findIndex((x) => n.startsWith(x)); if (i >= 0) { FAIL_ONCE.splice(i, 1); throw new Error('fake Drive failure'); } }
function it(a) { let i = 0; return { hasNext: () => i < a.length, next: () => a[i++] }; }
let ROOT, ULD, SRC, MYDRIVE, WRITES, FETCHES, TASKS, props;
function fresh() {
  ROOT = new D('eggplant_yolo'); ULD = new D('CVAT_UpLoader'); SRC = new D('GoPro_RAW'); MYDRIVE = new D('MyDrive'); WRITES = []; FETCHES = [];
  props = { BASE_FOLDER_ID: 'root', CVAT_TOKEN: 'tok-secret-123', CVAT_ORG: 'horti', AUTO_PROJECT_ID: '7', ULD_ROOT_FOLDER_ID: 'uld', ULD_SOURCE_FOLDER_ID: 'src' };
  TASKS = [];
}
const RealDate = Date;
class FakeDate extends RealDate { constructor(...a) { super(...(a.length ? a : [NOW])); } static now() { return NOW; } }
function makeCtx(withUld) {
  const ctx = { console: { log: () => {} }, JSON, Math, Object, Array, String, Number, Boolean, isNaN, Date: FakeDate, encodeURIComponent,
    LockService: { getScriptLock: () => ({ tryLock: () => true, releaseLock: () => {} }) },
    PropertiesService: { getScriptProperties: () => ({ getProperty: (k) => props[k] || null }) },
    DriveApp: { getFolderById: (id) => (id === 'uld' ? ULD : id === 'src' ? SRC : ROOT), getRootFolder: () => MYDRIVE, getFoldersByName: () => it([]) },
    MailApp: { sendEmail: () => {} },
    Utilities: { sleep: () => {}, parseCsv: (t) => t.trim().split('\n').map((l) => l.split(',')),
      formatDate: (d) => new RealDate(d.getTime() + 9 * 3600e3).toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15) },
    UrlFetchApp: { fetch: (url, opt) => {
      FETCHES.push({ url, method: (opt && opt.method) || 'get', auth: opt && opt.headers && opt.headers.Authorization });
      const body = /\/api\/tasks\?/.test(url) ? { count: TASKS.length, results: TASKS, next: null } : { status: 'finished' };
      return { getResponseCode: () => 200, getContentText: () => JSON.stringify(body) };
    } },
    ScriptApp: { getProjectTriggers: () => [], newTrigger: () => ({ timeBased: () => ({ everyMinutes: () => ({ create: () => {} }) }) }) } };
  vm.createContext(ctx);
  const src = fs.readFileSync(process.argv[2], 'utf8');
  vm.runInContext(src, ctx);
  if (withUld === 'real') vm.runInContext(fs.readFileSync(process.argv[3] || 'apps_script/G_collector/Uld.gs', 'utf8'), ctx);
  else if (withUld) vm.runInContext('function uldAfterCollect_(c, dir, snap, changes) { return { ran: true, n: changes.length }; }', ctx);
  return { ctx, src };
}
const ok = (c, m) => { if (!c) { console.log('❌', m); process.exitCode = 1; } else console.log('✅', m); };
const task = (id, name, upd, pid) => ({ id, name, updated_date: upd || '2026-11-15T01:00:00Z', status: 'annotation', size: 8, mode: 'annotation', project_id: pid || 7 });

fresh();const {ctx}=makeCtx(false);const sd=ROOT.sub('status');
const old={kind:'export',id:11,name:'eggplant_G6_261026_1_4_vf',updated:'2026-11-15T01:00:00Z',at:new Date(NOW).toISOString()};
ctx.queueHits_(sd,{export:[old]});FAIL_ONCE.push('REQ_');try{ctx.flushAutoRequests_(ctx.cfg_(),sd);}catch(e){console.log('first_create_failed',e.message);}
NOW+=60000;const newer={...old,name:'eggplant_G6_261026_1_4_vfdf',updated:'2026-11-15T02:00:00Z',at:new Date(NOW).toISOString()};ctx.queueHits_(sd,{export:[newer]});console.log('new_event_flush',ctx.flushAutoRequests_(ctx.cfg_(),sd));console.log('ledger_before',ROOT.get('status','auto_requests.json').items['export:11']);
NOW+=600000;console.log('old_retry',ctx.flushAutoRequests_(ctx.cfg_(),sd));console.log('ledger_after',ROOT.get('status','auto_requests.json').items['export:11']);
// Missing batch time is accepted and produces a request without its chronological timestamp.
fresh();const {ctx:c2}=makeCtx(false);const dir=ROOT.sub('status');const e={kind:'export',id:11,name:'x',updated:'2026-11-15T01:00:00Z',at:new Date(NOW).toISOString()};const key='export:11:'+e.updated;
dir.createFile('auto_pending.json',JSON.stringify({events:{[key]:e},batches:{REQOLD:{kind:'export',keys:[key]}}}));console.log('missing_at_validation',c2.pendingProblem_(ROOT.get('status','auto_pending.json')));console.log('missing_at_flush',c2.flushAutoRequests_(c2.cfg_(),dir));console.log('missing_at_body',ROOT.sub('requests').live().map(f=>JSON.parse(f.text)));
// Invalid attempt timestamp bypasses the wait although an earlier creation may have succeeded.
fresh();const {ctx:c3}=makeCtx(false);const st=ROOT.sub('status'),req=ROOT.sub('requests');const ev={kind:'export',id:11,name:'x',updated:'2026-11-15T01:00:00Z',at:new Date(NOW).toISOString()};const ek='export:11:'+ev.updated;
st.createFile('auto_pending.json',JSON.stringify({events:{[ek]:ev},batches:{probe:{kind:'export',keys:[ek],at:new Date(NOW).toISOString(),attempt_at:'broken'}}}));req.createFile('REQ_probe__export__pending.json','{}');SEARCH_LAG=true;console.log('invalid_attempt_problem',c3.pendingProblem_(ROOT.get('status','auto_pending.json')));console.log('invalid_attempt_flush',c3.flushAutoRequests_(c3.cfg_(),st),'physical_files',req.live().length);
