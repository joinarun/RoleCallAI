import json

from tests.eval.eval_api import rewrite_session_seed


def test_rewrite_session_seed_moves_only_rolecall_fixture_to_state() -> None:
    payload = {
        "events": [
            {
                "author": "user",
                "content": {"role": "user", "parts": [{"text": "Begin"}]},
                "stateDelta": {
                    "rolecallEval": {
                        "scenarioId": "scenario-1",
                        "meetingState": {"status": "RUNNING"},
                    },
                    "untrustedOtherState": "discarded",
                },
            }
        ]
    }

    rewritten = json.loads(rewrite_session_seed(json.dumps(payload).encode()))

    assert rewritten["state"] == {
        "rolecallEval": {
            "scenarioId": "scenario-1",
            "meetingState": {"status": "RUNNING"},
        }
    }
    assert "stateDelta" not in rewritten["events"][0]


def test_rewrite_session_seed_leaves_unseeded_body_unchanged() -> None:
    raw_body = b'{"events":[]}'
    assert rewrite_session_seed(raw_body) == raw_body
