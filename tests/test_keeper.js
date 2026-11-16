// Keeper.gs 시험 — 판정 함수(keeperDecide_)와 가짜 Drive에서의 keeper() 한 회. 실제 Drive·Kaggle에 접속하지 않음.
// 실행: node tests/test_keeper.js apps_script/G_keeper/Keeper.gs
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
const D_ = (st) => {
  const x = Object.assign({ now: NOW, grant: null, arbiter: null, asks: [], workers: [], pendingIds: [], signals: [],
    signalDone: [], wakeDone: {}, auto: {}, people: PEOPLE, collectorAt: null, alerts: [], mailed: [] }, st);
  if (x.holds === undefined) x.holds = (((x.arbiter || {}).wake || {}).holds || []).map((id) => ({ id, active: true, until: null }));   // 보류는 arb/holds/에서 직접 읽음
  return ctx.keeperDecide_(x);
};
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
ROOT.put('arb', 'ARBITER.json', { wake: { holds: [] } });
ROOT.put('arb/holds', 'stop__p__1.json', { stop_id: 'stop__p__1', active: true, until: null });
ROOT.put('jobs/signals', 'wake__M1__2.json', { release_stop: 'stop__p__1' }, 'a0@x');
ctx.keeper();
const rel = ROOT.sub('jobs/signals').files.find((f) => f.name.startsWith('release__keeper__'));
ok(rel && JSON.parse(rel.text).origin_signal === 'wake__M1__2' && rel.owner === 'g@x' && fetches.length === 1,
  "keeper(): 관리자의 '보류 해제하고 깨우기' → G 소유 해제 신호(원래 신호 연결) + 깨우기");
ok(ROOT.get('jobs/wake_done', 'wake__M1__2.json').release_stop === 'stop__p__1', 'keeper(): 해제할 정지 번호를 깨우기 기록에 남김');

