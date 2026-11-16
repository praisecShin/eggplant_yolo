/**
 * 가지 상태 수집기 Collector.gs — v4.33.0 (U1, G 계정 Apps Script 프로젝트 '수집기')
 *
 * 10분마다 CVAT에서 TASK 이름·상태 변화와 백업·export 준비 상태를 읽어 Drive eggplant_yolo/status/ 에 씁니다.
 * v4.33에서 바뀐 것 (Code.gs 4.31.9에서 나눔, 설계 8판 '계정 역할'):
 *   - 배정(dispatch)·마스터 깨우기·야간 승인·GPU 대기열·dispatcher.json·GitHub 경로를 모두 뺐습니다.
 *     배정은 CPU 마스터(심판)가, 깨우기·감시는 Keeper(같은 G 계정의 다른 프로젝트)가 합니다.
 *   - 자동 요청 규칙 (11/12 결정): backup은 TASK가 _uld로 올라올 때(원본이 없을 때만), export는 검토 단계(vf…)로 바뀔 때.
 *     _AA 감지 요청은 그만뒀습니다. 범위는 AUTO_PROJECT_ID 프로젝트(+ AUTO_NAME_PREFIX)뿐입니다.
 *     새 심판이 읽는 형식(tasks: TASK 번호 문자열 목록)으로 requests/에 씁니다.
 *     파일 소유 계정이 G라서 심판은 '수집기 자동 요청'(system:G)으로 접수합니다 (종류는 backup·export 등만).
 *   - ULD 기록 폴더는 Uld.gs와 같은 속성 ULD_ROOT_FOLDER_ID로 찾습니다 (G 계정의 내 드라이브에는 CVAT_UpLoader가 없음).
 *   - Uld.gs(ULD앱 확장)는 같은 프로젝트에 함께 넣습니다. 없으면 그 단계를 건너뜁니다.
 *
 * 쓰는 곳: status/ (스냅숏·변화·요청 상태·생존 신호), requests/ (자동 요청만), 그리고 Uld.gs가 CVAT_UpLoader/registry/sources.json(ULD앱 원본 목록).
 * 그 밖의 폴더와 CVAT에는 읽기만 합니다.
 * 웹앱으로 배포하지 않습니다 (doGet/doPost 없음).
 *
 * Script Properties (코드·Drive·로그에 쓰지 않음):
 *   CVAT_TOKEN       CVAT 개인 접근 토큰 (필수)
 *   BASE_FOLDER_ID   Drive eggplant_yolo 폴더 ID (필수) — 예행 연습은 eggplant_yolo_test
 *   CVAT_ORG         조직 slug (예: horti)
 *   CVAT_HOST        기본 https://app.cvat.ai
 *   CVAT_PROJECT_ID  (선택) 수집할 프로젝트 — 비우면 조직 전체 (Uld.gs의 중복 찾기는 조직 전체를 기대함)
 *   AUTO_PROJECT_ID  자동 요청을 만들 프로젝트 ID — 운영은 eggplant, 예행 연습은 eggplant_AA. 비우면 자동 요청 없음
 *   AUTO_NAME_PREFIX (선택) 이 글자로 시작하는 TASK만 자동 요청 — 예행 연습은 REH_
 *   ULD_ROOT_FOLDER_ID (선택) CVAT_UpLoader 폴더 ID — Uld.gs와 함께 씀. ULD 기록이 있는 TASK는 백업 요청을 하지 않음
 *   ULD_SOURCE_FOLDER_ID (Uld.gs) GoPro_RAW 폴더 ID — G 계정에서는 이름으로 못 찾으므로 넣음
 *   ULD_ALERT_EMAIL  (Uld.gs) 중복·직접 업로드 알림 메일
 *
 * 실행할 함수: checkSetup() · testOnce() · installTrigger() · uninstallTrigger() · fullSyncNow() · backfillVfNow() · (Uld.gs) uldCheckSetup()
 */
const COLLECTOR_VERSION = '4.33.0l';
const CFG = {
  EVERY_MIN: 10,            // 자동 실행 간격 (분): 1, 5, 10, 15, 30 중 하나
  FULL_EVERY_H: 24,        // 전체 다시 맞추기 간격 (시간) — 사라진 TASK는 이때 알아냄
  PAGE_SIZE: 100,
  MAX_PAGES: 80,           // 전체 맞추기에서 읽을 최대 페이지 (100 × 80 = TASK 8,000개)
  OVERLAP_MIN: 10,         // 증분 읽기: 지난번 가장 늦은 수정 시각보다 이만큼 앞부터 다시 봄 (시계 차이 대비)
  REQ_MAX: 60,             // 한 번에 확인할 백업·export 요청 수
  RECENT_KEEP: 500,
  SOFT_LIMIT_SEC: 240,     // 한 번 실행은 6분이 한도 — 이 시간이 넘으면 다음 차례로 미룸
};
const OPEN_PENDING = ['요청됨', '준비 중'];
const STATUS_DIR = 'status';

/* ---------------- 진입점 ---------------- */
function collect() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(5000)) { console.log('앞의 실행이 아직 끝나지 않아 건너뜀'); return null; }
  const t0 = Date.now();
  let res;
  try {
    res = collect_(t0, false);
  } catch (e) {
    res = { ok: false, error: String(e && e.message || e).slice(0, 500) };
    try { writeHeartbeat_(cfg_(), t0, res); } catch (e2) { console.log('collector.json 쓰기 실패: ' + e2); }
    throw e;
  } finally {
    lock.releaseLock();
  }
  return res;
}

