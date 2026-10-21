import json
import sys
import threading
import time

import pytest

from anybot import codex
from anybot.state import Settings


FAKE_SERVER = r'''
import json,sys,time,subprocess
def send(obj):
    print(json.dumps(obj),flush=True)
for line in sys.stdin:
    msg=json.loads(line)
    with open(config['transcript'],'a',encoding='utf-8') as f:
        f.write(json.dumps(msg)+'\n')
    method=msg.get('method')
    if 'id' not in msg: continue
    result={}
    if method=='thread/read': result={'thread':{'id':'old','source':config.get('source','appServer')}}
    if method in ('thread/start','thread/fork','thread/resume'):
        if config.get('ambiguous'): break
        result={'thread':{'id':'old' if method=='thread/resume' else 'new'}}
    if method=='turn/start':
        tid=msg['params']['threadId']
        result={'turn':{'id':'turn'}}
        if config.get('child'):
            subprocess.Popen([sys.executable,config['child']], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        if config.get('before_reply'):
            send({'method':'turn/completed','params':{'threadId':tid,'turn':{'id':'turn','status':'completed'}}})
    send({'id':msg['id'],'result':result})
    if method=='turn/start':
        mode=config.get('mode','completed')
        if mode=='exit': break
        if mode=='wait': continue
        if mode=='approval':
            send({'id':900,'method':'item/commandExecution/requestApproval','params':{}})
            continue
        send({'method':'turn/completed','params':{'threadId':'other','turn':{'id':'turn','status':'completed'}}})
        send({'method':'turn/completed','params':{'threadId':tid,'turn':{'id':'previous','status':'completed'}}})
        send({'method':'error','params':{'threadId':tid,'willRetry':True,'error':{'message':'temporary 401'}}})
        send({'method':'turn/completed','params':{'threadId':tid,'turn':{'id':'turn','status':mode,'error':{'message':config.get('error','failed')}}}})
    if method=='turn/interrupt':
        send({'method':'turn/completed','params':{'threadId':msg['params']['threadId'],'turn':{'id':'turn','status':'interrupted'}}})
'''


@pytest.fixture
def fake_server(tmp_path, monkeypatch):
    transcript = tmp_path / 'requests.jsonl'
    script = tmp_path / 'fake.py'
    real = codex.ProcessTree
    arguments = []

    def start(args, cwd=None):
        arguments.append(args)
        return real([sys.executable, str(script)], cwd)

    monkeypatch.setattr(codex, 'ProcessTree', start)

    def configure(**kwargs):
        config = {'transcript': str(transcript), **kwargs}
        script.write_text('config=' + repr(config) + '\n' + FAKE_SERVER, encoding='utf-8')

    configure()
    return configure, transcript, arguments


@pytest.mark.parametrize('mode,error,expected', [
    ('completed', '', 'success'), ('failed', '401 unauthorized', 'auth'),
    ('failed', 'already has an active writer', 'locked'),
    ('failed', 'permission denied', 'permission'), ('exit', '', 'failed'),
    ('interrupted', '', 'cancelled'), ('approval', '', 'permission'),
])
def test_only_matching_completed_turn_counts(fake_server, mode, error, expected):
    configure, _, _ = fake_server
    configure(mode=mode, error=error)
    result = codex.run_turn('fake', Settings(thread_id='old'), threading.Event(), lambda e: None)
    assert result == {'kind': expected, 'thread_id': 'old'}


def test_completion_before_start_reply_is_retained(fake_server):
    fake_server[0](before_reply=True, mode='wait')
    assert codex.run_turn('fake', Settings(thread_id='old'), threading.Event(), lambda e: None)['kind'] == 'success'


@pytest.mark.parametrize('source,selected,method,target', [
    ('exec', 'old', 'thread/fork', 'new'),
    ('appServer', 'old', 'thread/resume', 'old'),
    ('cli', 'old', 'thread/resume', 'old'),
    ('appServer', None, 'thread/start', 'new'),
])
def test_visible_history_and_process_only_notification_overrides(fake_server, tmp_path, source, selected, method, target):
    configure, transcript, arguments = fake_server
    configure(source=source, mode='failed')
    events = []
    prompt = '中文 "quoted"\n$(never execute)'
    result = codex.run_turn('fake', Settings(thread_id=selected, cwd=str(tmp_path), prompt=prompt), threading.Event(), events.append)
    requests = [json.loads(s) for s in transcript.read_text().splitlines()]
    assert result['thread_id'] == target
    assert events[0] == {'event': 'thread', 'thread_id': target}
    assert 'exec' not in arguments[0]
    assert 'notify=[]' in arguments[0] and 'tui.notifications=false' in arguments[0]
    chosen = next(r for r in requests if r['method'] == method)
    assert chosen['params']['config']['notify'] == []
    assert chosen['params']['cwd'] == str(tmp_path)
    turn = next(r for r in requests if r['method'] == 'turn/start')
    assert turn['params']['input'][0]['text'] == prompt
    assert turn['params']['threadId'] == target
    assert not any(r['method'] in ('thread/delete', 'thread/archive') for r in requests)
    assert any(r['method'] == 'thread/name/set' for r in requests) == (method != 'thread/resume')


def test_ambiguous_fork_pauses_instead_of_duplicating_history(fake_server):
    fake_server[0](source='exec', ambiguous=True)
    result = codex.run_turn('fake', Settings(thread_id='old'), threading.Event(), lambda e: None)
    assert result == {'kind': 'unknown_session', 'thread_id': 'old'}


def test_stop_interrupts_turn_and_kills_child_process_tree(fake_server, tmp_path):
    configure, transcript, _ = fake_server
    marker = tmp_path / 'heartbeat'
    child = tmp_path / 'child.py'
    child.write_text('import time,pathlib; p=pathlib.Path(' + repr(str(marker)) + ');\nwhile True: p.write_text(str(time.time())); time.sleep(0.05)', encoding='utf-8')
    configure(mode='wait', child=str(child))
    cancel = threading.Event()
    results = []
    worker = threading.Thread(target=lambda: results.append(codex.run_turn('fake', Settings(), cancel, lambda e: None)))
    worker.start()
    try:
        until = time.time() + 30
        while not marker.exists() and time.time() < until:
            time.sleep(0.05)
        assert marker.exists()
    finally:
        cancel.set()
        worker.join(10)
    assert not worker.is_alive() and results[0]['kind'] == 'cancelled'
    assert 'turn/interrupt' in transcript.read_text()
    previous = marker.read_text()
    time.sleep(0.3)
    assert marker.read_text() == previous


def test_cancel_during_handshake_is_prompt(fake_server):
    cancel = threading.Event()
    cancel.set()
    assert codex.run_turn('fake', Settings(), cancel, lambda e: None)['kind'] == 'cancelled'