// ══ b11 회귀 (Q4·Q5·Q6·Q8·Q9)
NOW = Date.parse('2026-11-14T02:00:00Z');
const hold = (id, until, active) => ({ id, active: active !== false, until: until === undefined ? null : until });
// Q4: 보류는 arb/holds/를 직접 읽고, 기한은 Keeper가 따지고, 못 읽으면 깨우지 않음
d = D_({ holds: [hold('stop__p__1')], arbiter: { wake: { holds: [] } } });
ok(!d.wake, '심판 요약에 없어도 arb/holds/에 살아 있는 보류가 있으면 깨우지 않음 (Q4)');
d = D_({ holds: [hold('stop__p__1', sec(NOW) - 10)] });
ok(d.wake && d.wake.reason === 'daytime_keepalive', '기한이 지난 보류는 Keeper가 직접 풀린 것으로 봄 (영영 막지 않음)');
d = D_({ holds: [hold('stop__p__1', null, false)] });
ok(!!d.wake, '해제된 보류는 막지 않음');
d = D_({ holds: null });
ok(!d.wake && d.mails.some((m) => m.key === 'hold_unknown'), "보류 기록을 못 읽으면 '보류 없음'이 아니라 '모름' — 깨우지 않고 알림");
d = D_({ arbiterUnreadable: true });
ok(!d.wake, '회차 기록(ARBITER.json)이 깨져 있으면 깨우지 않음');
d = D_({ signals: [sig('stop__p__5', 'a0@x')], signalDone: [] });
ok(!d.wake, '아직 처리되지 않은 정지 신호가 있으면 깨우지 않음 (새 정지를 놓치지 않음)');
d = D_({ signals: [sig('stop__p__5', 'a0@x')], signalDone: ['stop__p__5'], holds: [] });
ok(!!d.wake, '처리가 끝났고 보류가 없으면 깨움');
r = R({ signals: [sig('wake__M1__1', 'a0@x')], holds: null });
ok(!r.wake && !r.rej, '보류를 모르는 동안 깨우기 신호는 거절하지 않고 미룸');
r = R({ signals: [sig('wake__M1__1', 'a0@x', { release_stop: 'stop__p__5' }), sig('stop__p__5', 'a0@x')], holds: [] });
ok(r.wake && r.rel[0].stop_id === 'stop__p__5', '처리 전 정지 신호도 관리자가 번호를 맞춰 해제하고 깨울 수 있음');
// Q5: 다시 시도할 때도 권한·보류를 다시 확인
const pushedAt = (extra) => ({ 'wake__M2__1': Object.assign({ state: 'pushed', attempt: 1, at: sec(NOW) - 700 }, extra || {}) });
r = D_({ signals: [sig('wake__M2__1', 'm2@x', {}, 700000)], wakeDone: pushedAt(), auto: { at: sec(NOW) - 60 }, people: [PEOPLE[0], Object.assign({}, PEOPLE[1], { status: 'stopped' })] });
ok(!r.wake && r.wakeDone[0].obj.state === 'rejected' && r.wakeDone[0].obj.reason === 'stopped', '첫 시도 뒤 사용 중지된 사람 → 다시 시도하지 않음 (Q5)');
r = D_({ signals: [sig('wake__M2__1', 'm2@x', {}, 700000)], wakeDone: pushedAt(), auto: { at: sec(NOW) - 60 }, people: [PEOPLE[0], Object.assign({}, PEOPLE[1], { perms: ['request'] })] });
ok(!r.wake && r.wakeDone[0].obj.reason === 'no_wake_perm', '첫 시도 뒤 깨우기 권한이 없어진 사람 → 다시 시도하지 않음');
r = D_({ signals: [sig('wake__M2__1', 'm2@x', {}, 700000)], wakeDone: pushedAt(), auto: { at: sec(NOW) - 60 }, holds: [hold('stop__p__1')] });
ok(!r.wake && r.wakeDone[0].obj.reason === 'hold', '첫 시도 뒤 정지가 걸림 → 다시 시도하지 않음');
r = D_({ signals: [sig('wake__M2__1', 'm2@x', {}, 700000, 60000)], wakeDone: pushedAt(), auto: { at: sec(NOW) - 60 } });
ok(!r.wake && r.wakeDone[0].obj.reason === 'edited_after_create', '첫 시도 뒤 신호가 고쳐짐 → 다시 시도하지 않음');
r = D_({ signals: [sig('wake__M2__1', 'm2@x', {}, 700000)], wakeDone: pushedAt(), auto: { at: sec(NOW) - 60 } });
ok(r.wake && r.wake.attempt === 2, '조건이 그대로면 두 번째 시도');
// Q6: '해제하고 깨우기'가 해제 신호를 쓰기 전에 끊겨도 이어서 채움
const relRec = { 'wake__M1__2': { state: 'processing', attempt: 1, at: sec(NOW) - 60, release_stop: 'stop__p__1' } };
r = D_({ signals: [sig('wake__M1__2', 'a0@x', { release_stop: 'stop__p__1' }, 60000)], wakeDone: relRec, holds: [hold('stop__p__1')] });
ok(!r.wake && r.releases.length === 1 && r.releases[0].stop_id === 'stop__p__1', "기다리는 동안에도 빠진 해제 신호를 채움 (Q6)");
r = D_({ signals: [sig('wake__M1__2', 'a0@x', { release_stop: 'stop__p__1' }, 60000)], wakeDone: relRec, holds: [hold('stop__p__1')], workers: [master('MS7')] });
ok(r.releases.length === 1 && r.wakeDone[0].obj.state === 'done', "마스터가 켜져 '끝남'으로 적을 때도 해제 신호를 함께 냄");
r = D_({ signals: [sig('wake__M1__2', 'a0@x', { release_stop: 'stop__p__1' }, 60000)], wakeDone: relRec, holds: [hold('stop__p__1', null, false)], workers: [master('MS7')] });
ok(r.releases.length === 0 && r.wakeDone[0].obj.state === 'done', '보류가 이미 풀렸으면 해제 신호를 다시 내지 않고 끝냄');
fresh();
ROOT.put('arb/holds', 'stop__p__1.json', { stop_id: 'stop__p__1', active: true, until: null });
ROOT.put('jobs/signals', 'wake__M1__2.json', { release_stop: 'stop__p__1' }, 'a0@x');
ROOT.put('jobs/wake_done', 'wake__M1__2.json', { state: 'processing', attempt: 1, at: sec(NOW) - 30, release_stop: 'stop__p__1' });   // 해제 신호를 쓰기 전에 끊김
ROOT.put('jobs/wake_done', 'auto.json', { at: sec(NOW) - 30 });
ctx.keeper();
let rels = ROOT.sub('jobs/signals').files.filter((f) => f.name.startsWith('release__keeper__'));
ok(rels.length === 1 && fetches.length === 0, 'keeper(): 끊긴 뒤 다음 실행에서 해제 신호를 채움 (기동은 다시 하지 않고 기다림)');
const before = rels[0].updated; NOW += 60000; ctx.keeper(); NOW -= 60000;
rels = ROOT.sub('jobs/signals').files.filter((f) => f.name.startsWith('release__keeper__'));
ok(rels.length === 1 && rels[0].updated === before, 'keeper(): 이미 있는 해제 신호는 다시 쓰지 않음');
fresh();
ROOT.put('arb/holds', 'stop__p__1.json', '[1, 2]');
ROOT.put('jobs/signals', 'wake__M1__1.json', {}, 'a0@x');
ctx.keeper();
ok(fetches.length === 0 && !ROOT.sub('jobs/wake_done').files.some((f) => f.name === 'wake__M1__1.json'), 'keeper(): 보류 파일이 깨져 있으면 깨우지 않고 신호도 미룸');
fresh();
ROOT.put('workers', 'bad.json', '["x"]'); ROOT.put('jobs/arbiter_ask', 'bad.json', '"x"'); ROOT.put('arb', 'ARBITER.json', '[]');
res = ctx.keeper();
ok(res.ok && fetches.length === 0, 'keeper(): 형태가 틀린 파일이 있어도 죽지 않음 (깨진 회차 기록 → 깨우지 않음)');
// Q8: 밤에는 정해진 종류의 신호만 깨움
NOW = NIGHT;
d = D_({ signals: [sig('approve_night__p__1', '')] });
ok(!d.wake, '밤: 야간 승인 신호만으로는 깨우지 않음 (Q8)');
d = D_({ signals: [sig('unknown_kind__p__1', '')] });
ok(!d.wake, '밤: 모르는 종류의 신호로는 깨우지 않음');
['confirm_choice', 'cancel', 'release', 'run_choice', 'adopt_choice'].forEach((k) => {
  d = D_({ signals: [sig(k + '__p__1', '')] });
  ok(d.wake && d.wake.reason === 'control_signal', '밤: ' + k + ' 신호 → 깨움');
});
// Q9: 밤에 할 수 있는 일이 있거나 새 실행기가 나타나면 깨움
const nightArb = (w) => ({ session: 'MS1', epoch: 1, at: sec(NIGHT) - 3600, wake: Object.assign({ next_wake_at: null, observed_requests: [], workers: [] }, w) });
d = D_({ arbiter: nightArb({ runnable: 2 }) });
ok(d.wake && d.wake.reason === 'runnable', '밤: 심판이 남긴 "할 수 있는 일"이 있으면 깨움 (Q9)');
d = D_({ arbiter: Object.assign(nightArb({ runnable: 2 }), { at: sec(NOW) - 6 * 3600 }) });
ok(!d.wake, '밤: 낮에 계산한 요약은 쓰지 않음 (낮의 "할 수 있음"은 밤에 다름)');
d = D_({ arbiter: nightArb({ runnable: 0, executor_wait: 1, workers: ['G1'] }), workers: [{ session: 'G2', caps: ['gpu'], hb: sec(NOW) }] });
ok(d.wake && d.wake.reason === 'new_executor', '밤: 실행기를 기다리는 일이 있고 새 실행기가 나타나면 깨움');
d = D_({ arbiter: nightArb({ runnable: 0, executor_wait: 1, workers: ['G1'] }), workers: [{ session: 'G1', caps: ['gpu'], hb: sec(NOW) }] });
ok(!d.wake, '밤: 심판이 이미 알던 실행기뿐이면 깨우지 않음');
d = D_({ arbiter: nightArb({ runnable: 0, executor_wait: 0 }), workers: [{ session: 'G2', caps: ['gpu'], hb: sec(NOW) }] });
ok(!d.wake, '밤: 기다리는 일이 없으면 새 실행기가 와도 깨우지 않음');
NOW = Date.parse('2026-11-14T02:00:00Z');
// 자동 깨우기 연속 실패
d = D_({ auto: { at: sec(NOW) - 700, fails: 2 } });
ok(d.wake && d.wake.fails === 3 && !d.mails.length, '자동 깨우기: 10분 간격으로 다시 시도 (3번째)');
d = D_({ auto: { at: sec(NOW) - 700, fails: 3 } });
ok(!d.wake, '3번 연속 실패 뒤에는 10분으로는 다시 시도하지 않음');
d = D_({ auto: { at: sec(NOW) - 1900, fails: 3 } });
ok(d.wake && d.mails.length === 1, '30분 뒤 다시 시도하면서 메일 한 번');
d = D_({ auto: { at: sec(NOW) - 1900, fails: 4 } });
ok(d.wake && !d.mails.length, '그 뒤로는 30분 간격, 메일은 되풀이하지 않음');
d = D_({ auto: { at: sec(NOW) - 100, fails: 4 }, grant: { epoch: 1, session: 'MS1', at: sec(NOW) - 900 }, arbiter: { session: 'MS1', epoch: 1, at: sec(NOW) - 10 }, workers: [master('MS1')] });
ok(d.autoReset === true, '마스터가 살아나면 실패 횟수를 되돌림');
// 회차가 멈춘 심판
d = D_({ grant: { epoch: 3, session: 'MS1', at: sec(NOW) - 900 }, arbiter: { session: 'MS1', epoch: 3, at: sec(NOW) - 400 },
  asks: [{ session: 'MS1', at: sec(NOW) - 5 }], workers: [master('MS1')] });
