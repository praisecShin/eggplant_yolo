/**
 * 가지 상태 수집기 (Google Apps Script) — v1.0 (2026-11-02)
 *
 * 5분마다 CVAT에서 TASK 이름·상태 변화와 백업·export 요청의 준비 상태를 읽어
 * Drive eggplant_yolo/status/ 에 저장한다. 이 수집기는 status/ 폴더에만 쓰고,
 * 다른 폴더(relabel/, web/, backups/, exports/)는 읽기만 한다. CVAT에도 읽기만 한다.
 * 예외 (v4.31.4): 이름이 _AA로 끝나게 된 TASK를 찾으면 requests/에 LC 요청 파일(export, 영상이 없으면 backup)을 쓴다.
 *   끄기: config/routing.json 에 "auto_on_aa": false · 기존 _AA TASK는 backfillAaNow()로
 *
 * 만드는 파일 (eggplant_yolo/status/)
 *   cvat_tasks.json      TASK 스냅숏 {id: {name, state, tag, updated, ...}}
 *   changes_YYYYMM.csv   변화 이력 (신규 · 이름 변경 · CVAT에서 사라짐) — 달마다 한 파일
 *   changes_recent.json  최근 변화 500건 (앱이 읽기 쉽게)
 *   requests.json        노트북이 CVAT에 요청한 백업·export의 지금 상태 (준비됨/준비 중/실패/확인 불가)
 *   collector.json       마지막 실행 결과 (앱 위쪽 '수집기 n분 전')
 *
 * 설정 (프로젝트 설정 → 스크립트 속성) — 코드에는 아무것도 적지 않는다
 *   CVAT_TOKEN       CVAT 개인 접근 토큰 (필수)
 *   BASE_FOLDER_ID   Drive eggplant_yolo 폴더 ID (필수)
 *   CVAT_ORG         조직 slug (예: horti, 비우면 조직 구분 없음)
 *   CVAT_HOST        기본 https://app.cvat.ai
 *   CVAT_PROJECT_ID  이 프로젝트의 TASK만 (비우면 조직 전체)
 *
 * 실행할 함수
 *   checkSetup()       설정 확인 (토큰 값은 출력하지 않음)
 *   testOnce()         한 번 수집하고 결과를 로그로
 *   installTrigger()   5분마다 자동 실행 켜기
 *   uninstallTrigger() 자동 실행 끄기
 *   fullSyncNow()      전체 다시 맞추기 (평소에는 하루 한 번 자동)
 *
 * =============================================================================
 * Code.gs v4.31.0 패치: CPU 마스터 정지 신호(jobs/STOP_MASTER.json)가 있으면 깨우지 않기
 *
 * 왜 필요한가: dispatch()는 주간에 web/worker.json 이 stopping=true 이면 '마스터 없음'으로 보고
 * GitHub dispatch로 마스터를 다시 깨웁니다. 패치 없이 대시보드에서 마스터를 멈추면
 * dispatch 트리거가 설치된 경우 5분 안에 다시 켜집니다.
 * (지금 Drive에 status/dispatcher.json 이 없어 dispatch 트리거는 꺼져 있는 것으로 보입니다.)
 *
 * 아래 2곳을 고칩니다.
 *  ─── ① 파일 맨 아래(getSub_ 함수 뒤)에 readMasterHold_() 추가 
 *  ─── ② dispatch_() 안, 마스터를 깨우는 부분을 바꿈 
 * ============================================================================= 
**/


