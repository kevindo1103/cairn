import copy
from pathlib import Path
import sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from observed_receipts import ReceiptRejected, observed_receipt, operator_confirmation, validate_pair
from observed_receipts import receipt_from_agent_output
from observed_receipts import ReceiptJournal
from integrated_operator import StagedOperator
class Tests(unittest.TestCase):
 def setUp(self): self.c={"command_id":"c","event_id":"e","thread_id":"t"}; self.k=b"operator"; self.d="digest"
 def pair(self, stage="ack",turn="a"):
  r=observed_receipt(self.c,self.d,stage,turn,{"observed":stage},sequence=1,clock=lambda:1)
  return r,operator_confirmation(r,"pilot-operator",self.k,clock=lambda:2)
 def test_valid_pair(self):
  r,x=self.pair(); self.assertEqual(validate_pair(r,x,self.c,self.d,self.k,"ack","t"),{"observed":"ack"})
 def test_receipt_and_confirmation_cannot_authorize_themselves(self):
  r,x=self.pair()
  for bad in (r, {**x,"receipt_digest":"0"*64}, {**x,"event_id":"other"}, {**x,"stage":"start"}):
   with self.assertRaises(ReceiptRejected): validate_pair(r,bad,self.c,self.d,self.k,"ack","t")
 def test_mutated_wrong_thread_turn_stage_rejected(self):
  r,x=self.pair()
  for mutate in ({"thread_id":"bad"},{"turn_id":"bad"},{"stage":"start"}):
   bad=copy.deepcopy(r); bad.update(mutate)
   with self.assertRaises(ReceiptRejected): validate_pair(bad,x,self.c,self.d,self.k,"ack","t")
 def test_observation_needs_separate_confirmation_before_import(self):
  import tempfile
  with tempfile.TemporaryDirectory() as d:
   r,x=self.pair(); calls=[]; op=StagedOperator(ReceiptJournal(Path(d)/"r.sqlite"),self.k,lambda stage,payload:calls.append(stage))
   op.observe(r); self.assertEqual(calls,[])
   op.confirm(r,x,self.c,self.d,"ack"); self.assertEqual(calls,["ack"])
 def test_parser_output_becomes_observation_not_authorization(self):
  r=receipt_from_agent_output(self.c,self.d,"turn",{"action":"ACK_REQUEST"},sequence=1,clock=lambda:1)
  self.assertEqual(r["stage"],"ack")
  with self.assertRaises(ReceiptRejected): receipt_from_agent_output(self.c,self.d,"turn",{"action":"unknown"},sequence=1)