ok(!d.grant && d.mails.some((m) => /^stalled_/.test(m.key)) && d.wake, '회차가 멈춘 심판이 다시 신청해도 자격을 주지 않고 알림 — 새 마스터를 깨움');

// ══ b12 회귀 (R2·R3·R6)
// R2: 권한 없는 정지 신호가 깨우기를 막지 않음
d = D_({ signals: [sig('stop__bad__1', 'x@x')], holds: [] });
ok(d.wake && d.wake.reason === 'daytime_keepalive' && d.mails.some((m) => m.key === 'ignored_stop_stop__bad__1'), '미등록 계정의 정지 신호는 보류로 보지 않고 알림 (R2)');
d = D_({ signals: [sig('stop__p__1', 'm2@x')], holds: [] });
ok(!!d.wake, '정지 권한(release)이 없는 사람의 정지 신호는 보류로 보지 않음');
d = D_({ signals: [sig('stop__p__1', 'a0@x')], holds: [], people: [Object.assign({}, PEOPLE[0], { status: 'stopped' }), PEOPLE[1]] });
ok(!!d.wake, '사용 중지된 사람의 정지 신호는 보류로 보지 않음');
d = D_({ signals: [sig('stop__p__1', 'a0@x')], holds: [] });
ok(!d.wake, '관리자의 처리 전 정지 신호는 보류');
d = D_({ signals: [sig('stop__p__1', 'x@x')], holds: [], people: null });
ok(!d.wake, '사람 목록을 못 읽으면 정지 신호를 가려낼 수 없으므로 보류로 봄 (안전 쪽)');
d = D_({ signals: [sig('stop__p__1', 'a0@x')], signalDone: ['stop__p__1'], holds: [] });
ok(!!d.wake, '이미 처리(거절·완료)된 정지 신호는 보류로 되살리지 않음');
// R3: 깨우기 기록을 못 읽으면 덮어쓰지 않고 미룸
NOW = NIGHT;
r = D_({ signals: [sig('wake__M1__1', 'a0@x', {}, 700000)], wakeDoneUnknown: { 'wake__M1__1': true } });
ok(!r.wake && r.wakeDone.length === 0 && r.mails.some((m) => m.key === 'wake_done_unknown'), '깨우기 기록을 못 읽으면 만료 거절로 덮지 않고 미룸 (R3)');
r = D_({ signals: [sig('wake__M1__1', 'a0@x')], wakeDoneUnknown: { auto: true } });
ok(!r.wake && r.wakeDone.length === 0, '마지막 깨운 시각(auto)을 못 읽으면 깨우기를 미룸');
r = D_({ signals: [sig('wake__M1__1', 'a0@x', {}, 700000)], wakeDone: { 'wake__M1__1': { state: 'pushed', attempt: 1, at: sec(NOW) - 700 } }, auto: { at: sec(NOW) - 700 } });
ok(r.wake && r.wake.attempt === 2, '읽기가 회복되면 원래 기록에서 이어 감 (두 번째 시도)');
fresh();
ROOT.put('jobs/signals', 'wake__M1__1.json', {}, 'a0@x', NOW - 700000);
const wf = ROOT.put('jobs/wake_done', 'wake__M1__1.json', { state: 'processing', attempt: 1, at: sec(NOW) - 700 });
ROOT.put('jobs/wake_done', 'auto.json', { at: sec(NOW) - 700 });
const realBlob = wf.getBlob.bind(wf);
wf.getBlob = () => { throw new Error('일시 실패'); };
ctx.keeper();
wf.getBlob = realBlob;
ok(JSON.parse(wf.text).state === 'processing' && fetches.length === 0, 'keeper(): 기록 읽기가 잠깐 실패해도 그 기록을 덮지 않음');
ctx.keeper();
ok(fetches.length === 1 && JSON.parse(wf.text).attempt === 2, 'keeper(): 다음 실행에서 읽히면 이어서 두 번째 시도');
// R6: 낮에 남긴 '밤에도 할 수 있는 대기'는 밤의 새 실행기로 깨움
const dayArb = (w) => ({ session: 'MS1', epoch: 1, at: sec(Date.parse('2026-11-14T09:59:00Z')), wake: Object.assign({ next_wake_at: null, observed_requests: [], workers: [] }, w) });
d = D_({ arbiter: dayArb({ executor_wait: 1, executor_wait_night: 1 }), workers: [{ session: 'C9', caps: ['cpu'], hb: sec(NOW) }] });
ok(d.wake && d.wake.reason === 'new_executor', '18:59에 남긴 야간 승인 대기 + 19시 뒤 새 실행기 → 깨움 (R6)');
d = D_({ arbiter: dayArb({ executor_wait: 1, executor_wait_night: 0 }), workers: [{ session: 'C9', caps: ['cpu'], hb: sec(NOW) }] });
ok(!d.wake, '낮에만 할 수 있는 대기(야간 승인 없음)로는 밤에 깨우지 않음');
NOW = Date.parse('2026-11-14T02:00:00Z');
// b13: 사람 상태 해석을 심판과 맞춤
r = R({ signals: [sig('wake__M1__1', 'a0@x')], people: [Object.assign({}, PEOPLE[0], { status: '' })] });
ok(r.rej.reason === 'stopped' && !(r.wake && r.wake.id), "상태 칸이 빈 문자열이면 사용 중으로 보지 않음 (심판과 같음)");
r = R({ signals: [sig('wake__M1__1', 'a0@x')], people: [(() => { const p = Object.assign({}, PEOPLE[0]); delete p.status; return p; })()] });
ok(r.wake && r.wake.id === 'wake__M1__1', '상태 칸이 없으면 사용 중');
// ══ 0j: 보호 모드 알림 (메일 + ntfy 푸시)
const protArb = { session: 'MS1', epoch: 1, at: sec(NOW) - 10, protect: [{ path: 'arb/holds/stop__p__1.json', why: 'active' }], wake: { holds: [] } };
d = D_({ arbiter: protArb, grant: { epoch: 1, session: 'MS1', at: sec(NOW) - 900 } });
ok(d.mails.some((m) => /보호 모드/.test(m.subject) && /arb\/holds/.test(m.body)) && d.pushes.length === 1 && d.pushes[0].priority === 5 && d.protectKey,
  '보호 모드 들어감 → 메일(경로·이유) + 푸시(최고 우선순위) (0j)');
