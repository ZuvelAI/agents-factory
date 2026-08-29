# Connector manifest v1

`connector.schema.json` is generated from the backend `ConnectorManifest` and
describes provider metadata independently from business capabilities.

Business operations use stable names such as `orders.get_status`; provider
methods are never exposed to the model. A runtime tool is eligible only when:

1. its capability version is active and relevant;
2. the AgentSpec explicitly permits it;
3. an AgentSpec connector binding includes the operation; and
4. the available connector manifest declares the same operation.

Unavailable catalog entries contain no operations and no executable entry
point. Generic REST API/Webhook is deferred to v1.1 and has no v1 auth route,
webhook, client, or arbitrary HTTP tool.
