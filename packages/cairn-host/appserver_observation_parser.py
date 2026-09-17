"""Pinned parser for App Server item/completed agentMessage notifications."""
import json

class ObservationParseError(ValueError): pass
class ObservationTerminalError(ObservationParseError): pass

def terminal_turn(message, *, thread_id, turn_id):
    """Return the terminal turn only when it is bound to this exact request."""
    if not isinstance(message, dict) or message.get("method") != "turn/completed":
        return None
    params = message.get("params")
    turn = params.get("turn") if isinstance(params, dict) else None
    if (not isinstance(params, dict) or params.get("threadId") != thread_id
            or not isinstance(turn, dict) or turn.get("id") != turn_id):
        return None
    return turn

def final_agent_message(messages, *, thread_id, turn_id):
    """Select exactly one final agent item after the turn has terminated.

    Non-agent item/completed notifications are normal App Server traffic.  They
    are never parsed as a recipient receipt, and more than one agent receipt is
    ambiguous rather than an invitation to choose an intermediate message.
    """
    matches = []
    for message in messages:
        if not isinstance(message, dict) or message.get("method") != "item/completed":
            continue
        params = message.get("params")
        item = params.get("item") if isinstance(params, dict) else None
        if (isinstance(params, dict) and params.get("threadId") == thread_id
                and params.get("turnId") == turn_id and isinstance(item, dict)
                and item.get("type") == "agentMessage"):
            matches.append(message)
    if len(matches) != 1:
        raise ObservationParseError("Require exactly one final bound agent message")
    return matches[0]

def parse_completed(message, *, thread_id, turn_id):
    if not isinstance(message, dict) or message.get("method") != "item/completed":
        raise ObservationParseError("Require item/completed")
    params=message.get("params")
    item=params.get("item") if isinstance(params,dict) else None
    if (not isinstance(params,dict) or params.get("threadId") != thread_id
            or params.get("turnId") != turn_id or not isinstance(item,dict)
            or item.get("type") != "agentMessage" or not isinstance(item.get("text"),str)):
        raise ObservationParseError("Completed item binding mismatch")
    try: value=json.loads(item["text"])
    except json.JSONDecodeError as e: raise ObservationParseError("Agent output is not JSON") from e
    if not isinstance(value,list) or not value or not all(isinstance(x,dict) for x in value):
        raise ObservationParseError("Require nonempty object array")
    return value