d = D_({ arbiter: protArb, grant: { epoch: 1, session: 'MS1', at: sec(NOW) - 900 }, mailed: [d.protectKey], prevProtectKey: d.protectKey });
ok(!d.mails.length && !d.pushes.length, '같은 보호 모드는 한 번만 알림');
d = D_({ arbiter: { session: 'MS1', epoch: 1, at: sec(NOW) - 10, protect: [], wake: { holds: [] } }, grant: { epoch: 1, session: 'MS1', at: sec(NOW) - 900 }, prevProtectKey: 'protect_x' });
ok(d.mails.some((m) => /끝남/.test(m.subject)) && d.pushes.length === 1 && !d.protectKey, '보호 모드가 풀리면 끝남 메일·푸시');
d = D_({ arbiter: { session: 'MS1', epoch: 1, at: sec(NOW) - 900, protect: [], wake: { holds: [] } }, prevProtectKey: 'protect_x' });
ok(!d.mails.some((m) => /끝남/.test(m.subject)) && d.protectKey === 'protect_x', '심판 기록이 오래됐으면 끝났다고 보지 않음');
fresh();
props.NTFY_TOPIC = 'secret-topic-xyz';
ROOT.put('arb', 'ARBITER.json', protArb);
ROOT.put('jobs', 'ARBITER_GRANT.json', { epoch: 1, session: 'MS1', at: sec(NOW) - 900 }, 'g@x');
ctx.keeper();
const ntfy = fetches.filter((f) => /ntfy\.sh/.test(f.url));
ok(ntfy.length === 1 && JSON.parse(ntfy[0].opt.payload).topic === 'secret-topic-xyz' && mails.some((m) => /보호 모드/.test(m.subject))
  && !JSON.stringify(ROOT).includes('secret-topic-xyz') && !mails.some((m) => m.body.includes('secret-topic-xyz')),
  'keeper(): ntfy로 푸시하고 메일도 보냄 — 주제 이름은 Drive·메일에 남지 않음');
