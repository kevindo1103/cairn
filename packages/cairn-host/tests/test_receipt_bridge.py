from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from observed_receipts import *
from receipt_bridge import bridge
import json, hashlib, tempfile
import existing_task_uat as uat
from receipt_bridge import resume_existing_importer
class T(unittest.TestCase):
 def test_requires_distinct_bound_confirmation(self):
  c={"command_id":"c","event_id":"e","thread_id":"t"}; r=observed_receipt(c,"d","ack","a",{"x":1},sequence=1,clock=lambda:1); x=operator_confirmation(r,"op",b"k",clock=lambda:2)
  self.assertEqual(bridge(r,x,c,"d",b"k","ack"),{"x":1})
  x["stage"]="start"
  with self.assertRaises(ReceiptRejected): bridge(r,x,c,"d",b"k","ack")
 def test_real_operator_resume_uses_flat_observed_receipt(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/"uat"; public=uat.prepare(root,"a"*40); env=public["envelope"]
   sent=dict(observer="PM_MANUAL_PLATFORM_READBACK",origin=dict(thread_id=public["recipient"],turn_id=None,evidence_ref="artifact://fixture/sent"),readback=dict(env,action=uat.ACTION["sent"]))
   uat.import_observation(root,"sent",sent)
   flat=dict(event_id=env["event_id"],dedupe=env["dedupe"],checkpoint=env["checkpoint"],thread_id=public["recipient"],turn_id="turn-ack",action=uat.ACTION["ack"],readback=dict(env,action=uat.ACTION["ack"]),transport_ref="artifact://fixture/transport",stream_ref="artifact://fixture/stream")
   command={"command_id":"c","event_id":env["event_id"],"thread_id":public["recipient"]}
   outer=observed_receipt(command,"d","ack","turn-ack",flat,sequence=1,clock=lambda:1)
   raw=json.dumps(flat,sort_keys=True,separators=(",",":")).encode(); confirmation=dict(owner="pm",confirmed=True,stage="ack",event_id=env["event_id"],dedupe=env["dedupe"],checkpoint=env["checkpoint"],receipt_sha256=hashlib.sha256(raw).hexdigest())
   journal=ReceiptJournal(root/"broker"/"receipts.sqlite")
   self.assertEqual(resume_existing_importer(root,outer,flat,confirmation,"ack",receipt_journal=journal)[0]["state"],"ACKED")
   for stage,turn in (("start","turn-work"),("complete","turn-work")):
    flat=dict(event_id=env["event_id"],dedupe=env["dedupe"],checkpoint=env["checkpoint"],thread_id=public["recipient"],turn_id=turn,action=uat.ACTION[stage],readback=dict(env,action=uat.ACTION[stage]),transport_ref="artifact://fixture/transport",stream_ref="artifact://fixture/stream")
    if stage=="complete":
     output=root/"evidence"/"bridge-output.txt"; output.write_text("offline fake-child completion: arithmetic verified 42")
     h=hashlib.sha256(output.read_bytes()).hexdigest(); flat.update(readback=dict(env,action=uat.ACTION[stage],result=42),output_path=str(output),output_sha256=h,output_ref="artifact://sha256/"+h)
    outer=observed_receipt(command,"d",stage,turn,flat,sequence=2,clock=lambda:2)
    raw=json.dumps(flat,sort_keys=True,separators=(",",":")).encode(); confirmation=dict(owner="pm",confirmed=True,stage=stage,event_id=env["event_id"],dedupe=env["dedupe"],checkpoint=env["checkpoint"],receipt_sha256=hashlib.sha256(raw).hexdigest())
    self.assertEqual(resume_existing_importer(root,outer,flat,confirmation,stage,receipt_journal=journal)[0]["state"],{"start":"STARTED","complete":"COMPLETED"}[stage])
   with self.assertRaises(ReceiptRejected): resume_existing_importer(root,outer,flat,confirmation,"ack",receipt_journal=ReceiptJournal(root/"broker"/"receipts.sqlite"))
