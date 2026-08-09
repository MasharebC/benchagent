# NOTES — did / broken / exact next step (never stop at a clean boundary)

## 2026-08-09 (session 1 — CI fix, model IDs, real API validated)
**did:** fixed CI smoke test grep patterns (** is invalid BRE — added -F flag);
corrected stale model IDs in config.py (claude-opus-4-8 → claude-opus-4-6,
claude-fable-5 → claude-opus-4-6 for break-glass); CI green on main.
Real API validated on all 4 fixtures — AnthropicClient tool loop works:
  bootloop: FAIL conf 0.99 (no escalation, 18s)
  panic:     FAIL conf 0.91 (no escalation, 46s)
  silent_hang: FAIL conf 0.72 (no escalation, just above threshold — correct)
  clean_boot: PASS conf 0.98 (no escalation, 23s)
**broken:** bme280.c still a stub; RealSerial/EsptoolFlasher/UhubctlPower
still NotImplemented until hardware arrives.
**exact next step:** place hardware order (BOM in README — ~$200);
while waiting: write bme280.c register-level driver from datasheet.

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