ctx.keeper();
ok(fetches.filter((f) => /ntfy\.sh/.test(f.url)).length === 1, 'keeper(): 다음 실행에서 같은 보호 모드를 다시 푸시하지 않음');

// ══ 0k (b17)
// X4: 보호 → 정상 → 같은 손상으로 다시 보호: 다시 알림 (실제 keeper() 세 번)
fresh(); props.NTFY_TOPIC = 'tp';
ROOT.put('jobs', 'ARBITER_GRANT.json', { epoch: 1, session: 'MS1', at: sec(NOW) - 900 }, 'g@x');
ROOT.put('arb', 'ARBITER.json', protArb); ctx.keeper();
ROOT.put('arb', 'ARBITER.json', Object.assign({}, protArb, { protect: [], at: sec(NOW) - 5 })); ctx.keeper();
ROOT.put('arb', 'ARBITER.json', protArb); ctx.keeper();
const pushT = fetches.filter((f) => /ntfy/.test(f.url)).map((f) => JSON.parse(f.opt.payload).title);
ok(pushT.join('|') === '가지 앱 보호 모드|가지 앱 보호 모드 끝남|가지 앱 보호 모드' && mails.filter((m) => /⚠ 보호 모드/.test(m.subject)).length === 2,
  '보호 모드 진입 → 끝남 → 같은 손상으로 재진입: 재진입도 메일·푸시 (X4)');
