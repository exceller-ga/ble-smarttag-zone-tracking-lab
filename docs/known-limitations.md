# Known Limitations / Next Iteration

## Observed limitation

After Android device suspension, BLE scan recovery was not always automatic.

Observed states included:

- gateway HTTP POSTs continued, but BLE tag observations remained at `tags=0`
- in some cases the gateway POST loop itself stopped
- restarting BLE scanning restored tag detection

## Planned improvements

- move long-running scan/post work into an Android Foreground Service
- add BLE scan state monitoring and controlled scan restart
- handle scan failure and Bluetooth adapter state changes explicitly
- persist event history instead of using memory-only state
- log both current-zone and candidate-zone RSSI during zone changes
- add a gateway-health section to the dashboard