const COLLECTOR_VERSION = '4.31.9';   // 4.31.9: 이름 읽기를 노트북과 맞춤 (_test · vf_rN)
const COLLECTOR_VERSION_PREV = '4.31.5';   // 4.31.5: AA_r1 = AA · ULD(CVAT_UpLoader) 기록이 있으면 영상 있음(백업 요청 안 함) ·   // 4.31.4: _AA 감지 시 자동 export·백업 요청 · CVAT 503/429 다시 시도 (4.31.3.1: 배정 회수)
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
  const p = PropertiesService.getScriptProperties();
  const ghRepo = String(p.getProperty('GITHUB_REPO') || '').trim();
  const ghToken = String(p.getProperty('GITHUB_TOKEN') || '').trim();
  out.push(`GITHUB_REPO (마스터 Wake-On용): ${ghRepo ? ghRepo + ' ✅' : '미설정 ⚠️ (설정 시 CPU 마스터 자동 기상 작동)'}`);
  out.push(`GITHUB_TOKEN (마스터 Wake-On용): ${ghToken ? `있음 (${ghToken.length}자) ✅` : '미설정 ⚠️'}`);
  try {
    const baseFolder = DriveApp.getFolderById(c.base);
    const hb = checkCpuMasterHeartbeat_(baseFolder);
    const hold = readMasterHold_(baseFolder);
    out.push(`CPU 마스터 상태: ${hb.alive ? `켜짐 (${hb.who}, ${hb.age_sec}초 전) ✅` : `꺼짐/응답없음 (마지막 신호 ${hb.age_sec}초 전)`}`);
    if (hold) out.push(`CPU 마스터 정지 보류(STOP_MASTER.json): 활성 중 (by=${hold.by || ''}, time=${hold.time || ''}) 🛑`);
  } catch (e) {}
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
  writeJson_(dir, 'cvat_tasks.json', snap);
  if (changes.length) {
    appendChanges_(dir, changes);
    const recent = (readJson_(dir, 'changes_recent.json') || { changes: [] }).changes.concat(changes).slice(-CFG.RECENT_KEEP);
    writeJson_(dir, 'changes_recent.json', { generated: stamp, changes: recent });
  }

  // 3) 백업·export 요청: 노트북이 CVAT에 요청해 둔 것(대기 목록)의 지금 상태
  const req = checkRequests_(c, dir, t0);

  // 4) v4.31.4: 새로 _AA가 된 TASK → 자동 export(항상)·백업(영상 없을 때) 요청
  let auto = null;
  try { auto = first ? { skipped: '첫 실행' } : autoOnAa_(c, dir, changes); } catch (e) { auto = { error: String(e && e.message || e).slice(0, 200) }; }

  // 5) ULD앱 확장 (Uld.gs): 올린 파일 이름 · 중복 보고 · 직접 업로드 알림 — 끄기: routing.json "uld_ext": false
  let uld = null;
  try { uld = first ? { skipped: '첫 실행' } : uldAfterCollect_(c, dir, snap, changes, t0); } catch (e) { uld = { error: String(e && e.message || e).slice(0, 200) }; }

  const res = {
    ok: true, mode: full ? (complete ? 'full' : 'full(일부)') : 'incremental', first_run: first, pages, scanned,
    tasks: snap.count, changes: changes.length,
    change_summary: countBy_(changes, (x) => x.kind), requests: req, auto_aa: auto, uld: uld, sec: Math.round((Date.now() - t0) / 100) / 10,
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
  writeJson_(dir, 'collector.json', {
    version: COLLECTOR_VERSION, every_min: CFG.EVERY_MIN, last: run, last_ok: res.ok ? run.time : prev.last_ok || null, runs,
  });
}

/* =====================================================================
 * [v4.31.0 마스터 아키텍처]
 *   1) 단일 배정자 (LockService 기반 5분 주기 dispatch)
 *   2) 주간(08:00~19:00 KST) 상시 가동 & 야간(19:00~08:00) 승인제 통제
 *   3) Kaggle CPU 상주 마스터 Wakeup Heartbeat 감시 및 자동 기동
 * ===================================================================== */
const DISPATCH_CFG = {
  DISPATCH_MIN: 5,
  DAY_START_HOUR: 8,
  DAY_END_HOUR: 19,
  MASTER_STALE_SEC: 360,
  SHARD_COMPACT_MIN: 8,
  REASSIGN_MIN_AGE_MIN: 10,   // 4.31.3.1: 대기(pending)로 이만큼 지난 요청만 재배정 (작업자가 막 받는 순간과 겹치지 않게)
};

/* 4.31.3.1: 요청 종류 → 지금 routing.json의 경로 (데이터셋만 만들기는 CPU) */
const CPU_MASTER_KINDS = ['backup', 'export'];     // v4.31.4: CPU 마스터가 실제로 처리하는 종류
function routeFor_(routing, kind, params) {
  let r = (routing.routes && routing.routes[kind]) || (CPU_MASTER_KINDS.includes(kind) ? 'kaggle_cpu' : 'colab');
  if (kind === 'train' && params && params.build_only) r = (routing.routes && routing.routes.train_build) || 'colab';
  // CPU 마스터가 처리하지 않는 종류를 kaggle_cpu로, GPU 작업자(미구현)가 꺼져 있는데 kaggle_gpu로 보내지 않음 → colab
  if (r === 'kaggle_cpu' && !CPU_MASTER_KINDS.includes(kind) && !(kind === 'train' && params && params.build_only)) r = 'colab';
  if ((r === 'kaggle_gpu' || r === 'kaggle_train') && routing.gpu_worker_enabled !== true) r = 'colab';
  return r;
}