ctx.keeper();
ok(fetches.filter((f) => /ntfy/.test(f.url)).length === 3, '같은 보호 구간 안에서는 다시 알리지 않음');
// 상태 알림(수집기 멈춤)도 풀렸다 다시 생기면 다시 알림
d = D_({ collectorAt: NOW - 1300e3 }); ok(d.mails.some((m) => m.key === 'collector_stale'), '수집기 20분 넘게 멈춤 → 알림');
d = D_({ collectorAt: NOW - 60e3, mailed: ['collector_stale'] }); ok(d.forget.indexOf('collector_stale') >= 0, '수집기가 다시 돌면 멈춤 알림 이력을 지움');
d = D_({ collectorAt: NOW - 1300e3, mailed: [] }); ok(d.mails.some((m) => m.key === 'collector_stale'), '다시 멈추면 다시 알림');
// X5: 수집기의 실제 생존 기록 형태로 멈춤 감시 (4.33.0k 맨 위 time, 4.33.0 last.time 둘 다)
const t20 = new RealDate(NOW - 1300e3).toISOString();
const hbNew = { version: '4.33.0k', time: t20, ok: true, last: { time: t20, ok: true }, last_ok: t20, runs: [] };
const hbOld = { version: '4.33.0', last: { time: t20, ok: true }, last_ok: t20, runs: [] };
let sample = null; try { sample = JSON.parse(fs.readFileSync('/tmp/collector_hb_sample.json', 'utf8')); } catch (e) { /* 수집기 시험을 먼저 돌리면 생김 */ }
ok(ctx.kpCollectorAt_(hbNew) === NOW - 1300e3 && ctx.kpCollectorAt_(hbOld) === NOW - 1300e3 && ctx.kpCollectorAt_({}) === null,
  '수집기 생존 시각: 맨 위 time과 옛 last.time 모두 읽음 (X5)');
