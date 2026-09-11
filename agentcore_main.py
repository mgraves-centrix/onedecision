"""Amazon Bedrock AgentCore Runtime entrypoint for OneDecision.

AgentCore runs this file from the root of the deployment package, where the
`app` package sits beside it. All of the logic lives in `app/agentcore.py`;
this file only has to be importable from the package root.
"""

from app.agentcore import build_app

agentcore_app = build_app()

if __name__ == "__main__":
    agentcore_app.run()
