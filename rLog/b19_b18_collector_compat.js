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

fresh();const {ctx}=makeCtx(false);
TASKS=[task(11,'eggplant_G6_261026_1_4_uld')];ctx.collect();NOW+=600000;
TASKS=[task(11,'eggplant_G6_261026_1_4_vf','2026-11-15T02:05:00Z')];FAIL_ONCE.push('REQ_');console.log('first',ctx.collect().auto);
NOW+=600000;TASKS=[task(11,'eggplant_G6_261026_1_4_vfdf','2026-11-15T02:15:00Z')];console.log('second',ctx.collect().auto);
console.log('requests',ROOT.sub('requests').live().map(f=>JSON.parse(f.text).tasks));
// Separate fixture: two events accumulate without a batch (before a snapshot commit).
fresh();const {ctx:c2}=makeCtx(false);const dir=ROOT.sub('status');
c2.queueHits_(dir,{export:[{id:11,name:'a_vf',updated:'1'},{id:11,name:'a_vfdf',updated:'2'}]});
console.log('same_task_flush',c2.flushAutoRequests_(c2.cfg_(),dir));console.log('same_task_payload',ROOT.sub('requests').live().map(f=>JSON.parse(f.text).tasks));
// Malformed but valid JSON pending file loses events silently.
fresh();const {ctx:c3}=makeCtx(false);const sd=ROOT.sub('status');sd.put('', 'auto_pending.json', {unexpected:'broken'});
console.log('broken_read',c3.readPending_(sd));c3.queueHits_(sd,{export:[{id:22,name:'x',updated:'2'}]});console.log('broken_overwritten',ROOT.get('status','auto_pending.json'));
// A successful create followed by ledger failure; search index does not yet show the file.
fresh();const {ctx:c4}=makeCtx(false);TASKS=[task(11,'eggplant_G6_261026_1_4_uld')];c4.collect();NOW+=600000;TASKS=[task(11,'eggplant_G6_261026_1_4_vf','2026-11-15T02:05:00Z')];FAIL_ONCE.push('auto_requests.json');console.log('ledger_fail',c4.collect().auto);
ROOT.sub('requests').searchFiles=()=>it([]);NOW+=600000;console.log('index_lag_retry',c4.collect().auto);console.log('physical_duplicate_names',ROOT.sub('requests').live().map(f=>f.name));

// Queue saved, snapshot write interrupted; another state transition before next round.
fresh();const {ctx:c5}=makeCtx(false);TASKS=[task(11,'eggplant_G6_261026_1_4_uld')];c5.collect();NOW+=600000;
TASKS=[task(11,'eggplant_G6_261026_1_4_vf','2026-11-15T02:05:00Z')];FAIL_ONCE.push('cvat_tasks.json');try{c5.collect();}catch(e){console.log('snapshot_failure',e.message);}
NOW+=600000;TASKS=[task(11,'eggplant_G6_261026_1_4_vfdf','2026-11-15T02:15:00Z')];console.log('two_events_real',c5.collect().auto);console.log('two_events_payload',ROOT.sub('requests').live().map(f=>JSON.parse(f.text).tasks));
// Array maps are accepted, then JSON serialization discards string-keyed new events.
fresh();const {ctx:c6}=makeCtx(false);TASKS=[task(11,'eggplant_G6_261026_1_4_uld')];c6.collect();ROOT.put('status','auto_pending.json',{events:[],batches:{}});NOW+=600000;
TASKS=[task(11,'eggplant_G6_261026_1_4_vf','2026-11-15T02:05:00Z')];console.log('array_corruption',c6.collect().auto,'requests',ROOT.sub('requests').live().length,'pending',ROOT.get('status','auto_pending.json'));
