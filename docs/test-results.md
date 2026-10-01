# Test Results

## Verified scenarios

### 1. Gateway registration and heartbeat

```text
[GATEWAY_ONLINE] ZONE-A | first POST received
[HEARTBEAT] ZONE-A | ONLINE | last_post=1.4s ago | tags=0
```

The backend receives gateway POSTs continuously while only emitting periodic health summaries.

### 2. Bidirectional zone transition

```text
[ZONE_CHANGE] TEIA-TAG-01 | ZONE-C -> ZONE-A, RSSI=-41
[ZONE_CHANGE] TEIA-TAG-01 | ZONE-A -> ZONE-C, RSSI=-48
[ZONE_CHANGE] TEIA-TAG-01 | ZONE-C -> ZONE-A, RSSI=-83
```

The test confirmed repeated A ↔ C transitions using recent per-zone observations and switch confirmation logic.

### 3. Tag loss while gateways remain online

```text
[HEARTBEAT] ZONE-C | ONLINE | last_post=0.6s ago | tags=0
[HEARTBEAT] ZONE-A | ONLINE | last_post=0.9s ago | tags=1
[LOST] TEIA-TAG-01 | Signal lost from ZONE-A
[HEARTBEAT] ZONE-A | ONLINE | last_post=0.9s ago | tags=0
```

This shows that tag disappearance is distinguished from gateway communication failure.

### 4. Tag recovery

```text
[REAPPEARED] TEIA-TAG-01 | Signal restored at ZONE-A, RSSI=-50
[HEARTBEAT] ZONE-A | ONLINE | last_post=0.9s ago | tags=1
[HEARTBEAT] ZONE-C | ONLINE | last_post=0.5s ago | tags=1
```

### 5. Observed BLE scan recovery limitation

During device-suspension testing, the gateways could remain HTTP-online while BLE scanning stopped rediscovering the tag. A BLE scan Stop → Start restored detection.

This is documented as a lab limitation and future improvement area, not presented as production behavior.
