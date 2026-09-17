import io, json
from pathlib import Path
import sys, tempfile, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from appserver_stdio_transport import AppServerStdioTransport

class In:
 def __init__(self): self.items=[]
 def write(self, x): self.items.append(x)
 def flush(self): pass
class P:
 def __init__(self, stream=None): self.stdin=In(); self.stdout=io.StringIO(stream or '{"id":1,"result":{}}\n{"id":2,"result":{"thread":{"id":"thread"}}}\n{"id":3,"result":{"turn":{"id":"x"}}}\n')
class Tests(unittest.TestCase):
 def test_one_configured_process_and_jsonrpc_turn_start(self):
  with tempfile.TemporaryDirectory() as d:
   calls=[]
   transport=AppServerStdioTransport("codex", ["app-server"], Path(d)/"stream.jsonl",
     popen=lambda *a,**k: calls.append((a,k)) or P())
   try:
    transport.initialize_and_resume("thread")
    self.assertEqual(transport.turn_start("thread", {"x":1})["turn"]["id"],"x")
    self.assertEqual(calls[0][0][0],["codex","app-server"])
    self.assertFalse(calls[0][1]["shell"])
    self.assertEqual([json.loads(x)["method"] for x in transport.process.stdin.items],["initialize","initialized","thread/resume","turn/start"])
   finally: transport.close()
 def test_failed_resume_never_starts_turn(self):
  with tempfile.TemporaryDirectory() as d:
   transport=AppServerStdioTransport("codex", ["app-server"], Path(d)/"stream.jsonl",
     popen=lambda *a,**k: P('{"id":1,"result":{}}\n{"id":2,"result":{"thread":{"id":"other"}}}\n'))
   try:
    with self.assertRaises(RuntimeError): transport.initialize_and_resume("thread")
    self.assertEqual([json.loads(x)["method"] for x in transport.process.stdin.items],["initialize","initialized","thread/resume"])
   finally: transport.close()
