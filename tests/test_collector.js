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

fresh();
let { ctx, src } = makeCtx(false);
ok(!/function\s+do(Get|Post)\s*\(/.test(src), '웹앱 진입점(doGet/doPost) 없음');
['dispatch', 'dispatch_', 'wakeUpCpuMaster_', 'approveNightRequests', 'triggerGhDispatch_', 'wakeCpuMasterNow', 'stopCpuMasterNow',
  'stopGpuWorkerNow', 'resumeCpuMasterNow', 'installAllTriggers', 'checkCpuMasterHeartbeat_', 'readMasterHold_'].forEach((fn) =>
  ok(typeof ctx[fn] === 'undefined', `배정·깨우기 함수 없음: ${fn}`));
ok(!/GITHUB|github|gpu_queue|STOP_MASTER|STOP_GPU|dispatcher\.json|requests\/assign/.test(src.replace(/^ \*.*$/gm, '')),
  'GitHub·GPU 대기열·정지 파일·dispatcher·옛 배정 경로를 코드에서 쓰지 않음 (주석 제외)');

// 첫 실행: 스냅숏만
TASKS = [task(11, 'eggplant_G6_261026_1_4_uld'), task(12, 'eggplant_G5_261026_2_1_uld')];
let r = ctx.collect();
ok(r.ok && r.first_run && ROOT.get('status', 'cvat_tasks.json').count === 2 && ROOT.get('status', 'collector.json').version === '4.33.0l',
  '첫 실행: TASK 스냅숏과 생존 신호(collector.json, 판 4.33.0l)');
ok(FETCHES.every((f) => f.method === 'get'), 'CVAT에는 읽기(GET)만');

// 다음 실행 (11/12 규칙): _uld로 올라옴 → backup(원본 없을 때), 검토 단계로 바뀜 → export, _AA는 아무것도 안 함
ROOT.put('videos/G5', 'eggplant_G5_261026_2_2.mp4', 'x');
ULD.put('registry/tasks', '14.json', { upload_as: 'images' });
WRITES = [];
NOW += 600000;
TASKS = [task(11, 'eggplant_G6_261026_1_4_vf', '2026-11-15T02:05:00Z'), task(12, 'eggplant_G5_261026_2_1_AA', '2026-11-15T02:05:00Z'),
  task(13, 'eggplant_G2_261029_1_9_uld', '2026-11-15T02:06:00Z'), task(14, 'eggplant_G2_261029_1_8_uld', '2026-11-15T02:06:00Z'),
  task(15, 'eggplant_G5_261026_2_2_uld', '2026-11-15T02:06:00Z'), task(16, 'eggplant_G1_261029_1_1_uld', '2026-11-15T02:06:00Z', 9)];
r = ctx.collect();
let reqs = ROOT.sub('requests').live().filter((f) => f.name.startsWith('REQ_'));
const E = JSON.parse(reqs.find((f) => f.name.includes('__export__pending')).text);
const B = JSON.parse(reqs.find((f) => f.name.includes('__backup__pending')).text);
ok(JSON.stringify(E.tasks) === '["11"]' && E.params.format === 'CVAT for images 1.1' && E.params.images === false && E.params.auto === 'vf',
  'export: 검토 단계(vf)로 바뀐 11만 — _AA로 바뀐 12는 요청 안 함 (AA 감지는 그만둠)');
ok(JSON.stringify(B.tasks) === '["13"]' && JSON.stringify(B.task_ids) === '[13]' && B.params.auto === 'uld',
  'backup: 새로 _uld로 올라온 13만 — 14는 ULD 장부(clip이 원본), 15는 videos/에 영상, 16은 다른 프로젝트');
ok(r.auto.backup_skipped === 2 && r.auto.export === 1 && r.auto.backup === 1, '원본이 있어 건너뛴 백업 수를 기록');
ok(E.app === 'collector' && E.status === 'pending' && E.created && reqs.every((f) => /^REQ_[0-9A-Za-z_.-]+?__(export|backup)__pending\.json$/.test(f.name)),
  '요청 파일 이름·형식 (심판의 parse_req_name과 같음)');
ok(WRITES.every((p) => /^eggplant_yolo\/(status|requests)\//.test(p)), '쓰는 곳은 status/와 requests/뿐 — ' + [...new Set(WRITES.map((p) => p.split('/').slice(0, 2).join('/')))].join(', '));
ok(r.uld && r.uld.skipped === 'Uld.gs 없음', 'Uld.gs가 없으면 그 단계를 건너뜀 (실패로 보지 않음)');
ok(!JSON.stringify(ROOT).includes('tok-secret-123'), 'CVAT 토큰이 Drive에 남지 않음');
// 같은 수정 시각은 다시 요청하지 않음, vf → vfdf는 다시 export
NOW += 600000;
r = ctx.collect();
ok(ROOT.sub('requests').live().length === 2, '같은 TASK·같은 수정 시각은 다시 요청하지 않음');
NOW += 600000;
TASKS = [task(11, 'eggplant_G6_261026_1_4_vfdf', '2026-11-15T03:00:00Z')];
r = ctx.collect();
reqs = ROOT.sub('requests').live().filter((f) => f.name.includes('__export__'));
ok(reqs.length === 2 && JSON.parse(reqs[1].text).tasks[0] === '11', '검토 단계가 다시 바뀌면(vf → vfdf) 다시 export');
// 범위: AUTO_PROJECT_ID 없으면 자동 요청 없음, 이름 앞글자 제한
fresh(); delete props.AUTO_PROJECT_ID;
({ ctx } = makeCtx(false));
TASKS = [task(31, 'eggplant_G6_261026_1_4')]; ctx.collect(); NOW += 600000;
TASKS = [task(32, 'eggplant_G6_261026_1_5_uld', '2026-11-15T05:00:00Z')];
r = ctx.collect();
ok(r.auto && r.auto.off === 'AUTO_PROJECT_ID 없음' && !ROOT.sub('requests').live().length, 'AUTO_PROJECT_ID가 없으면 자동 요청을 하지 않음');
fresh(); props.AUTO_NAME_PREFIX = 'REH_';
({ ctx } = makeCtx(false));
TASKS = [task(41, 'eggplant_G6_261026_1_4')]; ctx.collect(); NOW += 600000;
TASKS = [task(42, 'REH_G6_261026_1_5_uld', '2026-11-15T06:00:00Z'), task(43, 'eggplant_G6_261026_1_6_uld', '2026-11-15T06:00:00Z')];
r = ctx.collect();
reqs = ROOT.sub('requests').live();
ok(reqs.length === 1 && JSON.parse(reqs[0].text).tasks.join() === '42', '예행 연습: AUTO_NAME_PREFIX(REH_)로 시작하는 TASK만 — eggplant_AA의 다른 TASK는 건드리지 않음');
// 기존분 채우기
fresh();
({ ctx } = makeCtx(false));
ROOT.put('status', 'cvat_tasks.json', { tasks: { 51: { name: 'eggplant_G1_261029_1_1_vf', state: 'vf', updated: 'u1', project_id: 7 },
  52: { name: 'eggplant_G1_261029_1_2_uld', state: 'uld', updated: 'u2', project_id: 7 }, 53: { name: 'x_vf', state: 'vf', updated: 'u3', project_id: 9 } } });
r = vm.runInContext('backfillVfNow(10)', ctx);
reqs = ROOT.sub('requests').live();
ok(reqs.length === 1 && JSON.parse(reqs[0].text).tasks.join() === '51', 'backfillVfNow: 이미 검토 단계인데 export를 안 한 TASK (범위 안)만');

// Uld.gs가 있으면 부름
fresh();
({ ctx } = makeCtx(true));
TASKS = [task(11, 'eggplant_G6_261026_1_4_uld')];
ctx.collect();
NOW += 600000;
TASKS = [task(11, 'eggplant_G6_261026_1_4_AA', '2026-11-15T03:05:00Z')];
r = ctx.collect();
ok(r.uld && r.uld.ran === true, 'Uld.gs(uldAfterCollect_)가 있으면 수집 뒤에 부름');

// 실제 Uld.gs와 함께: 함수가 맞물리고, ULD 장부(clips_registry.csv)의 TASK도 백업하지 않음
fresh();
({ ctx } = makeCtx('real'));
ULD.put('registry', 'clips_registry.csv', 'task_id,task_name_initial,src_name,src_bytes\n61,eggplant_G3_261029_1_1_uld,a.mp4,1\n');
TASKS = [task(60, 'eggplant_G3_261026_1_1')]; ctx.collect(); NOW += 600000;
TASKS = [task(61, 'eggplant_G3_261029_1_1_uld', '2026-11-15T07:00:00Z'), task(62, 'eggplant_G3_261029_1_2_uld', '2026-11-15T07:00:00Z')];
WRITES = [];
r = ctx.collect();
const bk = ROOT.sub('requests').live().filter((f) => f.name.includes('__backup__'));
ok(r.ok && r.uld && !r.uld.error && r.uld.version === '1.1' && typeof r.uld.dup_groups === 'number', '실제 Uld.gs가 수집기 함수로 돌아감 (오류 없음)');
ok(bk.length === 1 && JSON.parse(bk[0].text).tasks.join() === '62', 'ULD 장부(clips_registry.csv)에 있는 61은 백업하지 않음');
ok(WRITES.every((p) => /^eggplant_yolo\/(status|requests)\//.test(p) || /^CVAT_UpLoader\/registry\/sources\.json$/.test(p)),
  'Uld.gs까지 함께 써도 쓰는 곳은 status/·requests/와 ULD 원본 목록(sources.json)뿐');
const uldSrc = fs.readFileSync(process.argv[3] || 'apps_script/G_collector/Uld.gs', 'utf8');
ok(!/dispatch|wakeUp|GITHUB|gpu_queue|STOP_MASTER|requests\/assign/.test(uldSrc), 'Uld.gs는 배정·깨우기·옛 배정 경로를 쓰지 않음');

// ULD_ROOT_FOLDER_ID가 없으면 내 드라이브 최상위에서 찾음 (A0에서 시험할 때)
fresh();
delete props.ULD_ROOT_FOLDER_ID;
({ ctx } = makeCtx(false));
MYDRIVE.put('CVAT_UpLoader/registry/tasks', '21.json', {});
ok(JSON.stringify(Object.keys(vm.runInContext('uldTaskIds_(cfg_())', ctx))) === '["21"]', 'ULD_ROOT_FOLDER_ID가 없으면 예전처럼 내 드라이브에서 찾음');

// b17 X3: 자동 요청 만들기 실패 → 다음 차례에 다시 (보낼 목록)
const reqFiles = () => ROOT.sub('requests').live().filter((f) => f.name.startsWith('REQ_'));
fresh(); ({ ctx } = makeCtx(false));
TASKS = [task(11, 'eggplant_G6_261026_1_4_uld')]; ctx.collect(); NOW += 600000;
TASKS = [task(11, 'eggplant_G6_261026_1_4_vf', '2026-11-15T03:00:00Z')];
FAIL_ONCE.push('REQ_');
r = ctx.collect();
ok(r.ok && r.auto.error === 'fake Drive failure' && r.auto.pending === 1 && !reqFiles().length, '요청 파일 만들기 실패: 오류를 기록하고 보낼 목록에 1건 남김 (X3)');
NOW += 600000; r = ctx.collect();
ok(r.auto.export === 1 && r.auto.pending === 0 && reqFiles().length === 1 && JSON.parse(reqFiles()[0].text).tasks.join() === '11',
  '같은 TASK 목록으로 다음 수집 때 요청을 만듦 — 변화를 이미 기록했어도 잃지 않음 (X3)');
NOW += 600000; r = ctx.collect();
ok(reqFiles().length === 1 && (!r.auto.export) && r.auto.pending === 0, '만든 뒤에는 다시 만들지 않음');
// 요청 파일은 만들었는데 장부 저장이 실패 → 다음 차례에 같은 요청 ID라 중복 없음
fresh(); ({ ctx } = makeCtx(false));
TASKS = [task(11, 'eggplant_G6_261026_1_4_uld')]; ctx.collect(); NOW += 600000;
TASKS = [task(11, 'eggplant_G6_261026_1_4_vf', '2026-11-15T03:00:00Z')];
FAIL_ONCE.push('auto_requests.json');
r = ctx.collect();
ok(r.auto.error && reqFiles().length === 1 && r.auto.pending === 1, '요청 파일을 만든 뒤 장부 저장 실패: 목록에 남김 (X3)');
NOW += 600000; r = ctx.collect();
ok(reqFiles().length === 1 && r.auto.pending === 0 && r.auto.requests[0].existed === true && ROOT.get('status', 'auto_requests.json').items['export:11'],
  '다음 차례: 이미 있는 요청 파일을 다시 만들지 않고 장부만 마저 씀 (중복 없음, X3)');
// 요청 파일이 상태 이름으로 바뀌어 있어도 같은 요청으로 봄
fresh(); ({ ctx } = makeCtx(false));
TASKS = [task(11, 'eggplant_G6_261026_1_4_uld')]; ctx.collect(); NOW += 600000;
TASKS = [task(11, 'eggplant_G6_261026_1_4_vf', '2026-11-15T03:00:00Z')];
FAIL_ONCE.push('auto_requests.json'); ctx.collect();
reqFiles()[0].name = reqFiles()[0].name.replace('__pending', '__running');
NOW += 600000; r = ctx.collect();
ok(reqFiles().length === 1 && r.auto.pending === 0, '요청 파일 이름의 상태가 바뀌어 있어도 다시 만들지 않음 (X3)');
// 보낼 목록 저장이 실패하면 스냅숏을 바꾸지 않음 → 다음 차례에 같은 변화를 다시 봄
fresh(); ({ ctx } = makeCtx(false));
TASKS = [task(11, 'eggplant_G6_261026_1_4_uld')]; ctx.collect(); NOW += 600000;
TASKS = [task(11, 'eggplant_G6_261026_1_4_vf', '2026-11-15T03:00:00Z')];
FAIL_ONCE.push('auto_pending.json');
let threw = false; try { ctx.collect(); } catch (e) { threw = true; }
ok(threw && ROOT.get('status', 'cvat_tasks.json').tasks['11'].name.endsWith('_uld') && ROOT.get('status', 'collector.json').ok === false,
  '보낼 목록을 저장하지 못하면 실행 실패로 끝내고 스냅숏을 그대로 둠 (X3)');
NOW += 600000; r = ctx.collect();
ok(r.ok && r.auto.export === 1 && reqFiles().length === 1, '다음 차례에 같은 변화를 다시 보고 요청을 만듦 (X3)');

// b17 X5: 생존 기록 맨 위에 time·ok (Keeper가 읽는 칸)
const hb = ROOT.get('status', 'collector.json');
ok(typeof hb.time === 'string' && hb.time === hb.last.time && hb.ok === true, 'collector.json 맨 위에 time·ok (Keeper 멈춤 감시와 같은 칸, X5)');
fs.writeFileSync('/tmp/collector_hb_sample.json', JSON.stringify(hb));

// ══ b18 (0l)
const setup2 = () => { fresh(); ({ ctx } = makeCtx(false)); TASKS = [task(11, 'eggplant_G6_261026_1_4_uld')]; ctx.collect(); NOW += 600000; };
// Y2: 보낼 목록의 형태가 틀리면 수집 실패, 스냅숏 그대로, 사건을 잃지 않음
for (const [desc, bad] of [['events가 배열', { events: [], batches: {} }], ['batches 없음', { events: {} }], ['맨 위가 배열', []],
  ['사건 키가 내용과 다름', { events: { 'export:11:x': { kind: 'export', id: 11, name: 'a', updated: 'y' } }, batches: {} }],
  ['묶음이 없는 사건을 가리킴', { events: {}, batches: { b1: { kind: 'export', keys: ['export:9:z'] } } }]]) {
  setup2();
  ROOT.put('status', 'auto_pending.json', bad);
  TASKS = [task(11, 'eggplant_G6_261026_1_4_vf', '2026-11-15T03:00:00Z')];
  let th = null; try { ctx.collect(); } catch (e) { th = String(e.message); }
  ok(th && /auto_pending\.json 형태가 틀림/.test(th) && ROOT.get('status', 'cvat_tasks.json').tasks['11'].name.endsWith('_uld') && !reqFiles().length,
    `보낼 목록 형태 오류(${desc}) → 수집 실패, 스냅숏 그대로, 요청 없음 (Y2)`);
  ROOT.sub('status').files = ROOT.sub('status').files.filter((f) => f.name !== 'auto_pending.json');   // 관리자가 고침(지움)
  NOW += 600000; r = ctx.collect();
  ok(r.ok && r.auto.export === 1 && reqFiles().length === 1, `고친 뒤 다음 수집에서 같은 변화를 다시 보고 요청 (${desc})`);
}
// Y3: 같은 TASK의 사건 둘(_vf, _vfdf) → 요청 하나, TASK 한 번(최종 상태)
setup2();
TASKS = [task(11, 'eggplant_G6_261026_1_4_vf', '2026-11-15T03:00:00Z')];
FAIL_ONCE.push('cvat_tasks.json');
try { ctx.collect(); } catch (e) { /* 스냅숏 쓰기 실패 */ }
ok(Object.keys(ROOT.get('status', 'auto_pending.json').events).length === 1, '스냅숏 쓰기 실패: 사건은 목록에 남음');
NOW += 600000; TASKS = [task(11, 'eggplant_G6_261026_1_4_vfdf', '2026-11-15T03:10:00Z')];
r = ctx.collect();
const Y3 = reqFiles().map((f) => JSON.parse(f.text));
ok(Y3.length === 1 && JSON.stringify(Y3[0].tasks) === '["11"]' && Y3[0].task_names[0].endsWith('_vfdf') && r.auto.export === 1 && r.auto.requests[0].merged === 1,
  '같은 TASK의 사건 둘 → 요청 하나에 TASK 한 번, 최신 이름(_vfdf)으로 (최종 상태 export, Y3)');
const L3 = ROOT.get('status', 'auto_requests.json').items['export:11'];
ok(L3.merged === 2 && L3.updated === '2026-11-15T03:10:00Z' && r.auto.pending === 0, '장부에 두 사건을 합쳤다고 남김');
// Y4: 만든 뒤 장부 실패 + 검색 지연 → 파일 ID로 이미 만든 것을 앎 (중복 없음)
setup2();
TASKS = [task(11, 'eggplant_G6_261026_1_4_vf', '2026-11-15T03:00:00Z')];
FAIL_ONCE.push('auto_requests.json'); ctx.collect();
SEARCH_LAG = true; NOW += 600000; r = ctx.collect(); SEARCH_LAG = false;
ok(reqFiles().length === 1 && r.auto.pending === 0 && r.auto.requests[0].existed, '장부 실패 뒤 검색이 늦어도 저장한 파일 ID로 다시 만들지 않음 (Y4)');
// 파일 ID도 못 남기고 검색도 늦음 → 10분은 기다림, 그 뒤 검색이 되면 다시 만들지 않음
setup2();
TASKS = [task(11, 'eggplant_G6_261026_1_4_vf', '2026-11-15T03:00:00Z')];
// 사건 넣기(1)·묶기(2)·시도 기록(3)은 성공, 파일 ID 저장(4)만 실패시킴
let pendWrites = 0;
const statusDir = ROOT.sub('status'); const realCreate = statusDir.createFile.bind(statusDir);
const wrapF = (f) => { if (f && f.name === 'auto_pending.json' && !f.__w) { f.__w = true; const o = f.setContent.bind(f); f.setContent = (t) => { pendWrites++; if (pendWrites === 4) throw new Error('fake'); o(t); }; } return f; };
statusDir.createFile = (n, t) => { const f = realCreate(n, t); if (n === 'auto_pending.json') pendWrites++; return wrapF(f); };
statusDir.files.forEach(wrapF);
FAIL_ONCE.push('auto_requests.json');
try { ctx.collect(); } catch (e) { /* */ }
const pj = ROOT.get('status', 'auto_pending.json'), b0 = Object.values(pj.batches)[0];
ok(reqFiles().length === 1 && b0 && b0.attempt_at && !b0.file_id, '시도 기록은 남고 파일 ID 저장은 실패한 상태를 만듦');
SEARCH_LAG = true; NOW += 300000; r = ctx.collect();
ok(reqFiles().length === 1 && r.auto.waiting === 1 && r.auto.pending === 1, '검색이 비어도 시도 뒤 10분 안에는 다시 만들지 않고 기다림 (Y4)');
SEARCH_LAG = false; NOW += 400000; r = ctx.collect();
ok(reqFiles().length === 1 && r.auto.pending === 0 && r.auto.requests[0].existed, '검색이 되면 있는 파일을 찾아 장부만 마저 씀 — 중복 없음 (Y4)');

// 심판의 요청 이름 규칙과 맞는지 (Python arbiter.parse_req_name과 같은 정규식)
ok(/^REQ_([0-9A-Za-z_.-]+?)__([a-z0-9_]+)__pending\.json$/.test('REQ_20261115_110000_ga1x__export__pending.json'), '요청 이름 규칙');
console.log(process.exitCode ? 'RESULT False' : 'RESULT True');
