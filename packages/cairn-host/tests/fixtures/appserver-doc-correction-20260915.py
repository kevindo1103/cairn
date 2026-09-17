import hashlib, json, os, types
from pathlib import Path
import sqlite3, subprocess, sys, time
WORK=Path(r"C:\Users\ddkho\Documents\Codex\2026-09-10\codex-communication-ledger")
TREE=WORK/"work"/"cairn-issue15-adapter"; HOST=TREE/"packages"/"cairn-host"
sys.path.insert(0,str(HOST)); import existing_task_uat as uat
OBSERVER_PATH=Path(r"C:\ProgramData\CairnBroker\issue15-test\observer-21b4115ceb182c763d6f9f3ec7e3f2a2d10656a35e2f396330fa245a6da5f329.py")
OBSERVER_SHA256="21b4115ceb182c763d6f9f3ec7e3f2a2d10656a35e2f396330fa245a6da5f329"
def load_observer():
 if os.path.islink(OBSERVER_PATH) or (os.lstat(OBSERVER_PATH).st_file_attributes & 0x400):raise RuntimeError("observer artifact must not be a reparse point")
 data=OBSERVER_PATH.read_bytes()
 if hashlib.sha256(data).hexdigest()!=OBSERVER_SHA256:raise RuntimeError("observer artifact hash mismatch")
 module=types.ModuleType("cairn_protected_observer"); module.__file__=str(OBSERVER_PATH)
 exec(compile(data,str(OBSERVER_PATH),"exec"),module.__dict__)
 return module.AppServerStreamObserver,module.SafeNotificationJournal