/* 4.31.3.1: 요청 파일이 대기(pending)가 된 뒤 지난 분 */
function pendingAgeMin_(item) {
  let t = Date.parse(item.data.created || item.data.time || '');
  if (isNaN(t)) { try { t = item.file.getDateCreated().getTime(); } catch (e) { t = NaN; } }
  return isNaN(t) ? 1e9 : (Date.now() - t) / 60000;
}

function installAllTriggers() {
  uninstallAllTriggers();
  ScriptApp.newTrigger('collect').timeBased().everyMinutes(10).create();
  ScriptApp.newTrigger('dispatch').timeBased().everyMinutes(DISPATCH_CFG.DISPATCH_MIN).create();
  console.log('트리거 설치 완료: collect(10분 주기), dispatch(5분 주기 — 배정 및 CPU 마스터 하트비트 감시)');
}

function uninstallAllTriggers() {
  let n = 0;
  ScriptApp.getProjectTriggers().forEach((t) => {
    if (['collect', 'dispatch'].includes(t.getHandlerFunction())) {
      ScriptApp.deleteTrigger(t);
      n++;
    }
  });
  console.log(`기존 트리거 ${n}개 해제 완료`);
}

function isDaytimeKst_() {
  const h = Number(Utilities.formatDate(new Date(), 'Asia/Seoul', 'H'));
  return h >= DISPATCH_CFG.DAY_START_HOUR && h < DISPATCH_CFG.DAY_END_HOUR;
}

function dispatch() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) {
    console.log('앞선 실행(collect 또는 dispatch)이 진행 중이어서 건너뜀');
    return null;
  }
  const t0 = Date.now();
  try {
    return dispatch_(t0);
  } finally {
    lock.releaseLock();
  }
}