function testOnce() {
  const r = collect();
  console.log(JSON.stringify(r, null, 1));
  return r;
}

function fullSyncNow() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) throw new Error('다른 실행이 진행 중입니다. 잠시 뒤 다시 하세요.');
  try {
    const r = collect_(Date.now(), true);
    console.log(JSON.stringify(r, null, 1));
    return r;
  } finally { lock.releaseLock(); }
}

function installTrigger() {
  uninstallTrigger();
  ScriptApp.newTrigger('collect').timeBased().everyMinutes(CFG.EVERY_MIN).create();
  console.log(`${CFG.EVERY_MIN}분마다 collect 실행을 켰습니다.`);
}

function uninstallTrigger() {
  let n = 0;
  ScriptApp.getProjectTriggers().forEach((t) => { if (t.getHandlerFunction() === 'collect') { ScriptApp.deleteTrigger(t); n++; } });
  console.log(`자동 실행 ${n}개를 껐습니다.`);
}

function checkSetup() {
  const c = cfg_();
  const out = [];
  out.push(`CVAT_HOST: ${c.host}`);
  out.push(`CVAT_TOKEN: ${c.token ? `있음 (${c.token.length}자, 값은 표시하지 않음)` : '없음 ⛔'}`);
  out.push(`CVAT_ORG: ${c.org || '(조직 구분 없음)'} · CVAT_PROJECT_ID: ${c.project || '(전체)'}`);
  try {
    const f = DriveApp.getFolderById(c.base);
    out.push(`BASE_FOLDER_ID: ${f.getName()} ✅`);
  } catch (e) { out.push(`BASE_FOLDER_ID: 열 수 없음 ⛔ (${c.base || '비어 있음'})`); }
  if (c.token) {
    const me = api_(c, '/api/users/self');
    out.push(me.code === 200 ? `CVAT 로그인: ${me.json.username} ✅` : `CVAT 로그인 실패 HTTP ${me.code} ⛔`);
    const t = api_(c, `/api/tasks?page_size=1${c.project ? '&project_id=' + c.project : ''}`);
    out.push(t.code === 200 ? `TASK 수: ${t.json.count}` : `TASK 목록 실패 HTTP ${t.code}`);
  }
  out.push(`ULD_ROOT_FOLDER_ID: ${c.uld ? '있음' : '없음 (ULD 기록을 보지 않음 — 백업 판단은 videos/만으로)'}`);
  out.push(`자동 요청: ${c.autoProject ? '프로젝트 ' + c.autoProject + (c.autoPrefix ? ' · 이름 ' + c.autoPrefix + '…' : '') : '꺼짐 (AUTO_PROJECT_ID 없음)'}`);
  out.push(`Uld.gs: ${typeof uldAfterCollect_ === 'function' ? '있음 ✅' : '없음 (ULD 확장 단계를 건너뜀)'}`);
  console.log(out.join('\n'));
  return out;
}

/* ---------------- 설정 · CVAT ---------------- */
function cfg_() {
  const p = PropertiesService.getScriptProperties();
  const c = {
    host: String(p.getProperty('CVAT_HOST') || 'https://app.cvat.ai').trim().replace(/\/+$/, ''),
    token: String(p.getProperty('CVAT_TOKEN') || '').trim().replace(/^(Token|Bearer)\s+/i, ''),
    org: String(p.getProperty('CVAT_ORG') || '').trim(),
    project: String(p.getProperty('CVAT_PROJECT_ID') || '').trim(),
    base: String(p.getProperty('BASE_FOLDER_ID') || '').trim(),
    uld: String(p.getProperty('ULD_ROOT_FOLDER_ID') || '').trim(),
    autoProject: String(p.getProperty('AUTO_PROJECT_ID') || '').trim(),
    autoPrefix: String(p.getProperty('AUTO_NAME_PREFIX') || '').trim(),
  };
  return c;
}

function api_(c, path) {
  const headers = { Authorization: 'Bearer ' + c.token, Accept: 'application/vnd.cvat+json' };
  if (c.org) headers['X-Organization'] = c.org;
  let r, code;
  for (let i = 0; i < 3; i++) {           // v4.31.4: 503·429·502·504(서버 일시 장애)는 5초·15초 뒤 다시 시도
    r = UrlFetchApp.fetch(c.host + path, { method: 'get', headers, muteHttpExceptions: true, followRedirects: true });
    code = r.getResponseCode();
    if (![429, 502, 503, 504].includes(code) || i === 2) break;
    Utilities.sleep(i === 0 ? 5000 : 15000);
  }
  let json = null;
  try { json = JSON.parse(r.getContentText() || 'null'); } catch (e) { json = null; }
  return { code, json };
}

/* ---------------- TASK 이름 읽기 (노트북 cvat_task_tools.parse_task_name과 같은 규칙) ---------------- */
const NAME_RE = /^((?:([A-Za-z]+)_)?(?:(G\d+)_)?((?:20)?\d{6})_(\d+)_(\d+))(?:_([0-9A-Za-z가-힣_]+))?$/;
const KNOWN_STATES = ['uld', 'vf', 'vf_r1', 'vf_r2', 'vfdf', 'vfdf_ok', 'vf_r2df', 'vf_r2df_ok'];   // v4.31.5 (vf_r1·vf_r2 = vf)
const STATE_ALIAS = { 'vf_r2리뷰': 'vf_r2', 'vf_r2_리뷰': 'vf_r2', 'vf_r2리뷰df': 'vf_r2df', 'vf_r2_리뷰df': 'vf_r2df' };
const STATE_WORDS = KNOWN_STATES.concat(Object.keys(STATE_ALIAS)).sort((a, b) => b.length - a.length);
const NAME_TAGS = ['AA', 'test'];

