# Standard SME go-live

Go-live is an evidence decision for exact artifacts, not merely a successful
build. The platform admin completes Discovery and the 12-step wizard, connects
only required providers, reviews Knowledge, identity, confirmation, approval and
handoff rules, then runs the representative eval and scenario suites in Staging.

Required evidence includes code/image/migration versions, AgentSpec and Knowledge
digests, passing Quality Gate, connector/template health, privacy/retention,
backup/restore and rollback drills, legal/privacy review, responsible approvers
and first-conversation/cost monitors. Any critical failure records owner,
reproduction and eval ID and leaves Production blocked. Final promotion is the
protected manual GitHub environment action described in [deploy](deploy.md).
