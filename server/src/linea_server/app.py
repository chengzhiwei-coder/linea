import asyncio
import logging
from contextlib import suppress
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse

from linea_server.auth import require_bearer_auth
from linea_server.internal_test_page import CONVERSATION_TEST_HTML
from linea_server.calls import CallManager, WebRtcOfferRequest, WebRtcOfferResponse
from linea_server.db import DEFAULT_DB_PATH, initialize_db
from linea_server.hermes_runner import HermesJobManager
from linea_server.tools import ToolRegistry, register_default_tools
from linea_server.webrtc import AiortcWebRtcService
from linea_server.xai_config import load_xai_config
from linea_server.xai_realtime import XaiRealtimeBridge

logger = logging.getLogger(__name__)

INITIAL_GREETING_TEXT = "Hey, how can I help you?"


def build_tool_registry(hermes_job_manager: HermesJobManager) -> ToolRegistry:
    registry = ToolRegistry()
    register_default_tools(registry, hermes_job_manager=hermes_job_manager)
    return registry


async def end_active_call(app: Any, call_id: str) -> None:
    logger.info("call end call_id=%s", call_id)
    xai_event_task: asyncio.Task | None = app.state.xai_event_task
    if xai_event_task is not None and not xai_event_task.done():
        xai_event_task.cancel()
        with suppress(asyncio.CancelledError):
            await xai_event_task
    app.state.xai_event_task = None

    xai_bridge = getattr(app.state, "xai_bridge", None)
    if xai_bridge is not None:
        await xai_bridge.close()

    close_webrtc = getattr(app.state.webrtc_service, "close", None)
    if close_webrtc is not None:
        await close_webrtc()

    app.state.call_manager.release_call(call_id)


async def end_active_call_and_cancel_idle_monitor(app: Any, call_id: str) -> None:
    await end_active_call(app, call_id)
    idle_timeout_task: asyncio.Task | None = app.state.idle_timeout_task
    if idle_timeout_task is not None and not idle_timeout_task.done():
        idle_timeout_task.cancel()
        with suppress(asyncio.CancelledError):
            await idle_timeout_task
    app.state.idle_timeout_task = None


async def release_interrupted_active_call(app: Any) -> bool:
    call_id = app.state.call_manager.active_call_id
    if call_id is None:
        return False

    has_live_peer_connection = getattr(app.state.webrtc_service, "has_live_peer_connection", None)
    if has_live_peer_connection is None or has_live_peer_connection():
        return False

    logger.info("call stale call_id=%s reason=webrtc_not_live", call_id)
    await end_active_call_and_cancel_idle_monitor(app, call_id)
    return True


async def monitor_idle_call(app: Any, call_id: str, *, poll_interval_seconds: float = 1.0) -> None:
    while app.state.call_manager.active_call_id == call_id:
        if app.state.call_manager.is_idle(call_id):
            await end_active_call(app, call_id)
            return
        await asyncio.sleep(poll_interval_seconds)


def create_app(db_path: Path = DEFAULT_DB_PATH) -> FastAPI:
    init_result = initialize_db(db_path)

    app = FastAPI(title="Linea Server", version="0.1.0")
    app.state.db_path = db_path
    app.state.initial_server_token = init_result.plaintext_server_token
    app.state.call_manager = CallManager()
    app.state.hermes_job_manager = HermesJobManager(db_path=db_path)
    app.state.xai_config = load_xai_config()
    app.state.xai_bridge = XaiRealtimeBridge(
        app.state.xai_config,
        db_path=db_path,
        tool_registry=build_tool_registry(app.state.hermes_job_manager),
    )
    app.state.webrtc_service = AiortcWebRtcService(
        audio_sink=app.state.xai_bridge.send_audio_frame,
        audio_source=app.state.xai_bridge.receive_audio_frame,
    )
    app.state.xai_event_task = None
    app.state.idle_timeout_task = None

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/internal/conversation-test", response_class=HTMLResponse)
    async def internal_conversation_test() -> HTMLResponse:
        return HTMLResponse(CONVERSATION_TEST_HTML)

    @app.get("/auth/check", dependencies=[Depends(require_bearer_auth)])
    async def auth_check() -> dict[str, bool]:
        return {"ok": True}

    @app.delete(
        "/webrtc/calls/{call_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_bearer_auth)],
    )
    async def stop_webrtc_call(call_id: str) -> None:
        if app.state.call_manager.active_call_id != call_id:
            return

        await end_active_call_and_cancel_idle_monitor(app, call_id)

    @app.post(
        "/webrtc/offer",
        response_model=WebRtcOfferResponse,
        dependencies=[Depends(require_bearer_auth)],
    )
    async def webrtc_offer(offer: WebRtcOfferRequest) -> WebRtcOfferResponse:
        try:
            call_id = app.state.call_manager.reserve_call()
        except RuntimeError as exc:
            if await release_interrupted_active_call(app):
                call_id = app.state.call_manager.reserve_call()
            else:
                logger.warning("call rejected reason=already_active")
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        logger.info("call start call_id=%s", call_id)

        def activity_callback(call_id: str = call_id) -> None:
            app.state.call_manager.record_activity(call_id)

        async def discard_audio_frame(pcm16: bytes) -> None:
            _ = pcm16

        if app.state.xai_config is not None:
            webrtc_service: AiortcWebRtcService | None = None

            def interrupt_output_audio() -> None:
                if webrtc_service is not None:
                    webrtc_service.interrupt_output_audio()

            app.state.xai_bridge = XaiRealtimeBridge(
                app.state.xai_config,
                db_path=db_path,
                tool_registry=build_tool_registry(app.state.hermes_job_manager),
                record_activity=activity_callback,
                is_tool_call_active=lambda _tool_call_id, call_id=call_id: app.state.call_manager.active_call_id
                == call_id,
                initial_greeting_text=INITIAL_GREETING_TEXT,
                on_input_speech_started=interrupt_output_audio,
            )
            webrtc_service = AiortcWebRtcService(
                audio_sink=app.state.xai_bridge.send_audio_frame,
                audio_source=app.state.xai_bridge.receive_audio_frame,
                record_activity=activity_callback,
            )
            app.state.webrtc_service = webrtc_service
        else:
            app.state.webrtc_service = AiortcWebRtcService(
                audio_sink=discard_audio_frame,
                record_activity=activity_callback,
            )

        try:
            answer = await app.state.webrtc_service.create_answer(offer.sdp)
        except Exception:
            logger.error("call error call_id=%s stage=webrtc_answer", call_id)
            app.state.call_manager.release_call(call_id)
            logger.info("call end call_id=%s", call_id)
            raise

        if app.state.xai_bridge is not None:
            app.state.xai_event_task = asyncio.create_task(app.state.xai_bridge.process_events())

            def on_xai_event_task_done(task: asyncio.Task, call_id: str = call_id) -> None:
                if task.cancelled():
                    app.state.call_manager.release_call(call_id)
                    logger.info("call end call_id=%s", call_id)
                    return
                if task.exception() is not None:
                    logger.error("call error call_id=%s stage=xai_events", call_id)
                    app.state.call_manager.release_call(call_id)
                    logger.info("call end call_id=%s", call_id)

            app.state.xai_event_task.add_done_callback(on_xai_event_task_done)
        app.state.idle_timeout_task = asyncio.create_task(monitor_idle_call(app, call_id))

        return WebRtcOfferResponse(type=answer.type, sdp=answer.sdp, call_id=call_id)

    return app