AppServerStreamObserver,SafeNotificationJournal=load_observer()
CODEX=r"C:\Users\ddkho\AppData\Local\OpenAI\Codex\bin\12219cbfbcbddde7\codex.exe"
ROOT=Path(r"C:\ProgramData\CairnBroker\issue15-test\doc-correction-20260915-01"); ROOT.mkdir(); (ROOT/"evidence").mkdir()
HEAD="0dc7996c1281eb92f8e4ceb9e044cbcc32e25476"; DEDUPE="cairn:limited-pilot:doc-correction:001"; events=[]
p=subprocess.Popen([CODEX,"app-server","--listen","stdio://"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",bufsize=1)
observer=AppServerStreamObserver(p.stdout, journal=SafeNotificationJournal(ROOT/"evidence"/"stream-safe.jsonl"))
OPERATOR_CLEANUP=False
def req(i,m,x):
 p.stdin.write(json.dumps({"jsonrpc":"2.0","id":i,"method":m,"params":x})+"\n"); p.stdin.flush(); end=time.monotonic()+90
 q=observer.wait_for(lambda q:q.get("id")==i,timeout_seconds=90)
 events[:]=observer.received
 if "error" in q: raise RuntimeError(q["error"])
 return q["result"]
def until_turn(t):
 q=observer.wait_for(lambda q:q.get("method")=="turn/completed" and q["params"]["turn"]["id"]==t,timeout_seconds=90)
 events[:]=observer.received
 return q
def final(q):
 x=[z["text"] for z in q["params"]["turn"]["items"] if z.get("type")=="agentMessage"]
 if len(x)!=1: raise ValueError("one final agent message required")
 return json.loads(x[0])
def art(n,v):
 f=ROOT/"evidence"/n; f.write_text(json.dumps(v,indent=2)+"\n",encoding="utf-8")
 return "artifact://sha256/"+hashlib.sha256(f.read_bytes()).hexdigest()
def obs(env,act,turn,ref,result=None):
 r=dict(env,action=act)
 if result is not None:r["result"]=result
 return {"observer":"PM_MANUAL_PLATFORM_READBACK","origin":{"thread_id":recipient,"turn_id":turn,"evidence_ref":ref},"readback":r}
try:
 req(1,"initialize",{"clientInfo":{"name":"cairn-doc-correction","version":"0.1"},"capabilities":{"experimentalApi":True}})
 thread=req(2,"thread/start",{"ephemeral":True,"environments":[],"sandbox":"read-only","historyMode":"paginated"}); recipient=thread["thread"]["id"]
 pub=uat.prepare(ROOT/"uat",HEAD,recipient=recipient,dedupe=DEDUPE); env=pub["envelope"]; ack=dict(env,action="ACK_REQUEST",acknowledgement=True)
 at=req(3,"turn/start",{"threadId":recipient,"input":[{"type":"text","text":"Return exactly this JSON and do not use tools: "+json.dumps(ack,separators=(',',':'))}]})["turn"]["id"]
 receipt=art("transport.json",{"thread_id":recipient,"turn_id":at,"accepted":True}); uat.import_observation(ROOT/"uat","sent",obs(env,"TRANSPORT_ACCEPTED",None,receipt))
 if final(until_turn(at))!=ack:raise ValueError("ack mismatch")
 ar=art("ack.json",{"payload":ack,"events":events}); a=uat.import_observation(ROOT/"uat","ack",obs(env,"ACK_REQUEST",at,ar))
 start=dict(env,action="START_REQUEST"); complete=dict(env,action="COMPLETION_REQUEST",result=42)
 matrix=(WORK/"work"/"issue15-readiness"/"READINESS_MATRIX.md").read_text(encoding="utf-8"); local=(HOST/"LOCAL_PILOT.md").read_text(encoding="utf-8")
 instruction="No tools, no edits. Return exactly a JSON array: first "+json.dumps(start,separators=(',',':'))+". Second contains "+json.dumps(complete,separators=(',',':'))+" plus replacements: an array of exactly two objects {path,old,new}. Paths must be READINESS_MATRIX.md and LOCAL_PILOT.md. Canonical wording: LIMITED_PILOT_AUTHORIZED at accepted head0dc7996c1281eb92f8e4ceb9e044cbcc32e25476 under user grant #15comment5677339859. Accepted App Server pilot completed SENT→ACKED→STARTED→COMPLETED. Historical attempt1 remains STOP and is not replayed. OS isolation/platform-enforced identity NOT_PROVEN; automatic wake NOT_IMPLEMENTED; broad activation/topology migration/retirement/production NOT_AUTHORIZED. Full CUTOVER_READY remains false and is distinct from limited pilot acceptance. Preserve machine flags; prose only.\nMATRIX:\n"+matrix+"\nLOCAL:\n"+local
 wt=req(4,"turn/start",{"threadId":recipient,"input":[{"type":"text","text":instruction}]})["turn"]["id"]; out=final(until_turn(wt))
 if not isinstance(out,list) or len(out)!=2 or out[0]!=start:raise ValueError("start mismatch")
 c=out[1]
 if any(c.get(k)!=v for k,v in complete.items()) or not isinstance(c.get("replacements"),list) or len(c["replacements"])!=2:raise ValueError("complete mismatch")
 wr=art("work.json",{"payload":out,"events":events}); s=uat.import_observation(ROOT/"uat","start",obs(env,"START_REQUEST",wt,wr)); z=uat.import_observation(ROOT/"uat","complete",obs(env,"COMPLETION_REQUEST",wt,wr,42))
 store=uat.Uat(ROOT/"uat").store; api=uat.dependencies(); proof=api["proof"](store.path); bak=api["backup"](store.path,ROOT/"evidence"/"backup.sqlite"); restored=api["restore"](ROOT/"evidence"/"backup.sqlite",ROOT/"restored",bak,uat.PROJECT); reopened=api["Store"](ROOT/"restored",uat.PROJECT)
 if proof!=bak or restored!=bak or api["proof"](reopened.path)!=bak:raise RuntimeError("recovery mismatch")
 with sqlite3.connect("file:"+str(store.path)+"?mode=ro",uri=True) as db: counts=dict(db.execute("select action,count(*) from history where event_id=? group by action",(env["event_id"],)).fetchall())
 result={"event_id":env["event_id"],"dedupe":DEDUPE,"recipient":recipient,"turns":{"ack":at,"work":wt},"receipt":receipt,"ack":a,"start":s,"complete":z,"replacements":c["replacements"],"counts":counts,"backup_restore_equal":True,"final_state":z["state"]}
 art("result.json",result); print(json.dumps(result,indent=2))
finally:
 observer.close()
 if OPERATOR_CLEANUP:
  p.terminate()
  try:p.wait(timeout=5)
  except subprocess.TimeoutExpired:p.kill()
