/**
 * ULD앱(CVAT_UpLoader) 확장 — v1.0 (2026-11-10)
 *
 * Code.gs의 collect_()가 끝날 때 uldAfterCollect_()를 부른다 (Code.gs에는 3줄만 추가).
 * Code.gs의 함수(api_, readJson_, writeJson_, readCsv_, readRouting_, getSub_, fileIn_)를 그대로 쓴다.
 *
 * 하는 일
 *  1) 올린 영상 파일 이름 수집 → status/cvat_data_files.json
 *     '신규' TASK부터, 그다음 아직 모르는 TASK를 실행마다 조금씩(기본 20개) CVAT에 물어 채운다.
 *  2) 같은 프로젝트 안 중복 묶음 → status/cvat_duplicates.json
 *     · 이름 앞부분(base, 상태 꼬리를 뺀 이름)이 같은 TASK
 *     · 올린 영상 파일 이름이 같은 TASK
 *  3) 새로 생긴 중복 · 최근 직접 업로드(ULD 장부에 없는 신규 TASK) → status/uld_alerts.json (+ 메일)
 *  4) 원본 목록 → CVAT_UpLoader/registry/sources.json (v1.1)
 *     GoPro_RAW의 원본마다: 상태(미처리·요청 대기·처리 중·오류·중복·완료), ULD로 만든 TASK, CVAT에 이미 있는 TASK
 *
 * 스크립트 속성 (모두 선택)
 *   ULD_ALERT_EMAIL     알림 받을 메일 주소 (비우면 메일을 보내지 않음)
 *   ULD_ROOT_FOLDER_ID  Drive CVAT_UpLoader 폴더 ID (있으면 ULD 장부로 '직접 업로드'를 가려냄, 원본 목록도 이 폴더에 씀)
 *   ULD_SOURCE_FOLDER_ID  Drive GoPro_RAW 폴더 ID (비우면 이름이 GoPro_RAW인 폴더를 찾음)
 * 끄기: config/routing.json 에 "uld_ext": false
 *
 * 수동 실행
 *   uldReportNow()      지금 중복 보고서·원본 목록만 다시 만들기 (CVAT 호출 없음)
 *   uldCheckSetup()     설정 확인
 */
const ULD_VERSION = '1.1';   // 1.1: 원본 목록(sources.json) · 1.0.1: '직접 업로드' 판단을 장부만으로
const ULD_CFG = {
  META_PER_RUN: 20,        // 한 번에 파일 이름을 물어볼 TASK 수
  META_SEC_BUDGET: 60,     // 그 일에 쓸 최대 시간(초)
  META_MAX_TRIES: 3,       // 데이터가 아직 없는 TASK는 이만큼만 다시 시도
  ALERT_KEEP: 300,
  MAIL_MAX_LINES: 40,
};
const ULD_FILES = { data: 'cvat_data_files.json', dups: 'cvat_duplicates.json', alerts: 'uld_alerts.json' };

/* ---------------- 진입점 (collect_ 끝에서) ---------------- */
function uldAfterCollect_(c, dir, snap, changes, t0) {
  const base = DriveApp.getFolderById(c.base);
  if (readRouting_(base).uld_ext === false) return { off: true };
  const out = { version: ULD_VERSION };
  const data = readJson_(dir, ULD_FILES.data) || { files: {} };
  out.meta = uldFillDataFiles_(c, snap.tasks, data, changes, t0);
  if (out.meta.asked) { data.generated = new Date().toISOString(); writeJson_(dir, ULD_FILES.data, data); }
  const r = uldReport_(c, dir, snap.tasks, data, changes);
  try { out.sources = uldSources_(snap.tasks, data.files || {}); } catch (e) { out.sources = { error: String(e && e.message || e).slice(0, 200) }; }
  return Object.assign(out, r);
}

