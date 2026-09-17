import json, hashlib, hmac
from pathlib import Path
import sys, tempfile, unittest, subprocess, time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cairn_host import dispatch_on_transport, fixed_transport, host_flat_receipt, load_config, run_command, resume_work
from cairn_host import resume_command
from integrated_operator import AuthorityRejected
from observed_receipts import ReceiptJournal, observed_receipt
import existing_task_uat as uat
from appserver_observation_parser import ObservationTerminalError, parse_completed
from appserver_stdio_transport import AppServerStdioTransport
from observed_receipts import receipt_from_agent_output
class Tests(unittest.TestCase):
 def test_cli_resume_work_across_processes_completes_real_store_once(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)
   for folder in ("logs","confirmations","authority","secrets"): (root/folder).mkdir()
   public=uat.prepare(root/"uat","a"*40); env=public["envelope"]
   sent={"observer":"PM_MANUAL_PLATFORM_READBACK","origin":{"thread_id":public["recipient"],"turn_id":None,"evidence_ref":"artifact://fixture/sent"},"readback":dict(env,action=uat.ACTION["sent"])}
   uat.import_observation(root/"uat","sent",sent)
   key=b"offline-test-key"; (root/"secrets/key").write_bytes(key)
   command={"command_id":"c","event_id":env["event_id"],"dedupe":env["dedupe"],"checkpoint":env["checkpoint"],"thread_id":public["recipient"],"action":"send_work_once","attestation_ref":"a","project":"p","target":public["recipient"],"scope":"local-pilot","principal":"worker","generation":"1"}
   source=root/"command.json"; source.write_text(json.dumps(command))
   binding={"digest":hashlib.sha256(source.read_bytes()).hexdigest(),"command":command}
   binding["signature"]=hmac.new(key,json.dumps(binding,sort_keys=True,separators=(",",":")).encode(),hashlib.sha256).hexdigest()
   (root/"authority/c.json").write_text(json.dumps(binding))
   for phase in ("ack","work"): (root/(phase+".json")).write_text(json.dumps([{"type":"text","text":phase}]))
   # Only raw model readbacks leave the child. Production code supplies every
   # receipt identity, transport/stream digest, and completion output artifact.
   outputs={"ack":[dict(env,action=uat.ACTION["ack"])],"work":[dict(env,action=uat.ACTION["start"]),dict(env,action=uat.ACTION["complete"],result=42)]}
   sends=root/"sends.jsonl"; child=root/"child.py"
   child.write_text(
    "import json,sys,os\nfrom pathlib import Path\n"
    "OUT="+repr(outputs)+"\nLOG=Path("+repr(str(sends))+")\n"
    "for line in sys.stdin:\n"
    " r=json.loads(line); m=r['method']\n"
    " if m=='initialized': continue\n"
    " p=r['params']\n"
    " if m=='initialize': result={}\n"
    " elif m=='thread/resume': result={'thread':{'id':p['threadId']}}\n"
    " elif m=='turn/start':\n"
    "  phase=p['input'][0]['text']; turn=phase+'-turn'\n"
    "  with LOG.open('a') as log: log.write(json.dumps({'phase':phase,'pid':os.getpid()})+'\\n')\n"
    "  print(json.dumps({'method':'item/completed','params':{'threadId':p['threadId'],'turnId':turn,'item':{'type':'agentMessage','text':json.dumps(OUT[phase])}}}),flush=True)\n"
    "  result={'turn':{'id':turn}}\n"
    " else: raise RuntimeError(m)\n"
    " print(json.dumps({'id':r['id'],'result':result}),flush=True)\n"
    " if m=='turn/start': print(json.dumps({'method':'turn/completed','params':{'threadId':p['threadId'],'turn':{'id':turn,'status':'completed','error':None}}}),flush=True)\n")
   config={"executable":sys.executable,"arguments":[str(child)],"authority_key_file":"secrets/key","stream_journal":"logs/stream.jsonl","command_journal":"logs/commands.sqlite","receipt_journal":"logs/receipts.sqlite","payload_file":"ack.json","work_payload_file":"work.json","confirmation_wait_seconds":5,"uat_root":"uat","confirmation_dir":"confirmations"}
   cfg=root/"config.json"; cfg.write_text(json.dumps(config))
   cli=Path(__file__).resolve().parents[1]/"cairn_host.py"
   def invoke(action, success=True):
    proc=subprocess.run([sys.executable,str(cli),action,"--host-root",str(root),"--host-config",str(cfg),"--command-file",str(source)],capture_output=True,text=True,timeout=15)
    if success:
     self.assertEqual(proc.returncode,0,proc.stderr)
     return json.loads(proc.stdout)
    self.assertNotEqual(proc.returncode,0)
    return proc
   def assert_state(expected):
    fixture=uat.Uat(root/"uat")
    with fixture.store.transaction() as (db,ledger): self.assertEqual(ledger._get(db,env["event_id"])["state"],expected)
   journal=ReceiptJournal(root/"logs/receipts.sqlite")
   def confirm(stage):
    receipt=next(r for r in journal.pending("c") if r["stage"]==stage)
    payload=receipt["payload"]
    self.assertEqual(payload["readback"],next(v for v in outputs["ack" if stage=="ack" else "work"] if v["action"]==uat.ACTION[stage]))
    for field in ("transport_ref","stream_ref"): self.assertTrue(payload[field].startswith("artifact://sha256/"))
    raw=json.dumps(payload,sort_keys=True,separators=(",",":")).encode()
    confirmation={"owner":"pm","confirmed":True,"stage":stage,"event_id":env["event_id"],"dedupe":env["dedupe"],"checkpoint":env["checkpoint"],"receipt_sha256":hashlib.sha256(raw).hexdigest()}
    (root/"confirmations"/(receipt["receipt_digest"]+".json")).write_text(json.dumps(confirmation))
    return receipt
   assert_state("SENT")
   ack=invoke("run-command")
   ack_streams={p:p.read_bytes() for p in (root/"logs").glob("stream.*.jsonl")}
   self.assertEqual(len(ack_streams),1)
   self.assertEqual(ack["receipt_digests"],[r["receipt_digest"] for r in journal.pending("c")])
   self.assertEqual([r["stage"] for r in journal.pending("c")],["ack"])
   self.assertEqual(invoke("resume-command")["results"],[]); assert_state("SENT")
   confirm("ack")
   self.assertEqual([r["state"] for r in invoke("resume-command")["results"]],["ACKED"])
   assert_state("ACKED")
   work=invoke("resume-work")
   self.assertEqual(len(list((root/"logs").glob("stream.*.jsonl"))),2)
   for path,content in ack_streams.items(): self.assertEqual(path.read_bytes(),content)
   self.assertEqual(work["receipt_digests"],[r["receipt_digest"] for r in journal.pending("c")])
   self.assertEqual([r["stage"] for r in journal.pending("c")],["start","complete"])
   self.assertEqual(invoke("resume-command")["results"],[]); assert_state("ACKED")
   before=sends.read_bytes()
   duplicate=invoke("resume-work",success=False)
   self.assertIn("already accepted",duplicate.stderr)
   self.assertEqual(sends.read_bytes(),before); assert_state("ACKED")
   confirm("start")
   self.assertEqual([r["state"] for r in invoke("resume-command")["results"]],["STARTED"])
   assert_state("STARTED")
   completion=confirm("complete")["payload"]
   output=Path(completion["output_path"]).read_bytes()
   self.assertEqual(hashlib.sha256(output).hexdigest(),completion["output_sha256"])
   self.assertEqual(json.loads(output)["raw_model_output"],outputs["work"][1])
   self.assertEqual([r["state"] for r in invoke("resume-command")["results"]],["COMPLETED"])
   assert_state("COMPLETED")
   self.assertEqual(invoke("resume-command")["results"],[])
   self.assertEqual(journal.pending("c"),[])
   self.assertEqual(sends.read_bytes(),before)
   dispatched=[json.loads(line) for line in sends.read_text().splitlines()]
   self.assertEqual([entry["phase"] for entry in dispatched],["ack","work"])
   self.assertNotEqual(dispatched[0]["pid"],dispatched[1]["pid"])
 def test_resume_work_expired_acked_never_constructs_transport(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); [ (root/x).mkdir() for x in ("logs","authority","secrets","confirmations") ]
   public=uat.prepare(root/"uat","a"*40); env=public["envelope"]
   sent={"observer":"PM_MANUAL_PLATFORM_READBACK","origin":{"thread_id":public["recipient"],"turn_id":None,"evidence_ref":"artifact://fixture/s"},"readback":dict(env,action=uat.ACTION["sent"])}
   uat.import_observation(root/"uat","sent",sent,clock=lambda:1)
   ack={"observer":"PM_MANUAL_PLATFORM_READBACK","origin":{"thread_id":public["recipient"],"turn_id":"a","evidence_ref":"artifact://fixture/a"},"readback":dict(env,action=uat.ACTION["ack"])}
   uat.import_observation(root/"uat","ack",ack,clock=lambda:2)
   key=b"k"; (root/"secrets/key").write_bytes(key); command={"command_id":"c","event_id":env["event_id"],"dedupe":env["dedupe"],"checkpoint":env["checkpoint"],"thread_id":public["recipient"],"action":"send_work_once","attestation_ref":"a","project":"p","target":public["recipient"],"scope":"local-pilot","principal":"worker","generation":"1"}
   source=root/"command.json"; source.write_text(json.dumps(command)); digest=hashlib.sha256(source.read_bytes()).hexdigest(); binding={"digest":digest,"command":command}; binding["signature"]=hmac.new(key,json.dumps(binding,sort_keys=True,separators=(",",":")).encode(),hashlib.sha256).hexdigest(); (root/"authority/c.json").write_text(json.dumps(binding))
   config={"_host_root":str(root),"authority_key_file":str(root/"secrets/key"),"command_journal":str(root/"logs/c.sqlite"),"receipt_journal":str(root/"logs/r.sqlite"),"uat_root":str(root/"uat")}
   called=[]
   with self.assertRaises(ValueError): resume_work(source,config,{},transport_factory=lambda _:called.append(1))
   self.assertEqual(called,[])
 def test_config_must_stay_under_host_root(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); (root/"secrets").mkdir(); (root/"logs").mkdir(); (root/"uat").mkdir(); (root/"confirmations").mkdir()
   (root/"secrets/key").write_text("k")
   (root/"payload.json").write_text("{}")
   cfg={"executable":"codex","arguments":["app-server"],"authority_key_file":"secrets/key","stream_journal":"logs/stream.jsonl","command_journal":"logs/commands.sqlite","receipt_journal":"logs/receipts.sqlite","payload_file":"payload.json","work_payload_file":"payload.json","confirmation_wait_seconds":1,"uat_root":"uat","confirmation_dir":"confirmations"}
   p=root/"config.json"; p.write_text(json.dumps(cfg))
   self.assertEqual(load_config(root,p)["executable"],"codex")
   cfg["authority_key_file"]="../escape"; p.write_text(json.dumps(cfg))
   with self.assertRaises(ValueError): load_config(root,p)
 def test_fixed_transport_does_not_accept_caller_executable(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); (root/"secrets").mkdir(); (root/"logs").mkdir(); (root/"uat").mkdir(); (root/"confirmations").mkdir(); (root/"secrets/key").write_text("k")
   (root/"payload.json").write_text("{}")
   p=root/"config.json"; p.write_text(json.dumps({"executable":"fixed","arguments":[],"authority_key_file":"secrets/key","stream_journal":"logs/stream.jsonl","command_journal":"logs/commands.sqlite","receipt_journal":"logs/receipts.sqlite","payload_file":"payload.json","work_payload_file":"payload.json","confirmation_wait_seconds":1,"uat_root":"uat","confirmation_dir":"confirmations"}))
   class I:
    def write(self,x): pass
    def flush(self): pass
   class P: stdin=I(); stdout=__import__("io").StringIO()
   calls=[]; transport=fixed_transport(load_config(root,p),popen=lambda *a,**k:calls.append(a) or P())
   self.assertEqual(calls[0][0],["fixed"]); transport.close()
 def test_run_command_reserves_and_persists_observation_only(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); (root/"logs").mkdir(); (root/"authority").mkdir(); (root/"secrets").mkdir(); (root/"uat").mkdir(); (root/"confirmations").mkdir()
   key=b"k"; (root/"secrets/key").write_bytes(key)
   command={"command_id":"c","event_id":"e","dedupe":"d","checkpoint":"n","thread_id":"t","action":"send_work_once","attestation_ref":"a","project":"p","target":"t","scope":"s","principal":"worker","generation":"1"}
   source=root/"command.json"; source.write_text(json.dumps(command))
   digest=hashlib.sha256(source.read_bytes()).hexdigest(); body={"digest":digest,"command":command}
   body["signature"]=hmac.new(key,json.dumps(body,sort_keys=True,separators=(",",":")).encode(),hashlib.sha256).hexdigest()
   (root/"authority/c.json").write_text(json.dumps(body))
   config={"_host_root":str(root),"authority_key_file":str(root/"secrets/key"),"command_journal":str(root/"logs/c.sqlite"),"receipt_journal":str(root/"logs/r.sqlite")}
   class Transport:
    def __init__(self): self.observer=type("O",(),{"received":(
      {"method":"item/completed","params":{"threadId":"t","turnId":"turn","item":{"type":"userMessage","text":"input"}}},
      {"method":"item/completed","params":{"threadId":"t","turnId":"turn","item":{"type":"agentMessage","text":json.dumps([{"action":"ACK_REQUEST"}])}}},
      {"method":"turn/completed","params":{"threadId":"t","turn":{"id":"turn","status":"completed","error":None}}})})()
    def turn_start(self,*_): return {"turn":{"id":"turn"}}
    def initialize_and_resume(self,*_): pass
    def close(self): pass
   receipts=run_command(source,config,{},transport_factory=lambda _:Transport())
   self.assertEqual(len(receipts),1); self.assertEqual(receipts[0]["stage"],"ack")
 def test_interrupted_or_no_output_turn_stays_ambiguous_without_receipt(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); (root/"logs").mkdir(); (root/"authority").mkdir(); (root/"secrets").mkdir()
   key=b"k"; key_path=root/"secrets/key"; key_path.write_bytes(key)
   command={"command_id":"c","event_id":"e","dedupe":"d","checkpoint":"n","thread_id":"t","action":"send_work_once","attestation_ref":"a","project":"p","target":"t","scope":"s","principal":"worker","generation":"1"}
   source=root/"command.json"; source.write_text(json.dumps(command)); digest=hashlib.sha256(source.read_bytes()).hexdigest()
   binding={"digest":digest,"command":command}; binding["signature"]=hmac.new(key,json.dumps(binding,sort_keys=True,separators=(",",":")).encode(),hashlib.sha256).hexdigest(); (root/"authority/c.json").write_text(json.dumps(binding))
   config={"_host_root":str(root),"authority_key_file":str(key_path),"command_journal":str(root/"logs/c.sqlite"),"receipt_journal":str(root/"logs/r.sqlite")}
   class Transport:
    def __init__(self):
     self.sends=0; self.observer=type("Observer",(),{"received":(
      {"method":"turn/completed","params":{"threadId":"t","turn":{"id":"interrupted","status":"interrupted","error":None}}},)})()
    def initialize_and_resume(self,*_): pass
    def turn_start(self,*_): self.sends+=1; return {"turn":{"id":"interrupted"}}
    def close(self): pass
   transport=Transport()
   with self.assertRaises(ObservationTerminalError):
    run_command(source,config,{},transport_factory=lambda _:transport)
   self.assertEqual(transport.sends,1)
   self.assertFalse((root/"logs/r.sqlite").exists())
 def test_changed_or_revoked_binding_cannot_reserve_or_send_work_phase(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); (root/"logs").mkdir(); (root/"authority").mkdir(); (root/"secrets").mkdir()
   key=b"k"; key_path=root/"secrets/key"; key_path.write_bytes(key)
   command={"command_id":"c","event_id":"e","dedupe":"d","checkpoint":"n","thread_id":"t","action":"send_work_once","attestation_ref":"a","project":"p","target":"t","scope":"s","principal":"worker","generation":"1"}
   source=root/"command.json"; source.write_text(json.dumps(command)); digest=hashlib.sha256(source.read_bytes()).hexdigest()
   binding={"digest":digest,"command":command}; binding["signature"]=hmac.new(key,json.dumps(binding,sort_keys=True,separators=(",",":")).encode(),hashlib.sha256).hexdigest(); authority=root/"authority/c.json"; authority.write_text(json.dumps(binding))
   config={"_host_root":str(root),"authority_key_file":str(key_path),"command_journal":str(root/"logs/c.sqlite"),"receipt_journal":str(root/"logs/r.sqlite")}
   class Transport:
    observer=type("Observer",(),{"received":()})()
    def __init__(self): self.sends=0
    def turn_start(self,*_): self.sends+=1; return {"turn":{"id":"forbidden"}}
   for mutate in ("command", "authority"):
    transport=Transport()
    if mutate=="command":
     altered=dict(command, generation="stale"); source.write_text(json.dumps(altered))
    else:
     source.write_text(json.dumps(command)); authority.unlink()
    with self.assertRaises(AuthorityRejected):
     dispatch_on_transport(source,command,digest,config,{},transport,"work")
    self.assertEqual(transport.sends,0)
    self.assertFalse((root/"logs/c.sqlite").exists())
 def test_host_receipt_owns_identity_and_rejects_tampered_evidence(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); (root/"logs").mkdir(); (root/"uat/evidence").mkdir(parents=True)
   command={"command_id":"c","event_id":"event","dedupe":"dedupe","checkpoint":"checkpoint","thread_id":"thread"}
   config={"command_journal":str(root/"logs/c.sqlite"),"uat_root":str(root/"uat")}
   raw={"event_id":"spoofed","thread_id":"spoofed","action":"ACK_REQUEST"}
   receipt=host_flat_receipt(config,command,"turn",{"turn":{"id":"turn"}},raw,1)
   self.assertEqual(receipt["event_id"],"event"); self.assertEqual(receipt["thread_id"],"thread")
   self.assertEqual(receipt["readback"],raw)
   artifact=next((root/"logs/evidence").glob("*.json")); artifact.write_text("{}")
   with self.assertRaises(ValueError):
    host_flat_receipt(config,command,"turn",{"turn":{"id":"turn"}},raw,1)
 def test_executable_cli_runs_fixed_fake_child_to_receipt(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); (root/"logs").mkdir(); (root/"authority").mkdir(); (root/"secrets").mkdir()
   key=b"k"; (root/"secrets/key").write_bytes(key); (root/"payload.json").write_text("{}")
   command={"command_id":"c","event_id":"e","dedupe":"d","checkpoint":"n","thread_id":"t","action":"send_work_once","attestation_ref":"a","project":"p","target":"t","scope":"s","principal":"worker","generation":"1"}
   source=root/"command.json"; source.write_text(json.dumps(command)); digest=hashlib.sha256(source.read_bytes()).hexdigest()
   body={"digest":digest,"command":command}; body["signature"]=hmac.new(key,json.dumps(body,sort_keys=True,separators=(",",":")).encode(),hashlib.sha256).hexdigest(); (root/"authority/c.json").write_text(json.dumps(body))
   child=root/"child.py"; child.write_text(
    "import json,sys\n"
    "for line in sys.stdin:\n"
    " r=json.loads(line); m=r['method']\n"
    " if m=='initialized': continue\n"
    " p=r['params']\n"
    " if m=='initialize': result={}\n"
    " elif m=='thread/resume': result={'thread':{'id':p['threadId']}}\n"
    " else:\n"
    "  item={'method':'item/completed','params':{'threadId':p['threadId'],'turnId':'turn','item':{'type':'agentMessage','text':json.dumps([{'action':'ACK_REQUEST'}])}}}; print(json.dumps(item),flush=True); result={'turn':{'id':'turn'}}\n"
    " print(json.dumps({'id':r['id'],'result':result}),flush=True)\n"
    " if m=='turn/start': print(json.dumps({'method':'turn/completed','params':{'threadId':p['threadId'],'turn':{'id':result['turn']['id'],'status':'completed','error':None}}}),flush=True)\n")
   config={"executable":sys.executable,"arguments":[str(child)],"authority_key_file":"secrets/key","stream_journal":"logs/stream.jsonl","command_journal":"logs/commands.sqlite","receipt_journal":"logs/receipts.sqlite","payload_file":"payload.json","work_payload_file":"payload.json","confirmation_wait_seconds":1,"uat_root":"uat","confirmation_dir":"confirmations"}
   cfg=root/"config.json"; cfg.write_text(json.dumps(config))
   cli=Path(__file__).resolve().parents[1]/"cairn_host.py"
   result=subprocess.run([sys.executable,str(cli),"run-command","--host-root",str(root),"--host-config",str(cfg),"--command-file",str(source)],capture_output=True,text=True,timeout=10)
   self.assertEqual(result.returncode,0,result.stderr); self.assertIn("receipt_digests",result.stdout)
 def test_resume_command_imports_host_confirmation_with_real_store(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); (root/"confirmations").mkdir(); (root/"logs").mkdir(); (root/"authority").mkdir(); (root/"secrets").mkdir()
   key=b"k"; (root/"secrets/key").write_bytes(key)
   public=uat.prepare(root/"uat","a"*40); env=public["envelope"]
   sent={"observer":"PM_MANUAL_PLATFORM_READBACK","origin":{"thread_id":public["recipient"],"turn_id":None,"evidence_ref":"artifact://fixture/sent"},"readback":dict(env,action=uat.ACTION["sent"])}
   uat.import_observation(root/"uat","sent",sent)
   command={"command_id":"c","event_id":env["event_id"],"dedupe":env["dedupe"],"checkpoint":env["checkpoint"],"thread_id":public["recipient"],"action":"send_work_once","attestation_ref":"a","project":"p","target":public["recipient"],"scope":"local-pilot","principal":"worker","generation":"1"}
   source=root/"command.json"; source.write_text(json.dumps(command)); digest=hashlib.sha256(source.read_bytes()).hexdigest()
   binding={"digest":digest,"command":command}; binding["signature"]=hmac.new(key,json.dumps(binding,sort_keys=True,separators=(",",":")).encode(),hashlib.sha256).hexdigest(); (root/"authority/c.json").write_text(json.dumps(binding))
   flat={"event_id":env["event_id"],"dedupe":env["dedupe"],"checkpoint":env["checkpoint"],"thread_id":public["recipient"],"turn_id":"ack-turn","action":uat.ACTION["ack"],"readback":dict(env,action=uat.ACTION["ack"]),"transport_ref":"artifact://fixture/transport","stream_ref":"artifact://fixture/stream"}
   observed=observed_receipt(command,digest,"ack","ack-turn",flat,sequence=1,clock=lambda:1)
   journal=ReceiptJournal(root/"logs/receipts.sqlite"); journal.persist_receipt(observed)
   raw=json.dumps(flat,sort_keys=True,separators=(",",":")).encode()
   confirmation={"owner":"pm","confirmed":True,"stage":"ack","event_id":env["event_id"],"dedupe":env["dedupe"],"checkpoint":env["checkpoint"],"receipt_sha256":hashlib.sha256(raw).hexdigest()}
   (root/"confirmations"/(observed["receipt_digest"]+".json")).write_text(json.dumps(confirmation))
   config={"_host_root":str(root),"authority_key_file":str(root/"secrets/key"),"receipt_journal":str(root/"logs/receipts.sqlite"),"confirmation_dir":str(root/"confirmations"),"uat_root":str(root/"uat")}
   self.assertEqual(resume_command(source,config)[0]["state"],"ACKED")
   for stage,turn,state in (("start","work-turn","STARTED"),("complete","work-turn","COMPLETED")):
    flat={"event_id":env["event_id"],"dedupe":env["dedupe"],"checkpoint":env["checkpoint"],"thread_id":public["recipient"],"turn_id":turn,"action":uat.ACTION[stage],"readback":dict(env,action=uat.ACTION[stage]),"transport_ref":"artifact://fixture/transport","stream_ref":"artifact://fixture/stream"}
    if stage=="complete":
     output=root/"uat/evidence/meaningful-output.txt"; output.write_text("offline child verified requested arithmetic: 17 + 25 = 42")
     h=hashlib.sha256(output.read_bytes()).hexdigest()
     flat.update(readback=dict(env,action=uat.ACTION[stage],result=42),output_path=str(output),output_sha256=h,output_ref="artifact://sha256/"+h)
    observed=observed_receipt(command,digest,stage,turn,flat,sequence=2,clock=lambda:2)
    journal.persist_receipt(observed); raw=json.dumps(flat,sort_keys=True,separators=(",",":")).encode()
    confirmation={"owner":"pm","confirmed":True,"stage":stage,"event_id":env["event_id"],"dedupe":env["dedupe"],"checkpoint":env["checkpoint"],"receipt_sha256":hashlib.sha256(raw).hexdigest()}
    (root/"confirmations"/(observed["receipt_digest"]+".json")).write_text(json.dumps(confirmation))
    self.assertEqual(resume_command(source,config)[0]["state"],state)
   self.assertEqual(resume_command(source,config),[])
 def test_composition_regression_uses_same_transport_receipt_and_import_path(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); (root/"logs").mkdir(); (root/"confirmations").mkdir(); (root/"authority").mkdir(); (root/"secrets").mkdir()
   key=b"k"; (root/"secrets/key").write_bytes(key)
   public=uat.prepare(root/"uat","a"*40); env=public["envelope"]
   sent={"observer":"PM_MANUAL_PLATFORM_READBACK","origin":{"thread_id":public["recipient"],"turn_id":None,"evidence_ref":"artifact://fixture/sent"},"readback":dict(env,action=uat.ACTION["sent"])}
   uat.import_observation(root/"uat","sent",sent)
   command={"command_id":"c","event_id":env["event_id"],"dedupe":env["dedupe"],"checkpoint":env["checkpoint"],"thread_id":public["recipient"],"action":"send_work_once","attestation_ref":"a","project":"p","target":public["recipient"],"scope":"local-pilot","principal":"worker","generation":"1"}; source=root/"command.json"; source.write_text(json.dumps(command))
   command_digest=hashlib.sha256(source.read_bytes()).hexdigest()
   binding={"digest":command_digest,"command":command}; binding["signature"]=hmac.new(key,json.dumps(binding,sort_keys=True,separators=(",",":")).encode(),hashlib.sha256).hexdigest(); (root/"authority/c.json").write_text(json.dumps(binding))
   def flat(stage,turn):
    x={"event_id":env["event_id"],"dedupe":env["dedupe"],"checkpoint":env["checkpoint"],"thread_id":public["recipient"],"turn_id":turn,"action":uat.ACTION[stage],"readback":dict(env,action=uat.ACTION[stage]),"transport_ref":"artifact://fixture/transport","stream_ref":"artifact://fixture/stream"}
    if stage=="complete":
     output=root/"uat/evidence/child-output.txt"; output.write_text("fake child completed: 17 + 25 = 42"); h=hashlib.sha256(output.read_bytes()).hexdigest()
     x.update(readback=dict(env,action=uat.ACTION[stage],result=42),output_path=str(output),output_sha256=h,output_ref="artifact://sha256/"+h)
    return x
   outputs=[[flat("ack","ack-turn")],[flat("start","work-turn"),flat("complete","work-turn")]]
   child=root/"child.py"; child.write_text("import json,sys\nOUT="+repr(outputs)+"\ni=0\nfor line in sys.stdin:\n r=json.loads(line); m=r['method']\n if m=='initialized': continue\n p=r['params']\n if m=='initialize': result={}\n elif m=='thread/resume': result={'thread':{'id':p['threadId']}}\n else:\n  turn='ack-turn' if i==0 else 'work-turn'; item={'method':'item/completed','params':{'threadId':p['threadId'],'turnId':turn,'item':{'type':'agentMessage','text':json.dumps(OUT[i])}}}; print(json.dumps(item),flush=True); result={'turn':{'id':turn}}; i+=1\n print(json.dumps({'id':r['id'],'result':result}),flush=True)\n if m=='turn/start': print(json.dumps({'method':'turn/completed','params':{'threadId':p['threadId'],'turn':{'id':result['turn']['id'],'status':'completed','error':None}}}),flush=True)\n")
   transport=AppServerStdioTransport(sys.executable,[str(child)],root/"logs/stream.jsonl"); journal=ReceiptJournal(root/"logs/receipts.sqlite"); config={"_host_root":str(root),"authority_key_file":str(root/"secrets/key"),"receipt_journal":str(root/"logs/receipts.sqlite"),"confirmation_dir":str(root/"confirmations"),"uat_root":str(root/"uat")}
   try:
    transport.initialize_and_resume(public["recipient"])
    for turn_index in range(2):
     turn=transport.turn_start(public["recipient"],{})["turn"]["id"]
     item=[m for m in transport.observer.received if m.get("method")=="item/completed"][-1]
     for output in parse_completed(item,thread_id=public["recipient"],turn_id=turn):
      observed=receipt_from_agent_output(command,command_digest,turn,output,sequence=turn_index+1); journal.persist_receipt(observed)
      raw=json.dumps(output,sort_keys=True,separators=(",",":")).encode(); stage=observed["stage"]
      confirmation={"owner":"pm","confirmed":True,"stage":stage,"event_id":env["event_id"],"dedupe":env["dedupe"],"checkpoint":env["checkpoint"],"receipt_sha256":hashlib.sha256(raw).hexdigest()}
      (root/"confirmations"/(observed["receipt_digest"]+".json")).write_text(json.dumps(confirmation))
     resume_command(source,config)
   finally: transport.close()
   fixture=uat.Uat(root/"uat")
   with fixture.store.transaction() as (db,ledger):
    self.assertEqual(ledger._get(db,env["event_id"])["state"],"COMPLETED")
   self.assertEqual(resume_command(source,config),[])
 def test_cli_session_fake_child_receipts_then_separate_confirmations(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); [ (root/x).mkdir() for x in ("logs","confirmations","authority","secrets") ]
   public=uat.prepare(root/"uat","a"*40); env=public["envelope"]
   sent={"observer":"PM_MANUAL_PLATFORM_READBACK","origin":{"thread_id":public["recipient"],"turn_id":None,"evidence_ref":"artifact://fixture/sent"},"readback":dict(env,action=uat.ACTION["sent"])}; uat.import_observation(root/"uat","sent",sent)
   key=b"k"; (root/"secrets/key").write_bytes(key); (root/"ack.json").write_text("{}"); (root/"work.json").write_text("{}")
   command={"command_id":"c","event_id":env["event_id"],"dedupe":env["dedupe"],"checkpoint":env["checkpoint"],"thread_id":public["recipient"],"action":"send_work_once","attestation_ref":"a","project":"p","target":public["recipient"],"scope":"local-pilot","principal":"worker","generation":"1"}
   source=root/"command.json"; source.write_text(json.dumps(command)); digest=hashlib.sha256(source.read_bytes()).hexdigest()
   binding={"digest":digest,"command":command}; binding["signature"]=hmac.new(key,json.dumps(binding,sort_keys=True,separators=(",",":")).encode(),hashlib.sha256).hexdigest(); (root/"authority/c.json").write_text(json.dumps(binding))
   def readback(stage):
    value=dict(env,action=uat.ACTION[stage])
    if stage=="complete": value["result"]=42
    return value
   outputs=[[readback("ack")],[readback("start"),readback("complete")]]
   child=root/"child.py"; child.write_text("import json,sys\nOUT="+repr(outputs)+"\ni=0\nfor line in sys.stdin:\n r=json.loads(line); m=r['method']\n if m=='initialized': continue\n p=r['params']\n if m=='initialize': result={}\n elif m=='thread/resume': result={'thread':{'id':p['threadId']}}\n else:\n  turn='ack-turn' if i==0 else 'work-turn'\n  item={'method':'item/completed','params':{'threadId':p['threadId'],'turnId':turn,'item':{'type':'agentMessage','text':json.dumps(OUT[i])}}}; print(json.dumps(item),flush=True); result={'turn':{'id':turn}}; i+=1\n print(json.dumps({'id':r['id'],'result':result}),flush=True)\n if m=='turn/start': print(json.dumps({'method':'turn/completed','params':{'threadId':p['threadId'],'turn':{'id':result['turn']['id'],'status':'completed','error':None}}}),flush=True)\n")
   config={"executable":sys.executable,"arguments":[str(child)],"authority_key_file":"secrets/key","stream_journal":"logs/stream.jsonl","command_journal":"logs/commands.sqlite","receipt_journal":"logs/receipts.sqlite","payload_file":"ack.json","work_payload_file":"work.json","confirmation_wait_seconds":5,"uat_root":"uat","confirmation_dir":"confirmations"}; cfg=root/"config.json"; cfg.write_text(json.dumps(config))
   cli=Path(__file__).resolve().parents[1]/"cairn_host.py"; proc=subprocess.Popen([sys.executable,str(cli),"run-session","--host-root",str(root),"--host-config",str(cfg),"--command-file",str(source)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
   journal=ReceiptJournal(root/"logs/receipts.sqlite"); seen=set(); deadline=time.time()+5
   while time.time()<deadline and proc.poll() is None:
    for receipt in journal.pending("c"):
     if receipt["receipt_digest"] in seen: continue
     payload=receipt["payload"]; raw=json.dumps(payload,sort_keys=True,separators=(",",":")).encode()
     confirmation={"owner":"pm","confirmed":True,"stage":receipt["stage"],"event_id":env["event_id"],"dedupe":env["dedupe"],"checkpoint":env["checkpoint"],"receipt_sha256":hashlib.sha256(raw).hexdigest()}
     (root/"confirmations"/(receipt["receipt_digest"]+".json")).write_text(json.dumps(confirmation)); seen.add(receipt["receipt_digest"])
    time.sleep(.03)
   stdout,stderr=proc.communicate(timeout=5); self.assertEqual(proc.returncode,0,stderr); self.assertIn("run-session",stdout); self.assertEqual(len(seen),3)
   fixture=uat.Uat(root/"uat")
   with fixture.store.transaction() as (db,ledger): self.assertEqual(ledger._get(db,env["event_id"])["state"],"COMPLETED")
   restored=uat.backup_restore_uat(root/"uat")
   self.assertEqual(restored["state"],"COMPLETED")
   self.assertEqual(restored["envelope"]["event_id"],env["event_id"])
