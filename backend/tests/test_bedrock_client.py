import pytest
from botocore.exceptions import ClientError

from app.llm import bedrock
from app.llm.bedrock import BedrockLLMClient
from app.llm.client import LLMUnavailableError, ToolSpec

ALPHALAB_ARN = (
    "arn:aws:sts::637423355393:assumed-role/AWSReservedSSO_AlphaLabBedrock_c98f87e0aed9e7db/me"
)
ADMIN_ARN = (
    "arn:aws:sts::637423355393:assumed-role/AWSReservedSSO_AdministratorAccess_f3d6e93022aa23ec/me"
)


class FakeSession:
    def __init__(self, arn: str):
        self.arn = arn

    def __call__(self, profile_name, region_name):
        self.profile, self.region = profile_name, region_name
        return self

    def client(self, service, config=None):
        if service == "sts":
            return type("STS", (), {"get_caller_identity": lambda _: {"Arn": self.arn}})()
        return FakeRuntime()


class FakeRuntime:
    def __init__(self, error: Exception | None = None):
        self.kwargs = None
        self.error = error

    def converse(self, **kwargs):
        if self.error:
            raise self.error
        self.kwargs = kwargs
        return {
            "output": {"message": {"role": "assistant", "content": [{"text": "hi"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 12, "outputTokens": 3},
        }


def from_profile(monkeypatch, arn: str) -> BedrockLLMClient:
    monkeypatch.setattr(bedrock.boto3, "Session", FakeSession(arn))
    return BedrockLLMClient.from_profile("model-x", "alphalab", "us-east-1", "AlphaLabBedrock")


def test_accepts_the_restricted_alphalab_role(monkeypatch):
    assert from_profile(monkeypatch, ALPHALAB_ARN).model_id == "model-x"


def test_refuses_broader_credentials(monkeypatch):
    with pytest.raises(LLMUnavailableError, match="Refusing to use broader credentials"):
        from_profile(monkeypatch, ADMIN_ARN)


def test_converse_maps_requests_and_responses():
    runtime = FakeRuntime()
    client = BedrockLLMClient("model-x", runtime)
    tool = ToolSpec("get_portfolio", "desc", {"type": "object", "properties": {}})

    response = client.converse("sys", [{"role": "user", "content": [{"text": "go"}]}], [tool], 500)

    assert runtime.kwargs["modelId"] == "model-x"
    assert runtime.kwargs["system"] == [{"text": "sys"}]
    assert runtime.kwargs["toolConfig"]["tools"][0]["toolSpec"]["inputSchema"] == {
        "json": tool.input_schema
    }
    assert runtime.kwargs["inferenceConfig"] == {"maxTokens": 500}
    assert (response.stop_reason, response.input_tokens, response.output_tokens) == (
        "end_turn",
        12,
        3,
    )


def test_aws_errors_become_llm_unavailable():
    error = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "Converse"
    )
    client = BedrockLLMClient("model-x", FakeRuntime(error))
    with pytest.raises(LLMUnavailableError, match="ThrottlingException"):
        client.converse("sys", [], [], 10)