function dispatch_(t0) {
  const c = cfg_();
  const p = PropertiesService.getScriptProperties();
  c.ghToken = String(p.getProperty('GITHUB_TOKEN') || '').trim();
  c.ghRepo = String(p.getProperty('GITHUB_REPO') || '').trim();
  c.kgUser = String(p.getProperty('KAGGLE_USERNAME') || '').trim();
  c.kgKey = String(p.getProperty('KAGGLE_KEY') || '').trim();
  if (!c.base) throw new Error('스크립트 속성 BASE_FOLDER_ID를 먼저 설정하세요');

  const baseFolder = DriveApp.getFolderById(c.base);
  const routing = readRouting_(baseFolder);
  const assignDir = ensureSub_(baseFolder, ['requests', 'assign']);
  const jobsDir = ensureSub_(baseFolder, ['jobs']);
  const daytime = isDaytimeKst_();

  const lcReqDir = ensureSub_(baseFolder, ['requests']);
  const rlReqDir = ensureSub_(baseFolder, ['relabel', 'requests']);
  const pendingList = [
    ...scanPending_(lcReqDir, 'lc'),
    ...scanPending_(rlReqDir, 'relabel'),
  ];

  const assigned = [];
  const reassigned = [];          // 4.31.3.1
  const unqueueGpu = {};          // 4.31.3.1: GPU 대기열(jobs/gpu_queue.json)에서 뺄 요청 id
  const awaitingApproval = [];
  let hasApprovedWork = false;

  for (const item of pendingList) {
    if ((Date.now() - t0) / 1000 > CFG.SOFT_LIMIT_SEC) break;
    const assignName = `ASSIGN_${item.id}.json`;
    const existingAssign = readJson_(assignDir, assignName);
    const params = item.data.params || {};
    const nightApproved = Boolean(params.approve_night || item.data.approved_after_hours || (existingAssign && existingAssign.approved));

    if (!daytime && !nightApproved) {
      if (!existingAssign || existingAssign.status !== 'awaiting_night_approval') {
        writeJson_(assignDir, assignName, {
          req_id: item.id,
          scope: item.scope,
          kind: item.kind,
          route: routeFor_(routing, item.kind, params),
          status: 'awaiting_night_approval',
          approved: false,
          created_at: new Date().toISOString(),
          note: '19:00~08:00 야간 시간대 요청 — 야간 즉시 실행 승인 대기 중 (또는 08:00 주간 시작 시 자동 실행)',
        });
      }
      awaitingApproval.push(item.id);
      continue;
    }

    hasApprovedWork = true;
    if (existingAssign && existingAssign.status === 'assigned') {
      // 4.31.3.1 회수: 아직 아무도 받지 않은(pending) 요청이고, 배정 경로가 지금 routing.json과 다르면 새 경로로 다시 배정
      const routeNow = routeFor_(routing, item.kind, params);
      const oldRoute = String(existingAssign.route || '');
      if (oldRoute && oldRoute !== routeNow && pendingAgeMin_(item) >= DISPATCH_CFG.REASSIGN_MIN_AGE_MIN) {
        const nowIso2 = new Date().toISOString();
        const hist = (existingAssign.history || []).concat([{ time: nowIso2, from: oldRoute, to: routeNow, reason: 'routing.json 변경' }]);
        const re = Object.assign({}, existingAssign, {
          route: routeNow, previous_route: oldRoute, reassigned_at: nowIso2,
          attempt: (Number(existingAssign.attempt) || 1) + 1, history: hist,
        });
        writeJson_(assignDir, assignName, re);
        item.data.assigned_to = routeNow;
        item.data.assigned_at = nowIso2;
        item.file.setContent(JSON.stringify(item.data, null, 1));
        if (oldRoute.indexOf('kaggle_gpu') === 0 || oldRoute === 'kaggle_train') unqueueGpu[item.id] = true;
        reassigned.push({ id: item.id, kind: item.kind, from: oldRoute, to: routeNow, scope: item.scope });
      }
      continue;
    }

    const route = routeFor_(routing, item.kind, params);
    if (item.kind === 'backup') {
      item.data.params = item.data.params || {};
      if (item.data.params.export_reviewed === undefined) {
        item.data.params.export_reviewed = true;
      }
    }

    const nowIso = new Date().toISOString();
    const assignObj = {
      req_id: item.id,
      scope: item.scope,
      kind: item.kind,
      route: route,
      duty_person: currentDuty_(routing),
      assigned_at: nowIso,
      task_ids: item.data.task_ids || params.task_ids || [],
      params: item.data.params || {},
      status: 'assigned',
      approved: true,
      attempt: 1,
    };

    writeJson_(assignDir, assignName, assignObj);
    item.data.assigned_to = route;
    item.data.assigned_at = nowIso;
    item.file.setContent(JSON.stringify(item.data, null, 1));
    assigned.push({ id: item.id, kind: item.kind, route: route, scope: item.scope });
  }


// ─── ② dispatch_() 안, 마스터를 깨우는 부분을 바꿈 by James Claude 2026.11.06 05:41 ───
//
// [바꾸기 전]
//   const masterStatus = checkCpuMasterHeartbeat_(baseFolder);
//   let masterWoken = false;
//   if ((daytime || hasApprovedWork) && !masterStatus.alive) {
//
// [바꾼 뒤]
//   const masterStatus = checkCpuMasterHeartbeat_(baseFolder);
//   const masterHold = readMasterHold_(baseFolder);
//   let masterWoken = false;
//   if ((daytime || hasApprovedWork) && !masterStatus.alive && !masterHold) {
//
// 그리고 같은 함수의 res 객체에 한 줄 추가 (cpu_master_wakeup_sent 줄 아래):
//     cpu_master_hold: masterHold ? { by: masterHold.by || '', time: masterHold.time || '', until: masterHold.until || null } : null,
//
// → 대시보드의 Google Apps Script 카드에 '정지 신호 존중'으로 보입니다.

  // 4.31.3.1: 재배정된 요청은 GPU 대기열에서 뺌 (GPU 작업자가 켜져도 집어 가지 않게)
  const unq = Object.keys(unqueueGpu);
  let unqueued = 0;
  if (unq.length) {
    const q = readJson_(jobsDir, 'gpu_queue.json');
    if (q && Array.isArray(q.items)) {
      const before = q.items.length;
      q.items = q.items.filter((x) => !unqueueGpu[x.req_id]);
      unqueued = before - q.items.length;
      if (unqueued) { q.updated = new Date().toISOString(); writeJson_(jobsDir, 'gpu_queue.json', q); }
    }
  }

  // Kaggle CPU 상주 마스터 하트비트 점검 및 기동 (주간 08:00~19:00 상시 또는 야간 승인 작업 존재 시)
  const masterStatus = checkCpuMasterHeartbeat_(baseFolder);
  const masterHold = readMasterHold_(baseFolder);
  let masterWoken = false;
  if ((daytime || hasApprovedWork) && !masterStatus.alive && !masterHold) {
    masterWoken = wakeUpCpuMaster_(c, routing, daytime ? 'daytime_keepalive' : 'night_approved_job');
  }

  const res = {
    ok: true,
    version: COLLECTOR_VERSION,
    time: new Date().toISOString(),
    daytime_kst: daytime,
    cpu_master_alive: masterStatus.alive,
    cpu_master_age_sec: masterStatus.age_sec,
    cpu_master_wakeup_sent: masterWoken,
    cpu_master_hold: masterHold ? { by: masterHold.by || '', time: masterHold.time || '', until: masterHold.until || null } : null,
    assigned: assigned,
    reassigned: reassigned,
    gpu_queue_removed: unqueued,
    awaiting_night_approval: awaitingApproval,
    sec: Math.round((Date.now() - t0) / 100) / 10,
  };
  writeJson_(statusDir_(c), 'dispatcher.json', res);
  return res;
}

