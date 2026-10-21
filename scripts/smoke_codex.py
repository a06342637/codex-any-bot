"""Optional real-Codex smoke test, using only an isolated home and local fake API."""
import json, os, subprocess, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from anybot.codex import find_codex, rpc, run_turn
from anybot.state import Settings


class Handler(BaseHTTPRequestHandler):
    fail = False
    def log_message(self, *args): pass
    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']))
        if self.fail:
            self.send_response(401)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"test unauthorized","type":"authentication_error"}}')
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        item = {'id':'msg_test','type':'message','role':'assistant','status':'completed',
                'content':[{'type':'output_text','text':'OK','annotations':[]}]}
        response = {'id':'resp_test','object':'response','created_at':1,'status':'completed','model':'fixture',
                    'output':[item], 'usage':{'input_tokens':1,'output_tokens':1,'total_tokens':2}}
        for event in [
            {'type':'response.created','response':{**response,'status':'in_progress','output':[]}},
            {'type':'response.output_item.added','output_index':0,'item':{**item,'status':'in_progress','content':[]}},
            {'type':'response.output_text.delta','item_id':'msg_test','output_index':0,'content_index':0,'delta':'OK'},
            {'type':'response.output_item.done','output_index':0,'item':item},
            {'type':'response.completed','response':response},
        ]:
            self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode())
        self.wfile.flush()


binary = find_codex()
http = ThreadingHTTPServer(('127.0.0.1',0),Handler)
threading.Thread(target=http.serve_forever,daemon=True).start()
with tempfile.TemporaryDirectory(prefix='anybot-visibility-') as tmp:
    root=Path(tmp)
    os.environ['CODEX_HOME']=tmp
    (root/'config.toml').write_text(f'''model = "fixture"
model_provider = "fixture"
approval_policy = "never"
sandbox_mode = "read-only"
[model_providers.fixture]
name = "Local test fixture"
base_url = "http://127.0.0.1:{http.server_port}/v1"
wire_api = "responses"
requires_openai_auth = false
''',encoding='utf-8')
    kwargs={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
    legacy=subprocess.run([binary,'-c','notify=[]','exec','--json','--skip-git-repo-check','-'],input='Reply OK.',
                          cwd=tmp,text=True,capture_output=True,timeout=45,**kwargs)
    old=None
    for line in legacy.stdout.splitlines():
        try: ev=json.loads(line)
        except ValueError: continue
        if ev.get('type')=='thread.started':old=ev['thread_id']
    print('legacy exit',legacy.returncode,'thread',old,flush=True)
    assert old,legacy.stderr[-1500:]
    events=[]
    result=run_turn(binary,Settings(thread_id=old,cwd=tmp,prompt='Reply OK.'),threading.Event(),events.append)
    print('migration',result,events,flush=True)
    assert result['kind']=='success'
    migrated=result['thread_id']
    listed=rpc('thread/list',{'limit':100,'modelProviders':[]})['data']
    print('interactive list',[{k:t.get(k) for k in ['id','source','name','preview']} for t in listed],flush=True)
    assert migrated in {t['id'] for t in listed}
    assert old not in {t['id'] for t in listed}
    again=run_turn(binary,Settings(thread_id=migrated,cwd=tmp,prompt='Reply OK.'),threading.Event(),lambda e:None)
    assert again=={'kind':'success','thread_id':migrated},again
    new=run_turn(binary,Settings(cwd=tmp,prompt='Reply OK.'),threading.Event(),lambda e:None)
    assert new['kind']=='success',new
    listed=rpc('thread/list',{'limit':100,'modelProviders':[]})['data']
    assert new['thread_id'] in {t['id'] for t in listed}
    Handler.fail = True
    failed=run_turn(binary,Settings(cwd=tmp,prompt='Simulated failure.'),threading.Event(),lambda e:None)
    assert failed['kind']=='auth',failed
    listed=rpc('thread/list',{'limit':100,'modelProviders':[]})['data']
    assert failed['thread_id'] in {t['id'] for t in listed},'Failed first attempt must remain visible'
    print('PASS: old history preserved; new/migrated/failed sessions visible after exit; resumed ID stable.',flush=True)
http.shutdown()
