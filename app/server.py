import asyncio
import time
from datetime import datetime
from collections import deque
from typing import Dict

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import uvicorn


app = FastAPI(title="BLE SmartTag Control Center")


# ==================================================
# Configuration
# ==================================================

LOST_SECONDS = 5

# Zone RSSI observation lifetime
ZONE_READING_TTL = 3

# 새 Zone이 최소 8 dBm 강해야 이동 후보
ZONE_SWITCH_MARGIN_DB = 8

# 2초 동안 계속 우세해야 Zone 변경
ZONE_SWITCH_CONFIRM_SECONDS = 2

MAX_EVENTS = 200

# Gateway health monitoring
GATEWAY_OFFLINE_SECONDS = 10
GATEWAY_HEARTBEAT_SECONDS = 10
GATEWAY_CHECK_INTERVAL_SECONDS = 1

# ==================================================
# In-memory state
# ==================================================

# key = tag_id
tag_database: Dict[str, dict] = {}

# newest event first
event_log = deque(maxlen=MAX_EVENTS)

# key = scanner_id / zone
gateway_status: Dict[str, dict] = {}

# ==================================================
# Logging helpers
# ==================================================

def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_client_ip(request: Request):

    # Reverse proxy가 있으면 원래 client IP 우선
    forwarded_for = request.headers.get("x-forwarded-for")

    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("x-real-ip")

    if real_ip:
        return real_ip

    if request.client:
        return request.client.host

    return "UNKNOWN"


def log_request(
    client_ip: str,
    method: str,
    path: str,
    message: str = ""
):

    print(
        f'[{now_text()}] '
        f'[{client_ip}] '
        f'"{method} {path}" '
        f'{message}',
        flush=True
    )


def add_event(
    event_type: str,
    tag_id: str,
    message: str,
    client_ip: str = "-"
):


    event_log.appendleft({
        "timestamp": time.time(),
        "event_type": event_type,
        "tag_id": tag_id,
        "message": message,
        "client_ip": client_ip
    })

    print(
        f"[{now_text()}] "
        f"[{client_ip}] "
        f"[{event_type}] "
        f"{tag_id} | {message}",
        flush=True
    )

# ==================================================
# Gateway health monitoring
# ==================================================

async def gateway_monitor():

    while True:

        await asyncio.sleep(
            GATEWAY_CHECK_INTERVAL_SECONDS
        )

        current_time = time.time()

        for scanner_id, data in list(
            gateway_status.items()
        ):

            elapsed = (
                current_time
                - data["last_post"]
            )

            # --------------------------------------
            # Gateway OFFLINE
            # --------------------------------------

            if elapsed >= GATEWAY_OFFLINE_SECONDS:

                if data["online"]:

                    data["online"] = False

                    print(
                        f"[{now_text()}] "
                        f"[GATEWAY_OFFLINE] "
                        f"{scanner_id} | "
                        f"no POST for {elapsed:.1f}s",
                        flush=True
                    )

                continue

            # --------------------------------------
            # Normal heartbeat
            # --------------------------------------

            if (
                data["online"]
                and
                current_time
                - data["last_heartbeat"]
                >= GATEWAY_HEARTBEAT_SECONDS
            ):

                print(
                    f"[{now_text()}] "
                    f"[HEARTBEAT] "
                    f"{scanner_id} | "
                    f"ONLINE | "
                    f"last_post={elapsed:.1f}s ago | "
                    f"tags={data['last_tags']}",
                    flush=True
                )

                data["last_heartbeat"] = (
                    current_time
                )


@app.on_event("startup")
async def start_gateway_monitor():

    app.state.gateway_monitor_task = (
        asyncio.create_task(
            gateway_monitor()
        )
    )

# ==================================================
# LOST detection
# ==================================================

def update_lost_status():

    current_time = time.time()

    for tag_id, data in tag_database.items():

        elapsed = current_time - data["last_seen"]

        if elapsed >= LOST_SECONDS:

            if data["status"] != "LOST":

                data["status"] = "LOST"

                add_event(
                    "LOST",
                    tag_id,
                    f"Signal lost from {data['current_zone']}",
                    data.get("last_client_ip", "-")
                )


# ==================================================
# Health
# ==================================================

@app.get("/health")
async def health():

    update_lost_status()

    normal_count = sum(
        1
        for data in tag_database.values()
        if data["status"] == "NORMAL"
    )

    lost_count = sum(
        1
        for data in tag_database.values()
        if data["status"] == "LOST"
    )

    return {
        "status": "ok",
        "service": "ble-smarttag-server",
        "known_tags": len(tag_database),
        "normal_tags": normal_count,
        "lost_tags": lost_count
    }


# ==================================================
# Receive Android Gateway scan data
# ==================================================

