from types import SimpleNamespace

from tests.eval import eu_judge


def test_eu_judge_keeps_client_alive_for_request_and_closes_it(monkeypatch) -> None:
    verdict = eu_judge.Verdict(
        task_success=1,
        tool_use_quality=1,
        trajectory_quality=1,
        hallucination=1,
        instruction_following=1,
        safety=1,
        overall=1,
        explanation="pass",
    )

    class FakeClient:
        def __init__(self) -> None:
            self.closed = False
            self.models = self

        def generate_content(self, **kwargs):  # type: ignore[no-untyped-def]
            assert not self.closed
            assert kwargs["model"] == "gemini-3.7-flash"
            return SimpleNamespace(parsed=verdict, text=None)

        def close(self) -> None:
            self.closed = True

    client = FakeClient()
    monkeypatch.setattr(eu_judge, "_regional_client", lambda: client)
    eu_judge._CACHE.clear()

    result = eu_judge.evaluate_component({"case": "client-lifetime"}, "overall")

    assert result["score"] == 1
    assert client.closed


def test_eu_judge_retries_transient_capacity_failure(monkeypatch) -> None:
    verdict = eu_judge.Verdict(
        task_success=1,
        tool_use_quality=1,
        trajectory_quality=1,
        hallucination=1,
        instruction_following=1,
        safety=1,
        overall=1,
        explanation="pass after retry",
    )

    class CapacityError(RuntimeError):
        code = 429

    class FakeClient:
        def __init__(self) -> None:
            self.attempts = 0
            self.closed = False
            self.models = self

        def generate_content(self, **_kwargs):  # type: ignore[no-untyped-def]
            self.attempts += 1
            if self.attempts == 1:
                raise CapacityError("capacity")
            return SimpleNamespace(parsed=verdict, text=None)

        def close(self) -> None:
            self.closed = True

    client = FakeClient()
    monkeypatch.setattr(eu_judge, "_regional_client", lambda: client)
    monkeypatch.setattr(eu_judge.time, "sleep", lambda _seconds: None)
    eu_judge._CACHE.clear()

    result = eu_judge.evaluate_component({"case": "transient-capacity"}, "overall")

    assert result["score"] == 1
    assert client.attempts == 2
    assert client.closed
