# Signup timeout pilot update — 2026-10-12

Owner authorized deployment after local tests: 568 backend tests and 88 panel
tests passed; TypeScript and diff whitespace checks passed. Three backend test
files requiring canonical historical infrastructure were not run in this pass.

Built from the retained e437e8c source archive, verified baseline hashes for all
five changed files, and overlaid only three production files and two tests.
Locked Linux builds completed. No migration or credential change.

New active web pair:

- aiworkers-pilot-backend-timeout-20261012
- aiworkers-pilot-panel-timeout-20261012

Private release directory: /opt/aiworkers/.timeout-20261012. Configuration and
previous-container inspection snapshot are mode 600. Candidate health passed on
isolated loopback ports before cutover. Existing declared environments matched
running containers before copying; panel backend hostname is the only environment
change. Existing workers and Redis remained running unchanged.

Final observations: both web containers healthy; public login and readiness
returned 200; deployed backend TTL is 1800 seconds; panel chunk contains the new
server-deadline handling. Prior e437e8c web containers are retained stopped for
rollback. No image pruning, volume deletion, Nginx change, or account write.

Real Meta signup completion and persistence remain unverified. Owner must reload
the panel, use coexistence, and complete Meta as Daniel's portfolio. Do not revoke
or replace the existing reviewer account to recover the pending pilot.

## Owner-authorized recovery and sender-format repair

Recovered the existing Meta account 1572027171232643, phone ID 1342213852302971,
owned by Daniel's portfolio 588452965083436. Verified matching phone, both scopes,
SYSTEM_USER credential, is_on_biz_app=true and platform_type=CLOUD_API. Subscribed
the existing app to that account and configured the public webhook for messages,
mobile echoes, contact sync, history and account updates. No QR repeated.

Persisted account 01a132b4-c3f5-75b4-b1dd-21eaa076f291 with the existing encrypted
vault and an explicit system recovery audit. Original reviewer account fields and
credential reference compared unchanged within the transaction. A fresh vault
read was accepted by Meta. Removed the local temporary plaintext token file.

Owner screenshots confirmed the real COEXISTENCE/ELIGIBLE account in the panel.
Initial real messages reached the backend but returned 400. Owner authorized a
temporary privacy-safe diagnostic: only validation locations, error types and
sender-field presence booleans, no sender values, message contents or tokens.
Actual rejected messages omit from and include from_user_id. Regression test
failed against the original model, passed after adding the alternate validation
alias; missing sender remains rejected, and existing phone-based fixtures pass.

Fresh backend verification: 570 passed, one dependency deprecation warning, three
historical-environment files excluded as before. Earlier attempt failed setup
because Docker was closed (437 passed, 133 errors); after reopening isolated
services, a full run had 569 passed and one alert ordering failure in
test_platform_admin_can_read_bounded_account_update_alerts. Its isolated nine-test
file passed and the subsequent full partition passed. No alert code changed.

Deployed only schemas.py in image aiworkers-coex-runtime:sender-fix-20261012,
derived from the previously verified timeout image. Backend healthy; diagnostic
wrapper removed from the active image and normal uvicorn command restored.
Workers, panel and Redis unchanged. Real post-fix message reception still needs
owner test evidence; do not claim full pilot or outbound delivery completed.
