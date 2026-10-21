"""AWS Bedrock Converse API client."""

from collections.abc import Sequence
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.llm.client import LLMResponse, LLMUnavailableError, ToolSpec


class BedrockLLMClient:
    def __init__(self, model_id: str, runtime_client: Any):
        self.model_id = model_id
        self.runtime = runtime_client

    @classmethod
    def from_profile(
        cls, model_id: str, profile: str | None, region: str, expected_role: str
    ) -> "BedrockLLMClient":
        """Build a client, refusing to run under any role other than `expected_role`.

        This keeps AlphaLab from silently using broader credentials (e.g. an admin
        profile from another project) if the environment is misconfigured. With no
        profile, credentials come from the environment (e.g. GitHub Actions OIDC).
        """
        source = f"AWS profile '{profile}'" if profile else "AWS credentials from the environment"
        try:
            session = boto3.Session(profile_name=profile, region_name=region)
            arn = session.client("sts").get_caller_identity()["Arn"]
        except (BotoCoreError, ClientError) as exc:
            hint = (
                f"If your SSO session expired, run: aws sso login --profile {profile}"
                if profile
                else "Check that the job assumed its AWS role."
            )
            raise LLMUnavailableError(f"Could not authenticate {source}: {exc}. {hint}") from exc
        # Assumed SSO roles look like .../AWSReservedSSO_<PermissionSet>_<suffix>/<user>;
        # assumed IAM roles look like .../assumed-role/<RoleName>/<session>.
        if f"_{expected_role}_" not in arn and f"/{expected_role}/" not in arn:
            raise LLMUnavailableError(
                f"{source} is running as {arn}, not the {expected_role} role. "
                "Refusing to use broader credentials."
            )
        runtime = session.client(
            "bedrock-runtime", config=Config(retries={"max_attempts": 4, "mode": "adaptive"})
        )
        return cls(model_id, runtime)

    def converse(
        self,
        system: str,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[ToolSpec],
        max_tokens: int,
    ) -> LLMResponse:
        try:
            response = self.runtime.converse(
                modelId=self.model_id,
                system=[{"text": system}],
                messages=list(messages),
                toolConfig={
                    "tools": [
                        {
                            "toolSpec": {
                                "name": t.name,
                                "description": t.description,
                                "inputSchema": {"json": t.input_schema},
                            }
                        }
                        for t in tools
                    ]
                },
                inferenceConfig={"maxTokens": max_tokens},
            )
        except (BotoCoreError, ClientError) as exc:
            raise LLMUnavailableError(f"Bedrock request failed: {exc}") from exc
        usage = response.get("usage", {})
        return LLMResponse(
            message=response["output"]["message"],
            stop_reason=response["stopReason"],
            input_tokens=usage.get("inputTokens", 0),
            output_tokens=usage.get("outputTokens", 0),
        )