/* ---------------- 1) 올린 파일 이름 ---------------- */
function uldFillDataFiles_(c, tasks, data, changes, t0) {
  const files = data.files || (data.files = {});
  const want = [];
  const push = (id) => { id = String(id); const t = tasks[id]; const d = files[id];
    if (!t || t.gone || want.includes(id)) return;
    if (d && (d.checked || (d.tries || 0) >= ULD_CFG.META_MAX_TRIES)) return;
    want.push(id); };
  changes.filter((x) => x.kind === 'new' || x.kind === 'back').forEach((x) => push(x.task_id));
  Object.keys(tasks).sort((a, b) => Number(b) - Number(a)).forEach((id) => { if (want.length < ULD_CFG.META_PER_RUN * 3) push(id); });
  const t1 = Date.now();
  let asked = 0, filled = 0;
  for (const id of want) {
    if (asked >= ULD_CFG.META_PER_RUN) break;
    if ((Date.now() - t1) / 1000 > ULD_CFG.META_SEC_BUDGET || (Date.now() - t0) / 1000 > CFG.SOFT_LIMIT_SEC - 20) break;
    const r = api_(c, `/api/tasks/${id}/data/meta`);
    asked++;
    const d = files[id] || {};
    if (r.code === 200 && r.json) {
      const fr = r.json.frames || [];
      const one = fr.length === 1 ? String(fr[0].name || '') : '';
      Object.assign(d, { data_file: one, n_items: fr.length, size: r.json.size || 0,
                         frame_filter: r.json.frame_filter || '', checked: new Date().toISOString() });
      if (one) filled++;
    } else {
      d.tries = (d.tries || 0) + 1; d.last_code = r.code;
    }
    files[id] = d;
  }
  const known = Object.keys(tasks).filter((id) => !tasks[id].gone && files[id] && files[id].checked).length;
  const alive = Object.keys(tasks).filter((id) => !tasks[id].gone).length;
  return { asked, filled, known, alive };
}

/* ---------------- 2) 중복 묶음 · 3) 알림 ---------------- */
function uldReport_(c, dir, tasks, data, changes) {
  const uldIds = uldRegistryIds_();
  const files = (data && data.files) || {};
  const groups = uldDupGroups_(tasks, files, uldIds);
  const prevDoc = readJson_(dir, ULD_FILES.dups);
  const freshGroups = prevDoc ? uldNewDups_(prevDoc.groups || [], groups) : [];
  const direct = uldDirectNew_(changes, tasks, files, uldIds);
  const stamp = new Date().toISOString();
  writeJson_(dir, ULD_FILES.dups, {
    version: ULD_VERSION, generated: stamp, host: c.host,
    note: '같은 프로젝트 안에서 이름 앞부분(base) 또는 올린 영상 파일 이름이 같은 TASK 묶음. via: uld = ULD앱으로 만듦, direct = CVAT에 직접 올림, 빈칸 = 알 수 없음',
    uld_registry_rows: uldIds ? Object.keys(uldIds).length : null,
    groups,
  });
  const out = { dup_groups: groups.length, new_dup_groups: freshGroups.length, direct_new: direct.length, first_report: !prevDoc };
  if (freshGroups.length || direct.length) {
    const log = readJson_(dir, ULD_FILES.alerts) || { items: [] };
    freshGroups.forEach((g) => log.items.push({ time: stamp, kind: 'duplicate', match_by: g.match_by, key: g.key, project_id: g.project_id, task_ids: g.tasks.map((t) => t.id) }));
    direct.forEach((d) => log.items.push(Object.assign({ time: stamp, kind: 'direct_upload' }, d)));
    log.items = log.items.slice(-ULD_CFG.ALERT_KEEP);
    log.generated = stamp;
    writeJson_(dir, ULD_FILES.alerts, log);
    out.mail = uldMail_(c, freshGroups, direct);
  }
  return out;
}

