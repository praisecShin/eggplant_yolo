// 가짜 DriveApp·PropertiesService 등으로 Code.js의 dispatch()를 실행해 재배정을 확인
const fs = require('fs'), vm = require('vm');
let NOW = Date.parse('2026-11-06T02:00:00Z');          // KST 11:00 (주간)
class F { constructor(name, text, created) { this.name = name; this.text = text; this.created = created || NOW; this.trashed = false; }
  getName() { return this.name; } getBlob() { const t = this.text; return { getDataAsString: () => t }; }
  setContent(t) { this.text = t; } setTrashed(v) { this.trashed = v; } getDateCreated() { return new Date(this.created); } }
class D { constructor(name) { this.name = name; this.files = []; this.dirs = []; }
  live() { return this.files.filter((f) => !f.trashed); }
  getFoldersByName(n) { return it(this.dirs.filter((d) => d.name === n)); } createFolder(n) { const d = new D(n); this.dirs.push(d); return d; }
  getFilesByName(n) { return it(this.live().filter((f) => f.name === n)); } getFiles() { return it(this.live()); }
  createFile(n, t) { const f = new F(n, t); this.files.push(f); return f; }
  sub(p) { return p.split('/').reduce((d, x) => d.getFoldersByName(x).hasNext() ? d.getFoldersByName(x).next() : d.createFolder(x), this); }
  put(p, name, obj, created) { const f = new F(name, typeof obj === 'string' ? obj : JSON.stringify(obj), created); this.sub(p).files.push(f); return f; }
  get(p, name) { const d = this.sub(p); const x = d.live().find((f) => f.name === name); return x && JSON.parse(x.text); } }
function it(a) { let i = 0; return { hasNext: () => i < a.length, next: () => a[i++] }; }
const ROOT = new D('eggplant_yolo');
const props = { BASE_FOLDER_ID: 'root', CVAT_TOKEN: 'x' };
const RealDate = Date;
class FakeDate extends RealDate { constructor(...a) { super(...(a.length ? a : [NOW])); } static now() { return NOW; } }
const ctx = { console, JSON, Math, Object, Array, String, Number, Boolean, isNaN, Date: FakeDate,
  LockService: { getScriptLock: () => ({ tryLock: () => true, releaseLock: () => {} }) },
  PropertiesService: { getScriptProperties: () => ({ getProperty: (k) => props[k] || null }) },
  DriveApp: { getFolderById: () => ROOT },
  Utilities: { formatDate: (d, tz, f) => { const k = new RealDate(d.getTime() + 9 * 3600e3); return f === 'H' ? String(k.getUTCHours()) : k.toISOString().slice(0, 10); } },
  UrlFetchApp: { fetch: () => { throw new Error('외부 호출 안 함'); } }, ScriptApp: {} };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);
const ok = (c, m) => { if (!c) { console.log('❌', m); process.exitCode = 1; } else console.log('✅', m); };

