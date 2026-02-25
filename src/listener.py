"""WebSocket listener for pump.fun program events on Solana."""

import asyncio
import json
import logging
import time
from typing import AsyncIterator, Union

import websockets

from src.config import Config
from src.events import (
    CreateEvent, TradeEvent, CompleteEvent, parse_program_data,
)

logger = logging.getLogger("sniper.listener")

EventType = Union[CreateEvent, TradeEvent, CompleteEvent]


class PumpFunListener:
    """Connects to Solana WebSocket and streams pump.fun events."""

    def __init__(self, config: Config):
        self.config = config
        self._ws = None
        self._sub_id: int | None = None
        self.events_received: int = 0
        self.connected_at: float = 0
        self.disconnects: int = 0

    async def connect(self) -> None:
        """Connect and subscribe to pump.fun program logs."""
        url = self.config.SOLANA_WS_URL
        logger.info("Connecting to %s ...", url)
        self._ws = await websockets.connect(
            url,
            ping_interval=20,
            ping_timeout=30,
            close_timeout=5,
            max_size=5 * 1024 * 1024,
        )
        self.connected_at = time.time()
        logger.info("WebSocket connected")

        # Subscribe to pump.fun program logs
        sub_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "logsSubscribe",
            "params": [
                {"mentions": [self.config.PUMP_FUN_PROGRAM]},
                {"commitment": "confirmed"},
            ],
        }
        await self._ws.send(json.dumps(sub_request))
        resp = await asyncio.wait_for(self._ws.recv(), timeout=10)
        resp_data = json.loads(resp)

        if "result" in resp_data:
            self._sub_id = resp_data["result"]
            logger.info("Subscribed to pump.fun logs (sub_id=%s)", self._sub_id)
        else:
            error = resp_data.get("error", "unknown")
            raise ConnectionError(f"Failed to subscribe: {error}")

    async def disconnect(self) -> None:
        if self._ws:
            try:
                if self._sub_id is not None:
                    unsub = {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "logsUnsubscribe",
                        "params": [self._sub_id],
                    }
                    await self._ws.send(json.dumps(unsub))
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
            self._sub_id = None

    async def listen(self) -> AsyncIterator[EventType]:
        """Yield parsed pump.fun events. Auto-reconnects on failure."""
        while True:
            try:
                if self._ws is None:
                    await self.connect()

                async for raw_msg in self._ws:
                    events = self._parse_message(raw_msg)
                    for event in events:
                        self.events_received += 1
                        yield event

            except (
                websockets.ConnectionClosed,
                websockets.ConnectionClosedError,
                websockets.ConnectionClosedOK,
                ConnectionError,
                asyncio.TimeoutError,
            ) as e:
                self.disconnects += 1
                logger.warning("WebSocket disconnected (%s), reconnecting in 3s...", e)
                self._ws = None
                self._sub_id = None
                await asyncio.sleep(3)

            except Exception as e:
                self.disconnects += 1
                logger.error("Listener error: %s, reconnecting in 5s...", e)
                self._ws = None
                self._sub_id = None
                await asyncio.sleep(5)

    def _parse_message(self, raw: str) -> list[EventType]:
        """Extract pump.fun events from a WebSocket notification."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return []

        if msg.get("method") != "logsNotification":
            return []

        value = msg.get("params", {}).get("result", {}).get("value", {})
        if value.get("err") is not None:
            return []  # failed transaction

        logs = value.get("logs", [])
        events: list[EventType] = []

        for log_line in logs:
            if not log_line.startswith("Program data: "):
                continue
            b64_data = log_line[len("Program data: "):]
            event = parse_program_data(b64_data)
            if event is not None:
                events.append(event)

        return events