function checkCpuMasterHeartbeat_(baseFolder) {
  const webDir = getSub_(baseFolder, ['web']);
  if (!webDir) return { alive: false, age_sec: 999999 };
  const w = readJson_(webDir, 'worker.json');
  if (!w || w.stopping || !w.heartbeat) return { alive: false, age_sec: 999999 };
  const hbMs = Date.parse(w.heartbeat);
  if (isNaN(hbMs)) return { alive: false, age_sec: 999999 };
  const ageSec = Math.round((Date.now() - hbMs) / 1000);
  return { alive: ageSec <= DISPATCH_CFG.MASTER_STALE_SEC, age_sec: ageSec, who: w.who || '' };
}

function wakeUpCpuMaster_(c, routing, reason) {
  const kcfg = (routing && routing.kaggle_kernels) || {};
  const slug = kcfg.cpu_master_slug || 'eggplant-cpu-master';
  if (!c.ghToken || !c.ghRepo) {
    console.log('⚠️ [Wake-On 건너뜀] 스크립트 속성에 GITHUB_TOKEN 또는 GITHUB_REPO가 설정되지 않아 CPU 마스터 자동 기상을 호출할 수 없습니다.');
    return false;
  }
  const ok = triggerGhDispatch_(c, 'eggplant_kaggle_launcher', {
    slot: 'cpu_master',
    kernel_slug: slug,
    enable_gpu: false,
    reason: reason,
    triggered_at: new Date().toISOString(),
  });
  if (ok) {
    console.log(`🚀 [Wake-On 전송 완료] GitHub Actions(${c.ghRepo}) -> Kaggle CPU 마스터(${slug}) 기동 요청 (사유: ${reason})`);
  } else {
    console.log(`⛔ [Wake-On 전송 실패] GitHub API 호출 실패 (${c.ghRepo}) — GITHUB_TOKEN 권한(repo/workflow)을 확인하세요.`);
  }
  return ok;
}

function approveNightRequests() {
  const c = cfg_();
  const baseFolder = DriveApp.getFolderById(c.base);
  const assignDir = ensureSub_(baseFolder, ['requests', 'assign']);
  const it = assignDir.getFiles();
  let cnt = 0;
  while (it.hasNext()) {
    const f = it.next();
    if (!f.getName().startsWith('ASSIGN_')) continue;
    try {
      const d = JSON.parse(f.getBlob().getDataAsString('UTF-8') || '{}');
      if (d.status === 'awaiting_night_approval') {
        d.status = 'assigned';
        d.approved = true;
        d.approved_at = new Date().toISOString();
        f.setContent(JSON.stringify(d, null, 2));
        cnt++;
      }
    } catch (e) {}
  }
  console.log(`야간 대기 요청 ${cnt}건 승인 완료`);
  if (cnt > 0) dispatch();
}

function readRouting_(baseFolder) {
  const cfgDir = ensureSub_(baseFolder, ['config']);
  return readJson_(cfgDir, 'routing.json') || {
    version: 2,
    people: { p1: { name: '신재웅', weekly_gpu_h: 30 } },
    duty: { mon: 'p1', tue: 'p1', wed: 'p1', thu: 'p1', fri: 'p1', sat: 'p1', sun: 'p1' },
    routes: { backup: 'kaggle_cpu', export: 'kaggle_cpu', upload: 'kaggle_cpu', cleanup: 'kaggle_cpu', shape: 'kaggle_gpu', track: 'kaggle_gpu', aa: 'kaggle_gpu', compare: 'kaggle_gpu', train: 'kaggle_gpu' },
  };
}

function currentDuty_(routing) {
  const now = new Date();
  const ymd = Utilities.formatDate(now, 'Asia/Seoul', 'yyyy-MM-dd');
  if (routing.overrides && routing.overrides[ymd]) return routing.overrides[ymd];
  const dayKey = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'][now.getDay()];
  return (routing.duty && routing.duty[dayKey]) || 'p1';
}

