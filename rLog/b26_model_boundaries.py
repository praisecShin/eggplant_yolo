"""b26 모델별 격리: train.json 하위 형태와 legacy paths. 임시 저장소만 사용."""
import pathlib,sys,tempfile,json
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'drive/scripts'))
import arb_io as IO,handlers as H,h_agg as HA,exec_host as EH
with tempfile.TemporaryDirectory(prefix='b26_models_') as tmp:
    td=pathlib.Path(tmp);st=IO.LocalStore(td/'store');f=td/'best.pt';f.write_bytes(b'W');meta=td/'train.json'
    H.publish_version(st,'model','good','v',{'best.pt':str(f)});st.write_json('runs/good/CURRENT.json',{'version':'v'})
    for value in [{'metrics':[1]},{'args':[1]},[]]:
        meta.write_text(json.dumps(value));st.delete('runs/bad/v/v/_files.json')
        H.publish_version(st,'model','bad','v',{'best.pt':str(f),'train.json':str(meta)})
        st.write_json('runs/bad/CURRENT.json',{'version':'v'})
        skipped=[]
        try:print(json.dumps({'case':'metadata','train':value,'rows':HA.model_rows(HA.adopted_models(st,skipped)),'skipped':skipped},ensure_ascii=False))
        except Exception as e:print(json.dumps({'case':'metadata','train':value,'error':type(e).__name__,'skipped':skipped},ensure_ascii=False))
    # legacy의 잘못된 경로 값은 store에 넘기기 전 검사되지 않음.
    st.delete('runs/bad/CURRENT.json')
    manifest={'verified':True,'legacy':True,'files':{'best.pt':{'sha256':H.sha256_file(str(f)),'size':1},'results.csv':{'sha256':'a'*64,'size':1}},'paths':{'best.pt':'runs/old/weights/best.pt','results.csv':['invalid-path']}}
    st.write_json('runs/legacy/CURRENT.json',{'version':'legacy'});st.write_json('runs/legacy/v/legacy/_files.json',manifest)
    skipped=[];print(json.dumps({'case':'legacy_adopted','models':[m['name'] for m in HA.adopted_models(st,skipped)],'skipped':skipped}))
    web=EH.WebState(st,str(td/'web'),None,{})
    try:web._models(lambda *a:None);print('legacy_web returned')
    except Exception as e:print(json.dumps({'case':'legacy_web','error':type(e).__name__,'message':str(e)}))
