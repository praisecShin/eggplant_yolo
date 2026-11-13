// 가짜 DriveApp·PropertiesService 등으로 Code.js의 dispatch()를 실행해 재배정을 확인
const SLEPT = [], CODES = [];
const fs = require('fs'), vm = require('vm');
let NOW = Date.parse('2026-11-06T02:00:00Z');          // KST 11:00 (주간)
class F { constructor(name, text, created) { this.name = name; this.text = text; this.created = created || NOW; this.trashed = false; }
  getName() { return this.name; } getBlob() { const t = this.text; return { getDataAsString: () => t }; }
  setContent(t) { this.text = t; } setTrashed(v) { this.trashed = v; } getDateCreated() { return new Date(this.created); } }
class D { constructor(name) { this.name = name; this.files = []; this.dirs = []; }
  live() { return this.files.filter((f) => !f.trashed); }
  getFoldersByName(n) { return it(this.dirs.filter((d) => d.name === n)); } getFolders() { return it(this.dirs); } createFolder(n) { const d = new D(n); this.dirs.push(d); return d; }
  getFilesByName(n) { return it(this.live().filter((f) => f.name === n)); } getFiles() { return it(this.live()); }
  createFile(n, t) { const f = new F(n, t); this.files.push(f); return f; }
  sub(p) { return p.split('/').reduce((d, x) => d.getFoldersByName(x).hasNext() ? d.getFoldersByName(x).next() : d.createFolder(x), this); }
  put(p, name, obj, created) { const f = new F(name, typeof obj === 'string' ? obj : JSON.stringify(obj), created); this.sub(p).files.push(f); return f; }
  get(p, name) { const d = this.sub(p); const x = d.live().find((f) => f.name === name); return x && JSON.parse(x.text); } }
function it(a) { let i = 0; return { hasNext: () => i < a.length, next: () => a[i++] }; }
const ROOT = new D('eggplant_yolo');
const MYDRIVE = new D('MyDrive');
const props = { BASE_FOLDER_ID: 'root', CVAT_TOKEN: 'x' };
const RealDate = Date;
class FakeDate extends RealDate { constructor(...a) { super(...(a.length ? a : [NOW])); } static now() { return NOW; } }
const ctx = { console, JSON, Math, Object, Array, String, Number, Boolean, isNaN, Date: FakeDate,
  LockService: { getScriptLock: () => ({ tryLock: () => true, releaseLock: () => {} }) },
  PropertiesService: { getScriptProperties: () => ({ getProperty: (k) => props[k] || null }) },
  DriveApp: { getFolderById: () => ROOT, getRootFolder: () => MYDRIVE },
  Utilities: { sleep: (ms) => { SLEPT.push(ms); }, formatDate: (d, tz, f) => { const k = new RealDate(d.getTime() + 9 * 3600e3); if (f === 'yyyyMMdd_HHmmss') return k.toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15); return f === 'H' ? String(k.getUTCHours()) : k.toISOString().slice(0, 10); } },
  UrlFetchApp: { fetch: () => { const c = CODES.shift(); return { getResponseCode: () => c, getContentText: () => '{}' }; } }, ScriptApp: {} };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);
const ok = (c, m) => { if (!c) { console.log('❌', m); process.exitCode = 1; } else console.log('✅', m); };

