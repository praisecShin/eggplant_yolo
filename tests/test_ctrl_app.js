// CTRL앱 시험 — 가짜 Google Drive 커넥터로 화면·신호 파일을 확인. 실행: npm i jsdom && node tests/test_ctrl_app.js apps/ctrl/index.html
const { JSDOM } = require("jsdom");
const fs = require('fs');
const html = fs.readFileSync(process.argv[2] || 'apps/ctrl/index.html', 'utf8');
const NOW = Date.now() / 1000;
const files = {};   // id -> {title, parent, mime, content}
let n = 0;
const mk = (parent, title, content, folder) => { const id = 'f' + (++n); files[id] = { id, title, parent, folder: !!folder, content, modifiedTime: new Date().toISOString() }; return id; };
const root = mk('', 'eggplant_yolo', null, true), adm = mk('', 'eggplant_admin', null, true);
const arb = mk(root, 'arb', null, true), jobs = mk(root, 'jobs', null, true), status = mk(root, 'status', null, true), workers = mk(root, 'workers', null, true);
const cfg = mk(adm, 'config', null, true), holds = mk(arb, 'holds', null, true), alerts = mk(arb, 'alerts', null, true), locks = mk(arb, 'locks', null, true);
const signals = mk(jobs, 'signals', null, true), wd = mk(jobs, 'wake_done', null, true), sdone = mk(arb, 'signal_done', null, true);
mk(arb, 'ARBITER.json', { epoch: 2, round: 40, session: 'kgl-1', at: NOW - 30, protect: [{ path: 'arb/holds/stop__M1__1.json', why: 'active' }], unknown: [],
  check: { needs_check: ['mgmt'], executor_wait: ['d1'], orphans: [] }, wake: { runnable: 1, busy: 2, gpu_needed: 0 } });
mk(jobs, 'ARBITER_GRANT.json', { epoch: 2, session: 'kgl-1' });
mk(jobs, 'keeper.json', { at: NOW - 40, version: '4.33.0j' });
mk(status, 'collector.json', { version: '4.33.0', last: { time: new Date().toISOString(), ok: true } });
mk(cfg, 'people.json', [{ id: 'M1', name: '재웅', account: 'a0@x', role: 'admin', perms: ['request', 'wake', 'release'], status: 'active' }]);
mk(workers, 'kgl-1__fp.json', { session: 'kgl-1', caps: ['master'], hb: NOW - 20, status: { gpu_status_unknown_since: NOW - 900, config: { rejected: null } } });
mk(workers, 'kgw-1__fp.json', { session: 'kgw-1', caps: ['cpu', 'agg'], hb: NOW - 10 });
mk(holds, 'stop__M1__1.json', { stop_id: 'stop__M1__1', active: true, until: null });
mk(alerts, 'a1.json', { kind: 'protect', path: 'arb/holds/stop__M1__1.json' });
mk(locks, 'mgmt.json', { state: 'needs_check', run: 'mgmt_x', rid: 'd1', stop_reported: true });
mk(signals, 'wake__M1__2026.json', {}); mk(wd, 'wake__M1__2026.json', { state: 'rejected', reason: 'hold' });
const created = [];
let FAIL = false;
const DL_FAIL = new Set(); let LIST_FAIL = null, DELAY = 0;
const mcp = { callTool: async (srv, tool, input) => {
  if (DELAY) await new Promise((r) => setTimeout(r, DELAY));
  if (tool === 'search_files') {
    const qy = input.query;
    if (LIST_FAIL && qy.includes(`parentId = '${LIST_FAIL}'`) && /mimeType != /.test(qy)) throw { message: 'fake list failure' }; let out = Object.values(files);
    const m1 = /parentId = '([^']+)'/.exec(qy); if (m1) out = out.filter((f) => f.parent === m1[1]); else out = out.filter((f) => !f.parent);
    const m2 = /title = '([^']+)'/.exec(qy); if (m2) out = out.filter((f) => f.title === m2[1]);
    if (/mimeType = /.test(qy)) out = out.filter((f) => f.folder); if (/mimeType != /.test(qy)) out = out.filter((f) => !f.folder);
    return { payload: { files: out.map((f) => ({ id: f.id, title: f.title, modifiedTime: f.modifiedTime })) } };
  }
  if (tool === 'download_file_content' && DL_FAIL.has(input.fileId)) throw { message: 'fake download failure' };
  if (tool === 'download_file_content') return { payload: { content: Buffer.from(JSON.stringify(files[input.fileId].content)).toString('base64') } };
  if (tool === 'create_file') { created.push(input); mk(input.parentId, input.title, JSON.parse(input.textContent)); return { payload: { id: 'new' } }; }
} };
const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, beforeParse(w) {
  w.claude = { use: async () => mcp }; w.HTMLDialogElement.prototype.showModal = function () { this.open = true; }; w.HTMLDialogElement.prototype.close = function () { this.open = false; };
  w.TextDecoder = TextDecoder; w.atob = (b) => Buffer.from(b, 'base64').toString('binary'); } });
