"""지정 가짜 환경 시험 실행 및 로그 보관. 저장소 루트에서 실행."""
import os, subprocess, json, pathlib, time
root = pathlib.Path(__file__).resolve().parents[1]
env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PATH='/tmp/b24_venv/bin:/tmp/node-v22.16.0-linux-x64/bin:' + os.environ['PATH'], NODE_PATH='/tmp/b24_js/node_modules')
commands = [(n, ['/tmp/b24_venv/bin/python', f'tests/test_{n}_433.py', 'drive']) for n in ['arbiter','access','master','master_main','handlers','hosts','e2e','fuzz']]
commands += [('fuzz7', ['/tmp/b24_venv/bin/python','tests/test_fuzz_433.py','drive'])]
commands += [('collector', ['node','tests/test_collector.js','apps_script/G_collector/Collector.gs','apps_script/G_collector/Uld.gs']), ('keeper',['node','tests/test_keeper.js','apps_script/G_keeper/Keeper.gs']), ('ctrl',['node','tests/test_ctrl_app.js','apps/ctrl/index.html'])]
status=[]
for name, cmd in commands:
    t=time.time()
    with (root / f'rLog/b24_{name}.log').open('w') as f:
        r=subprocess.run(cmd,cwd=root,env=dict(env, **({'FUZZ_SEED':'7','FUZZ_N':'5'} if name=='fuzz7' else {})),stdout=f,stderr=subprocess.STDOUT)
    status.append(dict(name=name,cmd=cmd,rc=r.returncode,seconds=round(time.time()-t,1)))
    (root/'rLog/b24_test_status.json').write_text(json.dumps(status,indent=2))
    print(status[-1],flush=True)