function uldDupGroups_(tasks, files, uldIds) {
  const by = {};
  Object.entries(tasks).forEach(([id, t]) => {
    if (t.gone) return;
    const pid = t.project_id == null ? '' : String(t.project_id);
    const f = files[id] || {};
    const keys = [];
    if (t.rule_ok && t.base) keys.push(['base', t.base]);
    if (f.data_file) keys.push(['file', String(f.data_file).toLowerCase()]);
    keys.forEach(([how, k]) => {
      const key = `${pid}|${how}|${k}`;
      (by[key] = by[key] || { project_id: t.project_id, match_by: how, key: k, tasks: [] }).tasks.push(uldMember_(id, t, f, uldIds));
    });
  });
  // 이름 앞부분과 올린 파일이 같은 TASK 묶음이 똑같으면 하나로 합침
  const groups = Object.values(by).filter((g) => g.tasks.length > 1);
  const seenSet = {};
  const merged = [];
  groups.sort((a, b) => (a.match_by === 'base' ? -1 : 1) - (b.match_by === 'base' ? -1 : 1)).forEach((g) => {
    const sig = `${g.project_id}|` + g.tasks.map((t) => t.id).sort((a, b) => a - b).join(',');
    if (seenSet[sig]) { seenSet[sig].match_by = 'base+file'; seenSet[sig].file = g.key; return; }
    seenSet[sig] = g; merged.push(g);
  });
  return merged
    .map((g) => { g.tasks.sort((a, b) => a.id - b.id); g.latest = g.tasks.reduce((m, x) => (x.first_seen > m ? x.first_seen : m), ''); return g; })
    .sort((a, b) => String(b.latest).localeCompare(String(a.latest)));
}

function uldMember_(id, t, f, uldIds) {
  return { id: Number(id), name: t.name, state: stateLabel_(t), frames: t.frames, status: t.status,
           first_seen: t.first_seen || '', updated: t.updated || '', data_file: f.data_file || '', via: uldVia_(id, t, f, uldIds) };
}

/** ULD앱이 만든 TASK인지: ULD 장부에 있는지로만 판단 (기존 업로드도 영상 이름을 TASK 이름으로 지어 와서 파일 이름으로는 구분 못 함) */
function uldVia_(id, t, f, uldIds) {
  if (uldIds && uldIds[String(id)]) return 'uld';
  return uldIds ? 'direct' : '';
}

function uldNewDups_(prevGroups, groups) {
  const prev = {};
  prevGroups.forEach((g) => { prev[`${g.project_id}|${g.match_by}|${g.key}`] = new Set(g.tasks.map((t) => t.id)); });
  return groups.filter((g) => {
    const p = prev[`${g.project_id}|${g.match_by}|${g.key}`];
    return !p || g.tasks.some((t) => !p.has(t.id));
  });
}

function uldDirectNew_(changes, tasks, files, uldIds) {
  if (!uldIds) return [];
  return changes.filter((x) => x.kind === 'new').map((x) => {
    const id = String(x.task_id), t = tasks[id] || {}, f = files[id] || {};
    return { task_id: x.task_id, name: x.new_name, project_id: t.project_id, data_file: f.data_file || '', via: uldVia_(id, t, f, uldIds) };
  }).filter((d) => d.via === 'direct');
}

/** ULD 장부(CVAT_UpLoader/registry/clips_registry.csv) → {task_id: 처음 TASK 이름} · 설정이 없으면 null */
function uldRegistryIds_() {
  const id = String(PropertiesService.getScriptProperties().getProperty('ULD_ROOT_FOLDER_ID') || '').trim();
  if (!id) return null;
  try {
    const rows = readCsv_(DriveApp.getFolderById(id), 'registry', 'clips_registry.csv');
    const out = {};
    rows.forEach((r) => { if (r.task_id && r.task_id !== '0') out[String(r.task_id)] = r.task_name_initial || ''; });
    return out;
  } catch (e) { console.log('ULD 장부 읽기 실패: ' + e); return null; }
}

