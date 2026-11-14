/**
 * Keeper.gs v4.33.0d — 심판 자격·마스터 깨우기·감시 (설계 8판 '계정 역할', 'CTRL앱', '감시와 재시작 점검')
 *
 * G 계정의 **별도 Apps Script 프로젝트**에 둡니다 (수집기와 다른 프로젝트). 1분 트리거로 keeper()를 실행합니다.
 * 웹앱으로 배포하지 않습니다 (doGet/doPost 없음).
 *
 * Script Properties (코드·Drive·로그·메일에 쓰지 않음):
 *   BASE_FOLDER_ID     공유 폴더(eggplant_yolo) ID
 *   ADMIN_FOLDER_ID    관리자 전용 폴더(eggplant_admin) ID — config/people.json·accounts.json, deploy/
 *   KAGGLE_USERNAME, KAGGLE_KEY   K Kaggle 계정의 API 키
 *   MASTER_NB_SHA256   deploy/의 마스터 노트북 해시 (다르면 깨우지 않고 알림)
 *   ALERT_EMAIL        알림 받을 주소 (A0)
 *
 * 하는 일 (keeper):
 *   1) 심판 자격: 살아 있는 심판이 없을 때만 jobs/ARBITER_GRANT.json (세션·epoch+1). 이 파일은 G 소유 — 믿음의 시작점
 *   2) 깨우기: 모든 깨우기는 '정지 보류 판정' 하나를 거침. 깨우기 신호는 Keeper가 받는 유일한 신호
 *   3) 감시: 심판·수집기 멈춤, 마스터가 남긴 알림 → 메일.  자기 생존 신호 jobs/keeper.json
 *
 * ⚠ Kaggle API로 노트북을 올리는 부분(kagglePush_)은 실제 계정으로 한 번 시험해야 합니다 (먼저 시험할 것).
 */
const KEEPER_VERSION = '4.33.0d';
const KP = {
  ALIVE_SEC: 180,          // 심판 회차·생존 신호 3분
  WAKE_GAP_SEC: 600,       // 깨우기 사이 최소 10분 / 깨우기 신호 최대 나이
  SIGNAL_EDIT_SEC: 5,      // 만든 뒤 고친 신호는 거절 (만든 시각과 수정 시각 차이)
  COLLECTOR_STALE_SEC: 1200,
  DAY_START: 8, DAY_END: 19,
};

function keeper() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return { ok: false, reason: 'busy' };
  try { return keeper_(); } finally { lock.releaseLock(); }
}