function splitState_(rest) {
  if (!rest) return ['', ''];
  const low = rest.toLowerCase();
  if (/^test(_|$)/i.test(rest)) return ['', rest];                    // 4.31.9 (F13): …_test = 상태 없는 기본 TASK 계열 + 표시 test (노트북과 같음)
  const vm = /^(vf(?:_r\d+)?(?:df(?:_ok)?)?)(?:_(.*))?$/i.exec(rest);   // 4.31.9 (F13): vf · vf_r1 · vf_r3 · vfdf · vf_r2df_ok …
  if (vm && (vm[2] === undefined || !/^(r\d+|df|ok|리뷰)/i.test(vm[2]))) return [vm[1], vm[2] || ''];
  for (const s of STATE_WORDS) {
    if (low === s.toLowerCase() || low.startsWith(s.toLowerCase() + '_')) return [STATE_ALIAS[s] || s, rest.slice(s.length + 1)];
  }
  const m = new RegExp('^(.*?)_((?:' + NAME_TAGS.join('|') + ')(?:_.*)?)$', 'i').exec(rest);
  if (m) return [m[1], m[2]];
  return [rest, ''];
}

function parseName_(name) {
  const m = NAME_RE.exec(String(name || '').trim());
  if (!m) return null;
  const date = m[4].length === 8 && m[4].startsWith('20') ? m[4].slice(2) : m[4];
  const [state, tag] = splitState_(m[7] || '');
  return { base: m[1], project: m[2] || '', gh: m[3] || '', date, row: String(parseInt(m[5], 10)), plant: String(parseInt(m[6], 10)), state, tag };
}

function taskRow_(t) {
  const f = parseName_(t.name);
  return {
    name: t.name, base: f ? f.base : '', state: f ? f.state : '', tag: f ? f.tag : '', rule_ok: !!f,
    updated: t.updated_date || '', status: t.status || '', frames: t.size || 0,
    project_id: t.project_id || null, org_id: t.organization || null, mode: t.mode || '',
  };
}

/* ---------------- 수집 ---------------- */
function collect_(t0, forceFull) {
  const c = cfg_();
  if (!c.token || !c.base) throw new Error('스크립트 속성 CVAT_TOKEN·BASE_FOLDER_ID를 먼저 넣으세요 (checkSetup으로 확인)');
  const dir = statusDir_(c);
  const prev = readJson_(dir, 'cvat_tasks.json') || { tasks: {}, last_full: null, max_updated: null };
  const now = new Date();
  const full = forceFull || !prev.last_full || (now - new Date(prev.last_full)) / 36e5 >= CFG.FULL_EVERY_H;

  // 1) TASK 목록: 최근 수정 순으로 읽다가 지난번 시각보다 오래된 것이 나오면 멈춤 (증분) · 전체 맞추기는 끝까지
  const since = !full && prev.max_updated ? new Date(new Date(prev.max_updated).getTime() - CFG.OVERLAP_MIN * 60000) : null;
  const seen = {};
  let pages = 0, stop = false, maxUpd = prev.max_updated;
  for (let page = 1; page <= CFG.MAX_PAGES && !stop; page++) {
    const r = api_(c, `/api/tasks?sort=-updated_date&page_size=${CFG.PAGE_SIZE}&page=${page}${c.project ? '&project_id=' + c.project : ''}`);
    if (r.code !== 200) throw new Error(`CVAT TASK 목록 HTTP ${r.code}${r.code === 401 || r.code === 403 ? ' — 토큰·조직 권한 확인' : r.code >= 500 || r.code === 429 ? ' — CVAT 서버 일시 장애 (다음 차례에 다시)' : ''}`);
    pages++;
    const rows = (r.json && r.json.results) || [];
    for (const t of rows) {
      if (since && t.updated_date && new Date(t.updated_date) < since) { stop = true; break; }
      seen[String(t.id)] = taskRow_(t);
      if (!maxUpd || (t.updated_date && t.updated_date > maxUpd)) maxUpd = t.updated_date;
    }
    if (!r.json || !r.json.next) break;
    if ((Date.now() - t0) / 1000 > CFG.SOFT_LIMIT_SEC) { stop = true; break; }
  }

  // 2) 변화: 신규 · 이름 변경 · (전체 맞추기에서) CVAT에서 사라짐
  const tasks = Object.assign({}, prev.tasks);
  const first = !prev.last_full && !Object.keys(prev.tasks).length;
  const changes = [];
  const stamp = now.toISOString();
  for (const [id, row] of Object.entries(seen)) {
    const old = prev.tasks[id];
    if (!old) {
      if (!first) changes.push(change_(stamp, id, 'new', null, row));
    } else if (old.gone || old.name !== row.name) {
      changes.push(change_(stamp, id, old.gone ? 'back' : 'rename', old, row));
    }
    tasks[id] = Object.assign({}, row, { first_seen: old ? old.first_seen : stamp, gone: false, gone_at: null });
  }
  const scanned = Object.keys(seen).length;
  const complete = full && !stop;          // 끝까지 읽은 전체 맞추기에서만 '사라짐'을 판단
  if (complete) {
    for (const [id, old] of Object.entries(prev.tasks)) {
      if (!seen[id] && !old.gone) {
        changes.push(change_(stamp, id, 'gone', old, null));
        tasks[id] = Object.assign({}, old, { gone: true, gone_at: stamp });
      }
    }
  }
  const snap = {
    version: COLLECTOR_VERSION, generated: stamp, host: c.host, org: c.org, project: c.project,
    last_full: complete ? stamp : prev.last_full, max_updated: maxUpd, count: Object.values(tasks).filter((t) => !t.gone).length,
    by_state: countBy_(Object.values(tasks).filter((t) => !t.gone), (t) => (t.state || '(규칙 밖)') + (t.tag ? '_' + t.tag : '')),
    tasks,
  };
  // 4-1) 자동 요청할 사건을 스냅숏보다 먼저 '보낼 목록'(auto_pending.json)에 넣음 (b17 X3)
  //      여기서 실패하면 스냅숏을 바꾸지 않고 실행 실패 → 다음 차례에 같은 변화를 다시 봄
  const queued = first ? null : queueAutoEvents_(c, dir, changes, tasks);
  writeJson_(dir, 'cvat_tasks.json', snap);
  if (changes.length) {
    appendChanges_(dir, changes);
    const recent = (readJson_(dir, 'changes_recent.json') || { changes: [] }).changes.concat(changes).slice(-CFG.RECENT_KEEP);
    writeJson_(dir, 'changes_recent.json', { generated: stamp, changes: recent });
  }

  // 3) 백업·export 요청: 노트북이 CVAT에 요청해 둔 것(대기 목록)의 지금 상태
  const req = checkRequests_(c, dir, t0);

  // 4-2) 보낼 목록의 자동 요청을 만듦 — 실패해도 목록에 남아 다음 차례에 다시 (b17 X3)
  let auto = null;
  try { auto = first ? { skipped: '첫 실행' } : Object.assign({ queued: queued }, queued && queued.off ? { off: queued.off } : {}, flushAutoRequests_(c, dir)); }
  catch (e) { auto = { queued: queued, error: String(e && e.message || e).slice(0, 200), pending: pendingCount_(dir) }; }

  // 5) ULD앱 확장 (Uld.gs): 올린 파일 이름 · 중복 보고 · 직접 업로드 알림 — 끄기: routing.json "uld_ext": false
  let uld = null;
  try {
    uld = first ? { skipped: '첫 실행' } : typeof uldAfterCollect_ === 'function' ? uldAfterCollect_(c, dir, snap, changes, t0) : { skipped: 'Uld.gs 없음' };
  } catch (e) { uld = { error: String(e && e.message || e).slice(0, 200) }; }

  const res = {
    ok: true, mode: full ? (complete ? 'full' : 'full(일부)') : 'incremental', first_run: first, pages, scanned,
    tasks: snap.count, changes: changes.length,
    change_summary: countBy_(changes, (x) => x.kind), requests: req, auto: auto, uld: uld, sec: Math.round((Date.now() - t0) / 100) / 10,
  };
  writeHeartbeat_(c, t0, res);
  return res;
}

