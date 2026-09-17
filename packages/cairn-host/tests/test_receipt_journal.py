from pathlib import Path
import sys,tempfile,unittest,sqlite3
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from observed_receipts import *
class T(unittest.TestCase):
 def test_restart_idempotence_and_mutation(self):
  with tempfile.TemporaryDirectory() as d:
   c={"command_id":"c","event_id":"e","thread_id":"t"}; r=observed_receipt(c,"d","ack","a",{},sequence=1,clock=lambda:1); x=operator_confirmation(r,"op",b"k",clock=lambda:2)
   j=ReceiptJournal(Path(d)/"r.sqlite"); j.persist_receipt(r); ReceiptJournal(Path(d)/"r.sqlite").consume(r,x)
   with self.assertRaises(ReceiptRejected): ReceiptJournal(Path(d)/"r.sqlite").consume(r,x)
   bad=dict(r); bad["payload"]={"x":1}
   with self.assertRaises(ReceiptRejected): j.persist_receipt(bad)
 def test_consistent_backup_restores_pending_receipt(self):
  with tempfile.TemporaryDirectory() as d:
   c={"command_id":"c","event_id":"e","thread_id":"t"}; r=observed_receipt(c,"d","ack","a",{},sequence=1,clock=lambda:1)
   source=Path(d)/"source.sqlite"; ReceiptJournal(source).persist_receipt(r)
   backup=Path(d)/"backup.sqlite"
   source_db=sqlite3.connect(source); target_db=sqlite3.connect(backup)
   try: source_db.backup(target_db)
   finally: target_db.close(); source_db.close()
   self.assertEqual(ReceiptJournal(backup).pending("c")[0]["receipt_digest"],r["receipt_digest"])
