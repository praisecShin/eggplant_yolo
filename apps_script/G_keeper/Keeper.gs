/**
 * Keeper.gs v4.33.0j — 심판 자격·마스터 깨우기·감시 (설계 8판 '계정 역할', 'CTRL앱', '감시와 재시작 점검')
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
 *   NTFY_TOPIC         (선택) ntfy 푸시 주제 이름 — 아는 사람은 누구나 받을 수 있으므로 비밀처럼 다룸. 휴대폰 ntfy 앱에서 구독
 *   NTFY_SERVER        (선택) 기본 https://ntfy.sh
 *
 * 하는 일 (keeper):
 *   1) 심판 자격: 살아 있는 심판이 없을 때만 jobs/ARBITER_GRANT.json (세션·epoch+1). 이 파일은 G 소유 — 믿음의 시작점
 *   2) 깨우기: 모든 깨우기는 '정지 보류 판정' 하나를 거침. 깨우기 신호는 Keeper가 받는 유일한 신호
 *   3) 감시: 심판·수집기 멈춤, 마스터가 남긴 알림 → 메일.  자기 생존 신호 jobs/keeper.json
 *
 * ⚠ Kaggle API로 노트북을 올리는 부분(kagglePush_)은 실제 계정으로 한 번 시험해야 합니다 (먼저 시험할 것).
 */
const KEEPER_VERSION = '4.33.0l';
const KP = {
  ALIVE_SEC: 180,          // 심판 회차·생존 신호 3분
  WAKE_GAP_SEC: 600,       // 깨우기 사이 최소 10분 / 깨우기 신호 최대 나이
  SIGNAL_EDIT_SEC: 5,      // 만든 뒤 고친 신호는 거절 (만든 시각과 수정 시각 차이)
  COLLECTOR_STALE_SEC: 1200,
  DAY_START: 8, DAY_END: 19,
  AUTO_FAIL_LIMIT: 3,      // 자동 깨우기가 이만큼 연속 실패하면 메일 + 느린 간격
  AUTO_SLOW_SEC: 1800,
  OUTBOX_TRIES: 30,        // 메일·푸시 전송 실패는 다음 차례(1분)에 다시 — 이만큼 실패하면 버림 (b17 보충)
  OUTBOX_MAX: 50,          // 보낼 목록 상한 — 보호 모드 알림은 상한과 상관없이 남김 (b18 Y6)
  NIGHT_SIGNALS: ['confirm_choice', 'cancel', 'release', 'run_choice', 'adopt_choice'],   // 밤에 마스터를 깨우는 신호 종류
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
    nbSha: p.getProperty('MASTER_NB_SHA256'), mail: p.getProperty('ALERT_EMAIL'),
    ntfyTopic: p.getProperty('NTFY_TOPIC'), ntfyServer: p.getProperty('NTFY_SERVER') || 'https://ntfy.sh' };
}

// ─────────────────────────────────────────────────────────── 판정 (입출력 없음 — 시험 가능)
/** 사람 상태: 칸이 없으면 사용 중, 있으면 정확히 'active'일 때만 — 심판(person_ok·requester_ok)과 같은 해석 */
function kpActive_(p) { return p.status === undefined || p.status === 'active'; }

function kpIsDay_(nowMs) {
  const h = new Date(nowMs + 9 * 3600e3).getUTCHours();
  return h >= KP.DAY_START && h < KP.DAY_END;
}

/**
 * st: { now(ms), grant, arbiter, asks:[{session,at}], workers:[{session,hb,caps,stopping}], pendingIds:[],
 *       signals:[{id,kind,owner,created,modified,obj}], signalDone:[ids], wakeDone:{id:obj}, auto:{at},
 *       people:[…]|null, collectorAt(ms)|null, alerts:[{id,obj}], mailed:[ids],
 *       holds:[{id,active,until}]|null(읽지 못함), arbiterUnreadable:bool, auto:{at,fails} }
 *       prevProtectKey, keeperUnreadable:bool(keeper.json이 있는데 못 읽음)
 * → { grant|null, wake:{reason,id}|null, releases:[{stop_id,origin_signal}], wakeDone:[{id,obj}], mails:[{key,subject,body}],
 *     pushes:[{title,message,priority}], forget:[mailed에서 뺄 키], alive }
 */