if (sample) ok(typeof ctx.kpCollectorAt_(sample) === 'number', '실제 writeHeartbeat_ 산출물(수집기 시험이 남긴 것)에서 생존 시각을 읽음 (X5 연결)');
fresh(); ROOT.put('status', 'collector.json', hbNew); ctx.keeper();
ok(mails.some((m) => /수집기 멈춤/.test(m.subject)), 'keeper(): 수집기의 생존 기록이 20분 넘게 오래되면 멈춤 메일 (X5)');
// keeper.json을 못 읽으면: 상태 알림·심판 알림은 다시 보내지 않고, 그 사실을 한 번 알림
fresh();
ROOT.put('status', 'collector.json', hbNew); ctx.keeper();
const n0 = mails.length; ROOT.put('jobs', 'keeper.json', '{broken'); ctx.keeper();
ok(mails.length === n0 + 1 && /Keeper 기록을 읽지 못함/.test(mails[mails.length - 1].subject), 'keeper.json을 못 읽으면 보낸 알림을 다시 보내지 않고 그 사실만 알림');
// 메일·푸시 실패 → 다음 차례에 다시
fresh(); props.NTFY_TOPIC = 'tp';
ROOT.put('jobs', 'ARBITER_GRANT.json', { epoch: 1, session: 'MS1', at: sec(NOW) - 900 }, 'g@x');
ROOT.put('arb', 'ARBITER.json', protArb);
const realMail = ctx.MailApp.sendEmail, realFetch = ctx.UrlFetchApp.fetch;
ctx.MailApp.sendEmail = () => { throw new Error('quota'); };
ctx.UrlFetchApp.fetch = (url, opt) => { fetches.push({ url, opt }); return { getResponseCode: () => 503 }; };
ctx.keeper();
const kj = ROOT.get('jobs', 'keeper.json');
ok(kj.outbox.length === 2 && !JSON.stringify(kj).includes('"tp"') && !JSON.stringify(kj).includes('a0@x'), '메일·푸시가 실패하면 보낼 목록에 남김 — 주제 이름·메일 주소는 남기지 않음');
ctx.MailApp.sendEmail = realMail; ctx.UrlFetchApp.fetch = realFetch;
ctx.keeper();
ok(mails.some((m) => /⚠ 보호 모드/.test(m.subject)) && fetches.filter((f) => /ntfy/.test(f.url)).length === 2 && !ROOT.get('jobs', 'keeper.json').outbox.length,
  '다음 차례에 다시 보내 성공하면 목록에서 뺌 (같은 알림을 새로 만들지는 않음)');

