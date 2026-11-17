"""0z 모델 목록의 못 읽는 목록 처리 경계. 임시 LocalStore만 사용."""
import pathlib,sys,tempfile,json
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'drive/scripts'))
import arb_io as IO,handlers as H,h_agg as HA
with tempfile.TemporaryDirectory(prefix='b25_model_') as td:
    td=pathlib.Path(td);st=IO.LocalStore(td/'store');f=td/'best.pt';f.write_bytes(b'W')
    H.publish_version(st,'model','good','v1',{'best.pt':str(f)})
    st.write_json('runs/good/CURRENT.json',{'version':'v1'})
    st.write_json('runs/bad/CURRENT.json',{'version':'v1'})
    for malformed in [[],None,{'verified':True,'files':{'best.pt':[]}}]:
        st.write_json('runs/bad/v/v1/_files.json',malformed)
        try:print(json.dumps({'manifest':malformed,'models':HA.adopted_models(st)},ensure_ascii=False))
        except Exception as e:print(json.dumps({'manifest':malformed,'error':type(e).__name__,'message':str(e)},ensure_ascii=False))
