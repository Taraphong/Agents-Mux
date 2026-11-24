"""Localized status messages for the API and the UI.

Every message exists in both languages; the caller picks one from the request
language and the key, so a missing translation can never blank a response.
"""

from typing import Any

from flask import current_app, request


STATUS_MESSAGES = {
    "th": {
        "invalid_key": "API key ของ {label} ไม่ถูกต้องหรือหมดสิทธิ์ใช้งาน",
        "endpoint_missing": "ตรวจไม่พบ endpoint ของ {label} — ตรวจสอบ Base URL อีกครั้ง",
        "anthropic_model_missing": "ไม่พบโมเดล Anthropic ที่เลือก หรือโมเดลนี้ไม่เปิดให้ใช้งาน",
        "anthropic_model_error": "Anthropic เรียกโมเดลที่เลือกไม่ได้ (HTTP {status})",
        "http_error": "{label} ตอบกลับ HTTP {status}",
        "connection_failed": "เชื่อมต่อ {label} ไม่ได้: {error}",
        "missing_key": "ยังไม่ได้ตั้งค่า API key ของ {label}",
        "missing_model": "ยังไม่ได้เลือกโมเดลของ {label}",
        "invalid_key_shape": "API key ของ {label} ดูไม่ถูกต้อง (สั้นเกินไปหรือเป็นค่าตัวอย่าง)",
        "tls_invalid_mode": "โหมดการเชื่อมต่อไม่ถูกต้อง",
        "tls_cert_missing": "ไม่พบไฟล์ใบรับรอง — สร้างด้วย ./start_web.sh --make-cert <ip> หรือตั้ง AI_WEB_TLS_CERT และ AI_WEB_TLS_KEY ใน .env ให้ชี้ไฟล์ที่มีอยู่",
        "env_write_failed": "บันทึกไฟล์ .env ไม่สำเร็จ กรุณาดู log ของระบบ",
        "server_action_invalid": "คำสั่งควบคุมเซิร์ฟเวอร์ไม่ถูกต้อง",
        "server_script_missing": "ไม่พบสคริปต์ start_web.sh ในโฟลเดอร์โปรเจกต์",
        "server_busy": "มีคำสั่งควบคุมเซิร์ฟเวอร์กำลังทำงานอยู่",
        "server_action_failed": "เริ่มคำสั่งควบคุมเซิร์ฟเวอร์ไม่สำเร็จ กรุณาดู log ของระบบ",
        "gemini_key_missing": "ยังไม่ได้ตั้งค่า Gemini API key — เพิ่มคีย์ใน Settings ก่อนใช้ความสามารถนี้",
        "gemini_capability_failed": "ตรวจสอบความสามารถของคีย์ Gemini ไม่สำเร็จ ({error})",
        "gemini_decisions_invalid": "ข้อมูล Decisions API ไม่ถูกต้อง: ต้องมี input และ questions อย่างน้อย 1 ข้อ (noul, choice หรือ score)",
        "gemini_agents_invalid": "ข้อมูล Agents ไม่ถูกต้อง: ต้องระบุ agent และ input",
        "gemini_live_failed": "สร้าง Live API token ไม่สำเร็จ: {detail}",
        "gemini_request_failed": "เรียก Gemini API ไม่สำเร็จ: {detail}",
        "memory_schedule_invalid": "รูปแบบ cron ของ Memory ไม่ถูกต้อง",
        "memory_busy": "ระบบความจำกำลังทำงานอยู่ กรุณารอสักครู่",
        "memory_run_failed": "รันระบบความจำไม่สำเร็จ กรุณาดู log ของระบบแล้วลองใหม่",
        "memory_not_found": "ไม่พบรายการความจำนี้",
        "memory_forget_failed": "ลบรายการความจำไม่สำเร็จ",
        "memory_pin_failed": "ตั้งหรือยกเลิก pin ไม่สำเร็จ",
        "memory_pin_invalid": "ต้องระบุ pinned เป็น true หรือ false",
        "memory_reindex_failed": "สร้างดัชนีความจำใหม่ไม่สำเร็จ กรุณาดู log ของระบบ",
        "invalid_body": "รูปแบบข้อมูลไม่ถูกต้อง: ต้องเป็น JSON object",
        "attachment_unsupported": "ไฟล์ {name} ({mime}) เป็นชนิดที่ผู้ให้บริการนี้ส่งไม่ได้ — ไฟล์เสียงและวิดีโอใช้ได้กับ Gemini ส่วน PDF ใช้ได้กับ Gemini หรือ Anthropic",
        "pairing_required": "อุปกรณ์นี้ยังไม่ได้จับคู่ — กรุณาใส่ Pairing Key",
        "pairing_rate_limited": "พยายามจับคู่มากเกินไป กรุณารอสักครู่แล้วลองใหม่",
        "pairing_key_invalid": "Pairing Key นี้ไม่ถูกต้อง หมดอายุ หรือถูกใช้ไปแล้ว",
        "auth_disabled": "ระบบจับคู่อุปกรณ์ปิดอยู่ — ตั้ง AI_WEB_AUTH=on เพื่อใช้ Pairing Key",
        "device_not_found": "ไม่พบอุปกรณ์",
        "cross_origin": "คำขอจากเว็บอื่นถูกปฏิเสธ",
        "body_too_large": "ข้อมูลที่ส่งมีขนาดใหญ่เกินกว่าที่อนุญาต",
        "tool_invalid_payload": "ข้อมูลเครื่องมือไม่ถูกต้อง",
        "tool_approval_invalid": "คำขออนุมัติไม่ถูกต้องหรือหมดอายุ กรุณาขอใหม่อีกครั้ง",
        "tool_failed": "ใช้เครื่องมือไม่สำเร็จ กรุณาตรวจสอบพารามิเตอร์แล้วลองใหม่",
        "log_clear_failed": "ลบ log ไม่สำเร็จ",
        "schedule_name_required": "กรุณาระบุชื่องานและ prompt",
        "schedule_invalid": "รูปแบบ schedule ไม่ถูกต้อง (ต้องเป็น cron 5 ช่อง)",
        "schedule_channel_invalid": "Discord Channel ID ต้องเป็นตัวเลข",
        "schedule_not_found": "ไม่พบงานตามเวลา",
        "schedule_running": "งานนี้กำลังทำงานอยู่",
        "skill_not_found": "ไม่พบ Skill",
        "skill_read_failed": "อ่าน Skill ไม่สำเร็จ",
        "skill_create_failed": "สร้าง Skill ไม่สำเร็จ",
        "skill_content_invalid": "เนื้อหา Skill ไม่ถูกต้องหรือใหญ่เกินขนาดที่อนุญาต",
        "skill_save_failed": "บันทึก Skill ไม่สำเร็จ",
        "skill_delete_failed": "ลบ Skill ไม่สำเร็จ",
        "history_not_found": "ไม่พบประวัติการสนทนา",
        "history_corrupt": "ไฟล์ประวัติเสียหายหรืออ่านไม่ได้ กรุณาตรวจสอบไฟล์ในโฟลเดอร์ history",
        "history_message_id_required": "ต้องระบุ message_id",
        "history_locked_edit": "ประวัตินี้ถูกล็อก กรุณาปลดล็อกก่อนแก้ไข",
        "history_invalid": "รูปแบบประวัติไม่ถูกต้อง",
        "history_too_many_messages": "จำนวนข้อความมากเกินไป",
        "history_invalid_message": "รูปแบบข้อความไม่ถูกต้อง",
        "history_unsupported_role": "พบ role ที่ไม่อนุญาตในประวัติ",
        "history_locked_delete": "ประวัตินี้ถูกล็อก กรุณาปลดล็อกก่อนลบ",
        "history_conflict": "เกิดความขัดแย้งข้อมูล: บันทึกถูกปรับปรุงโดยผู้อื่น กรุณาโหลดใหม่",
        "history_locked_save": "ประวัตินี้ถูกล็อก กรุณาปลดล็อกก่อนบันทึกทับ",
        "models_fallback": "ดึงรายการโมเดลจาก API ไม่สำเร็จ ใช้รายการสำรองแทน",
        "discord_ids_invalid": "Discord ID ต้องเป็นตัวเลขเท่านั้น: {ids}",
        "custom_key_name_invalid": "ชื่อ Custom API key ไม่ถูกต้อง",
        "custom_key_nul": "ค่า Custom API key ต้องไม่มีอักขระ NUL",
        "update_mode_invalid": "โหมดอัปเดตไม่ถูกต้อง",
        "update_script_missing": "ไม่พบสคริปต์ update.sh ที่รันได้ในโฟลเดอร์โปรเจกต์",
        "update_busy": "มีการอัปเดตกำลังทำงานอยู่",
        "update_start_failed": "เริ่มอัปเดตไม่สำเร็จ กรุณาดู log ของระบบ",
        "chat_message_required": "กรุณาส่งข้อความ",
        "chat_failed": "ประมวลผลข้อความไม่สำเร็จ กรุณาลองใหม่อีกครั้ง",
        "test_connection_failed": "{label}: เชื่อมต่อไม่สำเร็จ กรุณาลองใหม่อีกครั้ง",
        "test_connection_hint": "ตรวจสอบ API key, โมเดล และ Base URL อีกครั้ง",
        "chat_busy": "{label} กำลังมีผู้ใช้หนาแน่นหรือถูกจำกัดอัตราการเรียก กรุณาลองใหม่อีกครั้ง หรือเลือกโมเดลอื่น",
        "chat_provider_error": "ผู้ให้บริการตอบกลับข้อผิดพลาด กรุณาตรวจสอบ API key และโมเดล",
        "chat_api_failed": "เรียก API ไม่สำเร็จ: {detail}",
        "chat_network_failed": "ติดต่อ {label} ไม่สำเร็จ เพราะรอคำตอบนานเกินกำหนดหรือเครือข่ายไม่พร้อมใช้งาน (ลองใหม่ให้แล้ว 1 ครั้ง) กรุณาตรวจสอบอินเทอร์เน็ตแล้วลองอีกครั้ง",
        "chat_empty_response": "{label} ตอบกลับมาโดยไม่มีข้อความ (finishReason: {reason}) — โมเดลมักใช้โควตาคำตอบไปกับการคิดจนหมด ลองเพิ่ม Max tokens หรือลดระดับการคิด",
        "tool_call_unreadable": "โมเดลส่ง tool call มาในรูปแบบที่อ่านไม่ได้ (JSON ไม่สมบูรณ์ หรือไม่มีชื่อเครื่องมือ) จึงยังไม่ได้รันคำสั่ง — ลองส่งข้อความเดิมอีกครั้ง หรือเปลี่ยนไปใช้โมเดลที่เก่งขึ้น",
        "rate_limited": "ทำรายการถี่เกินไป กรุณารอสักครู่แล้วลองใหม่",
    },
    "en": {
        "invalid_key": "{label} API key is invalid or unauthorized",
        "endpoint_missing": "{label} endpoint not found — check the Base URL",
        "anthropic_model_missing": "The selected Anthropic model was not found or is not available",
        "anthropic_model_error": "Anthropic could not call the selected model (HTTP {status})",
        "http_error": "{label} returned HTTP {status}",
        "connection_failed": "Could not connect to {label}: {error}",
        "missing_key": "{label} API key is not configured",
        "missing_model": "No {label} model is selected",
        "invalid_key_shape": "The {label} API key looks invalid (too short or a placeholder)",
        "tls_invalid_mode": "Invalid connection mode",
        "tls_cert_missing": "No certificate files found — create them with ./start_web.sh --make-cert <ip>, or point AI_WEB_TLS_CERT and AI_WEB_TLS_KEY in .env at existing files",
        "env_write_failed": "Could not write the .env file; check the system log",
        "server_action_invalid": "Invalid server action",
        "server_script_missing": "start_web.sh was not found in the project folder",
        "server_busy": "A server control command is already running",
        "memory_schedule_invalid": "The memory cron expression is invalid",
        "memory_busy": "A memory consolidation run is already in progress",
        "memory_run_failed": "The memory run failed; check the system log and try again",
        "memory_not_found": "That memory entry does not exist",
        "memory_forget_failed": "Could not forget that memory entry",
        "memory_pin_failed": "Could not update the pin on that memory entry",
        "memory_pin_invalid": "pinned must be true or false",
        "memory_reindex_failed": "Could not rebuild the memory index; check the system log",
        "server_action_failed": "Could not start the server control command; check the system log",
        "gemini_key_missing": "No Gemini API key is configured — add one in Settings before using this feature",
        "gemini_capability_failed": "Could not check the Gemini key capabilities ({error})",
        "gemini_decisions_invalid": "Invalid Decisions API payload: input and at least one question (noul, choice, or score) are required",
        "gemini_agents_invalid": "Invalid Agents payload: agent and input are required",
        "gemini_live_failed": "Could not create a Live API token: {detail}",
        "gemini_request_failed": "Gemini API request failed: {detail}",
        "invalid_body": "Invalid request body: expected a JSON object",
        "attachment_unsupported": "{name} ({mime}) cannot be sent to this provider — audio and video files work with Gemini, and PDF files work with Gemini or Anthropic",
        "pairing_required": "This device is not paired yet. Enter a Pairing Key.",
        "pairing_rate_limited": "Too many pairing attempts. Please wait a few minutes and try again.",
        "pairing_key_invalid": "This Pairing Key is invalid, expired, or already used.",
        "auth_disabled": "Web auth is disabled. Set AI_WEB_AUTH=on to use pairing keys.",
        "device_not_found": "Device not found",
        "cross_origin": "A request from another origin was rejected",
        "body_too_large": "The request body is larger than allowed",
        "tool_invalid_payload": "Invalid tool payload",
        "tool_approval_invalid": "The approval request is invalid or expired; request it again",
        "tool_failed": "The tool could not run; check the parameters and try again",
        "log_clear_failed": "Could not clear the log",
        "schedule_name_required": "Provide a job name and prompt",
        "schedule_invalid": "Invalid schedule (a 5-field cron expression is required)",
        "schedule_channel_invalid": "The Discord Channel ID must be a number",
        "schedule_not_found": "Scheduled job not found",
        "schedule_running": "This job is already running",
        "skill_not_found": "Skill not found",
        "skill_read_failed": "Could not read the skill",
        "skill_create_failed": "Could not create the skill",
        "skill_content_invalid": "The skill content is invalid or larger than allowed",
        "skill_save_failed": "Could not save the skill",
        "skill_delete_failed": "Could not delete the skill",
        "history_not_found": "Conversation not found",
        "history_corrupt": "The history file is corrupt or unreadable; check the files in the history folder",
        "history_message_id_required": "message_id is required",
        "history_locked_edit": "This conversation is locked; unlock it before editing",
        "history_invalid": "Invalid conversation payload",
        "history_too_many_messages": "Too many messages",
        "history_invalid_message": "Invalid message format",
        "history_unsupported_role": "An unsupported role was found in the history",
        "history_locked_delete": "This conversation is locked; unlock it before deleting",
        "history_conflict": "Conflict: the record was updated elsewhere; reload it",
        "history_locked_save": "This conversation is locked; unlock it before saving over it",
        "models_fallback": "Could not fetch the model list from the API; using the fallback list",
        "discord_ids_invalid": "Discord IDs must be numbers only: {ids}",
        "custom_key_name_invalid": "Invalid Custom API key name",
        "custom_key_nul": "A Custom API key value must not contain NUL characters",
        "update_mode_invalid": "Invalid update mode",
        "update_script_missing": "No runnable update.sh script was found in the project folder",
        "update_busy": "An update is already running",
        "update_start_failed": "Could not start the update; check the system log",
        "chat_message_required": "Send a message",
        "chat_failed": "Could not process the message; try again",
        "test_connection_failed": "{label}: connection failed; try again",
        "test_connection_hint": "Check the API key, the model and the Base URL again",
        "chat_busy": "{label} is busy or rate-limited; try again or choose another model",
        "chat_provider_error": "The provider returned an error; check the API key and the model",
        "chat_api_failed": "API request failed: {detail}",
        "chat_network_failed": "Could not reach {label}: the request timed out or the network is unavailable (retried once). Check the connection and try again",
        "chat_empty_response": "{label} returned no text (finishReason: {reason}); the model usually uses its whole output budget on thinking. Raise Max tokens or lower the thinking level",
        "tool_call_unreadable": "The model sent a tool call that could not be read (incomplete JSON or no tool name), so nothing was run. Send the message again or switch to a stronger model",
        "rate_limited": "Too many requests; wait a moment and try again",
    },
}


def normalize_language(value: Any) -> str:
    """Normalize a requested UI language to 'th' or 'en', defaulting to English."""
    return "th" if str(value or "").strip().lower().startswith("th") else "en"


def status_message(language: str, key: str, **kwargs: Any) -> str:
    """Format a localized readiness message from the shared status table."""
    messages = STATUS_MESSAGES.get(language) or STATUS_MESSAGES["en"]
    template = messages.get(key) or STATUS_MESSAGES["en"].get(key, key)
    return template.format(**kwargs)


def request_language(allow_body: bool = True) -> str:
    """Pick the response language the current page asked for."""
    value = request.headers.get("X-Interface-Language")
    if not value:
        value = request.args.get("lang")
    if not value and allow_body:
        # Reading an oversized body raises RequestEntityTooLarge again, which
        # would turn the 413 handler (or a rejection made while handling one)
        # into a 500, so the body is only parsed when it fits and cannot raise.
        limit = current_app.config.get("MAX_CONTENT_LENGTH")
        length = request.content_length
        if not (limit and length and length > limit):
            try:
                body = request.get_json(silent=True)
            except Exception:
                body = None
            if isinstance(body, dict):
                value = body.get("lang")
    return normalize_language(value)