function change_(time, id, kind, old, row) {
  return {
    time, task_id: Number(id), kind,
    old_name: old ? old.name : '', new_name: row ? row.name : '',
    old_state: old ? stateLabel_(old) : '', new_state: row ? stateLabel_(row) : '',
    updated: row ? row.updated : (old ? old.updated : ''),
  };
}
const stateLabel_ = (r) => (r.rule_ok ? (r.state || '') + (r.tag ? '_' + r.tag : '') : '(규칙 밖)');
const countBy_ = (arr, fn) => arr.reduce((m, x) => { const k = fn(x); m[k] = (m[k] || 0) + 1; return m; }, {});

/* ---------------- 백업·export 요청 상태 ---------------- */
function checkRequests_(c, dir, t0) {
  const base = DriveApp.getFolderById(c.base);
  const items = [];
  [['backup', 'backups', 'pending_backups.csv'], ['export', 'exports', 'pending_exports.csv']].forEach(([kind, sub, file]) => {
    const rows = readCsv_(base, sub, file);
    const last = {};
    rows.forEach((r) => { if (r.task_id) last[r.task_id + '|' + (r.kind || '') + '|' + (r.format || '')] = r; });   // TASK마다 마지막 줄
    Object.values(last).filter((r) => OPEN_PENDING.includes(r.status) && r.rq_id).forEach((r) => items.push({ kind, row: r }));
  });
  const prev = (readJson_(dir, 'requests.json') || { items: [] }).items;
  const prevBy = {}; prev.forEach((x) => (prevBy[x.rq_id] = x));
  const out = [];
  let checked = 0;
  for (const { kind, row } of items) {
    const base_ = { kind, task_id: Number(row.task_id), task_name: row.task_name, rq_id: row.rq_id, request_time: row.request_time,
                    notebook_status: row.status, format: row.format || '', org: row.org || '' };
    if (checked >= CFG.REQ_MAX || (Date.now() - t0) / 1000 > CFG.SOFT_LIMIT_SEC) { out.push(Object.assign({}, prevBy[row.rq_id] || {}, base_)); continue; }
    const r = api_(c, '/api/requests/' + encodeURIComponent(row.rq_id));
    checked++;
    let st, msg = '', prog = '';
    if (r.code === 200 && r.json) {
      const s = String(r.json.status || '').toLowerCase();
      st = s === 'finished' ? '준비됨' : s === 'failed' ? '실패' : (s === 'queued' || s === 'started') ? '준비 중' : (s || '알 수 없음');
      msg = r.json.message || ''; prog = r.json.progress != null ? r.json.progress : '';
    } else if (r.code === 404 || r.code === 410) {
      st = '확인 불가'; msg = 'CVAT에 없음 — 만료됐거나, 다른 계정이 요청한 것 (요청한 계정만 볼 수 있을 수 있음)';
    } else if (r.code === 403) {
      st = '확인 불가'; msg = '권한 없음 — 요청한 계정과 수집기 계정이 다름';
    } else {
      st = '확인 실패'; msg = 'HTTP ' + r.code;
    }
    out.push(Object.assign(base_, { cvat_status: st, message: String(msg).slice(0, 200), progress: prog, checked: new Date().toISOString() }));
  }
  writeJson_(dir, 'requests.json', { generated: new Date().toISOString(), items: out });
  return { open: items.length, checked, by_status: countBy_(out, (x) => x.cvat_status || '미확인') };
}