@app.post("/api/v1/scan-data")
async def receive_scan_data(request: Request):

    client_ip = get_client_ip(request)

    payload = await request.json()

    scanner_id = payload.get(
        "scanner_id",
        "UNKNOWN_ZONE"
    )

    tags = payload.get(
        "tags",
        []
    )

    current_time = time.time()

    # ----------------------------------------------
    # Gateway health state
    # ----------------------------------------------

    gateway = gateway_status.get(scanner_id)

    if gateway is None:

        gateway_status[scanner_id] = {
            "last_post": current_time,
            "last_heartbeat": current_time,
            "last_tags": len(tags),
            "client_ip": client_ip,
            "online": True
        }

        print(
            f"[{now_text()}] "
            f"[GATEWAY_ONLINE] "
            f"{scanner_id} | "
            f"first POST received",
            flush=True
        )

    else:

        previous_gap = (
            current_time
            - gateway["last_post"]
        )

        was_online = gateway["online"]

        gateway["last_post"] = current_time
        gateway["last_tags"] = len(tags)
        gateway["client_ip"] = client_ip
        gateway["online"] = True

        if not was_online:

            gateway["last_heartbeat"] = (
                current_time
            )

            print(
                f"[{now_text()}] "
                f"[GATEWAY_ONLINE] "
                f"{scanner_id} | "
                f"connection restored "
                f"after {previous_gap:.1f}s",
                flush=True
            )

    for tag in tags:

        name = tag.get("name")
        address = tag.get("address")
        rssi = tag.get("rssi")


        # 이름이 있으면 이름 사용,
        # Unknown이면 MAC 주소 사용
        if name and name != "Unknown":

            tag_id = name

        else:

            tag_id = address


        if not tag_id:
            continue


        # ------------------------------------------
        # New tag
        # ------------------------------------------

        if tag_id not in tag_database:

            tag_database[tag_id] = {
                "tag_id": tag_id,
                "mac_address": address,
                "current_zone": scanner_id,
                "rssi": rssi,
                "last_seen": current_time,
                "last_client_ip": client_ip,
                "status": "NORMAL",

                # Gateway별 최근 관측값
                "zone_readings": {
                    scanner_id: {
                        "rssi": rssi,
                        "last_seen": current_time,
                        "client_ip": client_ip
                    }
                },

                # Zone 이동 후보
                "candidate_zone": None,
                "candidate_since": None
            }

            add_event(
                "DISCOVERED",
                tag_id,
                f"Detected at {scanner_id}, RSSI={rssi}",
                client_ip
            )

            continue


        previous = tag_database[tag_id]

        old_status = previous["status"]


        # ------------------------------------------
        # Reappeared after LOST
        # ------------------------------------------

        if old_status == "LOST":

            add_event(
                "REAPPEARED",
                tag_id,
                f"Signal restored at {scanner_id}, RSSI={rssi}",
                client_ip
            )

            # 한동안 완전히 사라졌던 태그이므로
            # 재등장한 Gateway를 새 출발점으로 사용
            previous["current_zone"] = scanner_id
            previous["rssi"] = rssi
            previous["zone_readings"] = {}
            previous["candidate_zone"] = None
            previous["candidate_since"] = None


        # ------------------------------------------
        # Save this Gateway observation
        # ------------------------------------------

        zone_readings = previous.setdefault(
            "zone_readings",
            {}
        )

        zone_readings[scanner_id] = {
            "rssi": rssi,
            "last_seen": current_time,
            "client_ip": client_ip
        }


        # ------------------------------------------
        # Remove old Gateway observations
        # ------------------------------------------

        stale_zones = [
            zone
            for zone, reading in zone_readings.items()
            if current_time - reading["last_seen"]
            > ZONE_READING_TTL
        ]

        for zone in stale_zones:
            del zone_readings[zone]


        # ------------------------------------------
        # Update global tag status
        # ------------------------------------------

        previous.update({
            "mac_address": address,
            "last_seen": current_time,
            "last_client_ip": client_ip,
            "status": "NORMAL"
        })


        # ------------------------------------------
        # Find strongest active Zone
        # ------------------------------------------

        if zone_readings:

            strongest_zone, strongest_data = max(
                zone_readings.items(),
                key=lambda item: item[1]["rssi"]
            )

            strongest_rssi = strongest_data["rssi"]

            current_zone = previous["current_zone"]

            current_data = zone_readings.get(
                current_zone
            )

            current_rssi = (
                current_data["rssi"]
                if current_data
                else None
            )


            # --------------------------------------
            # Decide whether another Zone is
            # sufficiently stronger
            # --------------------------------------

            should_consider_switch = (
                strongest_zone != current_zone
                and
                (
                    current_rssi is None
                    or
                    strongest_rssi
                    >= current_rssi
                    + ZONE_SWITCH_MARGIN_DB
                )
            )


            if should_consider_switch:

                # 새로운 후보 Zone 발견
                if (
                    previous.get("candidate_zone")
                    != strongest_zone
                ):

                    previous["candidate_zone"] = (
                        strongest_zone
                    )

                    previous["candidate_since"] = (
                        current_time
                    )


                # 같은 후보가 일정시간 계속 우세
                elif (
                    previous.get("candidate_since")
                    is not None
                    and
                    current_time
                    - previous["candidate_since"]
                    >= ZONE_SWITCH_CONFIRM_SECONDS
                ):

                    old_zone = current_zone

                    previous["current_zone"] = (
                        strongest_zone
                    )

                    previous["rssi"] = (
                        strongest_rssi
                    )

                    previous["candidate_zone"] = None
                    previous["candidate_since"] = None


                    add_event(
                        "ZONE_CHANGE",
                        tag_id,
                        (
                            f"{old_zone} -> "
                            f"{strongest_zone}, "
                            f"RSSI={strongest_rssi}"
                        ),
                        client_ip
                    )


            else:

                # 후보가 우세하지 않으면 취소
                previous["candidate_zone"] = None
                previous["candidate_since"] = None


            # --------------------------------------
            # Dashboard RSSI는 현재 선택된 Zone의
            # RSSI를 표시
            # --------------------------------------

            selected_zone = previous["current_zone"]

            selected_data = zone_readings.get(
                selected_zone
            )

            if selected_data is not None:

                previous["rssi"] = (
                    selected_data["rssi"]
                )

    update_lost_status()




    return {
        "status": "success",
        "scanner_id": scanner_id,
        "processed_count": len(tags),
        "known_tags": len(tag_database)
    }