const w = dom.window, d = w.document;
setTimeout(async () => {
  const ok = (c, m) => { if (!c) FAIL = true; console.log((c ? '✅ ' : '❌ ') + m); };
  ok(!d.querySelector('#prot').hidden && /보호 모드/.test(d.querySelector('#prot').textContent) && /stop__M1__1/.test(d.querySelector('#prot').textContent), '보호 모드 띠: 경로·이유·복구 절차');
  ok(/판정 루프/.test(d.querySelector('#board').textContent) && /보호 모드/.test(d.querySelector('#board').textContent), '상태 판: 판정 루프 보호 모드');
  ok(/GPU 상태 모름/.test(d.querySelector('#board').textContent), '상태 판: 마스터의 GPU 상태 모름 표시');
  ok(/실행기/.test(d.querySelector('#board').textContent) && /cpu,agg/.test(d.querySelector('#board').textContent), '실행기 목록');
  ok(d.querySelector('#act-wake').disabled, '심판이 살아 있으면 깨우기 막힘');
  ok(d.querySelector('#act-stop').disabled, '보호 모드 중에는 정지 신호도 막힘 (처리되지 않으므로)');
  ok(/거절/.test(d.querySelector('#sigs').textContent) && /hold/.test(d.querySelector('#sigs').textContent), '보낸 깨우기 신호의 거절 사유 표시');
  ok(/멈춤 보고/.test(d.querySelector('#runs').textContent), '관리 일 확인 필요·멈춤 보고');
  // 보호 모드 끝, 심판 멈춤 → 관리자 '보류 해제하고 깨우기'
  const A = Object.values(files).find((f) => f.title === 'ARBITER.json'); A.content.protect = []; A.content.at = NOW - 900;
  d.querySelector('#reload').click();
  await new Promise((r) => setTimeout(r, 300));
  ok(!d.querySelector('#act-wake').disabled && /보류 해제하고 깨우기/.test(d.querySelector('#act-wake').textContent), '심판 멈춤 + 보류 하나 + 관리자 → 보류 해제하고 깨우기');
  d.querySelector('#act-wake').click(); d.querySelector('#dlg-ok').click();
  await new Promise((r) => setTimeout(r, 100));
  const c = created[0]; const body = c && JSON.parse(c.textContent);
  ok(c && /^wake__M1__\d{14}[a-z0-9]{3}\.json$/.test(c.title) && body.release_stop === 'stop__M1__1' && c.parentId === signals, '깨우기 신호: jobs/signals/wake__M1__…, release_stop 포함');
  d.querySelector('[data-rel]').click(); d.querySelector('#dlg-ok').click();
  await new Promise((r) => setTimeout(r, 100));
  const r2 = created[1]; ok(r2 && /^release__M1__/.test(r2.title) && JSON.parse(r2.textContent).stop_id === 'stop__M1__1', '해제 신호: stop_id');
  d.querySelector('#act-stop').click(); d.querySelector('#until').value = 'morning'; d.querySelector('#dlg-ok').click();
  await new Promise((r) => setTimeout(r, 100));
  const s3 = created[2] && JSON.parse(created[2].textContent); ok(s3 && typeof s3.until === 'number' && s3.until > NOW, '정지 신호: 다음 08:00 기한(초)');
  d.querySelector('#env-test').click(); await new Promise((r) => setTimeout(r, 300));
  ok(!d.querySelector('#testband').hidden && /eggplant_yolo_test/.test(d.querySelector('#note').textContent + d.querySelector('#testband').textContent), '시험 폴더 선택: 시험 띠, 없으면 찾지 못했다고 표시');
  // b17 X2: 시험 폴더를 찾지 못하면 운영 폴더로 보내지 않음
  const before = created.length;
  ok(d.querySelector('#act-stop').disabled && d.querySelector('#act-wake').disabled, '시험 환경을 읽지 못하면 정지·깨우기 버튼이 막힘 (X2)');
  d.querySelector('#act-stop').disabled = false; d.querySelector('#act-stop').click();
  ok(!d.querySelector('#dlg').open, '버튼을 강제로 눌러도 이 환경을 다 읽기 전에는 대화상자가 열리지 않음 (X2)');
  ok(created.length === before, '시험 환경 전환 실패 뒤 운영 signals 폴더에 아무것도 만들지 않음 (X2)');
  // 운영으로 돌아가 대화상자를 연 채 시험으로 바꾸면 대화상자가 닫히고 보내지 않음
  d.querySelector('#env-prod').click(); await new Promise((r) => setTimeout(r, 300));
  d.querySelector('#act-stop').click(); ok(d.querySelector('#dlg').open, '운영 환경을 다시 읽으면 정지 대화상자 열림');
  d.querySelector('#env-test').click(); await new Promise((r) => setTimeout(r, 50));
  ok(!d.querySelector('#dlg').open, '환경을 바꾸면 열린 대화상자를 닫음 (X2)');
  d.querySelector('#dlg-ok').click(); await new Promise((r) => setTimeout(r, 300));
  ok(created.length === before, '닫힌 대화상자의 확인을 눌러도 보내지 않음 (X2)');
  // 늦게 끝난 운영 읽기가 시험 화면을 덮지 않음
  d.querySelector('#env-prod').click(); await new Promise((r) => setTimeout(r, 300));
  DELAY = 40; d.querySelector('#reload').click(); await new Promise((r) => setTimeout(r, 10));
  d.querySelector('#env-test').click(); await new Promise((r) => setTimeout(r, 2500)); DELAY = 0;
  ok(d.querySelector('#act-stop').disabled && !d.querySelector('#testband').hidden, '늦게 끝난 운영 읽기가 시험 화면의 전송 대상을 되살리지 않음 (X2)');
  // b17 X6: 보류 파일을 못 읽으면 '읽지 못함' + 깨우기·해제 막음
  d.querySelector('#env-prod').click(); await new Promise((r) => setTimeout(r, 300));
  const hf = Object.values(files).find((f) => f.title === 'stop__M1__1.json'); DL_FAIL.add(hf.id);
  d.querySelector('#reload').click(); await new Promise((r) => setTimeout(r, 300));
  ok(/읽지 못함/.test(d.querySelector('#holds').textContent) && d.querySelector('#act-wake').disabled, '보류 파일을 못 읽으면 "읽지 못함" 표시, 깨우기 막음 (X6)');
  ok(/stop__M1__1\.json/.test(d.querySelector('#note').textContent), '읽지 못한 보류 파일을 오류 띠에 표시 (X6)');
  DL_FAIL.clear(); LIST_FAIL = holds;
  d.querySelector('#reload').click(); await new Promise((r) => setTimeout(r, 300));
  ok(/읽지 못함/.test(d.querySelector('#holds').textContent) && d.querySelector('#act-wake').disabled, '보류 목록을 못 읽어도 "없음"이 아니라 "읽지 못함", 깨우기 막음 (X6)');
  LIST_FAIL = null; d.querySelector('#reload').click(); await new Promise((r) => setTimeout(r, 300));
  ok(!d.querySelector('#act-wake').disabled && !/읽지 못함/.test(d.querySelector('#holds').textContent), '다시 읽히면 깨우기 다시 열림');
  // b18 Y5: 열어 둔 해제 대화상자 — 새로 읽어 보류를 모르게 되면 닫고 보내지 않음
  ok(!!d.querySelector('[data-rel]') && !d.querySelector('[data-rel]').disabled, '(준비) 보류 해제 버튼 열림');
  d.querySelector('[data-rel]').click(); ok(d.querySelector('#dlg').open, '해제 대화상자 열림');
  const n5 = created.length; DL_FAIL.add(hf.id);
  d.querySelector('#reload').click(); await new Promise((r) => setTimeout(r, 300));
  ok(!d.querySelector('#dlg').open, '새로 읽어 보류를 모르게 되면 열린 대화상자를 닫음 (Y5)');
  d.querySelector('#dlg-ok').click(); await new Promise((r) => setTimeout(r, 200));
  ok(created.length === n5, '닫힌 대화상자의 확인을 눌러도 해제 신호를 만들지 않음 (Y5)');
  DL_FAIL.clear(); d.querySelector('#reload').click(); await new Promise((r) => setTimeout(r, 300));
  // 대화상자를 연 채 보내기 직전 상태가 바뀜(보호 모드) → 보내기에서 다시 확인
  d.querySelector('[data-rel]').click(); ok(d.querySelector('#dlg').open, '다시 해제 대화상자 열림');
  const Af = Object.values(files).find((f) => f.title === 'ARBITER.json');
  Af.content.protect = [{ path: 'arb/x.json', why: 'active' }];
  const keepOpen = w.HTMLDialogElement.prototype.close; let closedBy = 0; w.HTMLDialogElement.prototype.close = function () { closedBy++; keepOpen.call(this); };
  d.querySelector('#reload').click(); await new Promise((r) => setTimeout(r, 300));
  ok(!d.querySelector('#dlg').open && closedBy > 0, '보호 모드가 되면 열린 해제 대화상자를 닫음 (Y5)');
  w.HTMLDialogElement.prototype.close = keepOpen; Af.content.protect = [];
  d.querySelector('#reload').click(); await new Promise((r) => setTimeout(r, 300));
  if (d.querySelector('#dlg').open) d.querySelector('#dlg-no').click();
  d.querySelector('#reload').click(); await new Promise((r) => setTimeout(r, 300));
  // 같은 이름 최상위 폴더가 둘이면 제어를 막음
  const dupRoot = mk('', 'eggplant_yolo', null, true);
  d.querySelector('#reload').click(); await new Promise((r) => setTimeout(r, 300));
  ok(/폴더가 2개/.test(d.querySelector('#note').textContent) && d.querySelector('#act-stop').disabled && d.querySelector('#act-wake').disabled,
    '같은 이름 최상위 폴더가 둘이면 경고하고 제어를 막음 (b18 보충)');
  delete files[dupRoot];
  d.querySelector('#reload').click(); await new Promise((r) => setTimeout(r, 300));
  ok(!d.querySelector('#act-stop').disabled, '하나만 남으면 다시 열림');
  console.log(FAIL ? 'RESULT False' : 'RESULT True'); process.exit(FAIL ? 1 : 0);
}, 800);