function installKeeperTrigger() {
  ScriptApp.getProjectTriggers().filter((t) => t.getHandlerFunction() === 'keeper').forEach((t) => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('keeper').timeBased().everyMinutes(1).create();
}

function kpCfg_() {
  const p = PropertiesService.getScriptProperties();
  return { base: p.getProperty('BASE_FOLDER_ID'), admin: p.getProperty('ADMIN_FOLDER_ID'),
    kUser: p.getProperty('KAGGLE_USERNAME'), kKey: p.getProperty('KAGGLE_KEY'),
    nbSha: p.getProperty('MASTER_NB_SHA256'), mail: p.getProperty('ALERT_EMAIL') };
}

// ─────────────────────────────────────────────────────────── 판정 (입출력 없음 — 시험 가능)
function kpIsDay_(nowMs) {
  const h = new Date(nowMs + 9 * 3600e3).getUTCHours();
  return h >= KP.DAY_START && h < KP.DAY_END;
}

/**
 * st: { now(ms), grant, arbiter, asks:[{session,at}], workers:[{session,hb,caps,stopping}], pendingIds:[],
 *       signals:[{id,kind,owner,created,modified,obj}], signalDone:[ids], wakeDone:{id:obj}, auto:{at},
 *       people:[…]|null, collectorAt(ms)|null, alerts:[{id,obj}], mailed:[ids] }
 * → { grant|null, wake:{reason,id}|null, releases:[{stop_id,origin_signal}], wakeDone:[{id,obj}], mails:[{subject,body}], alive }
 */
function keeperDecide_(st) {
  const now = st.now / 1000;
  const out = { grant: null, wake: null, releases: [], wakeDone: [], mails: [], alive: false };
  const g = st.grant || {};
  const arb = st.arbiter || {};
  const fresh = (w) => w && !w.stopping && now - Number(w.hb || 0) <= KP.ALIVE_SEC;
  const masters = (st.workers || []).filter((w) => (w.caps || []).indexOf('master') >= 0 && fresh(w));
  const holderHb = masters.some((w) => w.session === g.session);
  const roundFresh = arb.session === g.session && Number(arb.epoch) === Number(g.epoch) && now - Number(arb.at || 0) <= KP.ALIVE_SEC;
  const justGranted = holderHb && now - Number(g.at || 0) <= KP.ALIVE_SEC;
  out.alive = !!g.session && (roundFresh || justGranted);

  // 1) 자격: 살아 있는 심판이 없고, 살아 있는 마스터가 신청했을 때만
  if (!out.alive) {
    const cands = (st.asks || []).filter((a) => masters.some((w) => w.session === a.session))
      .sort((a, b) => Number(b.at || 0) - Number(a.at || 0));
    if (cands.length) {
      out.grant = { epoch: Number(g.epoch || 0) + 1, session: cands[0].session, at: now };
      out.alive = true;
    }
  }

  // 2) 깨우기 신호 (Keeper가 받는 유일한 신호) — 2차 권한 확인
  const wake = (arb.wake || {});
  const holds = wake.holds || [];
  const people = st.people;
  const byAcct = {};
  (people || []).forEach((p) => { byAcct[p.account] = p; });
  const masterStarting = masters.length > 0;
  const lastWake = Number((st.auto || {}).at || 0);
  let wakeSignal = null;
  (st.signals || []).filter((s) => s.kind === 'wake').sort((a, b) => a.created - b.created).forEach((s) => {
    const prev = (st.wakeDone || {})[s.id];
    if (prev && ['done', 'rejected', 'failed'].indexOf(prev.state) >= 0) return;
    const rej = (reason) => out.wakeDone.push({ id: s.id, obj: { state: 'rejected', reason: reason, at: now } });
    if (prev && (prev.state === 'processing' || prev.state === 'pushed')) {     // 중간 장애 뒤 이어 하기 (J8)
      if (out.alive || masterStarting) { out.wakeDone.push({ id: s.id, obj: Object.assign({}, prev, { state: 'done', at: now }) }); return; }
      if (now - Number(prev.at || 0) < KP.WAKE_GAP_SEC) return;                // 기동 결과 모름 — 기다림
      if (Number(prev.attempt || 1) >= 2) {
        out.wakeDone.push({ id: s.id, obj: Object.assign({}, prev, { state: 'failed', at: now }) });
        out.mails.push({ subject: '[가지 앱] 마스터 깨우기 실패', body: '깨우기 신호 ' + s.id + ': 두 번 시도했지만 마스터가 켜지지 않았습니다.' });
        return;
      }
      if (!wakeSignal) wakeSignal = { s: s, attempt: 2 };
      return;
    }
    if (people === null) return rej('people_unreadable');
    const p = byAcct[s.owner];
    if (!p) return rej('not_registered');
    if (p.status && p.status !== 'active') return rej('stopped');
    if ((p.perms || []).indexOf('wake') < 0) return rej('no_wake_perm');
    if (s.modified - s.created > KP.SIGNAL_EDIT_SEC * 1000) return rej('edited_after_create');
    if (st.now - s.created > KP.WAKE_GAP_SEC * 1000) return rej('expired');
    if (out.alive) return rej('already_alive');
    const rel = (s.obj || {}).release_stop;
    if (holds.length) {                                                         // 정지 보류 판정
      const admin = p.role === 'admin' && (p.perms || []).indexOf('release') >= 0;
      if (!rel) return rej('hold');
      if (!admin) return rej('release_needs_admin');
      if (holds.length !== 1 || holds[0] !== rel) return rej('stop_id_mismatch');
    } else if (rel) return rej('no_such_hold');
    if (masterStarting || now - lastWake < KP.WAKE_GAP_SEC) return rej('woken_recently');
    if (!wakeSignal) wakeSignal = { s: s, attempt: 1, release: rel || null };
  });
  if (wakeSignal) {
    out.wake = { reason: 'signal', id: wakeSignal.s.id, attempt: wakeSignal.attempt };
    if (wakeSignal.release) out.releases.push({ stop_id: wakeSignal.release, origin_signal: wakeSignal.s.id });
  }

  // 3) 자동 깨우기 — 같은 보류 판정. 보류 중에는 깨우지 않음 (해제 신호가 있다는 것만으로도 깨우지 않음)
  if (!out.wake && !out.alive && !masterStarting && !holds.length && now - lastWake >= KP.WAKE_GAP_SEC) {
    const day = kpIsDay_(st.now);
    const observed = {};
    (wake.observed_requests || []).forEach((x) => { observed[x] = 1; });
    const done = {};
    (st.signalDone || []).forEach((x) => { done[x] = 1; });
    const undone = (st.signals || []).some((s) => s.kind !== 'wake' && !done[s.id]);
    let reason = null;
    if (day) reason = 'daytime_keepalive';
    else if (wake.next_wake_at !== null && wake.next_wake_at !== undefined && Number(wake.next_wake_at) <= now) reason = 'next_wake_at';
    else if (undone) reason = 'control_signal';
    if (day && (st.pendingIds || []).some((id) => !observed[id])) reason = 'new_request';
    if (reason) out.wake = { reason: reason, id: null, attempt: 1 };
  }

  // 4) 감시 알림
  const mailed = {};
  (st.mailed || []).forEach((x) => { mailed[x] = 1; });
  if (st.collectorAt && st.now - st.collectorAt > KP.COLLECTOR_STALE_SEC * 1000 && !mailed.collector_stale) {
    out.mails.push({ key: 'collector_stale', subject: '[가지 앱] 수집기 멈춤', body: '수집기가 20분 넘게 갱신되지 않았습니다.' });
  }
  (st.alerts || []).forEach((a) => {
    if (mailed[a.id]) return;
    const kind = String((a.obj || {}).kind || '');
    if (['stale_report', 'confirm_denied'].indexOf(kind) >= 0) return;          // 흔한 알림은 메일로 보내지 않음
    out.mails.push({ key: a.id, subject: '[가지 앱] 알림: ' + kind, body: '심판이 남긴 알림입니다: ' + kind + ' (' + a.id + ')' });
  });
  return out;
}

// ─────────────────────────────────────────────────────────── Drive 입출력
function kpSub_(base, parts, create) {
  if (!base) return null;
  let cur = base;
  for (const p of parts) {
    const it = cur.getFoldersByName(p);
    if (it.hasNext()) cur = it.next(); else if (create) cur = cur.createFolder(p); else return null;
  }
  return cur;
}
function kpFile_(dir, name) { if (!dir) return null; const it = dir.getFilesByName(name); return it.hasNext() ? it.next() : null; }
function kpRead_(dir, name) {
  const f = kpFile_(dir, name);
  if (!f) return null;
  try { return JSON.parse(f.getBlob().getDataAsString('UTF-8') || 'null'); } catch (e) { return null; }
}
function kpWrite_(dir, name, obj) {
  const f = kpFile_(dir, name);
  const t = JSON.stringify(obj);
  if (f) f.setContent(t); else dir.createFile(name, t, 'application/json');
}
function kpList_(dir, fn) {
  const out = [];
  if (!dir) return out;
  const it = dir.getFiles();
  while (it.hasNext()) { const f = it.next(); const x = fn(f); if (x) out.push(x); }
  return out;
}
function kpObj_(f) { try { return JSON.parse(f.getBlob().getDataAsString('UTF-8') || 'null'); } catch (e) { return null; } }
function kpOwner_(f) { try { return f.getOwner().getEmail(); } catch (e) { return ''; } }

function keeper_() {
  const c = kpCfg_();
  const base = DriveApp.getFolderById(c.base);
  const jobs = kpSub_(base, ['jobs'], true);
  const arbDir = kpSub_(base, ['arb'], false);
  const admin = c.admin ? DriveApp.getFolderById(c.admin) : null;
  const people = admin ? kpRead_(kpSub_(admin, ['config'], false), 'people.json') : null;
  const prev = kpRead_(jobs, 'keeper.json') || {};
  const wakeDoneDir = kpSub_(jobs, ['wake_done'], true);
  const wakeDone = {};
  kpList_(wakeDoneDir, (f) => { const o = kpObj_(f); if (o) wakeDone[f.getName().replace(/\.json$/, '')] = o; return null; });
  const reqRe = /^REQ_([0-9A-Za-z_.-]+?)__([a-z0-9_]+)__pending\.json$/;
  const pend = (dir) => kpList_(dir, (f) => { const m = reqRe.exec(f.getName()); return m ? m[1] : null; });
  const st = {
    now: Date.now(),
    grant: kpRead_(jobs, 'ARBITER_GRANT.json'),
    arbiter: kpRead_(arbDir, 'ARBITER.json'),
    asks: kpList_(kpSub_(jobs, ['arbiter_ask'], false), kpObj_),
    workers: kpList_(kpSub_(base, ['workers'], false), kpObj_),
    pendingIds: pend(kpSub_(base, ['requests'], false)).concat(pend(kpSub_(base, ['relabel', 'requests'], false))),
    signals: kpList_(kpSub_(jobs, ['signals'], false), (f) => {
      const id = f.getName().replace(/\.json$/, '');
      const kind = id.split('__')[0];
      return { id: id, kind: kind, owner: kind === 'wake' ? kpOwner_(f) : '', created: f.getDateCreated().getTime(),
        modified: f.getLastUpdated().getTime(), obj: kind === 'wake' ? kpObj_(f) : null };
    }),
    signalDone: kpList_(kpSub_(arbDir, ['signal_done'], false), (f) => f.getName().replace(/\.json$/, '')),
    wakeDone: wakeDone, auto: wakeDone.auto || {},
    people: Array.isArray(people) ? people : null,
    collectorAt: (() => { const o = kpRead_(kpSub_(base, ['status'], false), 'collector.json'); return o && o.time ? Date.parse(o.time) : null; })(),
    alerts: kpList_(kpSub_(arbDir, ['alerts'], false), (f) => (f.getDateCreated().getTime() > (prev.at_ms || 0) - 120000
      ? { id: f.getName().replace(/\.json$/, ''), obj: kpObj_(f) } : null)),
    mailed: prev.mailed || [],
  };
  const d = keeperDecide_(st);
  if (d.grant) kpWrite_(jobs, 'ARBITER_GRANT.json', d.grant);
  d.wakeDone.forEach((w) => kpWrite_(wakeDoneDir, w.id + '.json', w.obj));
  let pushed = null;
  if (d.wake) {
    const rec = { state: 'processing', attempt: d.wake.attempt, reason: d.wake.reason, at: st.now / 1000 };
    kpWrite_(wakeDoneDir, (d.wake.id || 'auto') + '.json', rec);                 // 먼저 '처리 중'을 적음
    if (d.wake.id) kpWrite_(wakeDoneDir, 'auto.json', { at: st.now / 1000, by: d.wake.id });
    d.releases.forEach((r) => kpWrite_(kpSub_(jobs, ['signals'], true),
      'release__keeper__' + r.origin_signal.replace(/[^0-9A-Za-z_]/g, '') + '.json', { stop_id: r.stop_id, origin_signal: r.origin_signal }));
    pushed = kagglePush_(c, admin, d.wake.reason);
    kpWrite_(wakeDoneDir, (d.wake.id || 'auto') + '.json', Object.assign({}, rec, { state: pushed.ok ? 'pushed' : 'failed', why: pushed.why || '' }));
    if (!pushed.ok) d.mails.push({ key: 'push_' + pushed.why, subject: '[가지 앱] 마스터 깨우기 실패', body: '사유: ' + pushed.why });
  }
  const mailed = (st.mailed || []).slice(-200);
  d.mails.forEach((m) => {
    if (c.mail) { try { MailApp.sendEmail(c.mail, m.subject, m.body); } catch (e) { /* 메일 실패는 넘어감 */ } }
    if (m.key) mailed.push(m.key);
  });
  const res = { ok: true, version: KEEPER_VERSION, at: st.now / 1000, at_ms: st.now, alive: d.alive,
    epoch: (d.grant || st.grant || {}).epoch || 0, wake: d.wake ? d.wake.reason : null, pushed: pushed ? pushed.ok : null, mailed: mailed };
  kpWrite_(jobs, 'keeper.json', res);
  return res;
}

// ─────────────────────────────────────────────────────────── Kaggle로 마스터 노트북 올리기 (실제 시험 필요)
function kpSha256_(text) {
  const bytes = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text, Utilities.Charset.UTF_8);
  return bytes.map((b) => ('0' + ((b + 256) % 256).toString(16)).slice(-2)).join('');
}