// ══ 0l (b18)
// Y6: 보낼 목록이 넘쳐도 보호 모드 알림은 남김, 버린 일반 알림은 '보냄' 이력에서 지움
{
  const realMail = ctx.MailApp.sendEmail; ctx.MailApp.sendEmail = () => { throw new Error('quota'); };
  const items = [{ t: 'mail', key: 'protect_x', important: true, subject: 'p', body: '', tries: 0 }]
    .concat(Array.from({ length: 60 }, (_, i) => ({ t: 'mail', key: 'a' + i, subject: 's' + i, body: '', tries: 0 })));
  const o = ctx.kpSendOutbox_({ mail: 'a0@x' }, items);
  ok(o.left.length === 50 && o.left.some((x) => x.key === 'protect_x') && o.dropped.length === 11 && o.dropped[0].key === 'a0',
    '보낼 목록 상한(50)을 넘으면 오래된 일반 알림부터 버리고, 보호 모드 알림은 남김 (Y6)');
  const imp = ctx.kpSendOutbox_({ mail: 'a0@x' }, [{ t: 'mail', key: 'protect_y', important: true, subject: 'p', body: '', tries: 40 }]);
  ok(imp.left.length === 1, '보호 모드 알림은 30번 넘게 실패해도 버리지 않음');
  fresh();
  ROOT.put('jobs', 'keeper.json', { mailed: Array.from({ length: 60 }, (_, i) => 'a' + i),
    outbox: Array.from({ length: 60 }, (_, i) => ({ t: 'mail', key: 'a' + i, subject: 's' + i, body: '', tries: 0 })) });
  ctx.keeper();
  const kj = ROOT.get('jobs', 'keeper.json');
  ok(kj.outbox_dropped === 10 && !kj.mailed.includes('a0') && kj.mailed.includes('a59') && kj.outbox[0].key === 'outbox_overflow' && /10개/.test(kj.outbox[0].body),
    'keeper(): 버린 알림은 이력에서 지워 다시 만들 수 있게 하고, 버렸다는 요약 메일을 맨 앞에 넣음 (Y6)');
  ctx.MailApp.sendEmail = realMail;
  ctx.keeper();
  ok(mails.some((m) => /알림 일부를 보내지 못함/.test(m.subject)) && !ROOT.get('jobs', 'keeper.json').outbox.length, '메일이 회복되면 요약과 남은 알림을 보냄');
}
// 수집기가 실행할 때마다 실패하면(time은 새로워도 last_ok가 오래됨) 멈춤으로 알림
{
  const tNow = new RealDate(NOW - 60e3).toISOString(), tOld = new RealDate(NOW - 1300e3).toISOString();
  const failing = { version: '4.33.0l', time: tNow, ok: false, last: { time: tNow, ok: false, error: 'x' }, last_ok: tOld, runs: [] };
  ok(ctx.kpCollectorAt_(failing) === NOW - 1300e3, '수집기 생존 판단은 마지막 성공 시각(last_ok) 기준');
  fresh(); ROOT.put('status', 'collector.json', failing); ctx.keeper();
  ok(mails.some((m) => /수집기 멈춤/.test(m.subject)), 'keeper(): 수집기가 20분 넘게 계속 실패하면 멈춤 메일 (b18 보충)');
}
console.log(process.exitCode ? 'RESULT False' : 'RESULT True');
