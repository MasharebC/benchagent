# NOTES — did / broken / exact next step (never stop at a clean boundary)

## 2026-08-10 (hardware status check)
**did:** confirmed arrival status of the hardware order. Rest of the Amazon
BOM has arrived. Two items still in transit: the sensor (arriving
2026-08-11) and the UUGear MEGA4 hub (arriving 2026-08-13).
**broken:** nothing new — bench classes (RealSerial/EsptoolFlasher/
UhubctlPower) and bme280.c remain unvalidated against real hardware,
blocked on these two parts.
**exact next step:** while waiting, do hardware-independent Stage 1/2 work:
add free_heap trend detection to bench/classify.py for BUG_HEAP_LEAK (no
classifier support yet, no fixture/test); implement the two "planned"
bugs (BUG_DEADLOCK, BUG_STACK_OVF) in firmware behind compile flags; write
unit tests for the real bench classes with mocked serial/subprocess calls.
Once the sensor and MEGA4 arrive (~2026-08-13): validate
RealSerial/EsptoolFlasher/UhubctlPower end-to-end, then run the M1
acceptance test.

## 2026-08-09 (session 2 — Stage 1 software: BME280 driver, real bench classes)
**did:** wrote bme280.c register-level driver from the datasheet (no longer a
stub, 249 lines); implemented real bench classes — flash.py, power.py,
serial_monitor.py (RealSerial/EsptoolFlasher/UhubctlPower equivalents);
added 2 new planted bugs to evals/bugs.yaml. Commit f998f33.
**broken:** real bench classes are untested against actual hardware — no
board on hand yet. bme280.c untested on real I2C bus, only compiles clean.
**exact next step:** place hardware order (BOM in README — ~$200). Once it
arrives: validate RealSerial/EsptoolFlasher/UhubctlPower end-to-end, then
run the M1 acceptance test (flash → watch → power-cycle → verdict, 3 planted
bugs diagnosed unassisted).

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
