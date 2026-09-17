from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from appserver_observation_parser import *
class T(unittest.TestCase):
 def test_pinned_item_completed_shape(self):
  m={"method":"item/completed","params":{"threadId":"t","turnId":"u","item":{"type":"agentMessage","text":"[{\"action\":\"ACK_REQUEST\"}]"}}}
  self.assertEqual(parse_completed(m,thread_id="t",turn_id="u")[0]["action"],"ACK_REQUEST")
  with self.assertRaises(ObservationParseError): parse_completed(m,thread_id="bad",turn_id="u")
 def test_final_agent_selection_ignores_non_agent_and_rejects_ambiguity(self):
  non_agent={"method":"item/completed","params":{"threadId":"t","turnId":"u","item":{"type":"userMessage","text":"input"}}}
  agent={"method":"item/completed","params":{"threadId":"t","turnId":"u","item":{"type":"agentMessage","text":"[{\"action\":\"ACK_REQUEST\"}]"}}}
  wrong={"method":"item/completed","params":{"threadId":"wrong","turnId":"u","item":{"type":"agentMessage","text":"[]"}}}
  self.assertIs(final_agent_message([non_agent,wrong,agent],thread_id="t",turn_id="u"),agent)
  with self.assertRaises(ObservationParseError): final_agent_message([agent,agent],thread_id="t",turn_id="u")
 def test_terminal_turn_is_exact_and_carries_terminal_error(self):
  message={"method":"turn/completed","params":{"threadId":"t","turn":{"id":"u","status":"interrupted","error":None}}}
  self.assertEqual(terminal_turn(message,thread_id="t",turn_id="u")["status"],"interrupted")
  self.assertIsNone(terminal_turn(message,thread_id="wrong",turn_id="u"))