/* ---------------- Drive ---------------- */
function statusDir_(c) {
  const base = DriveApp.getFolderById(c.base);
  const it = base.getFoldersByName(STATUS_DIR);
  return it.hasNext() ? it.next() : base.createFolder(STATUS_DIR);
}

function fileIn_(folder, name) {
  const it = folder.getFilesByName(name);
  return it.hasNext() ? it.next() : null;
}

function readJson_(folder, name) {
  const f = fileIn_(folder, name);
  if (!f) return null;
  try { return JSON.parse(f.getBlob().getDataAsString('UTF-8')); } catch (e) { return null; }
}

function writeJson_(folder, name, obj) {
  const text = JSON.stringify(obj, null, 1);
  const f = fileIn_(folder, name);
  if (f) f.setContent(text); else folder.createFile(name, text, 'application/json');
}

function readCsv_(base, sub, name) {
  const it = base.getFoldersByName(sub);
  if (!it.hasNext()) return [];
  const f = fileIn_(it.next(), name);
  if (!f) return [];
  let text = f.getBlob().getDataAsString('UTF-8').replace(/^﻿/, '');
  const rows = Utilities.parseCsv(text);
  if (!rows.length) return [];
  const head = rows[0];
  return rows.slice(1).filter((r) => r.length > 1).map((r) => { const o = {}; head.forEach((h, i) => (o[h] = r[i] || '')); return o; });
}

