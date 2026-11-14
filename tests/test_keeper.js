// Keeper.gs 시험 — 판정 함수(keeperDecide_)와 가짜 Drive에서의 keeper() 한 회. 실제 Drive·Kaggle에 접속하지 않음.
// 실행: node tests/test_keeper.js apps_script/Keeper.gs
const fs = require('fs'), vm = require('vm'), crypto = require('crypto');
let NOW = Date.parse('2026-11-14T02:00:00Z');                 // KST 11:00 (주간)
const NIGHT = Date.parse('2026-11-14T14:00:00Z');             // KST 23:00
class F { constructor(name, text, owner, created) { this.name = name; this.text = text; this.owner = owner; this.created = created || NOW; this.updated = this.created; }
  getName() { return this.name; } getBlob() { const t = this.text; return { getDataAsString: () => t }; }
  setContent(t) { this.text = t; this.updated = NOW; } getDateCreated() { return new Date(this.created); } getLastUpdated() { return new Date(this.updated); }
  getOwner() { const o = this.owner; return { getEmail: () => o }; } }
class D { constructor(name) { this.name = name; this.files = []; this.dirs = []; }
  getFoldersByName(n) { return it(this.dirs.filter((d) => d.name === n)); } createFolder(n) { const d = new D(n); this.dirs.push(d); return d; }
  getFilesByName(n) { return it(this.files.filter((f) => f.name === n)); } getFiles() { return it(this.files.slice()); }
  createFile(n, t) { const f = new F(n, t, 'g@x'); this.files.push(f); return f; }
  sub(p) { return p.split('/').reduce((d, x) => d.getFoldersByName(x).hasNext() ? d.getFoldersByName(x).next() : d.createFolder(x), this); }
  put(p, name, obj, owner, created) { const d = p ? this.sub(p) : this; const old = d.files.find((f) => f.name === name);
    const t = typeof obj === 'string' ? obj : JSON.stringify(obj); if (old) { old.text = t; return old; } const f = new F(name, t, owner || 'a0@x', created); d.files.push(f); return f; }
  get(p, name) { const x = this.sub(p).files.find((f) => f.name === name); return x && JSON.parse(x.text); } }
function it(a) { let i = 0; return { hasNext: () => i < a.length, next: () => a[i++] }; }
const RealDate = Date;
class FakeDate extends RealDate { constructor(...a) { super(...(a.length ? a : [NOW])); } static now() { return NOW; } }
let ROOT, ADMIN, props, fetches, mails;
function fresh() {
  ROOT = new D('eggplant_yolo'); ADMIN = new D('eggplant_admin'); fetches = []; mails = [];
  props = { BASE_FOLDER_ID: 'root', ADMIN_FOLDER_ID: 'admin', KAGGLE_USERNAME: 'ku', KAGGLE_KEY: 'kk', ALERT_EMAIL: 'a0@x' };
  ADMIN.put('config', 'people.json', PEOPLE);
  ADMIN.put('deploy', 'kernel-metadata.json', { id: 'ku/eggplant-cpu-master', title: 'm', code_file: 'master.ipynb' });
  ADMIN.put('deploy', 'master.ipynb', NB);
  props.MASTER_NB_SHA256 = crypto.createHash('sha256').update(NB).digest('hex');
}
const NB = '{"cells": []}';
const PEOPLE = [{ id: 'M1', account: 'a0@x', role: 'admin', perms: ['request', 'wake', 'release'], status: 'active' },
  { id: 'M2', account: 'm2@x', role: 'user', perms: ['request', 'wake'], status: 'active' }];
const ctx = { console, JSON, Math, Object, Array, String, Number, Boolean, isNaN, Date: FakeDate,
  LockService: { getScriptLock: () => ({ tryLock: () => true, releaseLock: () => {} }) },
  PropertiesService: { getScriptProperties: () => ({ getProperty: (k) => props[k] || null }) },
  DriveApp: { getFolderById: (id) => (id === 'admin' ? ADMIN : ROOT) },
  Utilities: { computeDigest: (alg, text) => Array.from(crypto.createHash('sha256').update(text).digest()).map((b) => (b > 127 ? b - 256 : b)),
    DigestAlgorithm: { SHA_256: 1 }, Charset: { UTF_8: 1 }, base64Encode: (s) => Buffer.from(s).toString('base64') },
  UrlFetchApp: { fetch: (url, opt) => { fetches.push({ url, opt }); return { getResponseCode: () => 200 }; } },
  MailApp: { sendEmail: (to, subject, body) => mails.push({ to, subject, body }) }, ScriptApp: {} };