function keeperDecide_(st) {
  const now = st.now / 1000;
  const out = { grant: null, wake: null, releases: [], wakeDone: [], mails: [], pushes: [], forget: [], alive: false, autoReset: false,
    protectKey: '' };
  const g = st.grant || {};
  const arb = st.arbiter || {};
  const fresh = (w) => w && !w.stopping && now - Number(w.hb || 0) <= KP.ALIVE_SEC;
  const allFresh = (st.workers || []).filter((w) => w && typeof w === 'object' && fresh(w));
  const isMaster = (w) => Array.isArray(w.caps) && w.caps.indexOf('master') >= 0;
  let masters = allFresh.filter(isMaster);
  const holderHb = masters.some((w) => w.session === g.session);
  const roundFresh = arb.session === g.session && Number(arb.epoch) === Number(g.epoch) && now - Number(arb.at || 0) <= KP.ALIVE_SEC;
  const justGranted = holderHb && now - Number(g.at || 0) <= KP.ALIVE_SEC;
  out.alive = !!g.session && (roundFresh || justGranted);
  const mailed = {};
  (st.mailed || []).forEach((x) => { mailed[x] = 1; });
  if (st.keeperUnreadable) {
    // keeper.json을 못 읽음 → 보낸 알림 이력을 모름. 지금 보이는 상태 알림은 이미 보낸 것으로 보고(중복 방지),
    // 보호 모드는 안전 쪽으로 한 번 더 알림. 이 사실 자체를 메일 한 통으로 알림 (b17 보충)
    ['collector_stale', 'wake_done_unknown', 'hold_unknown'].forEach((k) => { mailed[k] = 1; });
    (st.alerts || []).forEach((a) => { mailed[a.id] = 1; });
    (st.signals || []).forEach((x) => { mailed['ignored_stop_' + x.id] = 1; });
    if (g.session) mailed['stalled_' + g.session + '_' + g.epoch] = 1;
    out.mails.push({ key: '', important: true, subject: '[가지 앱] Keeper 기록을 읽지 못함',
      body: 'jobs/keeper.json을 읽지 못해 보낸 알림 이력을 새로 시작합니다. 보호 모드 알림이 한 번 더 올 수 있습니다.' });
  }

  // 0) 생존 신호는 오지만 회차가 멈춘 심판: 다시 자격을 주지 않고, '켜지는 중'으로도 세지 않음 (b11 참고)
  if (!out.alive && holderHb) {
    masters = masters.filter((w) => w.session !== g.session);
    const key = 'stalled_' + g.session + '_' + g.epoch;
    if (!mailed[key]) out.mails.push({ key: key, subject: '[가지 앱] 심판 회차 멈춤', body: '심판 ' + g.session + '의 생존 신호는 오지만 회차 기록이 3분 넘게 멈췄습니다.' });
  }

  // 1) 자격: 살아 있는 심판이 없고, 살아 있는 마스터가 신청했을 때만
  if (!out.alive) {
    const cands = (st.asks || []).filter((a) => a && masters.some((w) => w.session === a.session))
      .sort((a, b) => Number(b.at || 0) - Number(a.at || 0));
    if (cands.length) {
      out.grant = { epoch: Number(g.epoch || 0) + 1, session: cands[0].session, at: now };
      out.alive = true;
    }
  }

  // 정지 보류 판정 (모든 깨우기가 거침, Q4): arb/holds/를 직접 읽음 + 아직 처리 안 된 정지 신호.
  // 기한은 Keeper가 직접 따짐. 읽지 못하면 '보류 없음'이 아니라 '모름' — 깨우지 않음
  const done = {};
  (st.signalDone || []).forEach((x) => { done[x] = 1; });
  const holdUnknown = st.holds === null || st.holds === undefined || st.arbiterUnreadable === true;
  const holdSet = {};
  (st.holds || []).forEach((h) => {
    if (h && h.active && (h.until === null || h.until === undefined || Number(h.until) > now)) holdSet[h.id] = 1;
  });
  // 처리 전 정지 신호: 정지 권한(release)이 있는 등록된 사람이 만든 것만 보류로 봄 — 심판과 같은 기준 (R2).
  // 사람 목록을 못 읽으면 가려낼 수 없으므로 보류로 봄 (안전 쪽)
  const pplByAcct = {};
  (st.people || []).forEach((p) => { if (p && p.account) pplByAcct[p.account] = p; });
  const stopTrusted = (s) => {
    if (st.people === null || st.people === undefined) return true;
    const p = pplByAcct[s.owner];
    return !!p && kpActive_(p) && (p.perms || []).indexOf('release') >= 0;
  };
  const ignoredStops = [];
  (st.signals || []).forEach((s) => {
    if (s.kind !== 'stop' || done[s.id]) return;
    if (stopTrusted(s)) holdSet[s.id] = 1; else ignoredStops.push(s.id);
  });
  const holds = Object.keys(holdSet).sort();

  // 2) 깨우기 신호 (Keeper가 받는 유일한 신호) — 2차 권한 확인. 다시 시도할 때도 같은 확인을 거침 (Q5)
  const wake = (arb.wake || {});
  const people = st.people;
  const byAcct = {};
  (people || []).forEach((p) => { if (p && p.account) byAcct[p.account] = p; });
  const masterStarting = masters.length > 0;
  const auto = st.auto || {};
  const lastWake = Number(auto.at || 0);
  const wdUnknown = st.wakeDoneUnknown || {};           // 기록 파일은 있는데 읽지 못함 — '없음'이 아님 (R3)
  const autoUnknown = !!wdUnknown.auto;
  let wakeSignal = null;
  (st.signals || []).filter((s) => s.kind === 'wake').sort((a, b) => a.created - b.created).forEach((s) => {
    if (wdUnknown[s.id] || autoUnknown) return;                                  // 처리·덮어쓰기를 미룸
    const prev = (st.wakeDone || {})[s.id];
    if (prev && ['done', 'rejected', 'failed'].indexOf(prev.state) >= 0) return;
    const resume = !!(prev && (prev.state === 'processing' || prev.state === 'pushed'));
    const keep = resume ? prev : {};
    const rej = (reason) => out.wakeDone.push({ id: s.id, obj: Object.assign({}, keep, { state: 'rejected', reason: reason, at: now }) });
    if (people === null) return rej('people_unreadable');
    const p = byAcct[s.owner];
    if (!p) return rej('not_registered');
    if (!kpActive_(p)) return rej('stopped');
    if ((p.perms || []).indexOf('wake') < 0) return rej('no_wake_perm');
    if (s.modified - s.created > KP.SIGNAL_EDIT_SEC * 1000) return rej('edited_after_create');
    if (!resume && st.now - s.created > KP.WAKE_GAP_SEC * 1000) return rej('expired');
    if (!resume && out.alive) return rej('already_alive');
    if (holdUnknown) return;                                                    // 보류 여부를 모름 → 미룸 (거절하지 않음)
    let rel = (s.obj || {}).release_stop || (resume ? prev.release_stop : null) || null;
    if (holds.length) {
      const admin = p.role === 'admin' && (p.perms || []).indexOf('release') >= 0;
      if (!rel) return rej('hold');
      if (!admin) return rej('release_needs_admin');
      if (holds.length !== 1 || holds[0] !== rel) return rej('stop_id_mismatch');
    } else if (rel) {
      if (!resume) return rej('no_such_hold');
      rel = null;                                                               // 이어 하는 중에 보류가 이미 풀림
    }
    const relOut = () => { if (rel) out.releases.push({ stop_id: rel, origin_signal: s.id }); };
    if (resume) {                                                               // 중간 장애 뒤 이어 하기 (J8·Q6)
      relOut();                                                                 // 빠진 해제 신호를 채움 (있으면 건드리지 않음)
      if (out.alive || masterStarting) { out.wakeDone.push({ id: s.id, obj: Object.assign({}, prev, { state: 'done', at: now }) }); return; }
      if (now - Number(prev.at || 0) < KP.WAKE_GAP_SEC) return;                // 기동 결과 모름 — 기다림
      if (Number(prev.attempt || 1) >= 2) {
        out.wakeDone.push({ id: s.id, obj: Object.assign({}, prev, { state: 'failed', at: now }) });
        out.mails.push({ subject: '[가지 앱] 마스터 깨우기 실패', body: '깨우기 신호 ' + s.id + ': 두 번 시도했지만 마스터가 켜지지 않았습니다.' });
        return;
      }
      if (!wakeSignal) wakeSignal = { s: s, attempt: 2, release: rel };
      return;
    }
    if (masterStarting || now - lastWake < KP.WAKE_GAP_SEC) return rej('woken_recently');
    if (!wakeSignal) { wakeSignal = { s: s, attempt: 1, release: rel }; relOut(); }
  });
  if (wakeSignal) out.wake = { reason: 'signal', id: wakeSignal.s.id, attempt: wakeSignal.attempt, release: wakeSignal.release || null };

  // 3) 자동 깨우기 — 같은 보류 판정. 보류 중이거나 보류 여부를 모르면 깨우지 않음
  const fails = Number(auto.fails || 0);
  if (out.alive && fails > 0) out.autoReset = true;
  const gap = fails >= KP.AUTO_FAIL_LIMIT ? KP.AUTO_SLOW_SEC : KP.WAKE_GAP_SEC;      // 3번 연속 실패 뒤에는 30분 간격
  if (!out.wake && !out.alive && !masterStarting && !holdUnknown && !autoUnknown && !holds.length && now - lastWake >= gap) {
    const day = kpIsDay_(st.now);
    const observed = {};
    (wake.observed_requests || []).forEach((x) => { observed[x] = 1; });
    const known = {};
    (wake.workers || []).forEach((x) => { known[x] = 1; });
    // 심판 요약은 같은 시간대(낮·밤)에 계산한 것만 씀 — 낮에 '할 수 있음'이던 일이 밤에도 그렇지는 않음
    const sameRegime = arb.at !== undefined && kpIsDay_(Number(arb.at) * 1000) === day;
    const undone = (st.signals || []).some((s) => KP.NIGHT_SIGNALS.indexOf(s.kind) >= 0 && !done[s.id]);   // Q8
    let reason = null;
    if (day) reason = 'daytime_keepalive';
    else if (wake.next_wake_at !== null && wake.next_wake_at !== undefined && Number(wake.next_wake_at) <= now) reason = 'next_wake_at';
    else if (undone) reason = 'control_signal';
    else if (sameRegime && Number(wake.runnable || 0) > 0) reason = 'runnable';                         // Q9
    else if ((sameRegime ? Number(wake.executor_wait || 0) : Number(wake.executor_wait_night || 0)) > 0
      && allFresh.some((w) => !isMaster(w) && !known[w.session])) reason = 'new_executor';      // 밤에도 할 수 있는 대기는 시간대와 무관 (R6)
    if (day && (st.pendingIds || []).some((id) => !observed[id])) reason = 'new_request';
    if (reason) {
      out.wake = { reason: reason, id: null, attempt: 1, release: null, fails: fails + 1 };
      if (fails === KP.AUTO_FAIL_LIMIT) out.mails.push({ subject: '[가지 앱] 마스터가 켜지지 않음',
        body: '자동 깨우기를 ' + fails + '번 연속 시도했지만 마스터가 켜지지 않았습니다. 이제 30분 간격으로 시도합니다.' });
    }
  }

  // 3.5) 보호 모드 (심판이 믿을 수 없는 판정 파일을 찾음) — 들어갈 때·끝날 때 메일 + 푸시
  const prot = Array.isArray(arb.protect) ? arb.protect.filter((x) => x && typeof x.path === 'string') : [];
  const arbFresh = now - Number(arb.at || 0) <= KP.ALIVE_SEC;
  if (prot.length) {
    out.protectKey = 'protect_' + prot.map((x) => x.path + ':' + x.why).sort().join('|').slice(0, 300);
    // 정상→보호로 바뀌면 같은 손상이어도 새 사건 (b17 X4). 보호 구간 안에서 같은 키는 한 번만
    if (!st.prevProtectKey || !mailed[out.protectKey]) {
      const lines = prot.slice(0, 10).map((x) => '- ' + x.path + ' (' + x.why + ')').join('\n');
      const body = '심판이 믿을 수 없는 판정 파일을 찾아 보호 모드로 들어갔습니다. 새 접수·배정·신호 처리를 멈췄습니다.\n' + lines +
        '\n\nCTRL앱에서 확인하고 배포 계획의 관리자 복구 절차를 따라 주세요.';
      out.mails.push({ key: out.protectKey, important: true, subject: '[가지 앱] ⚠ 보호 모드', body: body });
      out.pushes.push({ important: true, title: '가지 앱 보호 모드', message: '판정 파일 ' + prot.length + '개를 믿을 수 없어 새 일을 멈췄습니다. CTRL앱을 확인하세요.', priority: 5 });
    }
  } else if (st.prevProtectKey && arbFresh) {
    out.mails.push({ key: '', important: true, subject: '[가지 앱] 보호 모드 끝남', body: '판정 파일이 바로잡혀 정상으로 돌아왔습니다.' });
    out.pushes.push({ important: true, title: '가지 앱 보호 모드 끝남', message: '정상으로 돌아왔습니다.', priority: 3 });
    Object.keys(mailed).forEach((k) => { if (k.indexOf('protect_') === 0) out.forget.push(k); });   // 이 구간의 진입 기록을 지움
  } else if (st.prevProtectKey) {
    out.protectKey = st.prevProtectKey;                   // 심판 기록이 오래됨 — 끝났다고 보지 않음
  }

  // 4) 감시 알림
  const colStale = st.collectorAt && st.now - st.collectorAt > KP.COLLECTOR_STALE_SEC * 1000;
  if (colStale && !mailed.collector_stale) {
    out.mails.push({ key: 'collector_stale', subject: '[가지 앱] 수집기 멈춤', body: '수집기가 20분 넘게 성공하지 못했습니다 (멈췄거나 실행할 때마다 실패). CTRL앱의 수집기 칸에서 오류를 확인하세요.' });
  }
  // 상태 알림은 상태가 풀리면 이력에서 지움 → 다시 생기면 다시 알림 (b17 X4와 같은 문제)
  if (st.collectorAt && !colStale && mailed.collector_stale) out.forget.push('collector_stale');
  if (!Object.keys(wdUnknown).length && mailed.wake_done_unknown) out.forget.push('wake_done_unknown');
  if (!holdUnknown && mailed.hold_unknown) out.forget.push('hold_unknown');
  if (Object.keys(wdUnknown).length && !mailed.wake_done_unknown) {
    out.mails.push({ key: 'wake_done_unknown', subject: '[가지 앱] 깨우기 기록을 읽지 못함', body: '깨우기 기록 ' + Object.keys(wdUnknown).sort().join(', ') + '을(를) 읽지 못해 처리를 미루고 있습니다.' });
  }
  ignoredStops.forEach((id) => {
    if (!mailed['ignored_stop_' + id]) out.mails.push({ key: 'ignored_stop_' + id, subject: '[가지 앱] 권한 없는 정지 신호',
      body: '정지 권한이 없는 계정이 만든 정지 신호 ' + id + '는 깨우기 판단에서 뺐습니다. 심판이 켜지면 거절합니다.' });
  });
  if (holdUnknown && !out.alive && !mailed.hold_unknown) {
    out.mails.push({ key: 'hold_unknown', subject: '[가지 앱] 정지 보류를 읽지 못함', body: '정지 보류 기록을 읽지 못해 마스터를 깨우지 않고 있습니다.' });
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
/** 객체만 받음. { obj, bad } — 파일이 있는데 객체로 읽히지 않으면 bad */
function kpReadObj_(dir, name) {
  const f = kpFile_(dir, name);
  if (!f) return { obj: null, bad: false };
  const o = kpObj_(f);
  const good = o && typeof o === 'object' && !Array.isArray(o);
  return { obj: good ? o : null, bad: !good };
}
function kpWriteNew_(dir, name, obj) { if (!kpFile_(dir, name)) dir.createFile(name, JSON.stringify(obj), 'application/json'); }
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

/** 수집기가 마지막으로 성공한 시각(ms). last_ok가 기준 — 실행할 때마다 실패해도 멈춤으로 알림 (b18 보충).
 *  last_ok가 없으면 맨 위 time(4.33.0k~)이나 last.time(4.33.0). 모두 없으면 null (b17 X5) */
function kpCollectorAt_(o) {
  if (!o || typeof o !== 'object') return null;
  const t = o.last_ok || o.time || (o.last && o.last.time);
  const ms = t ? Date.parse(t) : NaN;
  return isNaN(ms) ? null : ms;
}

function keeper_() {
  const c = kpCfg_();
  const base = DriveApp.getFolderById(c.base);
  const jobs = kpSub_(base, ['jobs'], true);
  const arbDir = kpSub_(base, ['arb'], false);
  const admin = c.admin ? DriveApp.getFolderById(c.admin) : null;
  const people = admin ? kpRead_(kpSub_(admin, ['config'], false), 'people.json') : null;
  const prevRead = kpReadObj_(jobs, 'keeper.json');
  const prev = prevRead.obj || {};
  const wakeDoneDir = kpSub_(jobs, ['wake_done'], true);
  const wakeDone = {};
  const isObj = (o) => (o && typeof o === 'object' && !Array.isArray(o) ? o : null);
  const wakeDoneUnknown = {};
  kpList_(wakeDoneDir, (f) => {
    const id = f.getName().replace(/\.json$/, '');
    const o = isObj(kpObj_(f));
    if (o) wakeDone[id] = o; else wakeDoneUnknown[id] = true;                 // 있는데 못 읽음 → '모름' (R3)
    return null;
  });
  const reqRe = /^REQ_([0-9A-Za-z_.-]+?)__([a-z0-9_]+)__pending\.json$/;
  const pend = (dir) => kpList_(dir, (f) => { const m = reqRe.exec(f.getName()); return m ? m[1] : null; });
  const arbRead = kpReadObj_(arbDir, 'ARBITER.json');
  let holds = [];
  try {
    kpList_(kpSub_(arbDir, ['holds'], false), (f) => {
      const o = isObj(kpObj_(f));
      if (!o) throw new Error('hold');                        // 하나라도 못 읽으면 전체를 '모름'으로
      holds.push({ id: f.getName().replace(/\.json$/, ''), active: !!o.active, until: o.until === undefined ? null : o.until });
      return null;
    });
  } catch (e) { holds = null; }
  const st = {
    now: Date.now(),
    grant: isObj(kpRead_(jobs, 'ARBITER_GRANT.json')),
    arbiter: arbRead.obj, arbiterUnreadable: arbRead.bad, holds: holds,
    asks: kpList_(kpSub_(jobs, ['arbiter_ask'], false), (f) => isObj(kpObj_(f))),
    workers: kpList_(kpSub_(base, ['workers'], false), (f) => isObj(kpObj_(f))),
    pendingIds: pend(kpSub_(base, ['requests'], false)).concat(pend(kpSub_(base, ['relabel', 'requests'], false))),
    signals: kpList_(kpSub_(jobs, ['signals'], false), (f) => {
      const id = f.getName().replace(/\.json$/, '');
      const kind = id.split('__')[0];
      return { id: id, kind: kind, owner: (kind === 'wake' || kind === 'stop') ? kpOwner_(f) : '', created: f.getDateCreated().getTime(),
        modified: f.getLastUpdated().getTime(), obj: kind === 'wake' ? isObj(kpObj_(f)) : null };
    }),
    signalDone: kpList_(kpSub_(arbDir, ['signal_done'], false), (f) => f.getName().replace(/\.json$/, '')),
    wakeDone: wakeDone, wakeDoneUnknown: wakeDoneUnknown, auto: wakeDone.auto || {},
    people: Array.isArray(people) ? people : null,
    collectorAt: kpCollectorAt_(kpRead_(kpSub_(base, ['status'], false), 'collector.json')),
    alerts: kpList_(kpSub_(arbDir, ['alerts'], false), (f) => (f.getDateCreated().getTime() > (prev.at_ms || 0) - 120000
      ? { id: f.getName().replace(/\.json$/, ''), obj: kpObj_(f) } : null)),
    mailed: prev.mailed || [],
    prevProtectKey: prev.protect_key || '',
    keeperUnreadable: prevRead.bad,
  };
  const d = keeperDecide_(st);
  if (d.grant) kpWrite_(jobs, 'ARBITER_GRANT.json', d.grant);
  let pushed = null;
  const fails = Number((st.auto || {}).fails || 0);
  if (d.autoReset && !d.wake) kpWrite_(wakeDoneDir, 'auto.json', Object.assign({}, st.auto, { fails: 0 }));
  const putReleases = () => d.releases.forEach((r) => kpWriteNew_(kpSub_(jobs, ['signals'], true),   // 이미 있으면 건드리지 않음
    'release__keeper__' + r.origin_signal.replace(/[^0-9A-Za-z_]/g, '') + '.json', { stop_id: r.stop_id, origin_signal: r.origin_signal }));
  if (!d.wake || d.wake.attempt > 1) putReleases();                              // 이어 하기: 빠진 해제 신호를 먼저 채움 (Q6)
  d.wakeDone.forEach((w) => kpWrite_(wakeDoneDir, w.id + '.json', w.obj));       // 그 다음에 '끝남'을 적음
  if (d.wake) {
    const rec = { state: 'processing', attempt: d.wake.attempt, reason: d.wake.reason, at: st.now / 1000 };
    if (d.wake.release) rec.release_stop = d.wake.release;                        // 해제할 정지 번호를 기록에 남김 → 중단돼도 이어 함
    if (!d.wake.id) rec.fails = d.wake.fails;
    kpWrite_(wakeDoneDir, (d.wake.id || 'auto') + '.json', rec);                 // 먼저 '처리 중'을 적음
    if (d.wake.id) kpWrite_(wakeDoneDir, 'auto.json', { at: st.now / 1000, by: d.wake.id, fails: fails });
    putReleases();
    pushed = kagglePush_(c, admin, d.wake.reason);
    kpWrite_(wakeDoneDir, (d.wake.id || 'auto') + '.json', Object.assign({}, rec, { state: pushed.ok ? 'pushed' : 'failed', why: pushed.why || '' }));
    if (!pushed.ok) d.mails.push({ key: 'push_' + pushed.why, subject: '[가지 앱] 마스터 깨우기 실패', body: '사유: ' + pushed.why });
  }
  // 알림: 보낼 목록(outbox)에 넣고 보냄. 실패한 것은 keeper.json에 남겨 다음 차례에 다시 (b17 보충)
  const forget = {};
  d.forget.forEach((k) => { forget[k] = 1; });
  const mailed = (st.mailed || []).filter((k) => !forget[k]).slice(-200);
  d.mails.forEach((m) => { if (m.key) mailed.push(m.key); });          // 넣은 것은 '보냄'으로 — 결정이 같은 알림을 또 만들지 않음
  const sent = kpSendOutbox_(c, (Array.isArray(prev.outbox) ? prev.outbox : [])
    .concat(d.mails.map((m) => ({ t: 'mail', key: m.key || '', important: !!m.important, subject: m.subject, body: m.body, tries: 0 })))
    .concat(d.pushes.map((p) => ({ t: 'push', important: !!p.important, title: p.title, message: p.message, priority: p.priority, tries: 0 }))));
  const outbox = sent.left;
  if (sent.dropped.length) {             // 넘쳐서 버린 알림: '보냄' 이력에서 지워 상태가 남아 있으면 다시 만들게 함 + 요약 한 통 (Y6)
    const gone = {};
    sent.dropped.forEach((x) => { if (x.key) gone[x.key] = 1; });
    for (let i = mailed.length - 1; i >= 0; i--) if (gone[mailed[i]]) mailed.splice(i, 1);
    const prevN = Number((outbox.find((x) => x.t === 'mail' && x.key === 'outbox_overflow') || {}).n || 0);
    const rest = outbox.filter((x) => !(x.t === 'mail' && x.key === 'outbox_overflow'));
    const n = prevN + sent.dropped.length;
    rest.unshift({ t: 'mail', key: 'outbox_overflow', important: true, n, tries: 0, subject: '[가지 앱] 알림 일부를 보내지 못함',
      body: '보낼 목록이 가득 차 알림 ' + n + '개를 버렸습니다. 상태가 그대로면 다시 알립니다. 메일·ntfy 설정과 할당량을 확인하세요.' });
    outbox.length = 0; rest.forEach((x) => outbox.push(x));
  }
  const res = { ok: true, version: KEEPER_VERSION, at: st.now / 1000, at_ms: st.now, alive: d.alive,
    epoch: (d.grant || st.grant || {}).epoch || 0, wake: d.wake ? d.wake.reason : null, pushed: pushed ? pushed.ok : null, mailed: mailed,
    protect_key: d.protectKey, outbox: outbox, outbox_dropped: sent.dropped.length || undefined };
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

/** 보낼 목록을 보냄 → { left: 아직 못 보낸 것(keeper.json에 남김), dropped: 상한을 넘어 버린 것 }.
 *  주제 이름·메일 주소는 목록에 넣지 않음. 중요한 알림(보호 모드)은 상한과 상관없이 남김 (Y6) */
function kpSendOutbox_(c, items) {
  const left = [];
  items.forEach((x) => {
    if (!x || typeof x !== 'object') return;
    let sent;
    if (x.t === 'mail') {
      if (!c.mail) sent = true;                                     // 받을 주소가 없으면 버림
      else { try { MailApp.sendEmail(c.mail, x.subject, x.body); sent = true; } catch (e) { sent = false; } }
    } else sent = kpPush_(c, x) !== false;
    if (!sent && (x.important || Number(x.tries || 0) + 1 < KP.OUTBOX_TRIES)) left.push(Object.assign({}, x, { tries: Number(x.tries || 0) + 1 }));
  });
  const imp = left.filter((x) => x.important), rest = left.filter((x) => !x.important);
  const room = Math.max(0, KP.OUTBOX_MAX - imp.length);
  const cut = Math.max(0, rest.length - room);
  return { left: imp.concat(rest.slice(cut)), dropped: rest.slice(0, cut) };
}

/** ntfy 푸시 (JSON 게시). 주제 이름은 기록·메일에 쓰지 않음. 주제가 없으면 'off', 실패면 false */
function kpPush_(c, p) {
  if (!c.ntfyTopic) return 'off';
  try {
    const r = UrlFetchApp.fetch(String(c.ntfyServer).replace(/\/+$/, '') + '/', {
      method: 'post', contentType: 'application/json', muteHttpExceptions: true,
      payload: JSON.stringify({ topic: c.ntfyTopic, title: p.title, message: p.message, priority: p.priority || 3, tags: ['eggplant'] }),
    });
    return r.getResponseCode() >= 200 && r.getResponseCode() < 300;
  } catch (e) { return false; }
}

/** 설정 점검 (값은 출력하지 않음) */
function checkKeeperSetup() {
  const c = kpCfg_();
  const out = ['Keeper ' + KEEPER_VERSION];
  [['BASE_FOLDER_ID', c.base], ['ADMIN_FOLDER_ID', c.admin], ['KAGGLE_USERNAME', c.kUser], ['KAGGLE_KEY', c.kKey],
    ['MASTER_NB_SHA256', c.nbSha], ['ALERT_EMAIL', c.mail], ['NTFY_TOPIC (선택)', c.ntfyTopic]].forEach((kv) => out.push(kv[0] + ': ' + (kv[1] ? '있음 ✅' : '없음 ⚠️')));
  console.log(out.join('\n'));
  return out;
}
