# NOTES — did / broken / exact next step (never stop at a clean boundary)

## 2026-08-07 (session 0 — repo bootstrap)
**did:** repo skeleton; mock loop e2e green on all 4 failure classes
(clean-boot / boot-loop / panic / silent-hang); classifier + 6 unit tests
passing; escalation path verified (tier1 0.55 -> tier2 0.92 on bootloop);
runs/ archiving verdict.json + evidence.json + report.md; firmware
scaffolded with BUG_WDT_STARVE and BME280 driver interface.
**broken:** bme280.c is a stub (deliberate — I write it from the datasheet);
RealSerial/EsptoolFlasher/UhubctlPower are NotImplemented until hardware;
mock LLM is canned — real API path untested end-to-end.
**exact next step:** export ANTHROPIC_API_KEY and run
`./benchagent run --mock fixtures/logs/bootloop.log` WITHOUT --mock-llm;
fix whatever breaks in AnthropicClient tool loop. Then: place hardware order.
