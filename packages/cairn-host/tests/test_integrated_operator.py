import hashlib, hmac, json
from pathlib import Path
import sys, tempfile, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrated_operator import CommandAuthority, EvidenceAuthority, IntegratedOperator, AuthorityRejected, _canonical
from runnable_operator_path import DurableCommandJournal

class T:
    def __init__(self): self.calls=0
    def turn_start(self, thread, payload): self.calls += 1; return {"turn":{"id":"delivery-turn"}}
class O:
    def __init__(self, items): self.items=list(items)
    def next_evidence(self, stage, turn): return self.items.pop(0)
class Tests(unittest.TestCase):
 def test_path_authority_evidence_and_replay(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); (root/"authority").mkdir(); key=b"k"
   c=dict(command_id="c",event_id="e",dedupe="d",checkpoint="n",thread_id="t",action="send_work_once",project="p",target="t",scope="s",principal="worker",generation="1",attestation_ref="a")
   f=root/"command.json"; f.write_text(json.dumps(c)); digest=hashlib.sha256(f.read_bytes()).hexdigest()
   r={"digest":digest,"command":c}; r["signature"]=hmac.new(key,_canonical(r),hashlib.sha256).hexdigest()
   (root/"authority/c.json").write_text(json.dumps(r))
   cd=hashlib.sha256(_canonical(c)).hexdigest()
   def ev(stage,turn):
    x={"command_id":"c","digest":cd,"event_id":"e","thread_id":"t","turn_id":turn,"stage":stage,"observer":"APP_SERVER_LIVE_STREAM","observation":{"stage":stage}}
    x["signature"]=hmac.new(key,_canonical(x),hashlib.sha256).hexdigest(); return x
   transport=T(); imported=[]
   run=IntegratedOperator(DurableCommandJournal(root/"j.sqlite"),CommandAuthority(root,key),EvidenceAuthority(key),transport,O([ev("ack","ack"),ev("start","work"),ev("complete","work")]),lambda s,o: imported.append(s))
   self.assertEqual(run.run(f,{} )["state"],"COMPLETED"); self.assertEqual(imported,["ack","start","complete"]); self.assertEqual(transport.calls,1)
   with self.assertRaises(Exception): run.run(f,{})
   self.assertEqual(transport.calls,1)
 def test_mutated_command_and_evidence_rejected_before_send(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); (root/"authority").mkdir(); key=b"k"; c=dict(command_id="c",event_id="e",dedupe="d",checkpoint="n",thread_id="t",action="send_work_once",project="p",target="t",scope="s",principal="worker",generation="1",attestation_ref="a")
   f=root/"x.json"; f.write_text(json.dumps(c)); digest=hashlib.sha256(f.read_bytes()).hexdigest(); record={"digest":digest,"command":c}; record["signature"]="bad"; (root/"authority/c.json").write_text(json.dumps(record))
   t=T(); run=IntegratedOperator(DurableCommandJournal(root/"j.sqlite"),CommandAuthority(root,key),EvidenceAuthority(key),t,O([]),lambda *_:None)
   with self.assertRaises(AuthorityRejected): run.run(f,{})
   self.assertEqual(t.calls,0)