function scanPending_(folder, scope) {
  const out = [];
  const it = folder.getFiles();
  const re = /^REQ_([0-9A-Za-z_.-]+?)__([a-z]+)__pending\.json$/;
  while (it.hasNext()) {
    const f = it.next();
    const m = re.exec(f.getName());
    if (!m) continue;
    let data = {};
    try { data = JSON.parse(f.getBlob().getDataAsString('UTF-8') || '{}'); } catch (e) { continue; }
    out.push({ id: m[1], kind: m[2], scope: scope, file: f, folder: folder, data: data });
  }
  out.sort((a, b) => String(a.data.created || a.id).localeCompare(String(b.data.created || b.id)));
  return out;
}

function triggerGhDispatch_(c, eventType, clientPayload) {
  const url = `https://api.github.com/repos/${c.ghRepo}/dispatches`;
  const r = UrlFetchApp.fetch(url, {
    method: 'post',
    headers: {
      Authorization: 'Bearer ' + c.ghToken,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    contentType: 'application/json',
    payload: JSON.stringify({ event_type: eventType, client_payload: clientPayload }),
    muteHttpExceptions: true,
  });
  return r.getResponseCode() === 204;
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

// ─── ① 파일 맨 아래(getSub_ 함수 뒤)에 추가 ──────────────────────────────────
function readMasterHold_(baseFolder) {
  const jobsDir = getSub_(baseFolder, ['jobs']);
  if (!jobsDir) return null;
  const f = fileIn_(jobsDir, 'STOP_MASTER.json');
  if (!f) return null;
  let d = {};
  try { d = JSON.parse(f.getBlob().getDataAsString('UTF-8').replace(/^﻿/, '') || '{}'); } catch (e) { d = {}; }
  if (d.until && Date.parse(d.until) <= Date.now()) return null;   // 기한 지남 → 무효
  return d;
}

/* =====================================================================
 * [v4.31.3 추가] CPU 마스터 & GPU 워커 원격 기상(Wake-On) / 정지(Stop) / 재개 제어 함수
 * - Apps Script 에디터 상단 드롭다운에서 선택하여 즉시 수동 실행하거나 트리거 연동 가능
 * ===================================================================== */

/**
 * 1) CPU 마스터 수동 즉시 기상 (Wake-On)
 * - 기존 정지 보류(jobs/STOP_MASTER.json)가 있으면 자동 해제한 뒤,
 *   GitHub Actions 점화기(repository_dispatch + workflow_dispatch 이중 폴백)로
 *   Kaggle CPU 마스터 노트북(eggplant-cpu-master)을 즉시 원격 기동합니다.
 */
function wakeCpuMasterNow() {
  const c = cfg_();
  const p = PropertiesService.getScriptProperties();
  c.ghToken = String(p.getProperty('GITHUB_TOKEN') || '').trim();
  c.ghRepo = String(p.getProperty('GITHUB_REPO') || '').trim();
  if (!c.base) throw new Error('BASE_FOLDER_ID 스크립트 속성을 먼저 설정하세요.');

  const baseFolder = DriveApp.getFolderById(c.base);
  const routing = readRouting_(baseFolder);

  // 정지 신호(STOP_MASTER.json)가 남아 있으면 제거하여 기상 허용
  const jobsDir = ensureSub_(baseFolder, ['jobs']);
  removeFileIn_(jobsDir, 'STOP_MASTER.json');

  const ok = wakeUpCpuMaster_(c, routing, 'manual_wake_from_gas');
  const res = {
    ok: ok,
    action: 'wakeCpuMasterNow',
    time: new Date().toISOString(),
    repo: c.ghRepo || '(GITHUB_REPO 미설정)',
    note: ok
      ? 'GitHub Actions 점화기(eggplant_kaggle_launcher) 호출 성공 → 약 1~2분 내 Kaggle CPU 마스터가 기동됩니다.'
      : '기상 신호 전송 실패 — 스크립트 속성에 GITHUB_TOKEN 및 GITHUB_REPO(예: 아이디/저장소명)가 설정되어 있는지 확인하세요.',
  };
  console.log(JSON.stringify(res, null, 2));
  return res;
}

/**
 * 2) CPU 마스터 (및 GPU 워커) 원격 안전 종료 & 자동 재기동 방지(Hold)
 * - jobs/STOP_MASTER.json 및 jobs/STOP_GPU.json을 생성합니다.
 * - STOP_MASTER.json이 존재하는 동안에는 5분 주기 dispatch()가 돌아도
 *   readMasterHold_()가 이를 감지하여 마스터를 다시 깨우지 않습니다 ('정지 신호 존중').
 */
function stopCpuMasterNow() {
  const c = cfg_();
  if (!c.base) throw new Error('BASE_FOLDER_ID 스크립트 속성을 먼저 설정하세요.');
  const baseFolder = DriveApp.getFolderById(c.base);
  const jobsDir = ensureSub_(baseFolder, ['jobs']);

  const nowIso = new Date().toISOString();
  const holdObj = {
    by: 'GAS 관리자 (stopCpuMasterNow)',
    time: nowIso,
    reason: 'GAS에서 원격 안전 종료 요청',
    stop_gpu: true,
    until: null, // 무기한 보류 (resumeCpuMasterNow 또는 wakeCpuMasterNow 실행 시 해제)
  };

  writeJson_(jobsDir, 'STOP_MASTER.json', holdObj);
  writeJson_(jobsDir, 'STOP_GPU.json', {
    by: 'GAS 관리자 (stopCpuMasterNow)',
    time: nowIso,
    reason: 'CPU 마스터 종료에 따른 동반 안전 종료',
  });

  console.log('🛑 STOP_MASTER.json 및 STOP_GPU.json 생성 완료 — 30초 내 마스터가 종료되며, 재기동 보류(Hold) 상태가 유지됩니다.');
  return holdObj;
}

/**
 * 3) GPU 워커만 단독 비상 정지 (CPU 마스터는 계속 가동 유지)
 */
function stopGpuWorkerNow() {
  const c = cfg_();
  if (!c.base) throw new Error('BASE_FOLDER_ID 스크립트 속성을 먼저 설정하세요.');
  const baseFolder = DriveApp.getFolderById(c.base);
  const jobsDir = ensureSub_(baseFolder, ['jobs']);

  const payload = {
    by: 'GAS 관리자 (stopGpuWorkerNow)',
    time: new Date().toISOString(),
    reason: 'GPU 워커 단독 비상 정지',
  };
  writeJson_(jobsDir, 'STOP_GPU.json', payload);
  console.log('🛑 STOP_GPU.json 생성 완료 — 실행 중인 GPU 워커가 안전 종료됩니다.');
  return payload;
}

/**
 * 4) CPU 마스터 정지 보류(Hold) 해제 후 즉시 재기상 및 배정 실행
 */
function resumeCpuMasterNow() {
  const c = cfg_();
  if (!c.base) throw new Error('BASE_FOLDER_ID 스크립트 속성을 먼저 설정하세요.');
  const baseFolder = DriveApp.getFolderById(c.base);
  const jobsDir = ensureSub_(baseFolder, ['jobs']);

  removeFileIn_(jobsDir, 'STOP_MASTER.json');
  removeFileIn_(jobsDir, 'STOP_GPU.json');
  console.log('✅ STOP_MASTER.json 및 STOP_GPU.json 정지 신호 해제 완료 → dispatch()를 실행하여 마스터를 깨웁니다.');
  return dispatch();
}

function removeFileIn_(folder, name) {
  const it = folder.getFilesByName(name);
  while (it.hasNext()) {
    it.next().setTrashed(true);
  }
}


/* ---------------- v4.31.4: _AA 감지 → 자동 export·백업 요청 ----------------
 * TASK 이름이 _AA로 끝나게 되면(새로 생김 · uld→AA 이름 변경) LC 요청 파일을 requests/에 쓴다.
 *  - 라벨 export(CVAT for images 1.1, 이미지 없이)는 항상 → 자동 라벨(annotation_A) 확보
 *  - 백업은 Drive videos/에 원본 영상이 없을 때만
 *  - 중복 방지: status/auto_requests.json (TASK ID + CVAT 수정 시각) · 한 번 실행에 종류별 요청 하나로 묶음
 *  - 배정(dispatch)은 다른 요청과 같이 routing.json을 따름 · 야간에 생긴 요청은 승인 없이 08시 주간 시작 때 배정
 */
const AUTO_FILE = 'auto_requests.json';

function isAa_(row) {
  if (!row || !row.name) return false;
  if (/_AA(_r\d+)?$/i.test(String(row.name).trim())) return true;        // v4.31.5: AA_r1·AA_r2 = AA
  return /^AA(_r\d+)?$/i.test(String(row.tag || ''));
}

function autoOnAa_(c, dir, changes) {
  const base = DriveApp.getFolderById(c.base);
  const routing = readRouting_(base);
  if (routing.auto_on_aa === false) return { off: true };
  const hits = [];
  changes.forEach((x) => {
    if (x.kind !== 'new' && x.kind !== 'rename' && x.kind !== 'back') return;
    const now = { name: x.new_name, tag: (parseName_(x.new_name) || {}).tag };
    const was = { name: x.old_name, tag: (parseName_(x.old_name) || {}).tag };
    if (isAa_(now) && !isAa_(was)) hits.push({ id: x.task_id, name: x.new_name, updated: x.updated });
  });
  if (!hits.length) return { found: 0 };
  return makeAutoRequests_(c, dir, base, hits, 'GAS 자동 (AA 감지)');
}

function makeAutoRequests_(c, dir, base, hits, by) {
  const log = readJson_(dir, AUTO_FILE) || { items: {} };
  const fresh = hits.filter((h) => { const o = log.items[String(h.id)]; return !o || o.updated !== h.updated; });
  if (!fresh.length) return { found: hits.length, new: 0 };
  const videos = videoStems_(base);
  const uld = uldTaskIds_();                       // v4.31.5: ULD가 만든 TASK는 clip이 원본 → 백업 요청 안 함
  const needBk = fresh.filter((h) => { const p = parseName_(h.name); const b = (p ? p.base : h.name).toLowerCase(); return !videos[b] && !uld[String(h.id)]; });
  const reqDir = ensureSub_(base, ['requests']);
  const made = [];
  const now = new Date();
  const write = (kind, list, params, note) => {
    if (!list.length) return;
    const k = Utilities.formatDate(now, 'Asia/Seoul', 'yyyyMMdd_HHmmss');
    const id = `${k}_${kind === 'export' ? 'ga' : 'gb'}${Math.random().toString(36).slice(2, 4)}`;
    const body = {
      id, kind, status: 'pending', created: now.toISOString(), by, note,
      task_ids: list.map((h) => Number(h.id)), task_names: list.map((h) => h.name),
      params: Object.assign(c.org ? { org: c.org } : {}, params, { auto: 'aa' }), app: 'gas', auto_aa: true,
    };
    reqDir.createFile(`REQ_${id}__${kind}__pending.json`, JSON.stringify(body, null, 1), 'application/json');
    made.push({ id, kind, n: list.length });
  };
  write('export', fresh, { format: 'CVAT for images 1.1', images: false, mode: 'all' }, `AA 자동 라벨 확보 (${fresh.length}개)`);
  write('backup', needBk, { mode: 'all', export_reviewed: false }, `AA 원본 영상 확보 — videos/에 없음 (${needBk.length}개)`);
  const stamp = now.toISOString();
  fresh.forEach((h) => { log.items[String(h.id)] = { name: h.name, updated: h.updated, time: stamp, backup: needBk.includes(h), by }; });
  log.generated = stamp;
  writeJson_(dir, AUTO_FILE, log);
  return { found: hits.length, new: fresh.length, backup: needBk.length, requests: made };
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

/** 이미 _AA인 TASK에 대해 자동 요청을 만듦 (켜기 전부터 있던 것) — 실행: backfillAaNow() 또는 backfillAaNow(50) */
function backfillAaNow(maxN) {
  const n = maxN || 20;
  const c = cfg_();
  const dir = statusDir_(c);
  const base = DriveApp.getFolderById(c.base);
  const snap = readJson_(dir, 'cvat_tasks.json') || { tasks: {} };
  const log = readJson_(dir, AUTO_FILE) || { items: {} };
  const hits = Object.entries(snap.tasks)
    .filter(([id, t]) => !t.gone && isAa_(t) && !log.items[id])
    .map(([id, t]) => ({ id: Number(id), name: t.name, updated: t.updated }))
    .sort((a, b) => String(b.updated).localeCompare(String(a.updated)))
    .slice(0, n);
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) throw new Error('다른 실행이 진행 중입니다. 잠시 뒤 다시 하세요.');
  let r;
  try { r = hits.length ? makeAutoRequests_(c, dir, base, hits, 'GAS 자동 (AA 기존분)') : { found: 0 }; } finally { lock.releaseLock(); }
  console.log(`기존 _AA TASK 중 아직 자동 요청 안 한 것 ${hits.length}개 처리 (최대 ${n}) → ${JSON.stringify(r)}`);
  return r;
}

/** 내 드라이브 최상위 CVAT_UpLoader/registry/tasks/<TASK ID>.json 이 있는 TASK ID 모음 (읽기만 — v4.31.5) */
function uldTaskIds_() {
  const out = {};
  try {
    const it = DriveApp.getRootFolder().getFoldersByName('CVAT_UpLoader');
    if (!it.hasNext()) return out;
    const dir = getSub_(it.next(), ['registry', 'tasks']);
    if (!dir) return out;
    const files = dir.getFiles();
    while (files.hasNext()) { const m = /^(\d+)\.json$/.exec(files.next().getName()); if (m) out[m[1]] = true; }
  } catch (e) { console.log('ULD 기록 확인 실패 (백업 판단은 videos/만으로): ' + e); }
  return out;
}