const routing = { routes: { backup: 'kaggle_cpu', shape: 'colab', track: 'colab', train: 'colab', aa: 'colab', compare: 'colab' } };
ROOT.put('config', 'routing.json', routing);
const old = NOW - 30 * 60000, fresh = NOW - 2 * 60000;
// 1) pending + kaggle_gpu 배정 + 30분 지남 → colab으로 회수
ROOT.put('requests', 'REQ_a1__shape__pending.json', { id: 'a1', kind: 'shape', created: new RealDate(old).toISOString(), task_ids: [1] });
ROOT.put('requests/assign', 'ASSIGN_a1.json', { req_id: 'a1', kind: 'shape', route: 'kaggle_gpu', status: 'assigned', attempt: 1 });
// 2) 막 만든 요청(2분) — 배정이 달라도 아직 회수 안 함
ROOT.put('requests', 'REQ_a2__track__pending.json', { id: 'a2', kind: 'track', created: new RealDate(fresh).toISOString() });
ROOT.put('requests/assign', 'ASSIGN_a2.json', { req_id: 'a2', kind: 'track', route: 'kaggle_gpu', status: 'assigned' });
// 3) taken(진행 중) 요청 — 절대 손대지 않음
ROOT.put('requests', 'REQ_a3__train__taken.json', { id: 'a3', kind: 'train', created: new RealDate(old).toISOString() });
ROOT.put('requests/assign', 'ASSIGN_a3.json', { req_id: 'a3', kind: 'train', route: 'kaggle_gpu', status: 'assigned' });
// 4) 경로가 같은 요청 — 그대로
ROOT.put('requests', 'REQ_a4__backup__pending.json', { id: 'a4', kind: 'backup', created: new RealDate(old).toISOString() });
ROOT.put('requests/assign', 'ASSIGN_a4.json', { req_id: 'a4', kind: 'backup', route: 'kaggle_cpu', status: 'assigned', attempt: 1 });
// 5) AA앱 요청도 같은 규칙, 배정 없던 새 요청은 새로 배정
ROOT.put('relabel/requests', 'REQ_r1__shape__pending.json', { id: 'r1', kind: 'shape', created: new RealDate(old).toISOString() });
ROOT.put('relabel/requests', 'REQ_r2__track__pending.json', { id: 'r2', kind: 'track', created: new RealDate(old).toISOString() });
ROOT.put('requests/assign', 'ASSIGN_r2.json', { req_id: 'r2', kind: 'track', route: 'kaggle_gpu', status: 'assigned', attempt: 2 });
ROOT.put('jobs', 'gpu_queue.json', { items: [{ req_id: 'a1' }, { req_id: 'a3' }, { req_id: 'r2' }] });

const res = ctx.dispatch();
const A = (id) => ROOT.get('requests/assign', `ASSIGN_${id}.json`);
ok(A('a1').route === 'colab' && A('a1').previous_route === 'kaggle_gpu' && A('a1').attempt === 2 && A('a1').history.length === 1, 'a1: pending 30분 → colab으로 회수, 이력·시도 번호');
ok(ROOT.get('requests', 'REQ_a1__shape__pending.json').assigned_to === 'colab', 'a1: 요청 파일의 assigned_to도 colab');
ok(A('a2').route === 'kaggle_gpu', 'a2: 2분 된 요청은 아직 회수 안 함');
ok(A('a3').route === 'kaggle_gpu', 'a3: taken(진행 중)은 손대지 않음');
ok(A('a4').route === 'kaggle_cpu' && A('a4').attempt === 1 && !A('a4').history, 'a4: 경로 같으면 그대로');
ok(A('r1').route === 'colab' && A('r1').status === 'assigned', 'r1: 배정 없던 AA 요청은 새로 colab 배정');
ok(A('r2').route === 'colab' && A('r2').attempt === 3, 'r2: AA 요청도 회수');
const q = ROOT.get('jobs', 'gpu_queue.json').items.map((x) => x.req_id);
ok(JSON.stringify(q) === JSON.stringify(['a3']), 'GPU 대기열에서 a1·r2 빠지고 진행 중 a3는 남음');
const st = ROOT.get('status', 'dispatcher.json');
ok(st.reassigned.length === 2 && st.gpu_queue_removed === 2 && /^4\.31\./.test(st.version), 'dispatcher.json에 reassigned 2건 기록');
// 다시 돌려도 더 바뀌지 않음
NOW += 5 * 60000; ctx.dispatch();
ok(A('a1').attempt === 2 && ROOT.get('status', 'dispatcher.json').reassigned.length === 0, '두 번째 실행: 더 바꾸지 않음');
// 12분 뒤면 a2도 회수
NOW += 7 * 60000; ctx.dispatch();
ok(A('a2').route === 'colab', 'a2: 10분 지나면 회수');
console.log(process.exitCode ? '\n실패 있음' : '\n실패: 없음');