vm.createContext(ctx);
const src = fs.readFileSync(process.argv[2], 'utf8');
vm.runInContext(src, ctx);
const ok = (c, m) => { if (!c) { console.log('❌', m); process.exitCode = 1; } else console.log('✅', m); };
const sec = (ms) => ms / 1000;
const D_ = (st) => ctx.keeperDecide_(Object.assign({ now: NOW, grant: null, arbiter: null, asks: [], workers: [], pendingIds: [], signals: [],
  signalDone: [], wakeDone: {}, auto: {}, people: PEOPLE, collectorAt: null, alerts: [], mailed: [] }, st));
const master = (s, ago) => ({ session: s, caps: ['master'], hb: sec(NOW) - (ago || 0) });
const sig = (id, owner, obj, ageMs, editedMs) => ({ id, kind: id.split('__')[0], owner, obj: obj || {}, created: NOW - (ageMs || 0), modified: NOW - (ageMs || 0) + (editedMs || 0) });

ok(!/function\s+do(Get|Post)\s*\(/.test(src), '웹앱 진입점(doGet/doPost) 없음');
ok(!/GITHUB|github/.test(src), 'GitHub 경로 없음');

// ── 자격
let d = D_({ asks: [{ session: 'MS1', at: sec(NOW) }], workers: [master('MS1')] });
ok(d.grant && d.grant.epoch === 1 && d.grant.session === 'MS1', '심판이 없고 살아 있는 마스터가 신청 → 자격(epoch 1)');
d = D_({ grant: { epoch: 3, session: 'MS1', at: sec(NOW) - 500 }, arbiter: { session: 'MS1', epoch: 3, at: sec(NOW) - 30 },
  asks: [{ session: 'MS2', at: sec(NOW) }], workers: [master('MS1'), master('MS2')] });
ok(!d.grant && d.alive, '심판 회차가 3분 안에 올랐으면 다른 마스터가 신청해도 자격을 바꾸지 않음');
d = D_({ grant: { epoch: 3, session: 'MS1', at: sec(NOW) - 900 }, arbiter: { session: 'MS1', epoch: 3, at: sec(NOW) - 400 },
  asks: [{ session: 'MS1', at: sec(NOW) - 900 }, { session: 'MS2', at: sec(NOW) - 20 }], workers: [master('MS1'), master('MS2')] });
ok(d.grant && d.grant.epoch === 4 && d.grant.session === 'MS2', '생존 신호는 오지만 회차가 멈춘 심판 → 새 마스터에 자격(epoch +1)');
d = D_({ grant: { epoch: 3, session: 'MS1', at: sec(NOW) - 900 }, arbiter: { session: 'MS1', epoch: 3, at: sec(NOW) - 400 },
  asks: [{ session: 'MS9', at: sec(NOW) }], workers: [master('MS9', 999)] });
ok(!d.grant, '신청한 마스터의 생존 신호가 끊겼으면 자격을 주지 않음');
d = D_({ grant: { epoch: 4, session: 'MS2', at: sec(NOW) - 60 }, arbiter: { session: 'MS1', epoch: 3, at: sec(NOW) - 400 },
  asks: [{ session: 'MS2', at: sec(NOW) - 70 }], workers: [master('MS2')] });
ok(!d.grant && d.alive, '방금 자격을 받은 마스터는 첫 회차까지 기다려 줌 (epoch를 또 올리지 않음)');

// ── 자동 깨우기
d = D_({});
ok(d.wake && d.wake.reason === 'daytime_keepalive', '낮에는 할 일이 없어도 깨움 (주간 상시)');
NOW = NIGHT;
d = D_({ arbiter: { wake: { runnable: 0, next_wake_at: null, observed_requests: [], holds: [] } }, pendingIds: ['r9'] });
ok(!d.wake, '밤: 새 요청만으로는 깨우지 않음 (아침에 처리)');
d = D_({ arbiter: { wake: { next_wake_at: sec(NOW) - 5, holds: [] } } });
ok(d.wake && d.wake.reason === 'next_wake_at', '밤: next_wake_at이 지났으면 깨움 (받는 중 재개)');
d = D_({ arbiter: { wake: { next_wake_at: sec(NOW) + 600, holds: [] } } });
ok(!d.wake, '밤: next_wake_at이 아직이면 깨우지 않음');
d = D_({ arbiter: { wake: { holds: [] } }, signals: [sig('cancel__p__1', '')], signalDone: [] });
ok(d.wake && d.wake.reason === 'control_signal', '밤: 처리 안 된 제어 신호가 있으면 깨움');
d = D_({ arbiter: { wake: { holds: [] } }, signals: [sig('cancel__p__1', '')], signalDone: ['cancel__p__1'] });
ok(!d.wake, '밤: 처리된 신호는 깨울 근거가 아님');
d = D_({ arbiter: { wake: { next_wake_at: sec(NOW) - 5, holds: [] } }, auto: { at: sec(NOW) - 100 } });
ok(!d.wake, '최근 10분 안에 깨웠으면 다시 깨우지 않음');
NOW = Date.parse('2026-11-14T02:00:00Z');
d = D_({ arbiter: { wake: { holds: ['stop__p__1'] } }, signals: [sig('release__p__2', '')] });
ok(!d.wake, '정지 보류 중: 낮이어도, 해제 신호가 있어도 자동으로 깨우지 않음');
d = D_({ workers: [master('MS5')] });
ok(!d.wake, '마스터가 켜지는 중이면 깨우지 않음');

// ── 깨우기 신호 (2차 권한 확인)
const R = (st) => { const x = D_(st); return { wake: x.wake, rej: (x.wakeDone[0] || {}).obj, rel: x.releases }; };
NOW = NIGHT;
let r = R({ signals: [sig('wake__M1__1', 'a0@x')], arbiter: { wake: { holds: [] } } });
ok(r.wake && r.wake.reason === 'signal' && r.wake.id === 'wake__M1__1', '등록된 사람의 깨우기 신호 → 깨움');
r = R({ signals: [sig('wake__M1__1', 'x@x')], arbiter: { wake: { holds: [] } } });
ok(!r.wake && r.rej.reason === 'not_registered', '신호 이름에 M1이라 적어도 소유 계정이 미등록이면 거절');
r = R({ signals: [sig('wake__M1__1', 'a0@x')], people: null, arbiter: { wake: { holds: [] } } });
ok(!r.wake && r.rej.reason === 'people_unreadable', '사람 목록을 못 읽으면 거절');
r = R({ signals: [sig('wake__M1__1', 'a0@x', {}, 0, 60000)], arbiter: { wake: { holds: [] } } });
ok(!r.wake && r.rej.reason === 'edited_after_create', '만든 뒤 고친 신호는 거절');
r = R({ signals: [sig('wake__M1__1', 'a0@x', {}, 700000)], arbiter: { wake: { holds: [] } } });
ok(!r.wake && r.rej.reason === 'expired', '10분 넘은 신호는 거절');
r = R({ signals: [sig('wake__M1__1', 'a0@x')], grant: { epoch: 1, session: 'MS1', at: sec(NOW) - 900 }, arbiter: { session: 'MS1', epoch: 1, at: sec(NOW) - 10, wake: { holds: [] } }, workers: [master('MS1')] });
ok(!r.wake && r.rej.reason === 'already_alive', '심판이 살아 있으면 거절');
r = R({ signals: [sig('wake__M1__1', 'a0@x')], arbiter: { wake: { holds: ['stop__p__1'] } } });
ok(!r.wake && r.rej.reason === 'hold', '정지 보류 중 일반 깨우기 → 거절');
r = R({ signals: [sig('wake__M2__1', 'm2@x', { release_stop: 'stop__p__1' })], arbiter: { wake: { holds: ['stop__p__1'] } } });
ok(!r.wake && r.rej.reason === 'release_needs_admin', "'보류 해제하고 깨우기'는 관리자만");
r = R({ signals: [sig('wake__M1__1', 'a0@x', { release_stop: 'stop__p__9' })], arbiter: { wake: { holds: ['stop__p__1'] } } });
ok(!r.wake && r.rej.reason === 'stop_id_mismatch', '정지 ID가 지금 걸린 것과 다르면 거절');
r = R({ signals: [sig('wake__M1__1', 'a0@x', { release_stop: 'stop__p__1' })], arbiter: { wake: { holds: ['stop__p__1'] } } });
ok(r.wake && r.rel.length === 1 && r.rel[0].stop_id === 'stop__p__1' && r.rel[0].origin_signal === 'wake__M1__1',
  '관리자 + 정확한 정지 ID → 해제 신호(원래 신호 연결)와 깨우기');
// 중간 장애 뒤 이어 하기
r = D_({ signals: [sig('wake__M1__1', 'a0@x', {}, 60000)], wakeDone: { 'wake__M1__1': { state: 'pushed', attempt: 1, at: sec(NOW) - 60 } }, arbiter: { wake: { holds: [] } } });
ok(!r.wake && !r.wakeDone.length, "'기동 요청 보냄' 뒤 10분 안에는 다시 보내지 않고 기다림");
r = D_({ signals: [sig('wake__M1__1', 'a0@x', {}, 60000)], wakeDone: { 'wake__M1__1': { state: 'pushed', attempt: 1, at: sec(NOW) - 60 } }, workers: [master('MS7')], arbiter: { wake: { holds: [] } } });
ok(r.wakeDone[0] && r.wakeDone[0].obj.state === 'done', '마스터가 켜졌으면 완료로 적음');
r = D_({ signals: [sig('wake__M1__1', 'a0@x', {}, 700000)], wakeDone: { 'wake__M1__1': { state: 'pushed', attempt: 1, at: sec(NOW) - 700 } }, arbiter: { wake: { holds: [] } } });
ok(r.wake && r.wake.attempt === 2, '10분 뒤에도 안 켜졌으면 한 번만 다시 시도');
r = D_({ signals: [sig('wake__M1__1', 'a0@x', {}, 1400000)], wakeDone: { 'wake__M1__1': { state: 'pushed', attempt: 2, at: sec(NOW) - 700 } }, arbiter: { wake: { holds: [] } } });
ok(!r.wake && r.wakeDone[0].obj.state === 'failed' && r.mails.length === 1, '두 번째도 실패하면 실패로 적고 메일');

// ── 감시 메일
r = D_({ collectorAt: NOW - 1500000, arbiter: { wake: { holds: [] } } });
ok(r.mails.some((m) => m.key === 'collector_stale'), '수집기가 20분 넘게 멈추면 메일');
r = D_({ collectorAt: NOW - 1500000, mailed: ['collector_stale'], arbiter: { wake: { holds: [] } } });
ok(!r.mails.length, '같은 알림은 다시 보내지 않음');
r = D_({ alerts: [{ id: 'a1', obj: { kind: 'duplicate_session' } }, { id: 'a2', obj: { kind: 'stale_report' } }], arbiter: { wake: { holds: [] } } });
ok(r.mails.length === 1 && /duplicate_session/.test(r.mails[0].subject), '심판 알림은 메일로 (흔한 것은 제외)');

// ── 가짜 Drive에서 keeper() 한 회
fresh();
ROOT.put('jobs/arbiter_ask', 'MS1.json', { session: 'MS1', at: sec(NOW) });
ROOT.put('workers', 'MS1__fp.json', master('MS1'));
let res = ctx.keeper();
const g = ROOT.sub('jobs').files.find((f) => f.name === 'ARBITER_GRANT.json');
ok(JSON.parse(g.text).session === 'MS1' && g.owner === 'g@x', 'keeper(): 자격 파일을 G 소유로 만듦');
ok(ROOT.get('jobs', 'keeper.json').version && res.alive === true && fetches.length === 0, 'keeper(): 자기 생존 신호를 남기고, 마스터가 있으면 깨우지 않음');
fresh();
ROOT.put('arb', 'ARBITER.json', { wake: { holds: [] } });
ROOT.put('jobs/signals', 'wake__M1__1.json', {}, 'a0@x');
res = ctx.keeper();
ok(fetches.length === 1 && /kaggle\.com\/api\/v1\/kernels\/push/.test(fetches[0].url) && JSON.parse(fetches[0].opt.payload).slug === 'ku/eggplant-cpu-master',
  'keeper(): 깨우기 신호 → deploy/의 마스터 노트북을 Kaggle로 올림');
ok(ROOT.get('jobs/wake_done', 'wake__M1__1.json').state === 'pushed' && ROOT.get('jobs/wake_done', 'auto.json').at, "keeper(): wake_done에 '처리 중' → '기동 요청 보냄'");
ok(!JSON.stringify(ROOT).includes('kk') && !mails.some((m) => m.body.includes('kk')), 'Kaggle 키가 Drive·메일에 남지 않음');
fresh();
ADMIN.put('deploy', 'master.ipynb', NB + ' ');                                  // 승인 뒤 노트북이 바뀜
ROOT.put('arb', 'ARBITER.json', { wake: { holds: [] } });
ROOT.put('jobs/signals', 'wake__M1__1.json', {}, 'a0@x');
ctx.keeper();
ok(fetches.length === 0 && ROOT.get('jobs/wake_done', 'wake__M1__1.json').why === 'notebook_hash_mismatch' && mails.length === 1,
  'keeper(): 노트북 해시가 등록값과 다르면 올리지 않고 알림');
fresh();
ROOT.put('arb', 'ARBITER.json', { wake: { holds: ['stop__p__1'] } });
ROOT.put('jobs/signals', 'wake__M1__2.json', { release_stop: 'stop__p__1' }, 'a0@x');
ctx.keeper();
const rel = ROOT.sub('jobs/signals').files.find((f) => f.name.startsWith('release__keeper__'));
ok(rel && JSON.parse(rel.text).origin_signal === 'wake__M1__2' && rel.owner === 'g@x' && fetches.length === 1,
  "keeper(): 관리자의 '보류 해제하고 깨우기' → G 소유 해제 신호(원래 신호 연결) + 깨우기");
console.log(process.exitCode ? 'RESULT False' : 'RESULT True');