# ==================================================
# Current tags JSON
# ==================================================

@app.get("/api/v1/tags")
async def get_tags():

    update_lost_status()

    current_time = time.time()

    result = []


    for tag_id, data in tag_database.items():

        result.append({
            "tag_id": tag_id,
            "mac_address": data["mac_address"],
            "current_zone": data["current_zone"],
            "rssi": data["rssi"],
            "last_seen_seconds":
                round(
                    current_time - data["last_seen"],
                    1
                ),
            "status": data["status"],
            "gateway_ip":
                data.get(
                    "last_client_ip",
                    "-"
                )
        })


    return result


# ==================================================
# Event JSON
# ==================================================

@app.get("/api/v1/events")
async def get_events():

    return list(event_log)


# ==================================================
# Mobile-friendly dashboard
# ==================================================

@app.get("/", response_class=HTMLResponse)
async def dashboard():

    update_lost_status()

    current_time = time.time()

    tag_cards = ""

    normal_count = 0
    lost_count = 0


    # --------------------------------------------------
    # Tag cards
    # --------------------------------------------------

    for tag_id, data in tag_database.items():

        elapsed = int(
            current_time - data["last_seen"]
        )

        status = data["status"]


        if status == "NORMAL":

            normal_count += 1
            status_class = "normal"

        else:

            lost_count += 1
            status_class = "lost"


        tag_cards += f"""
        <div class="tag-card">

            <div class="tag-header">

                <div class="tag-name">
                    {data['tag_id']}
                </div>

                <div class="status {status_class}">
                    {status}
                </div>

            </div>


            <div class="info-row">

                <span class="label">
                    MAC
                </span>

                <span>
                    {data['mac_address']}
                </span>

            </div>


            <div class="info-row">

                <span class="label">
                    ZONE
                </span>

                <span class="zone">
                    {data['current_zone']}
                </span>

            </div>


            <div class="info-row">

                <span class="label">
                    RSSI
                </span>

                <span>
                    {data['rssi']} dBm
                </span>

            </div>


            <div class="info-row">

                <span class="label">
                    LAST SEEN
                </span>

                <span>
                    {elapsed} sec ago
                </span>

            </div>


            <div class="info-row">

                <span class="label">
                    GATEWAY IP
                </span>

                <span>
                    {data.get('last_client_ip', '-')}
                </span>

            </div>

        </div>
        """


    # --------------------------------------------------
    # Event cards
    # --------------------------------------------------

    event_cards = ""


    for event in list(event_log)[:30]:

        elapsed = int(
            current_time -
            event["timestamp"]
        )


        event_cards += f"""
        <div class="event-card">

            <div class="event-header">

                <b>
                    {event['event_type']}
                </b>

                <span>
                    {elapsed} sec ago
                </span>

            </div>


            <div class="event-tag">
                {event['tag_id']}
            </div>


            <div class="event-message">
                {event['message']}
            </div>


            <div class="event-ip">
                IP: {event.get('client_ip', '-')}
            </div>

        </div>
        """


    html_content = f"""
    <!DOCTYPE html>

    <html>

    <head>

        <meta charset="UTF-8">

        <meta
            name="viewport"
            content="width=device-width, initial-scale=1.0"
        >

        <meta
            http-equiv="refresh"
            content="2"
        >

        <title>
            BLE SmartTag Control Center
        </title>


        <style>

            * {{
                box-sizing: border-box;
            }}


            body {{
                margin: 0;
                padding: 16px;
                font-family: Arial, sans-serif;
                background: #0b1117;
                color: #e5e7eb;
                font-size: 18px;
            }}


            h1 {{
                font-size: 30px;
                margin: 4px 0 5px;
            }}


            h2 {{
                font-size: 24px;
                margin-top: 28px;
            }}


            .subtitle {{
                color: #94a3b8;
                margin-bottom: 20px;
            }}


            .summary {{
                display: grid;
                grid-template-columns:
                    repeat(3, 1fr);
                gap: 8px;
                margin-bottom: 25px;
            }}


            .summary-card {{
                background: #211f1f;
                border-radius: 10px;
                padding: 12px 5px;
                text-align: center;
                box-shadow:
                    0 1px 4px
                    rgba(0,0,0,0.35);
            }}


            .summary-label {{
                font-size: 13px;
                color: #aab3c3;
            }}


            .summary-number {{
                font-size: 28px;
                font-weight: bold;
                margin-top: 5px;
            }}


            .tag-card {{
                background: #211f1f;
                border-radius: 12px;
                padding: 17px;
                margin-bottom: 15px;
                box-shadow:
                    0 2px 6px
                    rgba(0,0,0,0.35);
            }}


            .tag-header {{
                display: flex;
                justify-content: space-between;
                gap: 10px;
                align-items: center;
                margin-bottom: 14px;
            }}


            .tag-name {{
                font-size: 22px;
                font-weight: bold;
                word-break: break-all;
            }}


            .status {{
                padding: 6px 10px;
                border-radius: 7px;
                font-size: 15px;
                font-weight: bold;
            }}


            .normal {{
                color: #22c55e;
                background: #12351f;
            }}


            .lost {{
                color: #ff6b6b;
                background: #421b1b;
            }}


            .info-row {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                gap: 12px;
                padding: 10px 0;
                border-top:
                    1px solid #374151;
                font-size: 18px;
            }}


            .label {{
                color: #94a3b8;
                font-weight: bold;
                font-size: 15px;
            }}


            .zone {{
                background: #12354d;
                color: #7dd3fc;
                padding: 5px 8px;
                border-radius: 5px;
                font-weight: bold;
            }}


            .event-card {{
                background: #211f1f;
                border-left:
                    5px solid #64748b;
                border-radius: 8px;
                padding: 14px;
                margin-bottom: 10px;
                font-size: 17px;
            }}


            .event-header {{
                display: flex;
                justify-content: space-between;
                color: #dbeafe;
            }}


            .event-tag {{
                margin-top: 6px;
                font-weight: bold;
            }}


            .event-message {{
                margin-top: 5px;
            }}


            .event-ip {{
                margin-top: 7px;
                color: #94a3b8;
                font-size: 14px;
            }}


            .empty {{
                background: #211f1f;
                padding: 24px 12px;
                border-radius: 10px;
                text-align: center;
                font-size: 18px;
            }}


            @media (min-width: 900px) {{

                body {{
                    max-width: 1100px;
                    margin: auto;
                }}


                .tags {{
                    display: grid;
                    grid-template-columns:
                        1fr 1fr;
                    gap: 16px;
                }}

            }}

        </style>

    </head>


    <body>


        <h1>
            BLE SmartTag Control Center
        </h1>


        <div class="subtitle">
            Real-time BLE Gateway Monitoring
        </div>


        <div class="summary">


            <div class="summary-card">

                <div class="summary-label">
                    KNOWN
                </div>

                <div class="summary-number">
                    {len(tag_database)}
                </div>

            </div>


            <div class="summary-card">

                <div class="summary-label">
                    NORMAL
                </div>

                <div
                    class="summary-number"
                    style="color:#22c55e;"
                >
                    {normal_count}
                </div>

            </div>


            <div class="summary-card">

                <div class="summary-label">
                    LOST
                </div>

                <div
                    class="summary-number"
                    style="color:#ff6b6b;"
                >
                    {lost_count}
                </div>

            </div>


        </div>


        <h2>
            Current Tags
        </h2>


        <div class="tags">


            {
                tag_cards
                if tag_cards
                else
                '''
                <div class="empty">
                    No BLE tags detected.
                    <br><br>
                    Start the Android Gateway.
                </div>
                '''
            }


        </div>


        <h2>
            Recent Events
        </h2>


        {
            event_cards
            if event_cards
            else
            '''
            <div class="empty">
                No events yet.
            </div>
            '''
        }


    </body>

    </html>
    """


    return html_content


# ==================================================
# Direct run
# ==================================================

if __name__ == "__main__":

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        access_log=False
    )