const routing = { routes: { backup: 'kaggle_cpu', shape: 'colab', track: 'colab', train: 'colab', aa: 'colab', compare: 'colab' } };
ROOT.put('config', 'routing.json', { routes: { export: 'colab', backup: 'colab' } });
ROOT.put('videos/G6', 'eggplant_G6_261026_1_4.mp4', 'x');
const run = (code) => vm.runInContext(code, ctx);
const C = run('cfg_()'); C.org = 'horti';
const dir = run('statusDir_(cfg_())');
ctx.__C = C; ctx.__dir = dir;
const ch = [
  { kind: 'rename', task_id: 11, old_name: 'eggplant_G6_261026_1_4_uld', new_name: 'eggplant_G6_261026_1_4_AA', updated: 'u1' },
  { kind: 'new', task_id: 12, old_name: '', new_name: 'eggplant_G5_261026_2_1_AA', updated: 'u2' },
  { kind: 'rename', task_id: 13, old_name: 'eggplant_G5_261026_2_2_AA', new_name: 'eggplant_G5_261026_2_2_AA', updated: 'u3' },
  { kind: 'rename', task_id: 14, old_name: 'eggplant_G5_261026_2_3_uld', new_name: 'eggplant_G5_261026_2_3_vf', updated: 'u4' },
];
ctx.__ch = ch;
const r1 = run('autoOnAa_(__C, __dir, __ch)');
const reqs = ROOT.sub('requests').live().filter((f) => f.name.startsWith('REQ_'));
const ex = reqs.find((f) => f.name.includes('__export__pending')), bk = reqs.find((f) => f.name.includes('__backup__pending'));
const E = JSON.parse(ex.text), B = JSON.parse(bk.text);
ok(r1.new === 2 && reqs.length === 2, 'AA가 새로 된 2개만 (이미 AA·vf 제외) 요청 2개');
ok(JSON.stringify(E.task_ids) === '[11,12]' && E.params.format === 'CVAT for images 1.1' && E.params.images === false && E.params.mode === 'all' && E.params.org === 'horti', 'export: 2개, 라벨만, 조직');
ok(JSON.stringify(B.task_ids) === '[12]' && B.params.export_reviewed === false, 'backup: 영상 없는 12만');
ok(/^REQ_[0-9A-Za-z_.-]+?__export__pending\.json$/.test(ex.name) && E.status === 'pending' && E.by.includes('GAS'), '요청 파일 이름·형식이 LC와 같음');
const r2 = run('autoOnAa_(__C, __dir, __ch)');
ok(r2.new === 0 && ROOT.sub('requests').live().length === 2, '같은 TASK·같은 수정 시각은 다시 요청 안 함');
ROOT.put('config', 'routing.json', { auto_on_aa: false });
// routing 파일이 둘이면 첫 것을 읽으므로 기존 파일을 지움
ROOT.sub('config').files[0].trashed = true;
ok(run('autoOnAa_(__C, __dir, __ch)').off === true, 'auto_on_aa: false 면 끔');
// backfill
ROOT.sub('config').files[1].trashed = true;
ROOT.put('status', 'cvat_tasks.json', { tasks: { 11: { name: 'eggplant_G6_261026_1_4_AA', updated: 'u1' }, 21: { name: 'eggplant_G2_261029_1_9_AA', updated: 'u9' }, 22: { name: 'x_AA', updated: 'u8', gone: true }, 23: { name: 'eggplant_G2_261029_1_8_vf', updated: 'u7' } } });
const r3 = run('backfillAaNow(5)');
ok(r3.new === 1 && r3.requests.length === 2, 'backfill: 아직 안 한 21만 (11은 이미, 22 사라짐, 23 AA 아님)');
// api_ retry
CODES.push(503, 503, 200);
const a = run("api_(__C, '/api/x')");
ok(a.code === 200 && SLEPT.join(',') === '5000,15000', 'api_: 503 두 번 → 5초·15초 쉬고 성공');
CODES.push(401); SLEPT.length = 0;
ok(run("api_(__C, '/api/x')").code === 401 && SLEPT.length === 0, 'api_: 401은 다시 시도 안 함');
const RF = (rt, k, p) => run(`routeFor_(${JSON.stringify(rt)}, '${k}', ${JSON.stringify(p || {})})`);
ok(RF({ routes: { shape: 'kaggle_gpu' } }, 'shape') === 'colab' && RF({ gpu_worker_enabled: true, routes: { shape: 'kaggle_gpu' } }, 'shape') === 'kaggle_gpu', 'routeFor_: GPU 꺼져 있으면 kaggle_gpu → colab');
ok(RF({ routes: { upload: 'kaggle_cpu' } }, 'upload') === 'colab' && RF({ routes: {} }, 'export') === 'kaggle_cpu' && RF({ routes: {} }, 'cleanup') === 'colab', 'routeFor_: CPU 마스터가 안 하는 종류는 colab');
ok(RF({ routes: { train: 'kaggle_gpu' } }, 'train', { build_only: true }) === 'colab', 'routeFor_: build_only → colab (CPU 마스터 미구현)');

// v4.31.5: AA_r1 = AA · ULD 기록이 있으면 백업 요청 안 함
MYDRIVE.put('CVAT_UpLoader/registry/tasks', '32.json', { upload_as: 'images' });
const before = ROOT.sub('requests').live().length;
ctx.__ch2 = [
  { kind: 'rename', task_id: 31, old_name: 'eggplant_G6_261102_3_8_uld', new_name: 'eggplant_G6_261102_3_8_uld_AA_r1', updated: 'x1' },
  { kind: 'rename', task_id: 32, old_name: 'eggplant_G6_261102_3_9_uld', new_name: 'eggplant_G6_261102_3_9_uld_AA', updated: 'x2' },
  { kind: 'rename', task_id: 33, old_name: 'eggplant_G6_261102_3_7_uld_AA', new_name: 'eggplant_G6_261102_3_7_uld_AA_r2', updated: 'x3' },
];
const r5 = run('autoOnAa_(__C, __dir, __ch2)');
const nw = ROOT.sub('requests').live().slice(before).map((f) => JSON.parse(f.text));
const e5 = nw.find((x) => x.kind === 'export'), b5 = nw.find((x) => x.kind === 'backup');
ok(JSON.stringify(e5.task_ids) === '[31,32]', 'AA_r1도 AA로 감지 · AA→AA_r2는 새로 AA가 된 것이 아님');
ok(JSON.stringify(b5.task_ids) === '[31]', 'ULD 기록이 있는 32는 백업 요청 안 함 (clip이 원본)');