function uldMail_(c, groups, direct) {
  const to = String(PropertiesService.getScriptProperties().getProperty('ULD_ALERT_EMAIL') || '').trim();
  if (!to) return 'ULD_ALERT_EMAIL 없음 — 메일 안 보냄';
  const link = (id) => `${c.host}/tasks/${id}`;
  const lines = [];
  if (groups.length) {
    lines.push(`■ 새로 생긴 중복 ${groups.length}묶음 (같은 프로젝트)`);
    groups.forEach((g) => {
      lines.push(`- 프로젝트 ${g.project_id} · ${g.match_by === 'file' ? '올린 파일' : '이름 앞부분'} ${g.key}${g.file ? ' (올린 파일도 같음: ' + g.file + ')' : ''}`);
      g.tasks.forEach((t) => lines.push(`    #${t.id} ${t.name} [${t.state}] ${t.via === 'direct' ? '직접 업로드' : t.via === 'uld' ? 'ULD' : ''} ${link(t.id)}`));
    });
  }
  if (direct.length) {
    lines.push('', `■ ULD앱을 거치지 않고 새로 올라온 TASK ${direct.length}건`);
    direct.forEach((d) => lines.push(`- #${d.task_id} ${d.name} (프로젝트 ${d.project_id}${d.data_file ? ', 파일 ' + d.data_file : ''}) ${link(d.task_id)}`));
  }
  const body = lines.slice(0, ULD_CFG.MAIL_MAX_LINES).join('\n') + (lines.length > ULD_CFG.MAIL_MAX_LINES ? `\n… 외 ${lines.length - ULD_CFG.MAIL_MAX_LINES}줄 (status/${ULD_FILES.dups} 참고)` : '')
    + '\n\n자동으로 지우지 않습니다. 라벨 작업이 있는 쪽을 확인한 뒤 정리하세요.';
  try {
    MailApp.sendEmail(to, `[ULD] 새 중복 ${groups.length}묶음 · 직접 업로드 ${direct.length}건`, body);
    return 'sent';
  } catch (e) { return '메일 실패: ' + String(e).slice(0, 120); }
}

/* ---------------- 수동 실행 ---------------- */
function uldReportNow() {
  const c = cfg_();
  const dir = statusDir_(c);
  const snap = readJson_(dir, 'cvat_tasks.json') || { tasks: {} };
  const data = readJson_(dir, ULD_FILES.data) || { files: {} };
  const r = uldReport_(c, dir, snap.tasks, data, []);
  r.sources = uldSources_(snap.tasks, data.files || {});
  console.log(JSON.stringify(r, null, 1));
  return r;
}

function uldCheckSetup() {
  const p = PropertiesService.getScriptProperties();
  const out = [];
  const mail = String(p.getProperty('ULD_ALERT_EMAIL') || '').trim();
  const root = String(p.getProperty('ULD_ROOT_FOLDER_ID') || '').trim();
  out.push(`ULD_ALERT_EMAIL: ${mail ? '있음 ✅' : '없음 (메일 알림 꺼짐)'}`);
  if (root) {
    try { out.push(`ULD_ROOT_FOLDER_ID: ${DriveApp.getFolderById(root).getName()} ✅`); }
    catch (e) { out.push('ULD_ROOT_FOLDER_ID: 열 수 없음 ⛔'); }
    const ids = uldRegistryIds_();
    out.push(`ULD 장부: ${ids ? Object.keys(ids).length + '행' : '읽지 못함'}`);
  } else out.push('ULD_ROOT_FOLDER_ID: 없음 (직접 업로드 구분 꺼짐)');
  const c = cfg_();
  out.push(`CVAT_PROJECT_ID: ${c.project || '(비어 있음 — 조직 전체 수집 ✅)'}`);
  const dir = statusDir_(c);
  const data = readJson_(dir, ULD_FILES.data);
  out.push(`올린 파일 이름 수집: ${data ? Object.values(data.files || {}).filter((d) => d.checked).length + '개' : '아직 없음'}`);
  console.log(out.join('\n'));
  return out;
}


/* ---------------- 4) 원본 목록 (v1.1) ---------------- */
const ULD_VIDEO_RE = /\.(mp4|mov)$/i;
const ULD_REQ_RE = /^req_(\d{8}-\d{6})_(.+?)(?:__(processing|done_t(\d+)|error|duplicate))?\.json$/;

/** 이름 앞부분: 규칙 이름이면 parseName_의 base, 아니면 끝의 상태 꼬리(_uld·_AA·_vf…)를 뗀 이름 */
function uldBase_(name) {
  const n = String(name || '').trim().replace(ULD_VIDEO_RE, '');
  const f = parseName_(n);
  if (f) return f.base;
  return n.replace(/_(uld|aa|test|vf[0-9a-z가-힣_]*)$/i, '');
}