const CHANGE_COLS = ['time', 'task_id', 'kind', 'old_name', 'new_name', 'old_state', 'new_state', 'updated'];
function appendChanges_(dir, changes) {
  const name = `changes_${changes[0].time.slice(0, 7).replace('-', '')}.csv`;
  const q = (v) => { const s = String(v == null ? '' : v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  const lines = changes.map((x) => CHANGE_COLS.map((k) => q(k === 'kind' ? KIND_KO[x.kind] || x.kind : x[k])).join(',')).join('\n') + '\n';
  const f = fileIn_(dir, name);
  if (f) f.setContent(f.getBlob().getDataAsString('UTF-8') + lines);
  else dir.createFile(name, '﻿' + CHANGE_COLS.join(',') + '\n' + lines, 'text/csv');
}
const KIND_KO = { new: '신규', rename: '이름 변경', gone: 'CVAT에서 사라짐', back: '다시 나타남' };

function writeHeartbeat_(c, t0, res) {
  const dir = statusDir_(c);
  const prev = readJson_(dir, 'collector.json') || { runs: [] };
  const run = Object.assign({ time: new Date().toISOString(), sec: Math.round((Date.now() - t0) / 100) / 10 }, res);
  const runs = (prev.runs || []).concat([{ time: run.time, ok: run.ok, mode: run.mode, changes: run.changes, sec: run.sec, error: run.error }]).slice(-30);
  writeJson_(dir, 'collector.json', {     // time·ok는 맨 위에도 — Keeper의 멈춤 감시가 읽음 (b17 X5)
    version: COLLECTOR_VERSION, time: run.time, ok: !!res.ok, every_min: CFG.EVERY_MIN, last: run,
    last_ok: res.ok ? run.time : prev.last_ok || null, runs,
  });
}

/* ---------------- 설정 파일·폴더 ---------------- */
function readRouting_(baseFolder) {
  const cfgDir = getSub_(baseFolder, ['config']);
  if (!cfgDir) return {};
  return readJson_(cfgDir, 'routing.json') || {};          // v4.33: 수집기는 auto_on_aa 스위치만 읽음
}


function ensureSub_(base, parts) {
  let cur = base;
  for (const p of parts) {
    const it = cur.getFoldersByName(p);
    cur = it.hasNext() ? it.next() : cur.createFolder(p);
  }
  return cur;
}

function getSub_(base, parts) {
  let cur = base;
  for (const p of parts) {
    const it = cur.getFoldersByName(p);
    if (!it.hasNext()) return null;
    cur = it.next();
  }
  return cur;
}


const AUTO_FILE = 'auto_requests.json';
// 검토 단계 상태 — 이 상태로 바뀌면 export (11/12 결정). uld는 올린 직후 상태
const VF_STATES = KNOWN_STATES.filter((x) => x !== 'uld');

/**
 * 자동 요청 (11/12 결정, v4.33.0에 넣음)
 *   backup: TASK가 _uld로 올라올 때 — 원본 영상 보존이 목적. videos/에 영상이 있거나 ULD 장부에 있으면(clip이 원본) 하지 않음
 *   export: 이름이 검토 단계(vf·vf_r1·vf_r2·vfdf·vfdf_ok·…)로 바뀔 때마다 — 검토자가 고친 라벨을 받음
 *   _AA 감지로 하던 export·backup은 그만둠
 * 범위: Script Properties의 AUTO_PROJECT_ID 프로젝트의 TASK만 (비우면 자동 요청을 하지 않음).
 *       AUTO_NAME_PREFIX가 있으면 그 글자로 시작하는 TASK만 (예행 연습: REH_)
 * 끄기: config/routing.json 에 "auto_requests": false (전부) · "auto_backup_uld": false · "auto_export_vf": false
 */
function autoEvents_(c, routing, changes, tasks) {
  if (routing.auto_requests === false) return { off: true };
  if (!c.autoProject) return { off: 'AUTO_PROJECT_ID 없음' };
  const inScope = (id, name) => {
    const t = tasks[String(id)] || {};
    if (String(t.project_id == null ? '' : t.project_id) !== c.autoProject) return false;
    return !c.autoPrefix || String(name || '').indexOf(c.autoPrefix) === 0;
  };
  const backup = [], exp = [];
  changes.forEach((x) => {
    if (x.kind !== 'new' && x.kind !== 'rename' && x.kind !== 'back') return;
    if (!inScope(x.task_id, x.new_name)) return;
    const now = parseName_(x.new_name) || {}, was = x.kind === 'new' ? {} : (parseName_(x.old_name) || {});
    const hit = { id: x.task_id, name: x.new_name, updated: x.updated, state: now.state };
    if (routing.auto_backup_uld !== false && now.state === 'uld' && was.state !== 'uld') backup.push(hit);
    if (routing.auto_export_vf !== false && VF_STATES.indexOf(now.state) >= 0 && now.state !== was.state) exp.push(hit);
  });
  return { backup, export: exp };
}

/* ---- 자동 요청 보낼 목록 (b17 X3, b18 Y2~Y4) ----
 * status/auto_pending.json = { events: {사건키: {kind,id,name,updated,state,at}},
 *                              batches: {요청ID: {kind, keys, at, attempt_at?, file_id?}} }
 *   1) 사건은 스냅숏을 바꾸기 전에 events에 넣음 (넣지 못하면 실행 실패 → 스냅숏도 그대로라 다음에 다시 봄)
 *   2) 묶을 때 요청 ID를 정해 batches에 먼저 저장 → '만들기 시도' 시각 저장 → 요청 파일 → 파일 ID 저장 → 장부 → 목록에서 뺌
 *   3) 같은 TASK·같은 종류의 사건이 여럿이면 최신 하나로 합침 (11/16 결정: export는 그때의 최종 상태를 받음)
 *   4) 다시 할 때: 파일 ID가 있으면 이미 만든 것. '시도'만 있고 ID가 없으면 검색으로 찾고, 못 찾아도
 *      시도 뒤 PENDING_RECHECK_SEC 동안은 다시 만들지 않음 (Drive 검색 반영이 늦을 수 있음)
 *   목록 파일의 형태가 틀리면 던짐 → 수집 실패, 스냅숏 그대로 (관리자가 고칠 때까지 사건을 잃지 않음)
 */
const PENDING_FILE = 'auto_pending.json';
const PENDING_RECHECK_SEC = 600;
const AUTO_KINDS_ = ['export', 'backup'];
const evKey_ = (kind, h) => `${kind}:${h.id}:${h.updated || ''}`;
const isMap_ = (x) => !!x && typeof x === 'object' && !Array.isArray(x);
function pendingProblem_(o) {
  if (!isMap_(o)) return 'top';
  if (!isMap_(o.events)) return 'events';
  if (!isMap_(o.batches)) return 'batches';
  for (const [k, e] of Object.entries(o.events)) {
    if (!isMap_(e) || AUTO_KINDS_.indexOf(e.kind) < 0 || !isFinite(Number(e.id)) || e.id === null || e.id === ''
      || typeof e.name !== 'string' || (e.updated != null && typeof e.updated !== 'string')) return 'event:' + k;
    if (k !== evKey_(e.kind, e)) return 'event_key:' + k;
  }
  for (const [id, b] of Object.entries(o.batches)) {
    if (!isMap_(b) || AUTO_KINDS_.indexOf(b.kind) < 0 || !Array.isArray(b.keys)) return 'batch:' + id;
    for (const k of b.keys) if (typeof k !== 'string' || !o.events[k] || o.events[k].kind !== b.kind) return 'batch_key:' + id;
    if (b.file_id != null && typeof b.file_id !== 'string') return 'batch_file:' + id;
    if (b.attempt_at != null && typeof b.attempt_at !== 'string') return 'batch_attempt:' + id;
  }
  return '';
}
function readPending_(dir) {
  const f = fileIn_(dir, PENDING_FILE);
  if (!f) return { events: {}, batches: {} };
  const o = JSON.parse(f.getBlob().getDataAsString('UTF-8'));   // 읽기·해석 실패는 그대로 던짐 (빈 목록으로 덮지 않음)
  const bad = pendingProblem_(o);
  if (bad) throw new Error(`${PENDING_FILE} 형태가 틀림 (${bad}) — 관리자가 확인할 때까지 수집을 멈춤 (스냅숏 그대로)`);
  return o;
}
function pendingCount_(dir) { try { return Object.keys(readPending_(dir).events).length; } catch (e) { return null; } }

/** 변화에서 자동 요청 사건을 골라 보낼 목록에 넣음. 이미 장부에 같은 수정 시각으로 있거나 목록에 있으면 건너뜀 */
function queueAutoEvents_(c, dir, changes, tasks) {
  const base = DriveApp.getFolderById(c.base);
  const ev = autoEvents_(c, readRouting_(base), changes, tasks);
  if (ev.off) return { off: ev.off };
  return queueHits_(dir, ev);
}
function queueHits_(dir, lists) {
  const all = [].concat((lists.backup || []).map((h) => ['backup', h]), (lists.export || []).map((h) => ['export', h]));
  if (!all.length) return { found: 0 };
  const log = readJson_(dir, AUTO_FILE) || { items: {} };
  const pend = readPending_(dir);
  let n = 0;
  all.forEach(([kind, h]) => {
    const o = log.items[`${kind}:${h.id}`], k = evKey_(kind, h);
    if ((o && o.updated === h.updated) || pend.events[k]) return;
    pend.events[k] = { kind, id: h.id, name: h.name, updated: h.updated || '', state: h.state, at: new Date().toISOString() };
    n++;
  });
  if (n) writeJson_(dir, PENDING_FILE, pend);
  return { found: all.length, queued: n };
}

/** 사건 목록 → TASK마다 최신 하나 (updated, 같으면 넣은 시각 순) */
function latestPerTask_(evs) {
  const by = {};
  evs.forEach((e) => {
    const k = String(e.id), o = by[k];
    if (!o || String(e.updated) > String(o.updated) || (String(e.updated) === String(o.updated) && String(e.at) > String(o.at))) by[k] = e;
  });
  return Object.keys(by).sort((a, b) => Number(a) - Number(b)).map((k) => by[k]);
}

/** 보낼 목록을 요청 파일로 만듦 */
function flushAutoRequests_(c, dir, by) {
  by = by || 'GAS 자동 (수집기)';
  const pend = readPending_(dir);
  const inBatch = {};
  Object.values(pend.batches).forEach((b) => b.keys.forEach((k) => (inBatch[k] = true)));
  const loose = Object.keys(pend.events).filter((k) => !inBatch[k]).sort();
  const base = DriveApp.getFolderById(c.base);
  const log = readJson_(dir, AUTO_FILE) || { items: {} };
  let skipped = 0, dirty = false;
  // 원본이 이미 있으면 백업하지 않음 (장부에 '건너뜀'으로 남기고 목록에서 뺌)
  const looseBackup = loose.filter((k) => pend.events[k].kind === 'backup');
  if (looseBackup.length) {
    const videos = videoStems_(base);
    const uld = Object.assign({}, uldTaskIds_(c), typeof uldRegistryIds_ === 'function' ? (uldRegistryIds_() || {}) : {});
    looseBackup.forEach((k) => {
      const h = pend.events[k], p = parseName_(h.name), b = (p ? p.base : h.name).toLowerCase();
      if (videos[b] || uld[String(h.id)]) {
        log.items[`backup:${h.id}`] = { name: h.name, updated: h.updated, time: new Date().toISOString(), skipped: 'original_exists' };
        delete pend.events[k]; skipped++; dirty = true;
      }
    });
  }
  // 묶기: 아직 만들기를 시도하지 않은 같은 종류 묶음이 있으면 거기에 합치고(Y3), 없으면 새 요청 ID
  const now = new Date();
  AUTO_KINDS_.forEach((kind) => {
    const keys = loose.filter((k) => pend.events[k] && pend.events[k].kind === kind);
    if (!keys.length) return;
    const open = Object.keys(pend.batches).sort().find((id) => pend.batches[id].kind === kind && !pend.batches[id].attempt_at);
    if (open) pend.batches[open].keys = pend.batches[open].keys.concat(keys);
    else {
      const id = `${Utilities.formatDate(now, 'Asia/Seoul', 'yyyyMMdd_HHmmss')}_${kind === 'export' ? 'ga' : 'gb'}${shortHash_(keys.join('|'))}`;
      pend.batches[id] = { kind, keys, at: now.toISOString() };
    }
    dirty = true;
  });
  if (dirty) writeJson_(dir, PENDING_FILE, pend);
  if (skipped) writeJson_(dir, AUTO_FILE, log);
  // 요청 파일 만들기 → 장부 → 목록에서 빼기 (요청 하나씩)
  const reqDir = ensureSub_(base, ['requests']);
  const made = [];
  let nExp = 0, nBak = 0, waiting = 0;
  for (const id of Object.keys(pend.batches).sort()) {
    const b = pend.batches[id], evs = b.keys.map((k) => pend.events[k]).filter(Boolean);
    const list = latestPerTask_(evs);                                     // 같은 TASK는 최신 하나 (Y3)
    let existed = false;
    if (list.length) {
      let fid = b.file_id || null;
      if (!fid && b.attempt_at) fid = requestExists_(reqDir, id);          // 시도했는데 ID를 못 남김 → 검색
      if (fid) existed = true;
      else if (b.attempt_at && (now.getTime() - Date.parse(b.attempt_at)) / 1000 < PENDING_RECHECK_SEC) {
        waiting++; continue;                                              // 검색 반영을 기다림 (Y4)
      } else {
        b.attempt_at = new Date().toISOString();
        writeJson_(dir, PENDING_FILE, pend);                              // '시도함'을 먼저 남김
        const exp = b.kind === 'export';
        const body = {                               // v4.33: 심판이 읽는 tasks(문자열) + 옛 칸(task_ids)도 함께
          id, kind: b.kind, status: 'pending', created: b.at, by,
          note: exp ? `검토 단계 라벨 확보 (${list.length}개)` : `_uld 원본 영상 보존 — videos/·ULD 장부에 없음 (${list.length}개)`,
          tasks: list.map((h) => String(h.id)), task_ids: list.map((h) => Number(h.id)), task_names: list.map((h) => h.name),
          params: Object.assign(c.org ? { org: c.org } : {},
            exp ? { format: 'CVAT for images 1.1', images: false, mode: 'all' } : { mode: 'all', export_reviewed: false },
            { auto: exp ? 'vf' : 'uld' }), app: 'collector',
        };
        const f = reqDir.createFile(`REQ_${id}__${b.kind}__pending.json`, JSON.stringify(body, null, 1), 'application/json');
        try { b.file_id = f.getId(); writeJson_(dir, PENDING_FILE, pend); } catch (e) { /* 못 남기면 다음에 검색으로 */ }
      }
      made.push({ id, kind: b.kind, n: list.length, merged: evs.length - list.length || undefined, existed: existed || undefined });
      if (b.kind === 'export') nExp += list.length; else nBak += list.length;
      const stamp = new Date().toISOString();
      list.forEach((h) => {
        const n = evs.filter((e) => String(e.id) === String(h.id)).length;
        log.items[`${b.kind}:${h.id}`] = Object.assign({ name: h.name, updated: h.updated, time: stamp, request: id, by }, n > 1 ? { merged: n } : {});
      });
      log.generated = stamp;
      writeJson_(dir, AUTO_FILE, log);
    }
    b.keys.forEach((k) => delete pend.events[k]);
    delete pend.batches[id];
    writeJson_(dir, PENDING_FILE, pend);
  }
  return { export: nExp, backup: nBak, backup_skipped: skipped, requests: made, waiting: waiting || undefined,
    pending: Object.keys(pend.events).length };
}

/** requests/에 이 요청 ID의 파일이 있으면 그 파일 ID (상태가 바뀌어 이름 끝이 달라도). 여럿이면 첫 것 */
function requestExists_(reqDir, id) {
  const it = reqDir.searchFiles(`title contains 'REQ_${id}__' and trashed = false`);
  while (it.hasNext()) { const f = it.next(); if (f.getName().indexOf(`REQ_${id}__`) === 0) return f.getId ? f.getId() : 'found'; }
  return null;
}
function shortHash_(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
  return h.toString(36).slice(0, 5);
}

/** videos/ 폴더(하위 폴더 포함)의 영상 이름(확장자 뺀 소문자) 모음 */
function videoStems_(base) {
  const out = {};
  const root = getSub_(base, ['videos']);
  if (!root) return out;
  const walk = (f, depth) => {
    const it = f.getFiles();
    while (it.hasNext()) { const n = it.next().getName(); out[n.replace(/\.[^.]+$/, '').toLowerCase()] = true; }
    if (depth < 3) { const fi = f.getFolders(); while (fi.hasNext()) walk(fi.next(), depth + 1); }
  };
  walk(root, 0);
  return out;
}

/** 이미 검토 단계인데 export 자동 요청을 한 적이 없는 TASK에 요청 (규칙을 켜기 전부터 있던 것) — backfillVfNow() 또는 backfillVfNow(50) */
function backfillVfNow(maxN) {
  const n = maxN || 20;
  const c = cfg_();
  if (!c.autoProject) throw new Error('AUTO_PROJECT_ID를 먼저 넣으세요');
  const dir = statusDir_(c);
  const base = DriveApp.getFolderById(c.base);
  const snap = readJson_(dir, 'cvat_tasks.json') || { tasks: {} };
  const log = readJson_(dir, AUTO_FILE) || { items: {} };
  const hits = Object.entries(snap.tasks)
    .filter(([id, t]) => !t.gone && VF_STATES.indexOf(t.state) >= 0 && !log.items['export:' + id]
      && String(t.project_id == null ? '' : t.project_id) === c.autoProject && (!c.autoPrefix || String(t.name).indexOf(c.autoPrefix) === 0))
    .map(([id, t]) => ({ id: Number(id), name: t.name, updated: t.updated, state: t.state }))
    .sort((a, b) => String(b.updated).localeCompare(String(a.updated)))
    .slice(0, n);
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) throw new Error('다른 실행이 진행 중입니다. 잠시 뒤 다시 하세요.');
  let r;
  try {
    r = hits.length ? Object.assign(queueHits_(dir, { export: hits, backup: [] }), flushAutoRequests_(c, dir, 'GAS 자동 (검토 단계 기존분)')) : { found: 0 };
  } finally { lock.releaseLock(); }
  console.log(`검토 단계 TASK 중 export 요청을 안 한 것 ${hits.length}개 처리 (최대 ${n}) → ${JSON.stringify(r)}`);
  return r;
}

/** CVAT_UpLoader/registry/tasks/<TASK ID>.json 이 있는 TASK ID 모음 (읽기만).
 *  ULD_ROOT_FOLDER_ID(Uld.gs와 같은 속성)로 찾고, 없으면 내 드라이브 최상위에서 찾음 (A0 계정에서 시험할 때) */
function uldTaskIds_(c) {
  const out = {};
  try {
    let root = null;
    if (c && c.uld) root = DriveApp.getFolderById(c.uld);
    else { const it = DriveApp.getRootFolder().getFoldersByName('CVAT_UpLoader'); if (it.hasNext()) root = it.next(); }
    if (!root) return out;
    const dir = getSub_(root, ['registry', 'tasks']);
    if (!dir) return out;
    const files = dir.getFiles();
    while (files.hasNext()) { const m = /^(\d+)\.json$/.exec(files.next().getName()); if (m) out[m[1]] = true; }
  } catch (e) { console.log('ULD 기록 확인 실패 (백업 판단은 videos/만으로): ' + e); }
  return out;
}
