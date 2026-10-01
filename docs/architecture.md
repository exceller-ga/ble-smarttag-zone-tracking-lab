# Architecture Notes

```text
BLE Smart Tag / Simulated Advertiser
        |
        +-----------------------+
        |                       |
        v                       v
Android Gateway A          Android Gateway C
ZONE-A                     ZONE-C
BLE Scan                   BLE Scan
1-second POST              1-second POST
        |                       |
        +-----------+-----------+
                    |
                    v
              FastAPI Backend
                    |
        +-----------+-----------+
        |           |           |
        v           v           v
   Zone Logic   Asset State   Gateway Health
   RSSI/TTL     LOST/         HEARTBEAT/
   Hysteresis   REAPPEARED    ONLINE/OFFLINE
```

The backend separates gateway communication health from BLE tag visibility.