function uldSources_(tasks, files) {
  const p = PropertiesService.getScriptProperties();
  const rootId = String(p.getProperty('ULD_ROOT_FOLDER_ID') || '').trim();
  if (!rootId) return { skipped: 'ULD_ROOT_FOLDER_ID 없음' };
  const root = DriveApp.getFolderById(rootId);
  let src = null;
  const sid = String(p.getProperty('ULD_SOURCE_FOLDER_ID') || '').trim();
  if (sid) src = DriveApp.getFolderById(sid);
  else { const it = DriveApp.getFoldersByName('GoPro_RAW'); if (it.hasNext()) src = it.next(); }
  if (!src) return { skipped: 'GoPro_RAW 폴더를 찾지 못함 (ULD_SOURCE_FOLDER_ID 설정)' };

  // 원본 (하위 폴더 3단계까지)
  const vids = [];
  const walk = (f, path, depth) => {
    const it = f.getFiles();
    while (it.hasNext()) {
      const x = it.next(); const n = x.getName();
      if (ULD_VIDEO_RE.test(n)) vids.push({ name: n, size: x.getSize(), file_id: x.getId(), path: path + n, modified: x.getLastUpdated().toISOString() });
    }
    if (depth < 3) { const fi = f.getFolders(); while (fi.hasNext()) { const d = fi.next(); walk(d, path + d.getName() + '/', depth + 1); } }
  };
  walk(src, '', 0);
  const key = (n, sz) => String(n) + '|' + String(sz || '');

  // ULD 장부: 원본 → TASK
  const reg = {};
  readCsv_(root, 'registry', 'clips_registry.csv').forEach((r) => {
    if (!r.task_id || r.task_id === '0') return;
    reg[key(r.src_name, r.src_bytes)] = { task_id: Number(r.task_id), name: r.task_name_initial, cut: `${r.cut_start_s}~${r.cut_end_s}s`, created: r.created_at };
  });

  // 요청: 원본 → 가장 최근 요청 (완료된 것은 장부에 있으므로 내용을 열지 않음)
  const reqs = {};
  const rdir = getSub_(root, ['requests']);
  if (rdir) {
    const it = rdir.getFiles();
    while (it.hasNext()) {
      const f = it.next(); const m = ULD_REQ_RE.exec(f.getName());
      if (!m || (m[3] || '').indexOf('done') === 0) continue;
      let d = {};
      try { d = JSON.parse(f.getBlob().getDataAsString('UTF-8') || '{}'); } catch (e) { continue; }
      const s = d.source || {};
      const k = key(s.file_name, s.size_bytes);
      const st = !m[3] ? 'pending' : m[3];
      if (!reqs[k] || reqs[k].stamp < m[1]) reqs[k] = { stamp: m[1], state: st, task_name: m[2], file_id: f.getId(), reason: (d.result && (d.result.reason || d.result.error)) || '' };
    }
  }

  // CVAT에 이미 있는 TASK: 이름 앞부분 또는 올린 파일 이름이 원본과 같음
  const byBase = {}, byFile = {};
  Object.entries(tasks).forEach(([id, t]) => {
    if (t.gone) return;
    const b = t.base || uldBase_(t.name);
    (byBase[b] = byBase[b] || []).push(Number(id));
    const df = files[id] && files[id].data_file;
    if (df) (byFile[df.toLowerCase()] = byFile[df.toLowerCase()] || []).push(Number(id));
  });

  const items = vids.map((v) => {
    const r = reg[key(v.name, v.size)];
    const q = reqs[key(v.name, v.size)] || reqs[key(v.name, '')];
    const ids = Array.from(new Set([].concat(byBase[uldBase_(v.name)] || [], byFile[v.name.toLowerCase()] || [])))
      .filter((id) => !r || id !== r.task_id).sort((a, b) => a - b);
    const status = r ? 'done' : q ? q.state : 'new';
    return Object.assign({}, v, { status, task: r || null, request: q || null,
      cvat_existing: ids.map((id) => ({ id, name: (tasks[String(id)] || {}).name || '', project_id: (tasks[String(id)] || {}).project_id || null })) });
  }).sort((a, b) => String(b.modified).localeCompare(String(a.modified)));

  const out = { version: ULD_VERSION, generated: new Date().toISOString(), source_folder: src.getName(),
    counts: countBy_(items, (x) => x.status), with_cvat_existing: items.filter((x) => x.cvat_existing.length).length, items };
  const regDir = getSub_(root, ['registry']) || root.createFolder('registry');
  writeJson_(regDir, 'sources.json', out);
  return { originals: items.length, counts: out.counts, with_cvat_existing: out.with_cvat_existing };
}
