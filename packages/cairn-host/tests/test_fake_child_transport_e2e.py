import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from appserver_stdio_transport import AppServerStdioTransport
from appserver_observation_parser import parse_completed

class FakeChildTransportTests(unittest.TestCase):
    def test_one_real_child_emits_pinned_observation(self):
        with tempfile.TemporaryDirectory() as temp:
            child = Path(temp) / "child.py"
            child.write_text(
                "import json,sys\n"
                "for line in sys.stdin:\n"
                " request=json.loads(line); m=request['method']\n"
                " if m=='initialized': continue\n"
                " p=request['params']\n"
                " if m=='initialize': result={}\n"
                " elif m=='thread/resume': result={'thread':{'id':p['threadId']}}\n"
                " else:\n"
                "  turn='fake-turn'; item={'method':'item/completed','params':{'threadId':p['threadId'],'turnId':turn,'item':{'type':'agentMessage','text':'[{\\\"action\\\":\\\"ACK_REQUEST\\\"}]'}}}; print(json.dumps(item),flush=True); result={'turn':{'id':turn}}\n"
                " print(json.dumps({'id':request['id'],'result':result}),flush=True)\n",
                encoding="utf-8")
            transport = AppServerStdioTransport(
                sys.executable, [str(child)], Path(temp) / "stream.jsonl")
            try:
                transport.initialize_and_resume("fake-thread")
                response = transport.turn_start("fake-thread", {"request": "bounded"})
                self.assertEqual(response["turn"]["id"], "fake-turn")
                item = next(m for m in transport.observer.received if m.get("method") == "item/completed")
                self.assertEqual(parse_completed(item, thread_id="fake-thread", turn_id="fake-turn"),
                                 [{"action": "ACK_REQUEST"}])
            finally:
                transport.close()

    def test_one_child_serves_ack_then_work_turn_without_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            child = Path(temp) / "child.py"
            child.write_text(
                "import json,sys\n"
                "i=0\n"
                "for line in sys.stdin:\n"
                " r=json.loads(line); m=r['method']\n"
                " if m=='initialized': continue\n"
                " p=r['params']\n"
                " if m=='initialize': result={}\n"
                " elif m=='thread/resume': result={'thread':{'id':p['threadId']}}\n"
                " else:\n"
                "  turn='turn-'+str(i); action='ACK_REQUEST' if i==0 else 'START_REQUEST'; i+=1\n"
                "  item={'method':'item/completed','params':{'threadId':p['threadId'],'turnId':turn,'item':{'type':'agentMessage','text':json.dumps([{'action':action}])}}}; print(json.dumps(item),flush=True); result={'turn':{'id':turn}}\n"
                " print(json.dumps({'id':r['id'],'result':result}),flush=True)\n",
                encoding="utf-8")
            transport = AppServerStdioTransport(sys.executable, [str(child)], Path(temp) / "stream.jsonl")
            try:
                transport.initialize_and_resume("t")
                self.assertEqual(transport.turn_start("t", {})["turn"]["id"], "turn-0")
                self.assertEqual(transport.turn_start("t", {})["turn"]["id"], "turn-1")
                completed = [x for x in transport.observer.received if x.get("method") == "item/completed"]
                self.assertEqual([x["params"]["turnId"] for x in completed], ["turn-0", "turn-1"])
            finally:
                transport.close()