function kagglePush_(c, admin, reason) {
  if (!c.kUser || !c.kKey) return { ok: false, why: 'no_kaggle_key' };
  const deploy = admin ? kpSub_(admin, ['deploy'], false) : null;
  const meta = kpRead_(deploy, 'kernel-metadata.json');              // { id: "<user>/<slug>", title, code_file, … }
  if (!meta || !meta.id || !meta.code_file) return { ok: false, why: 'no_deploy_metadata' };
  const nb = kpFile_(deploy, meta.code_file);
  if (!nb) return { ok: false, why: 'no_master_notebook' };
  const text = nb.getBlob().getDataAsString('UTF-8');
  if (!c.nbSha || kpSha256_(text) !== c.nbSha) return { ok: false, why: 'notebook_hash_mismatch' };   // 승인된 노트북만
  const body = { slug: meta.id, newTitle: meta.title || '', text: text, language: 'python', kernelType: 'notebook',
    isPrivate: true, enableGpu: false, enableInternet: true,
    datasetDataSources: meta.dataset_sources || [], competitionDataSources: [], kernelDataSources: meta.kernel_sources || [] };
  let code = 0;
  try {
    const r = UrlFetchApp.fetch('https://www.kaggle.com/api/v1/kernels/push', {
      method: 'post', contentType: 'application/json', payload: JSON.stringify(body), muteHttpExceptions: true,
      headers: { Authorization: 'Basic ' + Utilities.base64Encode(c.kUser + ':' + c.kKey) },
    });
    code = r.getResponseCode();                                       // 응답 본문은 기록하지 않음
  } catch (e) { return { ok: false, why: 'fetch_error' }; }
  return code >= 200 && code < 300 ? { ok: true, why: '', reason: reason } : { ok: false, why: 'http_' + code };
}

/** 설정 점검 (값은 출력하지 않음) */
function checkKeeperSetup() {
  const c = kpCfg_();
  const out = ['Keeper ' + KEEPER_VERSION];
  [['BASE_FOLDER_ID', c.base], ['ADMIN_FOLDER_ID', c.admin], ['KAGGLE_USERNAME', c.kUser], ['KAGGLE_KEY', c.kKey],
    ['MASTER_NB_SHA256', c.nbSha], ['ALERT_EMAIL', c.mail]].forEach((kv) => out.push(kv[0] + ': ' + (kv[1] ? '있음 ✅' : '없음 ⚠️')));
  console.log(out.join('\n'));
  return out;
}
