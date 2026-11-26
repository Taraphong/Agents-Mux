const $ = (id) => document.getElementById(id);
// Monochrome line icons, drawn with currentColor so they follow the theme
// (white on the dark theme, black on the light theme).
const ICONS = {
  copy: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>',
  edit: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" /></svg>',
  pin: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 17v5" /><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1z" /></svg>',
  pinFilled:
    '<svg class="is-filled" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 17v5" /><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1z" /></svg>',
  lock: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>',
  unlock:
    '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 9.9-1" /></svg>',
  trash:
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18" /><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" /><path d="M10 11v6" /><path d="M14 11v6" /></svg>',
};
const LANGUAGE_STORAGE_KEY = "ai-control-center-language";
// Provider whose default base URL may still be replaced when the user switches.
let activeProvider = "openai";
// A custom OpenAI-compatible endpoint is remembered per provider so switching
// away and back does not silently discard it.
const customBaseUrls = {};
const SUPPORTED_LANGUAGES = ["th", "en"];
const I18N = {
  th: {
    "app.title": "AI Control Center",
    "sidebar.newChat": "แชตใหม่",
    "nav.chat": "แชต",
    "nav.settings": "ตั้งค่า",
    "nav.schedule": "งานตามเวลา",
    "nav.logs": "Log ระบบ",
    "nav.about": "เกี่ยวกับ",
    "sidebar.history": "ประวัติการพูดคุย",
    "history.renameTitle": "เปลี่ยนชื่อประวัติ",
    "history.renamePlaceholder": "ชื่อประวัติใหม่",
              "common.cancel": "ยกเลิก",
          "common.confirm": "ยืนยัน",
          "common.confirmTitle": "ยืนยันการทำรายการ",
    "common.save": "บันทึก",
    "common.delete": "ลบ",
    "header.openMenu": "เปิดเมนู",
    "header.toolsAria": "เครื่องมือแชต",
    "header.themeTitle": "สลับธีม",
    "header.tagline": "พื้นที่ทำงาน AI ส่วนตัว",
    "language.title": "ภาษา",
    "status.checkingModel": "กำลังตรวจสอบ...",
    "chat.title": "แชตกับ AI",
    "chat.placeholder": "ส่งข้อความถึง AI...",
    "chat.attach": "แนบไฟล์",
    "chat.thinkingTitle": "ระดับการคิด",
    "chat.thinkingOff": "ปิด",
    "chat.thinkingLow": "ต่ำ",
    "chat.thinkingMedium": "กลาง",
    "chat.thinkingHigh": "สูง",
    "chat.commandModeTitle": "โหมดการรันคำสั่ง",
    "chat.commandAsk": "ถามก่อน",
    "chat.commandAuto": "อัตโนมัติ",
    "chat.commandFast": "Fast+",
    "chat.modelTitle": "เลือกโมเดล",
    "chat.modelLoading": "กำลังโหลดโมเดล...",
    "chat.send": "ส่ง",
    "header.toggleSidebar": "ย่อ/ขยายแถบด้านข้าง",
    "message.copyPrompt": "คัดลอกคำสั่ง",
    "message.copyAnswer": "คัดลอกคำตอบ",
    "message.editPrompt": "แก้ไขคำสั่ง",
    "message.editTitle": "แก้ไขคำสั่ง",
    "message.editHint":
      "บันทึกแล้วระบบจะลบคำตอบเดิมของคำสั่งนี้ แล้วส่งคำสั่งที่แก้ไขไปถาม AI ใหม่อีกครั้ง",
    "message.editSave": "บันทึกและส่งใหม่",
    "message.editEmpty": "คำสั่งต้องไม่ว่าง",
    "message.editBusy": "รอให้ AI ตอบเสร็จก่อนแก้ไขคำสั่ง",
    "message.editFailed": "แก้ไขคำสั่งไม่สำเร็จ",
    "message.copied": "คัดลอกแล้ว",
    "message.copyFailed": "คัดลอกไม่สำเร็จ",
    "server.title": "ควบคุมเซิร์ฟเวอร์",
    "server.hint":
      "สั่งเปิด ปิด หรือรีสตาร์ตเซิร์ฟเวอร์จากหน้านี้ เมื่อหยุดแล้วหน้าเว็บจะใช้งานไม่ได้จนกว่าจะเปิดใหม่จากเครื่องด้วย ./start_web.sh --start",
    "server.refresh": "รีเฟรชสถานะ",
    "server.state": "สถานะ",
    "server.pid": "PID",
    "server.uptime": "ทำงานมา",
    "server.mode": "โหมด",
    "server.start": "เริ่ม",
    "server.restart": "รีสตาร์ต",
    "server.stop": "หยุด",
    "server.running": "กำลังทำงาน",
    "server.stopped": "หยุดแล้ว",
    "server.unknown": "ไม่ทราบสถานะ",
    "server.loadFailed": "โหลดสถานะเซิร์ฟเวอร์ไม่สำเร็จ",
    "server.actionPending": "กำลังส่งคำสั่ง: {action}",
    "server.actionFailed": "สั่งงานไม่สำเร็จ: {error}",
    "server.confirmRestart":
      "รีสตาร์ตเซิร์ฟเวอร์หรือไม่? หน้าเว็บจะขาดการเชื่อมต่อชั่วครู่",
    "server.confirmStop":
      "หยุดเซิร์ฟเวอร์หรือไม่? หน้าเว็บจะใช้งานไม่ได้จนกว่าจะเปิดใหม่จากเครื่อง",
    "server.restartConfirmTitle": "ยืนยันการรีสตาร์ต",
    "server.stopConfirmTitle": "ยืนยันการหยุดเซิร์ฟเวอร์",
    "server.restarting": "กำลังรีสตาร์ตเซิร์ฟเวอร์...",
    "server.restartDone": "เซิร์ฟเวอร์กลับมาทำงานแล้ว",
    "server.restartNewScheme":
      "กำลังเปลี่ยนโหมดการเชื่อมต่อ — เปิดที่อยู่ใหม่เมื่อเซิร์ฟเวอร์กลับมา: {url}",
    "server.restartSlow":
      "ยังเชื่อมต่อเซิร์ฟเวอร์ไม่ได้ หากเปลี่ยน HTTP/HTTPS ให้เปิดที่อยู่ใหม่ในเบราว์เซอร์",
    "server.stoppedNow":
      "ส่งคำสั่งหยุดเซิร์ฟเวอร์แล้ว เปิดใหม่ได้จากเครื่องด้วย ./start_web.sh --start",
    "server.uptimeValue": "{hours} ชม. {minutes} นาที",
    "server.uptimeMinutes": "{minutes} นาที",
    "settings.group.server": "เซิร์ฟเวอร์",
    "settings.group.serverDesc": "เปิด ปิด และรีสตาร์ตเซิร์ฟเวอร์ของเว็บนี้",
    "settings.group.network": "เว็บและ HTTPS",
    "settings.group.networkDesc":
      "เลือกโหมด HTTP หรือ HTTPS ที่เซิร์ฟเวอร์ใช้ให้บริการหน้าเว็บนี้",
    "network.title": "การเชื่อมต่อเว็บ (HTTP / HTTPS)",
    "network.hint":
      "เลือกโหมดที่เซิร์ฟเวอร์ใช้ให้บริการหน้าเว็บ การเปลี่ยนโหมดมีผลหลังรีสตาร์ตเซิร์ฟเวอร์",
    "network.refresh": "รีเฟรช",
    "network.currentMode": "โหมดที่ใช้งาน",
    "network.address": "ที่อยู่",
    "network.certState": "ใบรับรอง",
    "network.optionsAria": "เลือกโหมด HTTP หรือ HTTPS",
    "network.httpTitle": "HTTP",
    "network.httpHint":
      "ไม่เข้ารหัสการเชื่อมต่อ เหมาะกับเครือข่ายที่เชื่อถือได้ในบ้าน",
    "network.certTitle": "HTTPS ด้วยไฟล์ใบรับรอง",
    "network.certHint":
      "ใช้ certs/cert.pem และ certs/key.pem หรือคู่ไฟล์ที่ตั้งไว้ใน .env",
    "network.adhocTitle": "HTTPS ด้วยใบรับรองชั่วคราว",
    "network.adhocHint":
      "สร้างใบรับรอง self-signed อัตโนมัติด้วย openssl และใช้ไฟล์เดิมทุกครั้งที่รีสตาร์ต",
    "network.save": "บันทึกโหมด",
    "network.saveScopeHint":
      "ปุ่มนี้ใช้กับการตั้งค่าทั่วไปเท่านั้น — โหมดเครือข่ายใช้ปุ่ม \"บันทึกโหมด\" ใน Web & HTTPS",
    "network.restart": "รีสตาร์ตเซิร์ฟเวอร์",
    "network.certHelp": "สร้างใบรับรองถาวรได้ด้วย ./start_web.sh --make-cert <ip>",
    "network.saved": "บันทึกโหมดการเชื่อมต่อแล้ว",
    "network.saveFailed": "บันทึกโหมดการเชื่อมต่อไม่สำเร็จ",
    "network.needRestart":
      "บันทึกแล้ว — กดรีสตาร์ตเซิร์ฟเวอร์เพื่อให้โหมดใหม่มีผล ที่อยู่ใหม่: {url}",
    "network.loadFailed": "โหลดการตั้งค่าการเชื่อมต่อไม่สำเร็จ",
    "network.certReady": "พร้อมใช้งาน",
    "network.certMissing": "ไม่พบไฟล์",
    "network.certOff": "ไม่ได้ใช้",
    "network.adhocOn": "ใช้ใบรับรองชั่วคราว",
    "page.network": "HTTPS / HTTP",
    "chat.typingThinking": "AI กำลังคิด",
    "chat.typingWorking": "AI กำลังเรียบเรียงคำตอบ",
    "chat.typingStillWorking": "AI ยังทำงานอยู่ กรุณารออีกนิด",
    "chat.typingElapsed": "· {seconds} วิ",
    "chat.fallbackUsed": " · สำรอง: {model}",
    "chat.newConversationTitle": "บทสนทนาใหม่",
    "chat.defaultAttachmentPrompt": "ช่วยวิเคราะห์ไฟล์แนบนี้ให้หน่อย",
    "chat.error": "เกิดข้อผิดพลาด",
    "chat.errorPrefix": "ข้อผิดพลาด: {message}",
    "chat.saveWarning": "บันทึกประวัติไม่สำเร็จ",
    "slash.commandLabel": "⌘ คำสั่ง",
    "slash.menuAria": "คำสั่งในแชต",
    "slash.error": "คำสั่งไม่สำเร็จ",
    "slash.helpTitle": "คำสั่งที่ใช้ได้ในเว็บ",
    "slash.helpHint": "พิมพ์ / แล้วเลือกจากเมนู หรือพิมพ์คำสั่งเองได้เลย",
    "slash.helpDesc": "แสดงรายการคำสั่งทั้งหมด",
    "slash.newDesc": "เริ่มบทสนทนาใหม่",
    "slash.clearDesc": "ล้างบริบทการสนทนาปัจจุบัน",
    "slash.modelDesc": "ดู provider และ model ที่ใช้งาน",
    "slash.modelsDesc": "ดูรายการ model หรือสลับ provider/model",
    "slash.statusDesc": "ตรวจสอบสถานะการเชื่อมต่อ",
    "slash.pingDesc": "วัดเวลาตอบกลับของเซิร์ฟเวอร์",
    "slash.fallbackDesc": "ดูหรือตั้ง fallback model",
    "slash.skillDesc": "ใช้ Skill กับข้อความถัดไปหรือข้อความที่ระบุ",
    "slash.skillsDesc": "แสดงรายการ Skill ที่มี",
    "slash.skillItemDesc": "ใช้ Skill นี้",
    "slash.skillActivated": "จะใช้ Skill “{name}” กับข้อความถัดไป",
    "slash.clearSkill": "ยกเลิก Skill ที่รอใช้",
    "slash.skillMissing": "ไม่พบ Skill “{name}”",
    "slash.skillUsage": "ใช้ /skill <ชื่อ> [ข้อความ] หรือพิมพ์ /ชื่อ-skill ตามด้วยข้อความ",
    "slash.unknown": "ไม่รู้จักคำสั่ง “/{command}” — พิมพ์ /help เพื่อดูคำสั่งทั้งหมด",
    "slash.newDone": "เริ่มบทสนทนาใหม่แล้ว",
    "slash.clearDone": "ล้างบริบทการสนทนาแล้ว",
    "slash.modelInfo": "Provider: {provider}\nModel: {model}\nสถานะ: {status}",
    "slash.modelsTitle": "Model ของ {provider}",
    "slash.modelsEmpty": "ไม่พบรายการ model",
    "slash.modelsMore":
      "มีโมเดลทั้งหมด {count} รายการ — แสดง 25 รายการแรก เลือกโมเดลจากตัวเลือกโมเดล",
    "slash.modelSwitched": "สลับไปใช้ {provider} / {model} แล้ว",
    "slash.switchFailed": "สลับ model ไม่สำเร็จ: {error}",
    "slash.pingResult": "Pong! เซิร์ฟเวอร์ตอบกลับใน {ms} ms",
    "slash.pingFailed": "เชื่อมต่อเซิร์ฟเวอร์ไม่สำเร็จ: {error}",
    "slash.fallbackInfo": "Fallback: {state}\nProvider: {provider}\nModel: {model}",
    "slash.fallbackNone": "ยังไม่ได้ตั้งค่า",
    "slash.fallbackOff": "ปิด fallback แล้ว",
    "slash.fallbackSet": "ตั้ง fallback model เป็น {model} แล้ว",
    "slash.fallbackFailed": "ตั้ง fallback ไม่สำเร็จ: {error}",
    "slash.skillsTitle": "Skills ที่ใช้ได้",
    "slash.skillsEmpty": "ยังไม่มี Skill ในโฟลเดอร์ skills",
    "slash.statusOn": "พร้อมใช้งาน",
    "slash.statusOff": "ยังไม่พร้อม: {reason}",
    "settings.categoriesAria": "หมวดหมู่การตั้งค่า",
    "settings.group.connection": "การเชื่อมต่อ",
    "settings.group.connectionDesc":
      "ผู้ให้บริการ โมเดล และคีย์ API ที่ใช้ตอบแชต",
    "settings.group.agent": "Agent",
    "settings.group.agentDesc": "ตัวตน บทบาท คำสั่งประจำ และ Skill ของ Agent",
    "settings.group.response": "การตอบ",
    "settings.group.responseDesc":
      "พารามิเตอร์การสร้างคำตอบและระดับการคิด",
    "settings.group.integrations": "ช่องทางและเครื่องมือ",
    "settings.group.integrationsDesc": "Discord bot และ tool ของ Agent",
    "settings.group.security": "ความปลอดภัย",
    "settings.group.securityDesc": "Pairing Key และอุปกรณ์ที่เชื่อมต่อ",
    "settings.group.update": "อัปเดต",
    "settings.group.updateDesc":
      "ดึงไฟล์เวอร์ชันใหม่จาก GitHub และรีสตาร์ตเซิร์ฟเวอร์",
    "settings.updateBuildTitle": "เวอร์ชันที่ติดตั้ง",
    "settings.updateBuildHint":
      "เวลาที่ไฟล์แอปถูกแก้ไขล่าสุดบนเครื่องนี้ และสถานะสคริปต์ updater",
    "settings.updateAppUpdated": "ไฟล์แอปอัปเดตล่าสุด",
    "settings.updateScript": "สคริปต์ update.sh",
    "settings.updateScriptReady": "พร้อมใช้งาน",
    "settings.updateScriptMissing": "ไม่พบสคริปต์",
    "settings.updateUnknown": "ไม่ทราบ",
    "settings.updateCheck": "ตรวจสอบการอัปเดต",
    "settings.updateRun": "อัปเดตเลย",
    "settings.updateLogTitle": "ผลการทำงาน",
    "settings.updateNote":
      "การอัปเดตจะดาวน์โหลดจาก GitHub แล้วรีสตาร์ตเซิร์ฟเวอร์ โดยไม่แตะ .env การตั้งค่า ประวัติ หรือใบรับรอง ระหว่างรีสตาร์ตหน้าเว็บอาจขาดการเชื่อมต่อชั่วครู่",
    "settings.updateConfirm": "อัปเดตไฟล์แอปและรีสตาร์ตเซิร์ฟเวอร์หรือไม่?",
    "settings.updateIdle": "ยังไม่ได้ตรวจสอบในรอบนี้",
    "settings.updateLoading": "กำลังโหลดสถานะ...",
    "settings.updateRunning": "กำลังทำงาน: {mode}",
    "settings.updateModeCheck": "กำลังตรวจสอบ",
    "settings.updateModeApply": "กำลังติดตั้งไฟล์ใหม่",
    "settings.updateCheckDone": "ตรวจสอบเสร็จแล้วเมื่อ {time}",
    "settings.updateDone": "อัปเดตเสร็จแล้วเมื่อ {time}",
    "settings.updateError": "ไม่สำเร็จ (exit {code}) — ดู log ด้านล่าง",
    "settings.updateCheckStarted": "เริ่มตรวจสอบการอัปเดตแล้ว",
    "settings.updateRunStarted": "เริ่มอัปเดตแล้ว — เซิร์ฟเวอร์อาจรีสตาร์ต",
    "settings.updateFailed": "เริ่มการอัปเดตไม่สำเร็จ",
    "settings.updateLoadFailed": "โหลดสถานะการอัปเดตไม่สำเร็จ",
    "settings.updateRestarting": "เซิร์ฟเวอร์กำลังรีสตาร์ต รอสักครู่...",
    "settings.updateFinishedUnknown":
      "อัปเดตจบแล้วแต่ไม่ทราบผล — ดู log ด้านล่าง",
    "settings.updateLogEmpty": "ยังไม่มีผลการทำงาน",
    "settings.updateLogTruncated": "…แสดงเฉพาะท้าย log",
    "settings.saveScopeHint": "การบันทึกมีผลกับการตั้งค่าทุกหมวด",
    "settings.agentInstructionsTitle": "คำสั่งประจำ Agent",
    "settings.agentInstructionsHint":
      "System prompt และสิ่งที่ Agent ควรทบทวนก่อนตอบ",
    "settings.skillsCardTitle": "Skills",
    "settings.skillsCardHint":
      "เลือก Skill ที่จะใช้กับ Agent หรือสร้าง Skill ใหม่จากที่นี่",
    "settings.responseParamsTitle": "พารามิเตอร์การสร้างคำตอบ",
    "settings.responseParamsHint":
      "ปรับความสร้างสรรค์ ความยาว และระดับการคิดของคำตอบ",
    "settings.providerTitle": "ผู้ให้บริการและโมเดล",
    "settings.agentProfileTitle": "โปรไฟล์ Agent",
    "settings.agentProfileHint": "กำหนดตัวตน บทบาท ภาษา และรูปแบบการตอบของ Agent",
    "settings.agentName": "ชื่อ Agent",
    "settings.agentRole": "บทบาท",
    "settings.responseLanguage": "ภาษาคำตอบ",
    "settings.responseStyle": "โทนและสไตล์",
    "settings.useMarkdown": "ใช้ Markdown",
    "settings.askQuestions": "ถามกลับเมื่อข้อมูลไม่พอ",
    "settings.languageAuto": "ตามภาษาผู้ใช้",
    "settings.languageTh": "ไทย",
    "settings.languageEn": "English",
    "settings.providerLabel": "ผู้ให้บริการ",
    "settings.modelLabel": "โมเดล",
    "settings.providerHint":
      "เลือกเส้นทางที่ใช้ตอบแชต และกำหนด endpoint ได้เองสำหรับ OpenAI-compatible API",
    "settings.modelNotFetched": "ยังไม่ได้ดึงจาก API",
    "settings.modelCustomPlaceholder": "พิมพ์ชื่อโมเดลเอง",
    "settings.fallbackTitle":
      "Fallback model เมื่อโมเดลหลักใช้ไม่ได้",
    "settings.fallbackEnable": "เปิดใช้งาน",
    "settings.fallbackNone": "ไม่ใช้ fallback",
    "settings.fallbackHint":
      "จะลองใช้เมื่อ API ตอบกลับว่าโมเดลไม่พร้อมใช้งานหรือถูกจำกัดอัตรา",
    "settings.fallbackProviderAria": "ผู้ให้บริการ Fallback",
    "settings.baseUrlLabel": "Base URL",
    "settings.apiKeyLabel": "คีย์ API",
    "settings.apiKeyPlaceholder": "เว้นว่างเพื่อใช้คีย์เดิม",
    "settings.customKeysTitle": "คีย์ API อื่น ๆ",
    "settings.customKeysHint":
      "เก็บคีย์ของบริการอื่น เช่น สภาพอากาศ ไว้ในเครื่องนี้ tool ของ Agent จะเห็นคีย์เป็นตัวแปรสภาพแวดล้อมตามชื่อที่ตั้งไว้",
    "settings.customKeyName": "ชื่อคีย์",
    "settings.customKeyNamePlaceholder": "WEATHER_API_KEY",
    "settings.customKeyValue": "ค่า API key",
    "settings.customKeyValuePlaceholder": "วางคีย์ที่นี่",
    "settings.customKeyAdd": "เพิ่มคีย์",
    "settings.customKeyAdded": "บันทึกคีย์แล้ว",
    "settings.customKeyAddFailed": "บันทึกคีย์ไม่สำเร็จ",
    "settings.customKeyDelete": "ลบ",
    "settings.customKeyDeleteAria": "ลบคีย์ {name}",
    "settings.customKeyDeleted": "ลบคีย์แล้ว",
    "settings.customKeySaved": "บันทึกไว้ในเครื่องนี้แล้ว",
    "settings.customKeysEmpty": "ยังไม่มีคีย์อื่นที่บันทึกไว้",
    "settings.customKeyNameRequired": "กรอกชื่อคีย์และค่า API key ก่อนบันทึก",
    "settings.memoryReview": "ทบทวนความจำ",
    "settings.memoryReviewPlaceholder": "กำหนดสิ่งที่ Agent ควรทบทวนก่อนตอบ",
    "settings.memoryReviewHint": "แนวทางนี้จะถูกส่งให้ Agent ทุกครั้งที่ตอบ เพื่อรักษาบริบทและลดความผิดพลาด",
    "settings.skills": "Skills ที่ใช้กับ Agent",
    "settings.skillsHint": "เลือกได้หลายสกิล ระบบจะส่งเนื้อหาไปเป็นแนวทางให้ Agent",
    "settings.newSkillName": "ชื่อ Skill ใหม่",
    "settings.newSkillDescription": "คำอธิบาย Skill",
    "settings.newSkillDescriptionHint":
      "บันทึกเป็น description ใน frontmatter ใช้ให้ Agent เลือก Skill ได้ตรงงาน",
    "settings.newSkillDescriptionPlaceholder":
      "บอกว่า Skill นี้ใช้เมื่อไร เช่น รีวิวโค้ดก่อน merge",
    "settings.newSkillDescriptionRequired":
      "กรอกคำอธิบาย Skill ก่อนสร้าง เพื่อให้ Agent เลือก Skill ได้ตรงงาน",
    "settings.newSkillContent": "เนื้อหา Skill",
    "settings.newSkillNamePlaceholder": "เช่น code-review",
    "settings.newSkillContentPlaceholder": "เขียนแนวทางการทำงานของ Skill",
    "settings.createSkill": "สร้าง Skill",
    "settings.createSkillDone": "สร้าง Skill แล้ว",
    "settings.createSkillFailed": "สร้าง Skill ไม่สำเร็จ",
    "settings.updateSkill": "บันทึกการแก้ไข",
    "settings.deleteSkill": "ลบ Skill",
    "settings.deleteSkillConfirm": "ต้องการลบ Skill นี้ถาวรหรือไม่?",
    "settings.skillSaved": "บันทึก Skill แล้ว",
    "settings.skillDeleted": "ลบ Skill แล้ว",
    "settings.systemPromptLabel": "System prompt",
    "settings.thinkingLevel": "ระดับการคิด",
    "settings.temperatureLabel": "Temperature",
    "settings.temperatureHint": "ค่าต่ำให้คำตอบสม่ำเสมอและคาดเดาง่าย ค่าสูงให้คำตอบหลากหลายขึ้น",
    "settings.topPLabel": "Top P",
    "settings.topPHint": "เลือกคำจากกลุ่มที่มีความน่าจะเป็นรวมกันตามค่านี้ ค่ายิ่งต่ำยิ่งจำกัดคำที่เลือก",
    "settings.maxTokensLabel": "จำนวน token สูงสุด",
    "settings.thinkingOff": "ปิด",
    "settings.thinkingLow": "ต่ำ",
    "settings.thinkingMedium": "กลาง",
    "settings.thinkingHigh": "สูง",
    "settings.stream": "เปิดการตอบแบบ streaming (เตรียมรองรับ)",
    "settings.discordTitle": "Discord bot",
    "settings.discordHint": "ให้ bot รับข้อความจาก Discord แล้วตอบด้วย provider/model หลักของระบบ",
    "settings.discordEnable": "เปิดใช้งาน Discord bot",
    "settings.discordToken": "Bot token",
    "settings.discordTokenPlaceholder": "เว้นว่างเพื่อใช้ token เดิม",
    "settings.discordTokenHintHas": "มี token แล้ว — เว้นว่างเพื่อคงค่าเดิม",
    "settings.discordTokenHintMissing": "ยังไม่มี token — ใส่ token จาก Discord Developer Portal",
    "settings.discordPrefix": "Prefix",
    "settings.discordAllowedChannels": "จำกัดเฉพาะช่อง (Channel ID)",
    "settings.discordAllowedChannelsPlaceholder": "เช่น 123456789012345678, 987654321098765432",
    "settings.discordAllowedChannelsHint": "เว้นว่างเพื่อให้ bot ตอบได้ทุกช่อง ใส่ Channel ID คั่นด้วยจุลภาค (DM ใช้ Channel ID ของ DM)",
    "settings.discordAllowedUsers": "จำกัดเฉพาะผู้ใช้ (User ID)",
    "settings.discordAllowedUsersPlaceholder": "เช่น 123456789012345678, 987654321098765432",
    "settings.discordAllowedUsersHint": "เว้นว่างเพื่อให้ทุกคนในช่องที่อนุญาตใช้งานได้ ใส่ User ID คั่นด้วยจุลภาค (เปิด Developer Mode แล้วคลิกขวาที่ผู้ใช้ > Copy ID)",
    "settings.machineTitle": "สิทธิ์เข้าถึงเครื่อง",
    "settings.machineHint":
      "ให้ agent เข้าถึงทุก path ในเครื่องและรันคำสั่งผ่าน shell จริง (รวม sudo ถ้าผู้ใช้ที่รันแอปมีสิทธิ์) ทุกการเรียกเครื่องมือจะขออนุมัติในแชตก่อนทุกครั้ง",
    "settings.machineEnable": "ให้ agent เข้าถึงทั้งเครื่อง (ขออนุมัติทุกครั้ง)",
    "auth.title": "ความปลอดภัยและการจับคู่อุปกรณ์",
    "auth.hint":
      "เว็บนี้ต้องจับคู่อุปกรณ์ก่อนใช้งาน สร้าง Pairing Key จากฝั่ง server แล้วนำคีย์ไปใส่ที่หน้า /pair ของ client คีย์ใช้ได้ครั้งเดียวและมีอายุจำกัด",
    "auth.generate": "สร้าง Pairing Key",
    "auth.keyCreated": "สร้าง Pairing Key แล้ว — นำไปใส่ที่อุปกรณ์อื่นได้ทันที",
    "auth.keyFailed": "สร้าง Pairing Key ไม่สำเร็จ",
    "auth.keyGenerated": "Pairing Key ใหม่ (ใช้ได้ครั้งเดียว)",
    "auth.keyExpiry": "ใช้ได้ถึง {time} (ราว {minutes} นาที)",
    "auth.devices": "อุปกรณ์ที่เชื่อมต่อ",
    "auth.deviceFallback": "อุปกรณ์ไม่ทราบชื่อ",
    "auth.lastSeen": "ใช้งานล่าสุด {time}",
    "auth.unknownTime": "ไม่ทราบเวลา",
    "auth.thisDevice": "อุปกรณ์นี้",
    "auth.logout": "ออกจากระบบอุปกรณ์นี้",
    "auth.revoke": "ยกเลิกการเชื่อมต่อ",
    "auth.revoked": "ยกเลิกอุปกรณ์แล้ว",
    "auth.revokeFailed": "ยกเลิกอุปกรณ์ไม่สำเร็จ",
    "auth.empty": "ยังไม่มีอุปกรณ์ที่เชื่อมต่อ",
    "auth.disabled":
      "Web auth ปิดอยู่ (AI_WEB_AUTH=off) — ไม่ต้องจับคู่อุปกรณ์",
    "auth.offline": "โหลดสถานะอุปกรณ์ไม่สำเร็จ",
    "auth.logoutFailed": "ออกจากระบบไม่สำเร็จ กรุณาลองใหม่",
    "settings.save": "บันทึกการตั้งค่า",
    "settings.loadFailed": "โหลดการตั้งค่าไม่สำเร็จ: {error}",
    "settings.test": "ทดสอบการเชื่อมต่อ",
    "settings.reset": "รีเซ็ต",
    "schedule.title": "งานตามเวลา (Cron jobs)",
    "schedule.hint":
      "ตั้ง prompt ให้ AI ทำงานซ้ำตามเวลา ระบบจะทำงานเมื่อ server กำลังเปิดอยู่",
    "schedule.loading": "กำลังโหลด...",
    "schedule.timezoneLabel": "Timezone:",
    "schedule.cronSummary": "วิธีตั้งค่า Cron jobs",
    "schedule.cronFieldsText": "รูปแบบมี 5 ช่อง:",
    "schedule.cronFieldsCode":
      "นาที ชั่วโมง วันที่ เดือน วันในสัปดาห์",
    "schedule.cronEvery": "= ทุกค่า",
    "schedule.cronStep": "= ทุก 5 หน่วย",
    "schedule.cronRange": "= ช่วง",
    "schedule.cronList": "= หลายค่า",
    "schedule.cronExamplesText": "ตัวอย่าง:",
    "schedule.cronEvery5": "ทุก 5 นาที",
    "schedule.cronWeekdays": "จันทร์-ศุกร์ 09:00",
    "schedule.cronMidnight": "ทุกวันเที่ยงคืน",
    "schedule.cronNote":
      "งานจะใช้โมเดลตามที่เลือก และบันทึกผลลัพธ์เป็นประวัติการสนทนา งานที่มีการรันคำสั่งระบบจะไม่ทำงานอัตโนมัติ",
    "schedule.namePlaceholder": "ชื่องาน เช่น สรุปข่าวประจำวัน",
    "schedule.presetTitle": "ตัวอย่างเวลา",
    "schedule.presetPlaceholder":
      "เลือกตัวอย่างเวลา หรือพิมพ์เองด้านล่าง",
    "schedule.every5": "ทุก 5 นาที",
    "schedule.hourly": "ทุกชั่วโมง",
    "schedule.weekdays9": "จันทร์-ศุกร์ เวลา 09:00",
    "schedule.dailyMidnight": "ทุกวัน เวลา 00:00",
    "schedule.expressionPlaceholder": "Cron เช่น 0 9 * * 1-5",
    "schedule.modelTitle": "โมเดลสำหรับงาน",
    "schedule.useMainModel": "ใช้โมเดลหลักจาก Settings",
    "schedule.discordChannelPlaceholder": "Discord Channel ID (ไม่บังคับ)",
    "schedule.discordChannelTitle": "รหัสช่อง Discord",
    "schedule.promptPlaceholder": "Prompt ที่ต้องการให้ AI ทำงาน",
    "schedule.enableNow": "เปิดใช้งานทันที",
    "schedule.add": "เพิ่มงานตามเวลา",
    "schedule.saveEdit": "บันทึกการแก้ไข",
    "schedule.cancelEdit": "ยกเลิกการแก้ไข",
    "schedule.empty": "ยังไม่มีงานตามเวลา",
    "schedule.timezoneFallback": "เวลาของเครื่อง Server",
    "schedule.modelLabel": "โมเดล: {model}",
    "schedule.discordChannel": "ส่งผลไป Discord ช่อง: {id}",
    "schedule.enabled": "เปิดใช้งาน",
    "schedule.disabled": "ปิดใช้งาน",
    "schedule.neverRun": "ยังไม่เคยทำงาน",
    "schedule.success": "สำเร็จ",
    "schedule.failed": "ล้มเหลว",
    "schedule.retryAt": "จะลองใหม่ {time}",
    "schedule.toggleEnable": "เปิดใช้งาน",
    "schedule.toggleDisable": "ปิดใช้งาน",
    "schedule.added": "เพิ่มงานตามเวลาแล้ว",
    "schedule.addFailed": "เพิ่มงานไม่สำเร็จ",
    "schedule.loadFailed": "โหลดงานตามเวลาไม่สำเร็จ: {error}",
    "schedule.runNow": "รันทันที",
    "schedule.started": "เริ่มรันงานแล้ว",
    "schedule.edit": "แก้ไข",
    "schedule.editing": "กำลังแก้ไขงานตามเวลา",
    "schedule.updated": "บันทึกการแก้ไขแล้ว",
    "schedule.editCancelled": "ยกเลิกการแก้ไขแล้ว",
    "logs.title": "Log ระบบ",
    "logs.system": "Log ระบบ",
    "logs.agent": "Log Agent",
    "logs.filterAria": "ประเภท log",
    "logs.hint":
      "ดูขั้นตอนการเรียก AI และเครื่องมือย้อนหลังล่าสุด โดยไม่แสดง API key หรือเนื้อหาไฟล์",
    "logs.saveFile": "บันทึกไฟล์",
    "logs.delete": "ลบ Log",
    "logs.deleteConfirm": "ต้องการลบ Log ทั้งหมดถาวรหรือไม่?",
    "logs.deleteFailed": "ลบไม่สำเร็จ",
    "logs.refresh": "รีเฟรช",
    "logs.loading": "กำลังโหลด...",
    "logs.empty": "ยังไม่มี log",
    "logs.loadError": "โหลด log ไม่สำเร็จ: {message}",
    "logs.saveFailed": "บันทึกไม่สำเร็จ",
    "about.title": "เกี่ยวกับระบบ",
    "about.text1":
      "เว็บแชต AI ที่รันบน Termux พร้อมหน้า settings สำหรับควบคุม provider, model, endpoint, prompt และพารามิเตอร์ต่าง ๆ",
    "about.text2":
      "API key จะเก็บฝั่งเซิร์ฟเวอร์ในไฟล์ตั้งค่าที่ไม่ถูก commit เข้า Git",
    "page.settings": "ตั้งค่าระบบ",
    "page.schedule": "งานตามเวลา",
    "page.logs": "Log ระบบ",
    "page.about": "เกี่ยวกับระบบ",
    "usage.duration": "{duration} วินาที",
    "usage.unknownDuration": "ไม่ทราบเวลา",
    "usage.unknownTokens": "ไม่ทราบ token",
    "usage.summary": "ใช้เวลา {duration} · {tokens}",
    "usage.tokens": "{count} tokens",
    "tool.approve": "อนุมัติใช้ {name}",
    "tool.contentLabel": "เนื้อหา:",
    "tool.working": "กำลังทำงาน...",
    "tool.done": "ทำงานแล้ว",
    "tool.error": "ใช้เครื่องมือไม่สำเร็จ",
    "tool.expired": "คำขออนุมัติหมดอายุ กรุณาส่งข้อความใหม่",
    "tool.failedAfterApproval":
      "ใช้เครื่องมือไม่สำเร็จ: {message} (คำขออนุมัตินี้ถูกใช้แล้ว กรุณาส่งข้อความใหม่)",
    "tool.retry": "ลองอีกครั้ง ({message})",
    "tool.resultPrefix": "ผลการใช้เครื่องมือ:",
    "tool.resultChip": "ใช้ {name} แล้ว",
    "tool.resultChipUnknown": "เครื่องมือของ Agent",
    "tool.resultDetails": "ดูผลลัพธ์เครื่องมือ",
    "attachment.tooLarge": "ไฟล์ใหญ่เกิน 1 MB",
    "attachment.binaryTooLarge": "ไฟล์ใหญ่เกิน 6 MB",
    "attachment.readFailed": "อ่านไฟล์ไม่สำเร็จ",
    "attachment.unsupported": "ไม่รองรับไฟล์ชนิดนี้",
    "attachment.providerUnsupported":
      "ไฟล์ {name} ({mime}) ส่งให้ผู้ให้บริการนี้ไม่ได้ — ไฟล์เสียงและวิดีโอใช้ได้กับ Gemini ส่วน PDF ใช้ได้กับ Gemini หรือ Anthropic",
    "attachment.clear": "ยกเลิกไฟล์แนบ",
    "common.close": "ปิด",
    "gemini.title": "ความสามารถของคีย์ Gemini",
    "gemini.hint": "คีย์ Gemini เดียวใช้ได้กับหลายกลุ่มความสามารถ ระบบจะตรวจจากคีย์ที่บันทึกไว้",
    "gemini.refresh": "ตรวจสอบอีกครั้ง",
    "gemini.notChecked": "กดตรวจสอบเพื่อดูว่าคีย์รองรับอะไร",
    "gemini.checking": "กำลังตรวจสอบ...",
    "gemini.liveModel": "โมเดล Live API",
    "gemini.defaultModel": "ใช้ค่าเริ่มต้นอัตโนมัติ",
    "gemini.agent": "Managed agent",
    "gemini.decisionModel": "โมเดล Decisions API",
    "gemini.openTools": "เครื่องมือ Gemini",
    "gemini.toolsTitle": "เครื่องมือ Gemini",
    "gemini.toolsHint": "Live API, Decisions API และ Managed agents ใช้คีย์ Gemini เดียวกัน",
    "gemini.liveTitle": "Live API (เสียงเรียลไทม์)",
    "gemini.liveHint": "อนุญาตไมโครโฟนแล้วกดเริ่ม ระบบจะออก token อายุสั้นให้เบราว์เซอร์โดยไม่เปิดเผย API key",
    "gemini.liveStart": "เริ่มสนทนาเสียง",
    "gemini.liveStop": "หยุดสนทนาเสียง",
    "gemini.liveStarting": "กำลังเชื่อมต่อ...",
    "gemini.liveListening": "กำลังฟัง — พูดได้เลย",
    "gemini.liveStopped": "หยุดแล้ว",
    "gemini.liveError": "เชื่อมต่อ Live API ไม่สำเร็จ",
    "gemini.liveUnsupported": "เบราว์เซอร์นี้ไม่รองรับไมโครโฟนหรือ WebSocket",
    "gemini.liveYou": "คุณ",
    "gemini.liveAgent": "Gemini",
    "gemini.decisionsTitle": "Decisions API",
    "gemini.decisionsHint": "ประเมินหลายคำถามจาก input เดียว รองรับ noul (จริง/เท็จ), choice และ score",
    "gemini.decisionsInput": "Input",
    "gemini.decisionsQuestions": "Questions (JSON)",
    "gemini.runDecisions": "ประเมินคำถาม",
    "gemini.agentsTitle": "Managed agents",
    "gemini.agentsHint": "ส่งงานให้ agent ที่จัดการโดย Gemini ใน sandbox และรับผลลัพธ์กลับมา",
    "gemini.agentLabel": "Agent",
    "gemini.agentPrompt": "งานที่ต้องการ",
    "gemini.runAgent": "ส่งงานให้ Agent",
    "gemini.running": "กำลังทำงาน...",
    "gemini.noResult": "(ไม่มีข้อความตอบกลับ)",
    "gemini.notConfigured": "ยังไม่ได้ตั้งค่า Gemini API key",
    "gemini.badQuestions": "Questions ต้องเป็น JSON ที่ถูกต้อง",
    "gemini.loadFailed": "ตรวจสอบไม่สำเร็จ",
    "gemini.ready": "พร้อมใช้",
    "gemini.unverified": "ยังไม่ได้ยืนยัน",
    "gemini.unavailable": "ไม่พบ",
    "gemini.group.multimodal": "Multi-modal generative models",
    "gemini.group.live": "Live API",
    "gemini.group.decisions": "Decisions API",
    "gemini.group.agents": "Agents",
    "gemini.group.other": "Other",
    "gemini.agentIds": "Interaction: {interaction} · Environment: {environment}",
    "model.custom": "กำหนดเอง...",
    "model.fetching": "กำลังดึงจาก API...",
    "model.fetched": "ดึงจาก API แล้ว {count} รายการ",
    "model.fallback": "API ใช้งานไม่ได้ — ใช้รายการสำรอง",
    "model.fetchError": "ดึงรายการโมเดลไม่สำเร็จ",
    "model.none": "ยังไม่ได้เลือกโมเดล",
    "chatModel.notConnected": "ยังไม่ได้เชื่อมต่อ",
    "status.ready": "● พร้อมใช้งาน",
    "status.notReady": "● ยังไม่พร้อมใช้งาน",
    "status.connectedTitle": "เชื่อมต่อ {model} พร้อมใช้งาน",
    "status.notConnectedReason": "ยังเชื่อมต่อผู้ให้บริการไม่ได้",
    "status.inputDisabled":
      "ใส่ API key และเลือกโมเดลใน Settings ก่อนใช้งาน",
    "status.checkFailed": "ตรวจสอบสถานะการเชื่อมต่อไม่สำเร็จ",
    "status.settingsLoadFailed": "โหลดการตั้งค่าไม่สำเร็จ",
    "apiKey.hasPlaceholder":
      "มีคีย์ของ {provider} แล้ว — เว้นว่างเพื่อคงเดิม",
    "apiKey.missingPlaceholder":
      "ยังไม่มีคีย์ของ {provider} — ใส่ API key",
    "apiKey.hasHint": "บันทึกคีย์ของ {provider} ไว้แล้ว",
    "apiKey.missingHint":
      "ยังไม่มีคีย์ของ {provider} — ถ้าเว้นว่าง สถานะจะยังไม่พร้อมใช้งาน",
    "notice.settingsSaved": "บันทึกการตั้งค่าแล้ว",
    "notice.settingsSaveFailed": "บันทึกไม่สำเร็จ",
    "notice.testing": "กำลังทดสอบ...",
    "notice.testSuccess": "เชื่อมต่อสำเร็จ: {answer}",
    "notice.testFailed": "เชื่อมต่อไม่สำเร็จ: {error}",
    "notice.resetConfirm": "รีเซ็ตการตั้งค่าทั้งหมดหรือไม่?",
    "notice.resetDone": "รีเซ็ตการตั้งค่าแล้ว",
    "history.untitled": "บทสนทนาไม่มีชื่อ",
    "history.rename": "เปลี่ยนชื่อ",
    "history.pin": "ปักหมุด",
    "history.unpin": "ถอนหมุด",
    "history.lock": "ล็อก",
    "history.unlock": "ปลดล็อก",
    "history.delete": "ลบ",
    "history.pinned": "ปักหมุด",
    "history.empty": "ยังไม่มีประวัติ",
    "history.loadFailed": "โหลดประวัติไม่สำเร็จ: {error}",
    "history.unknownDate": "ไม่ทราบวันที่",
    "history.deleteTitle": "ลบประวัติ",
    "history.deleteConfirm":
      "ประวัตินี้จะถูกลบออกจากเครื่องและไม่สามารถกู้คืนได้",
    "history.renameDescription": "กำหนดชื่อใหม่ให้ประวัติการสนทนา",
    "history.actionFailed": "ดำเนินการไม่สำเร็จ",
    "history.renameFailed": "แก้ไขประวัติไม่สำเร็จ",
    "history.deleteFailed": "ลบประวัติไม่สำเร็จ",
    "history.startedNew": "เริ่มบทสนทนาใหม่",
    "history.emptyHint": "เริ่มบทสนทนาใหม่ได้เลยครับ",
    "nav.memory": "ความจำ",
    "page.memory": "ความจำ",
    "settings.group.memory": "ความจำ",
    "settings.group.memoryDesc":
      "คัดกรองความจำเบื้องหลังตอนเครื่องว่าง แล้วโปรโมตเฉพาะเรื่องที่ผ่านเกณฑ์ลง MEMORY.md",
    "memory.settingsTitle": "ระบบคัดกรองความจำ",
    "memory.settingsHint":
      "การตัดคำซ้ำ คำนวณคะแนน และเงื่อนไขรันเป็นโค้ดในเครื่องทั้งหมด ส่วนการสรุปความหมายจะส่งให้โมเดลที่เลือก",
    "memory.enableLabel": "เปิดใช้งานการคัดกรองอัตโนมัติ",
    "memory.scheduleLabel": "เวลาเริ่ม (cron 5 ช่วง)",
    "memory.scheduleHint": "ค่าเริ่มต้น 03:00 น. ตาม timezone ของเซิร์ฟเวอร์",
    "memory.windowEndLabel": "เลื่อนได้ถึงเวลา",
    "memory.windowEndHint": "ถ้าเครื่องยังไม่ว่าง จะรอจนถึงเวลานี้แล้วข้าม",
    "memory.lookbackLabel": "วิเคราะห์ย้อนหลัง (วัน)",
    "memory.thresholdLabel": "เกณฑ์คะแนนขั้นต่ำ",
    "memory.idleLabel": "ต้องว่างอย่างน้อย (นาที)",
    "memory.maxItemsLabel": "โปรโมตสูงสุดต่อคืน",
    "memory.maxEntriesLabel": "เก็บไว้สูงสุด (รายการ)",
    "memory.pin": "ปักหมุด",
    "memory.unpin": "เอาหมุดออก",
    "memory.pinned": "ปักหมุดไว้",
    "memory.retrievalLabel": "แนบความจำระยะยาวที่เกี่ยวข้องกับแชท",
    "memory.retrievalHint":
      "ใช้เฉพาะรายการที่คำใกล้เคียงกับข้อความล่าสุด และไม่เกินจำนวน/งบตัวอักษรที่ตั้งไว้",
    "memory.retrievalItemsLabel": "ความจำสูงสุดต่อข้อความ",
    "memory.retrievalCharsLabel": "งบตัวอักษรของความจำ",
    "memory.includeLockedLabel": "รวมบทสนทนาที่ล็อกไว้",
    "memory.llmLabel": "ให้โมเดลช่วยสรุปความหมาย (ปิดได้เพื่อรันออฟไลน์ 100%)",
    "memory.providerLabel": "โมเดลที่ใช้สรุป",
    "memory.providerInherit": "ใช้ provider ที่ตั้งไว้",
    "memory.modelLabel": "ชื่อโมเดล (เว้นว่าง = ใช้ค่าเดิม)",
    "memory.baseUrlLabel": "Base URL เฉพาะงานสรุปความจำ",
    "memory.baseUrlHint":
      "เว้นว่างเพื่อใช้ Base URL เดียวกับแชต ใช้ค่านี้เมื่ออยากให้แชตอยู่บน Cloud แต่สรุปความจำในเครื่อง",
    "memory.localModelHint":
      "รันฟรีในเครื่องได้ผ่าน Ollama หรือ llama-server ที่ http://127.0.0.1 (RAM 1.8 GB ใช้โมเดลเล็กได้เท่านั้น)",
    "memory.saveHint":
      "ค่าเหล่านี้บันทึกพร้อมปุ่ม “บันทึกการตั้งค่า” ด้านล่าง",
    "memory.title": "ความจำระยะยาว",
    "memory.hint":
      "ระบบจะย่อยบันทึกประจำวันและประวัติแชทเป็นความจำระยะยาวตอนเครื่องว่าง แล้วเขียนเฉพาะเรื่องที่ผ่านเกณฑ์ลง MEMORY.md",
    "memory.runNow": "รันเลย",
    "memory.dryRun": "ทดลอง (ไม่โปรโมต)",
    "memory.reindex": "ล้างดัชนี",
    "memory.promotedTitle": "สิ่งที่จำได้",
    "memory.promotedHint":
      "แต่ละรายการมาจาก MEMORY.md และลบออกจากทั้งสองชั้นข้อมูลได้",
    "memory.dreamsTitle": "DREAMS.md",
    "memory.dreamsHint": "สรุปกลางคืนว่าอะไรถูกเลือก อะไรถูกข้าม",
    "memory.loading": "กำลังโหลด...",
    "memory.empty": "ยังไม่มีความจำที่ผ่านเกณฑ์ — รันคืนนี้หรือลดเกณฑ์คะแนน",
    "memory.noDreams": "ยังไม่มีบันทึกกลางคืน",
    "memory.running": "กำลังทำงาน...",
    "memory.forget": "ลืม",
    "memory.forgetConfirm": "กดอีกครั้งเพื่อลบ",
    "memory.score": "คะแนน",
    "memory.enabled": "เปิด",
    "memory.disabled": "ปิด",
    "memory.schedule": "เวลา",
    "memory.threshold": "เกณฑ์",
    "memory.idle": "ว่าง",
    "memory.messages": "ข้อความ",
    "memory.conversations": "บทสนทนา",
    "memory.promoted": "ความจำ",
    "memory.index": "ดัชนี",
    "memory.lastRunLine": "รันล่าสุด: {time} · {status}",
    "memory.lastRunPromoted": "โปรโมต {count} รายการ",
    "memory.neverRun": "ยังไม่เคยรัน",
    "memory.idleMinutes": "{minutes} นาที",
    "memory.statusOk": "สำเร็จ",
    "memory.statusDegraded": "สำเร็จ (โมเดลขัดข้อง)",
    "memory.statusFailed": "ล้มเหลว",
    "memory.runDone": "รันแล้ว: โปรโมต {count} รายการ จาก {messages} ข้อความใหม่",
    "memory.dryRunDone": "ทดลองเสร็จ: จะโปรโมต {count} รายการ (ยังไม่โปรโมตจริง)",
    "memory.reindexed": "ล้างดัชนีแล้ว — การรันครั้งถัดไปจะสร้างดัชนีจากประวัติใหม่",
    "memory.error": "ระบบความจำผิดพลาด: {error}",
    "memory.capability":
      "SQLite {version} · FTS5 {fts} · vector {vector} · embedding {embedding}",
    "memory.paths": "MEMORY.md: {memory} · DREAMS.md: {dreams} · DB: {db}",
    "memory.llmOn": "ใช้โมเดลสรุป",
    "memory.llmOff": "ออฟไลน์เต็มรูปแบบ",
  },
  en: {
    "app.title": "AI Control Center",
    "sidebar.newChat": "New chat",
    "nav.chat": "Chat",
    "nav.settings": "Settings",
    "nav.schedule": "Scheduled jobs",
    "nav.logs": "System logs",
    "nav.about": "About",
    "sidebar.history": "Conversation history",
    "history.renameTitle": "Rename conversation",
    "history.renamePlaceholder": "New conversation name",
    "common.cancel": "Cancel",
    "common.confirm": "Confirm",
    "common.confirmTitle": "Confirm action",
    "common.save": "Save",
    "common.delete": "Delete",
    "header.openMenu": "Open menu",
    "header.toolsAria": "Chat tools",
    "header.themeTitle": "Toggle theme",
    "header.tagline": "Self-hosted AI workspace",
    "language.title": "Language",
    "status.checkingModel": "Checking...",
    "chat.title": "Chat with AI",
    "chat.placeholder": "Message the AI...",
    "chat.attach": "Attach file",
    "chat.thinkingTitle": "Thinking level",
    "chat.thinkingOff": "Off",
    "chat.thinkingLow": "Low",
    "chat.thinkingMedium": "Medium",
    "chat.thinkingHigh": "High",
    "chat.commandModeTitle": "Command execution mode",
    "chat.commandAsk": "Ask first",
    "chat.commandAuto": "Auto",
    "chat.commandFast": "Fast+",
    "chat.modelTitle": "Choose model",
    "chat.modelLoading": "Loading models...",
    "chat.send": "Send",
    "header.toggleSidebar": "Show or hide the sidebar",
    "message.copyPrompt": "Copy prompt",
    "message.copyAnswer": "Copy answer",
    "message.editPrompt": "Edit prompt",
    "message.editTitle": "Edit prompt",
    "message.editHint":
      "Saving removes this prompt's old answer and sends the edited prompt to the AI again",
    "message.editSave": "Save and resend",
    "message.editEmpty": "The prompt cannot be empty",
    "message.editBusy": "Wait for the AI to finish before editing a prompt",
    "message.editFailed": "Could not edit the prompt",
    "message.copied": "Copied",
    "message.copyFailed": "Could not copy",
    "server.title": "Server control",
    "server.hint":
      "Start, stop, or restart the server here. After stopping, the web page stays offline until you start it on the machine with ./start_web.sh --start",
    "server.refresh": "Refresh status",
    "server.state": "State",
    "server.pid": "PID",
    "server.uptime": "Uptime",
    "server.mode": "Mode",
    "server.start": "Start",
    "server.restart": "Restart",
    "server.stop": "Stop",
    "server.running": "Running",
    "server.stopped": "Stopped",
    "server.unknown": "Unknown state",
    "server.loadFailed": "Could not load the server status",
    "server.actionPending": "Sending command: {action}",
    "server.actionFailed": "Command failed: {error}",
    "server.confirmRestart":
      "Restart the server? The page will disconnect briefly.",
    "server.confirmStop":
      "Stop the server? The page will be unavailable until you start it on the machine.",
    "server.restartConfirmTitle": "Confirm restart",
    "server.stopConfirmTitle": "Confirm stop",
    "server.restarting": "Restarting the server...",
    "server.restartDone": "The server is back online",
    "server.restartNewScheme":
      "Switching the connection mode — open the new address once the server is back: {url}",
    "server.restartSlow":
      "Still cannot reach the server. If you changed HTTP/HTTPS, open the new address in the browser.",
    "server.stoppedNow":
      "Stop command sent. Start it on the machine with ./start_web.sh --start",
    "server.uptimeValue": "{hours}h {minutes}m",
    "server.uptimeMinutes": "{minutes}m",
    "settings.group.server": "Server",
    "settings.group.serverDesc": "Start, stop, and restart this web server",
    "settings.group.network": "Web & HTTPS",
    "settings.group.networkDesc":
      "Choose the HTTP or HTTPS mode this server uses to serve the page",
    "network.title": "Web connection (HTTP / HTTPS)",
    "network.hint":
      "Choose whether the server serves this page over HTTP or HTTPS. A change takes effect after a server restart.",
    "network.refresh": "Refresh",
    "network.currentMode": "Active mode",
    "network.address": "Address",
    "network.certState": "Certificate",
    "network.optionsAria": "Choose HTTP or HTTPS mode",
    "network.httpTitle": "HTTP",
    "network.httpHint":
      "No encryption; suitable for a trusted home network",
    "network.certTitle": "HTTPS with certificate files",
    "network.certHint":
      "Uses certs/cert.pem and certs/key.pem, or the pair already set in .env",
    "network.adhocTitle": "HTTPS with an ad-hoc certificate",
    "network.adhocHint":
      "Generates a self-signed certificate with openssl and reuses the same files on every restart",
    "network.save": "Save mode",
    "network.saveScopeHint":
      "This button applies the other sections only — the network mode uses the \"Save mode\" button in Web & HTTPS",
    "network.restart": "Restart server",
    "network.certHelp": "Create a permanent certificate with ./start_web.sh --make-cert <ip>",
    "network.saved": "Connection mode saved",
    "network.saveFailed": "Could not save the connection mode",
    "network.needRestart":
      "Saved — restart the server to apply the new mode. New address: {url}",
    "network.loadFailed": "Could not load the connection settings",
    "network.certReady": "Ready",
    "network.certMissing": "Files missing",
    "network.certOff": "Not used",
    "network.adhocOn": "Ad-hoc certificate",
    "page.network": "HTTPS / HTTP",
    "chat.typingThinking": "AI is thinking",
    "chat.typingWorking": "AI is composing a reply",
    "chat.typingStillWorking": "AI is still working — one moment",
    "chat.typingElapsed": "· {seconds}s",
    "chat.fallbackUsed": " · fallback: {model}",
    "chat.newConversationTitle": "New conversation",
    "chat.defaultAttachmentPrompt": "Please analyze this attachment",
    "chat.error": "Something went wrong",
    "chat.errorPrefix": "Error: {message}",
    "chat.saveWarning": "Could not save the conversation",
    "slash.commandLabel": "⌘ COMMAND",
    "slash.menuAria": "Chat commands",
    "slash.error": "Command failed",
    "slash.helpTitle": "Web chat commands",
    "slash.helpHint": "Type / and choose from the menu, or type a command directly.",
    "slash.helpDesc": "Show every command",
    "slash.newDesc": "Start a new conversation",
    "slash.clearDesc": "Clear the current conversation context",
    "slash.modelDesc": "Show the active provider and model",
    "slash.modelsDesc": "List models or switch provider/model",
    "slash.statusDesc": "Check the connection status",
    "slash.pingDesc": "Measure the server response time",
    "slash.fallbackDesc": "Show or set the fallback model",
    "slash.skillDesc": "Apply a skill to the next or given message",
    "slash.skillsDesc": "List available skills",
    "slash.skillItemDesc": "Use this skill",
    "slash.skillActivated": "Skill “{name}” will apply to the next message",
    "slash.clearSkill": "Cancel the pending skill",
    "slash.skillMissing": "Skill “{name}” was not found",
    "slash.skillUsage": "Use /skill <name> [message] or /<skill-name> followed by a message",
    "slash.unknown": "Unknown command “/{command}” — type /help to see all commands",
    "slash.newDone": "Started a new conversation",
    "slash.clearDone": "Cleared the conversation context",
    "slash.modelInfo": "Provider: {provider}\nModel: {model}\nStatus: {status}",
    "slash.modelsTitle": "Models for {provider}",
    "slash.modelsEmpty": "No models found",
    "slash.modelsMore":
      "{count} models available — showing the first 25. Choose a model from the model selector.",
    "slash.modelSwitched": "Switched to {provider} / {model}",
    "slash.switchFailed": "Could not switch model: {error}",
    "slash.pingResult": "Pong! The server responded in {ms} ms",
    "slash.pingFailed": "Could not reach the server: {error}",
    "slash.fallbackInfo": "Fallback: {state}\nProvider: {provider}\nModel: {model}",
    "slash.fallbackNone": "Not configured",
    "slash.fallbackOff": "Fallback disabled",
    "slash.fallbackSet": "Fallback model set to {model}",
    "slash.fallbackFailed": "Could not set fallback: {error}",
    "slash.skillsTitle": "Available skills",
    "slash.skillsEmpty": "No skills found in the skills folder",
    "slash.statusOn": "Ready",
    "slash.statusOff": "Not ready: {reason}",
    "settings.categoriesAria": "Settings categories",
    "settings.group.connection": "Connection",
    "settings.group.connectionDesc":
      "Provider, model and the API key used for replies",
    "settings.group.agent": "Agent",
    "settings.group.agentDesc":
      "Identity, role, standing instructions and skills",
    "settings.group.response": "Response",
    "settings.group.responseDesc":
      "Generation parameters and thinking level",
    "settings.group.integrations": "Channels and tools",
    "settings.group.integrationsDesc": "Discord bot and Agent tools",
    "settings.group.security": "Security",
    "settings.group.securityDesc": "Pairing key and paired devices",
    "settings.group.update": "Update",
    "settings.group.updateDesc":
      "Fetch the newest files from GitHub and restart the server",
    "settings.updateBuildTitle": "Installed build",
    "settings.updateBuildHint":
      "When the app files were last changed on this machine, and whether the updater is available",
    "settings.updateAppUpdated": "App files last updated",
    "settings.updateScript": "update.sh script",
    "settings.updateScriptReady": "Ready",
    "settings.updateScriptMissing": "Script not found",
    "settings.updateUnknown": "Unknown",
    "settings.updateCheck": "Check for updates",
    "settings.updateRun": "Update now",
    "settings.updateLogTitle": "Output",
    "settings.updateNote":
      "Updating downloads from GitHub and restarts the server without touching .env, settings, history or certificates. The page may disconnect briefly during the restart.",
    "settings.updateConfirm":
      "Update the app files and restart the server now?",
    "settings.updateIdle": "Not checked yet",
    "settings.updateLoading": "Loading status...",
    "settings.updateRunning": "Running: {mode}",
    "settings.updateModeCheck": "checking",
    "settings.updateModeApply": "installing files",
    "settings.updateCheckDone": "Check finished at {time}",
    "settings.updateDone": "Update finished at {time}",
    "settings.updateError": "Failed (exit {code}) — see the output below",
    "settings.updateCheckStarted": "Update check started",
    "settings.updateRunStarted": "Update started — the server may restart",
    "settings.updateFailed": "Could not start the update",
    "settings.updateLoadFailed": "Could not load the update status",
    "settings.updateRestarting": "The server is restarting, waiting...",
    "settings.updateFinishedUnknown":
      "Update finished but the result is unknown — see the output below",
    "settings.updateLogEmpty": "No output yet",
    "settings.updateLogTruncated": "…showing only the end of the output",
    "settings.saveScopeHint": "Saving applies to every section",
    "settings.agentInstructionsTitle": "Agent instructions",
    "settings.agentInstructionsHint":
      "System prompt and what the agent should review before answering",
    "settings.skillsCardTitle": "Skills",
    "settings.skillsCardHint":
      "Pick the skills that guide the agent, or add a new one here",
    "settings.responseParamsTitle": "Generation parameters",
    "settings.responseParamsHint":
      "Tune creativity, response length and thinking depth",
    "settings.providerTitle": "Provider and model",
    "settings.agentProfileTitle": "Agent profile",
    "settings.agentProfileHint": "Define the agent identity, role, language, and response style.",
    "settings.agentName": "Agent name",
    "settings.agentRole": "Role",
    "settings.responseLanguage": "Response language",
    "settings.responseStyle": "Tone and style",
    "settings.useMarkdown": "Use Markdown",
    "settings.askQuestions": "Ask clarifying questions",
    "settings.languageAuto": "Match the user's language",
    "settings.languageTh": "Thai",
    "settings.languageEn": "English",
    "settings.providerLabel": "Provider",
    "settings.modelLabel": "Model",
    "settings.providerHint":
      "Choose the provider used for chat and set a custom endpoint for OpenAI-compatible APIs.",
    "settings.modelNotFetched": "Not fetched from API yet",
    "settings.modelCustomPlaceholder": "Type a model name",
    "settings.fallbackTitle":
      "Fallback model when the primary model is unavailable",
    "settings.fallbackEnable": "Enabled",
    "settings.fallbackNone": "No fallback",
    "settings.fallbackHint":
      "Used when the API reports the model is unavailable or rate-limited.",
    "settings.fallbackProviderAria": "Fallback provider",
    "settings.baseUrlLabel": "Base URL",
    "settings.apiKeyLabel": "API key",
    "settings.apiKeyPlaceholder": "Leave blank to keep the current key",
    "settings.customKeysTitle": "Other API keys",
    "settings.customKeysHint":
      "Store keys for other services, such as weather, on this machine. Agent tools see each key as an environment variable named after it.",
    "settings.customKeyName": "Key name",
    "settings.customKeyNamePlaceholder": "WEATHER_API_KEY",
    "settings.customKeyValue": "API key value",
    "settings.customKeyValuePlaceholder": "Paste the key here",
    "settings.customKeyAdd": "Add key",
    "settings.customKeyAdded": "Key saved",
    "settings.customKeyAddFailed": "Could not save the key",
    "settings.customKeyDelete": "Delete",
    "settings.customKeyDeleteAria": "Delete key {name}",
    "settings.customKeyDeleted": "Key deleted",
    "settings.customKeySaved": "Saved on this machine",
    "settings.customKeysEmpty": "No other keys saved yet",
    "settings.customKeyNameRequired": "Enter a key name and value before saving",
    "settings.memoryReview": "Memory review",
    "settings.memoryReviewPlaceholder": "Define what the agent should review before answering",
    "settings.memoryReviewHint": "This guidance is sent to the agent on every response to preserve context and reduce errors.",
    "settings.skills": "Skills used by the agent",
    "settings.skillsHint": "Select multiple skills. Their content will guide the agent.",
    "settings.newSkillName": "New skill name",
    "settings.newSkillDescription": "Skill description",
    "settings.newSkillDescriptionHint":
      "Saved as the frontmatter description so the agent can pick the right skill.",
    "settings.newSkillDescriptionPlaceholder":
      "Say when to use this skill, e.g. review code before merge",
    "settings.newSkillDescriptionRequired":
      "Add a skill description before creating it so the agent picks the right skill.",
    "settings.newSkillContent": "Skill content",
    "settings.newSkillNamePlaceholder": "e.g. code-review",
    "settings.newSkillContentPlaceholder": "Describe how the skill should work",
    "settings.createSkill": "Create skill",
    "settings.createSkillDone": "Skill created",
    "settings.createSkillFailed": "Could not create skill",
    "settings.updateSkill": "Save changes",
    "settings.deleteSkill": "Delete skill",
    "settings.deleteSkillConfirm": "Delete this skill permanently?",
    "settings.skillSaved": "Skill saved",
    "settings.skillDeleted": "Skill deleted",
    "settings.systemPromptLabel": "System prompt",
    "settings.thinkingLevel": "Thinking level",
    "settings.temperatureLabel": "Temperature",
    "settings.temperatureHint": "Lower values make answers steadier; higher values make them more varied.",
    "settings.topPLabel": "Top P",
    "settings.topPHint": "Select from the smallest high-probability token group whose total probability reaches this value.",
    "settings.maxTokensLabel": "Max output tokens",
    "settings.thinkingOff": "Off",
    "settings.thinkingLow": "Low",
    "settings.thinkingMedium": "Medium",
    "settings.thinkingHigh": "High",
    "settings.stream": "Enable streaming responses (preview)",
    "settings.discordTitle": "Discord bot",
    "settings.discordHint": "Let the bot receive Discord messages and answer with the app's main provider/model.",
    "settings.discordEnable": "Enable Discord bot",
    "settings.discordToken": "Bot token",
    "settings.discordTokenPlaceholder": "Leave blank to keep the current token",
    "settings.discordTokenHintHas": "A token is saved — leave blank to keep it",
    "settings.discordTokenHintMissing": "No token yet — enter a token from the Discord Developer Portal",
    "settings.discordPrefix": "Prefix",
    "settings.discordAllowedChannels": "Allowed channels (Channel ID)",
    "settings.discordAllowedChannelsPlaceholder": "e.g. 123456789012345678, 987654321098765432",
    "settings.discordAllowedChannelsHint": "Leave blank to reply in every channel. Separate Channel IDs with commas (a DM uses the DM's Channel ID).",
    "settings.discordAllowedUsers": "Allowed users (User ID)",
    "settings.discordAllowedUsersPlaceholder": "e.g. 123456789012345678, 987654321098765432",
    "settings.discordAllowedUsersHint": "Leave blank to allow everyone in the allowed channels. Separate User IDs with commas (enable Developer Mode, then right-click a user > Copy ID).",
    "settings.machineTitle": "Machine access",
    "settings.machineHint":
      "Let agents reach every path on this machine and run commands through a real shell (including sudo when the user running the app is allowed to). Every tool call asks for approval in the chat first.",
    "settings.machineEnable": "Let agents reach the whole machine (approval every time)",
    "auth.title": "Security and device pairing",
    "auth.hint":
      "This web app requires a paired device. Generate a Pairing Key on the server and enter it on the client's /pair page. Each key is single-use and expires.",
    "auth.generate": "Generate Pairing Key",
    "auth.keyCreated": "Pairing Key created — enter it on the other device now",
    "auth.keyFailed": "Could not create a Pairing Key",
    "auth.keyGenerated": "New Pairing Key (single use)",
    "auth.keyExpiry": "Valid until {time} (about {minutes} minutes)",
    "auth.devices": "Connected devices",
    "auth.deviceFallback": "Unnamed device",
    "auth.lastSeen": "Last seen {time}",
    "auth.unknownTime": "unknown time",
    "auth.thisDevice": "This device",
    "auth.logout": "Sign out this device",
    "auth.revoke": "Revoke",
    "auth.revoked": "Device revoked",
    "auth.revokeFailed": "Could not revoke the device",
    "auth.empty": "No paired devices yet",
    "auth.disabled":
      "Web auth is off (AI_WEB_AUTH=off) — no pairing required",
    "auth.offline": "Could not load device status",
    "auth.logoutFailed": "Could not sign out. Please try again.",
    "settings.save": "Save settings",
    "settings.loadFailed": "Could not load settings: {error}",
    "settings.test": "Test connection",
    "settings.reset": "Reset",
    "schedule.title": "Scheduled jobs (Cron)",
    "schedule.hint":
      "Schedule prompts for the AI to run repeatedly. Jobs run while the server is up.",
    "schedule.loading": "Loading...",
    "schedule.timezoneLabel": "Timezone:",
    "schedule.cronSummary": "How to configure Cron jobs",
    "schedule.cronFieldsText": "The format has 5 fields:",
    "schedule.cronFieldsCode": "minute hour day month weekday",
    "schedule.cronEvery": "= every value",
    "schedule.cronStep": "= every 5 units",
    "schedule.cronRange": "= range",
    "schedule.cronList": "= list",
    "schedule.cronExamplesText": "Examples:",
    "schedule.cronEvery5": "every 5 minutes",
    "schedule.cronWeekdays": "Monday-Friday 09:00",
    "schedule.cronMidnight": "every day at midnight",
    "schedule.cronNote":
      "Jobs use the selected model and save results to conversation history. Jobs that run system commands are not executed automatically.",
    "schedule.namePlaceholder": "Job name, e.g. Daily news summary",
    "schedule.presetTitle": "Time presets",
    "schedule.presetPlaceholder":
      "Choose a preset or type your own below",
    "schedule.every5": "Every 5 minutes",
    "schedule.hourly": "Every hour",
    "schedule.weekdays9": "Weekdays at 09:00",
    "schedule.dailyMidnight": "Daily at 00:00",
    "schedule.expressionPlaceholder": "Cron, e.g. 0 9 * * 1-5",
    "schedule.modelTitle": "Model for jobs",
    "schedule.useMainModel": "Use the main model from Settings",
    "schedule.discordChannelPlaceholder": "Discord Channel ID (optional)",
    "schedule.discordChannelTitle": "Discord channel ID",
    "schedule.promptPlaceholder": "Prompt for the AI to run",
    "schedule.enableNow": "Enable immediately",
    "schedule.add": "Add scheduled job",
    "schedule.saveEdit": "Save changes",
    "schedule.cancelEdit": "Cancel edit",
    "schedule.empty": "No scheduled jobs yet",
    "schedule.timezoneFallback": "Server timezone",
    "schedule.modelLabel": "Model: {model}",
    "schedule.discordChannel": "Send results to Discord channel: {id}",
    "schedule.enabled": "Enabled",
    "schedule.disabled": "Disabled",
    "schedule.neverRun": "Never run",
    "schedule.success": "Success",
    "schedule.failed": "Failed",
    "schedule.retryAt": "Retry at {time}",
    "schedule.toggleEnable": "Enable",
    "schedule.toggleDisable": "Disable",
    "schedule.added": "Scheduled job added",
    "schedule.addFailed": "Could not add the scheduled job",
    "schedule.loadFailed": "Could not load scheduled jobs: {error}",
    "schedule.runNow": "Run now",
    "schedule.started": "Job started",
    "schedule.edit": "Edit",
    "schedule.editing": "Editing scheduled job",
    "schedule.updated": "Scheduled job updated",
    "schedule.editCancelled": "Edit cancelled",
    "logs.title": "System logs",
    "logs.system": "System logs",
    "logs.agent": "Agent logs",
    "logs.filterAria": "Log type",
    "logs.hint":
      "Review recent AI and tool activity without exposing API keys or file contents.",
    "logs.saveFile": "Save file",
    "logs.delete": "Delete logs",
    "logs.deleteConfirm": "Delete all logs permanently?",
    "logs.deleteFailed": "Delete failed",
    "logs.refresh": "Refresh",
    "logs.loading": "Loading...",
    "logs.empty": "No logs yet",
    "logs.loadError": "Could not load logs: {message}",
    "logs.saveFailed": "Save failed",
    "about.title": "About",
    "about.text1":
      "A self-hosted AI chat app running on Termux, with a settings page for provider, model, endpoint, prompt, and response parameters.",
    "about.text2":
      "API keys are stored only on the server in a settings file that is not committed to Git.",
    "page.settings": "Settings",
    "page.schedule": "Scheduled jobs",
    "page.logs": "System logs",
    "page.about": "About",
    "usage.duration": "{duration}s",
    "usage.unknownDuration": "unknown duration",
    "usage.unknownTokens": "unknown tokens",
    "usage.summary": "Took {duration} · {tokens}",
    "usage.tokens": "{count} tokens",
    "tool.approve": "Approve {name}",
    "tool.contentLabel": "Content:",
    "tool.working": "Working...",
    "tool.done": "Done",
    "tool.error": "The tool could not run",
    "tool.expired": "Approval expired. Please send a new message.",
    "tool.failedAfterApproval":
      "The tool failed: {message} (this approval was already used, please send a new message)",
    "tool.retry": "Try again ({message})",
    "tool.resultPrefix": "Tool result:",
    "tool.resultChip": "Used {name}",
    "tool.resultChipUnknown": "an agent tool",
    "tool.resultDetails": "Show the tool output",
    "attachment.tooLarge": "File is larger than 1 MB",
    "attachment.binaryTooLarge": "File is larger than 6 MB",
    "attachment.readFailed": "Could not read the file",
    "attachment.unsupported": "This file type is not supported",
    "attachment.providerUnsupported":
      "{name} ({mime}) cannot be sent to this provider — audio and video files work with Gemini, and PDF files work with Gemini or Anthropic",
    "attachment.clear": "Remove attachment",
    "common.close": "Close",
    "gemini.title": "Gemini key capabilities",
    "gemini.hint": "One Gemini API key can cover several feature groups; the app checks the saved key",
    "gemini.refresh": "Check again",
    "gemini.notChecked": "Run a check to see what this key supports",
    "gemini.checking": "Checking...",
    "gemini.liveModel": "Live API model",
    "gemini.defaultModel": "Use the automatic default",
    "gemini.agent": "Managed agent",
    "gemini.decisionModel": "Decisions API model",
    "gemini.openTools": "Gemini tools",
    "gemini.toolsTitle": "Gemini tools",
    "gemini.toolsHint": "Live API, Decisions API and Managed agents share the same Gemini key",
    "gemini.liveTitle": "Live API (real-time voice)",
    "gemini.liveHint": "Allow the microphone and press start; the server mints a short-lived token so the API key never reaches the browser",
    "gemini.liveStart": "Start voice chat",
    "gemini.liveStop": "Stop voice chat",
    "gemini.liveStarting": "Connecting...",
    "gemini.liveListening": "Listening — start speaking",
    "gemini.liveStopped": "Stopped",
    "gemini.liveError": "Could not connect to the Live API",
    "gemini.liveUnsupported": "This browser has no microphone or WebSocket support",
    "gemini.liveYou": "You",
    "gemini.liveAgent": "Gemini",
    "gemini.decisionsTitle": "Decisions API",
    "gemini.decisionsHint": "Evaluate several questions against one input: noul (true/false), choice and score",
    "gemini.decisionsInput": "Input",
    "gemini.decisionsQuestions": "Questions (JSON)",
    "gemini.runDecisions": "Evaluate questions",
    "gemini.agentsTitle": "Managed agents",
    "gemini.agentsHint": "Send a task to a Gemini-managed agent in its sandbox and get the result back",
    "gemini.agentLabel": "Agent",
    "gemini.agentPrompt": "Task",
    "gemini.runAgent": "Send task to the agent",
    "gemini.running": "Working...",
    "gemini.noResult": "(no text response)",
    "gemini.notConfigured": "No Gemini API key is configured",
    "gemini.badQuestions": "Questions must be valid JSON",
    "gemini.loadFailed": "Could not check the key",
    "gemini.ready": "Ready",
    "gemini.unverified": "Unverified",
    "gemini.unavailable": "Not found",
    "gemini.group.multimodal": "Multi-modal generative models",
    "gemini.group.live": "Live API",
    "gemini.group.decisions": "Decisions API",
    "gemini.group.agents": "Agents",
    "gemini.group.other": "Other",
    "gemini.agentIds": "Interaction: {interaction} · Environment: {environment}",
    "model.custom": "Custom...",
    "model.fetching": "Fetching from API...",
    "model.fetched": "Fetched {count} models from the API",
    "model.fallback": "API unavailable — using the fallback list",
    "model.fetchError": "Could not fetch the model list",
    "model.none": "No model selected",
    "chatModel.notConnected": "Not connected",
    "status.ready": "● Ready",
    "status.notReady": "● Not ready",
    "status.connectedTitle": "Connected to {model}",
    "status.notConnectedReason": "Cannot connect to the provider yet",
    "status.inputDisabled":
      "Add an API key and choose a model in Settings first",
    "status.checkFailed": "Could not check the connection status",
    "status.settingsLoadFailed": "Could not load settings",
    "apiKey.hasPlaceholder":
      "A {provider} key is already saved — leave blank to keep it",
    "apiKey.missingPlaceholder":
      "No {provider} key yet — enter an API key",
    "apiKey.hasHint": "A {provider} key is saved",
    "apiKey.missingHint":
      "No {provider} key yet — leaving it blank keeps the app not ready",
    "notice.settingsSaved": "Settings saved",
    "notice.settingsSaveFailed": "Could not save",
    "notice.testing": "Testing...",
    "notice.testSuccess": "Connection successful: {answer}",
    "notice.testFailed": "Connection failed: {error}",
    "notice.resetConfirm": "Reset all settings?",
    "notice.resetDone": "Settings reset",
    "history.untitled": "Untitled conversation",
    "history.rename": "Rename",
    "history.pin": "Pin",
    "history.unpin": "Unpin",
    "history.lock": "Lock",
    "history.unlock": "Unlock",
    "history.delete": "Delete",
    "history.pinned": "Pinned",
    "history.empty": "No history yet",
    "history.loadFailed": "Could not load history: {error}",
    "history.unknownDate": "Unknown date",
    "history.deleteTitle": "Delete conversation",
    "history.deleteConfirm":
      "This conversation will be deleted from this device and cannot be recovered.",
    "history.renameDescription": "Set a new name for this conversation.",
    "history.actionFailed": "Action failed",
    "history.renameFailed": "Could not update the conversation",
    "history.deleteFailed": "Could not delete the conversation",
    "history.startedNew": "Started a new conversation",
    "history.emptyHint": "You can start a new conversation.",
    "nav.memory": "Memory",
    "page.memory": "Memory",
    "settings.group.memory": "Memory",
    "settings.group.memoryDesc":
      "Consolidate memory in the background when the machine is idle, and promote only the topics that pass the threshold into MEMORY.md",
    "memory.settingsTitle": "Memory filter",
    "memory.settingsHint":
      "De-duplication, scoring and the promote gate all run in local code; only the semantic summary is sent to the chosen model.",
    "memory.enableLabel": "Enable automatic consolidation",
    "memory.scheduleLabel": "Start time (5-field cron)",
    "memory.scheduleHint": "Defaults to 03:00 in the server timezone",
    "memory.windowEndLabel": "Catch up until",
    "memory.windowEndHint": "If the machine is busy, wait until this time and then skip tonight",
    "memory.lookbackLabel": "Look back (days)",
    "memory.thresholdLabel": "Minimum score",
    "memory.idleLabel": "Idle for at least (minutes)",
    "memory.maxItemsLabel": "Promote at most per night",
    "memory.maxEntriesLabel": "Keep at most (entries)",
    "memory.pin": "Pin",
    "memory.unpin": "Unpin",
    "memory.pinned": "Pinned",
    "memory.retrievalLabel": "Attach relevant long-term memories to chat",
    "memory.retrievalHint":
      "Only entries whose wording overlaps the latest message, within the count and character budget below",
    "memory.retrievalItemsLabel": "Memories per message",
    "memory.retrievalCharsLabel": "Memory character budget",
    "memory.includeLockedLabel": "Include locked conversations",
    "memory.llmLabel": "Let a model help summarise (turn off to run fully offline)",
    "memory.providerLabel": "Model used for summaries",
    "memory.providerInherit": "Use the configured provider",
    "memory.modelLabel": "Model name (blank = keep the current one)",
    "memory.baseUrlLabel": "Base URL for summaries only",
    "memory.baseUrlHint":
      "Leave blank to use the chat Base URL. Set it to keep chat on a cloud provider while summaries run locally.",
    "memory.localModelHint":
      "Run free on the machine through Ollama or llama-server on http://127.0.0.1 (with 1.8 GB RAM only a small model fits)",
    "memory.saveHint": "These values are saved with the “Save settings” button below.",
    "memory.title": "Long-term memory",
    "memory.hint":
      "The engine distils daily notes and chat history into long-term memory while the machine is idle, and writes only the topics that pass the threshold into MEMORY.md",
    "memory.runNow": "Run now",
    "memory.dryRun": "Preview (no promotion)",
    "memory.reindex": "Reset index",
    "memory.promotedTitle": "What is remembered",
    "memory.promotedHint": "Each entry comes from MEMORY.md and is removed from both storage tiers",
    "memory.dreamsTitle": "DREAMS.md",
    "memory.dreamsHint": "The nightly summary of what was picked and what was skipped",
    "memory.loading": "Loading...",
    "memory.empty": "Nothing has passed the threshold yet — run tonight or lower the score",
    "memory.noDreams": "No nightly notes yet",
    "memory.running": "Working...",
    "memory.forget": "Forget",
    "memory.forgetConfirm": "Click again to delete",
    "memory.score": "Score",
    "memory.enabled": "On",
    "memory.disabled": "Off",
    "memory.schedule": "Schedule",
    "memory.threshold": "Threshold",
    "memory.idle": "Idle",
    "memory.messages": "Messages",
    "memory.conversations": "Conversations",
    "memory.promoted": "Memories",
    "memory.index": "Index",
    "memory.lastRunLine": "Last run: {time} · {status}",
    "memory.lastRunPromoted": "promoted {count}",
    "memory.neverRun": "Never run",
    "memory.idleMinutes": "{minutes} min",
    "memory.statusOk": "Succeeded",
    "memory.statusDegraded": "Succeeded (model error)",
    "memory.statusFailed": "Failed",
    "memory.runDone": "Done: promoted {count} items from {messages} new messages",
    "memory.dryRunDone": "Preview finished: {count} items would be promoted (nothing promoted)",
    "memory.reindexed": "Index reset — the next consolidation run rebuilds it from history",
    "memory.error": "Memory engine error: {error}",
    "memory.capability":
      "SQLite {version} · FTS5 {fts} · vector {vector} · embedding {embedding}",
    "memory.paths": "MEMORY.md: {memory} · DREAMS.md: {dreams} · DB: {db}",
    "memory.llmOn": "Model summaries on",
    "memory.llmOff": "Fully offline",
  },
};
function getSavedLanguage() {
  const saved = localStorage.getItem(LANGUAGE_STORAGE_KEY);
  return SUPPORTED_LANGUAGES.includes(saved) ? saved : "en";
}
let currentLanguage = getSavedLanguage();
// Tell the server which interface language an API error should be reported in.
const nativeFetch = window.fetch.bind(window);
window.fetch = (input, init) => {
  const url =
    typeof input === "string"
      ? input
      : input instanceof Request
        ? input.url
        : "";
  if (!url.includes("/api/")) return nativeFetch(input, init);
  const options = { ...(init || {}) };
  const headers = new Headers(options.headers || (input instanceof Request ? input.headers : {}));
  headers.set("X-Interface-Language", currentLanguage);
  options.headers = headers;
  return nativeFetch(input, options);
};
function t(key, vars = {}) {
  const dictionary = I18N[currentLanguage] || I18N.en;
  const template = dictionary[key] ?? I18N.en[key] ?? key;
  return String(template).replace(/\{(\w+)\}/g, (match, name) =>
    vars[name] === undefined || vars[name] === null
      ? match
      : String(vars[name]),
  );
}
const savedTheme = localStorage.getItem("ai-control-center-theme");
if (savedTheme === "light") document.body.classList.add("light-theme");
$("theme-toggle").addEventListener("click", () => {
  const light = document.body.classList.toggle("light-theme");
  localStorage.setItem(
    "ai-control-center-theme",
    light ? "light" : "dark",
  );
});
const messages = [];
const PROVIDER_LABELS_WEB = {
  openai: "OpenAI / OpenAI-compatible",
  gemini: "Google Gemini",
  anthropic: "Anthropic Claude",
  hf: "Hugging Face",
  or: "OpenRouter",
  groq: "Groq",
};
const SLASH_COMMANDS = [
  { name: "help", usage: "/help", descKey: "slash.helpDesc" },
  { name: "new", usage: "/new", descKey: "slash.newDesc" },
  { name: "clear", usage: "/clear", descKey: "slash.clearDesc" },
  { name: "model", usage: "/model", descKey: "slash.modelDesc" },
  {
    name: "models",
    usage: "/models [provider] [model]",
    descKey: "slash.modelsDesc",
  },
  { name: "status", usage: "/status", descKey: "slash.statusDesc" },
  { name: "ping", usage: "/ping", descKey: "slash.pingDesc" },
  {
    name: "fallback",
    usage: "/fallback [model|off]",
    descKey: "slash.fallbackDesc",
  },
  {
    name: "skill",
    usage: "/skill <name> [prompt]",
    descKey: "slash.skillDesc",
  },
  { name: "skills", usage: "/skills", descKey: "slash.skillsDesc" },
];
let defaultSkills = [];
let availableSkills = [];
let pendingSkill = null;
// Set right before submitting an approved tool result, so the saved turn can be
// marked as machine output instead of guessing from its first words.
let pendingToolResult = null;
let chatBusy = false;
let chatSessionToken = 0;
let slashMatches = [];
let slashIndex = 0;
let keyProviders = [];
let hasDiscordToken = false;
let conversationId = null;
let conversationCreatedAt = null;
let conversationTitle = null;
let persistedMessageCount = 0;
let historyLoadToken = 0;
let conversationGeneration = null;
const pendingHistoryAppends = new Map();
let pendingAppendFlush = null;
let failedSend = null; // { message, skills }
let pendingAttachment = null;
// Gemini feature state: the capability report drives the Settings card, and the
// live session state drives the Live API panel.
const geminiSettings = { liveModel: "", agent: "", decisionModel: "" };
let geminiCapabilityReport = null;
let geminiCapabilityLoading = false;
let geminiCapabilityRequest = 0;
const liveState = {
  ws: null,
  mic: null,
  micCtx: null,
  node: null,
  outCtx: null,
  playAt: 0,
  inputLine: null,
  outputLine: null,
  // The reserved attempt covers the token request and the permission prompt,
  // so Stop can cancel a session that does not own a socket yet.
  attempt: null,
  // Translated phase (starting/listening/idle) kept apart from the socket.
  phase: "idle",
  sources: [],
};
let typingIndicator = null;
let typingTicker = null;
let connectionState = {
  connected: false,
  model: "",
  reason: "",
  known: false,
};
let currentHistoryItems = [];
let currentSchedules = [];
let currentScheduleTimezone = "";
// The job list carries a retry time that changes without user input, so it is
// refreshed while the view is open. Only a changed payload repaints it, which
// keeps the list from flashing and leaves the edit form untouched.
let scheduleListSignature = "";
let scheduleLoadInFlight = false;
let scheduleRefreshTimer = null;
const SCHEDULE_REFRESH_MS = 20000;
let currentLogs = [];
let logsFilter = "system";
const agentLogPrefixes = ["chat.", "tool.", "provider."];
let logsLoaded = false;
let logsError = "";
let emptyConversationMode = "ready";
let modelStatus = { key: "settings.modelNotFetched", vars: {}, title: "" };
let currentChatModels = [];
let currentChatSelected = "";
let currentScheduleModels = [];
let currentScheduleSelected = "";
let currentScheduleEditingId = "";
let currentFallbackModels = [];
let currentFallbackSelected = "";
function setModelStatus(key, vars = {}, title = "") {
  modelStatus = { key, vars, title };
  $("model_status").textContent = t(key, vars);
  $("model_status").title = title;
}
function activeView() {
  return (
    document.querySelector("nav button.active")?.dataset.view || "chat"
  );
}
function updatePageTitle() {
  const view = activeView();
  $("page-title").textContent =
    view === "chat"
      ? conversationTitle || t("chat.title")
      : t(`page.${view}`);
}
function normalizeConversationTitle(title) {
  return (
    String(title || "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 80) || null
  );
}
function setConversationTitle(title) {
  conversationTitle = normalizeConversationTitle(title);
  updatePageTitle();
}
function addCommandResult(text, error = false) {
  const el = document.createElement("div");
  el.className = `message assistant command-result${error ? " error" : ""}`;
  const label = document.createElement("span");
  label.className = "command-result-label";
  label.textContent = error ? t("slash.error") : t("slash.commandLabel");
  const body = document.createElement("div");
  body.textContent = text;
  el.append(label, body);
  $("messages").appendChild(el);
  $("messages").scrollTop = $("messages").scrollHeight;
}
function activeSkills(extra = null) {
  const list = [...defaultSkills];
  if (pendingSkill) list.push(pendingSkill);
  if (extra) list.push(extra);
  return [...new Set(list.filter(Boolean))];
}
function updateSkillChip() {
  const chip = $("skill-chip");
  chip.textContent = pendingSkill ? `🧩 ${pendingSkill} ×` : "";
  chip.hidden = !pendingSkill;
}
function setPendingSkill(name) {
  pendingSkill = name;
  updateSkillChip();
}
function clearPendingSkill() {
  pendingSkill = null;
  updateSkillChip();
}
function slashCatalog() {
  return SLASH_COMMANDS.concat(
    availableSkills.map((name) => ({
      name,
      usage: `/${name}`,
      descKey: "slash.skillItemDesc",
      isSkill: true,
    })),
  );
}
function hideSlashMenu() {
  $("slash-menu").hidden = true;
  $("slash-menu").innerHTML = "";
  slashMatches = [];
  slashIndex = 0;
}
function renderSlashMenu() {
  const menu = $("slash-menu");
  menu.innerHTML = "";
  slashMatches.forEach((item, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `slash-item${index === slashIndex ? " active" : ""}`;
    button.dataset.slashIndex = String(index);
    button.setAttribute("role", "option");
    button.setAttribute(
      "aria-selected",
      index === slashIndex ? "true" : "false",
    );
    const code = document.createElement("code");
    code.textContent = item.usage || `/${item.name}`;
    const description = document.createElement("small");
    description.textContent = t(item.descKey);
    button.append(code, description);
    menu.appendChild(button);
  });
  menu.hidden = false;
}
function updateSlashMenu() {
  const value = $("input").value;
  if (!value.startsWith("/") || /\s/.test(value.slice(1))) {
    hideSlashMenu();
    return;
  }
  const query = value.slice(1).toLowerCase();
  slashMatches = slashCatalog()
    .filter((item) => item.name.toLowerCase().startsWith(query))
    .slice(0, 8);
  if (!slashMatches.length) {
    hideSlashMenu();
    return;
  }
  if (slashIndex >= slashMatches.length) slashIndex = 0;
  renderSlashMenu();
}
function applySlashSuggestion(index = slashIndex) {
  const item = slashMatches[index];
  if (!item) return;
  $("input").value = `/${item.name} `;
  resizeInput();
  hideSlashMenu();
  updateSendState();
  $("input").focus();
}
function moveSlashSelection(delta) {
  if (!slashMatches.length) return;
  slashIndex =
    (slashIndex + delta + slashMatches.length) % slashMatches.length;
  renderSlashMenu();
}
async function fetchSettings() {
  const response = await fetch("/api/settings");
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}
function showSlashHelp() {
  const lines = SLASH_COMMANDS.map(
    (item) => `${item.usage} — ${t(item.descKey)}`,
  );
  if (availableSkills.length) {
    lines.push(
      "",
      t("slash.skillsTitle"),
      ...availableSkills.map((name) => `  /${name}`),
    );
  }
  addCommandResult(
    `${t("slash.helpTitle")}\n${t("slash.helpHint")}\n\n${lines.join("\n")}`,
  );
}
async function applySkillCommand(name, prompt) {
  if (!availableSkills.includes(name)) {
    addCommandResult(t("slash.skillMissing", { name }), true);
    return { handled: true };
  }
  if (prompt) {
    return {
      send: true,
      prompt,
      skills: activeSkills(name),
      skill: name,
    };
  }
  setPendingSkill(name);
  addCommandResult(t("slash.skillActivated", { name }));
  return { handled: true };
}
async function runSlashCommand(raw) {
  const body = raw.trim().slice(1).trim();
  const match = body.match(/^(\S+)(?:\s+([\s\S]*))?$/);
  const name = (match?.[1] || "").toLowerCase();
  const rest = (match?.[2] || "").trim();
  if (!name) {
    showSlashHelp();
    return { handled: true };
  }
  let skillName = availableSkills.includes(name)
    ? name
    : availableSkills.find((s) => s.toLowerCase() === name);
  if (skillName) {
    return applySkillCommand(skillName, rest);
  }
  switch (name) {
    case "help":
      showSlashHelp();
      return { handled: true };
    case "new":
    case "clear":
      startNewChat("new");
      addCommandResult(
        t(name === "new" ? "slash.newDone" : "slash.clearDone"),
      );
      return { handled: true };
    case "model":
    case "status": {
      const data = await refreshConnectionState();
      if (!data) {
        addCommandResult(
          t("status.checkFailed"),
          true,
        );
        return { handled: true };
      }
      const state = data.ready
        ? t("slash.statusOn")
        : t("slash.statusOff", {
            reason: data.reason || t("status.notConnectedReason"),
          });
      addCommandResult(
        t("slash.modelInfo", {
          provider:
            PROVIDER_LABELS_WEB[data.provider] || data.provider || "-",
          model: data.model || t("model.none"),
          status: state,
        }),
      );
      return { handled: true };
    }
    case "models": {
      let provider = connectionState.provider || "openai";
      const parts = rest.split(/\s+/).filter(Boolean);
      let model = "";
      if (parts.length) {
        const candidate = parts[0].toLowerCase();
        if (PROVIDER_LABELS_WEB[candidate]) {
          provider = candidate;
          model = parts.slice(1).join(" ");
        } else {
          model = parts.join(" ");
        }
      }
      if (model) {
        try {
          const body = { provider, model };
          if (
            connectionState.provider &&
            provider !== connectionState.provider
          ) {
            body.base_url = "";
          }
          const response = await fetch("/api/settings", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
          const data = await response.json();
          if (!response.ok)
            throw new Error(data.error || `HTTP ${response.status}`);
          await loadChatMeta();
          addCommandResult(
            t("slash.modelSwitched", {
              provider: PROVIDER_LABELS_WEB[provider] || provider,
              model,
            }),
          );
        } catch (error) {
          addCommandResult(
            t("slash.switchFailed", { error: error.message }),
            true,
          );
        }
        return { handled: true };
      }
      try {
        const response = await fetch(
          `/api/models?provider=${encodeURIComponent(provider)}`,
        );
        const data = await response.json();
        const models = Array.isArray(data.models) ? data.models : [];
        const listing =
          models
            .slice(0, 25)
            .map((item) => `• ${item.id || item}`)
            .join("\n") || t("slash.modelsEmpty");
        const moreNotice =
          models.length > 25
            ? `\n${t("slash.modelsMore", { count: models.length })}`
            : "";
        const isFallback = !response.ok;
        const fallbackNotice = isFallback
          ? `\n${t("model.fallback")}: ${
              data.error || t("status.notConnectedReason")
            }`
          : "";
        addCommandResult(
          `${t("slash.modelsTitle", {
            provider: PROVIDER_LABELS_WEB[provider] || provider,
          })}${fallbackNotice}\n${listing}${moreNotice}`,
        );
      } catch (error) {
        addCommandResult(
          t("slash.switchFailed", { error: error.message }),
          true,
        );
      }
      return { handled: true };
    }
    case "ping": {
      const started = performance.now();
      try {
        const response = await fetch(
          `/api/status?lang=${encodeURIComponent(currentLanguage)}`,
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        await response.json();
        addCommandResult(
          t("slash.pingResult", {
            ms: Math.round(performance.now() - started),
          }),
        );
      } catch (error) {
        addCommandResult(
          t("slash.pingFailed", { error: error.message }),
          true,
        );
      }
      return { handled: true };
    }
    case "fallback": {
      try {
        const settings = await fetchSettings();
        if (!rest) {
          const state = settings.fallback_enabled
            ? `${
                PROVIDER_LABELS_WEB[settings.fallback_provider] ||
                settings.fallback_provider ||
                settings.provider
              } / ${settings.fallback_model || t("slash.fallbackNone")}`
            : t("slash.fallbackNone");
          addCommandResult(
            t("slash.fallbackInfo", {
              state,
              provider:
                PROVIDER_LABELS_WEB[settings.provider] ||
                settings.provider,
              model: settings.model || t("model.none"),
            }),
          );
          return { handled: true };
        }
        // "ปิด" is the Thai word for off and stays an alias so an existing
        // habit of typing it keeps disabling fallback instead of being saved
        // as a model ID.
        const disable = ["off", "none", "disabled", "ปิด"].includes(
          rest.toLowerCase(),
        );
        const response = await fetch("/api/settings", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(
            disable
              ? { fallback_enabled: false }
              : {
                  fallback_enabled: true,
                  fallback_provider: settings.provider,
                  fallback_model: rest,
                },
          ),
        });
        const data = await response.json();
        if (!response.ok)
          throw new Error(data.error || `HTTP ${response.status}`);
        addCommandResult(
          disable
            ? t("slash.fallbackOff")
            : t("slash.fallbackSet", { model: rest }),
        );
      } catch (error) {
        addCommandResult(
          t("slash.fallbackFailed", { error: error.message }),
          true,
        );
      }
      return { handled: true };
    }
    case "skills": {
      try {
        const settings = await fetchSettings();
        availableSkills = (settings.available_skills || []).map(
          (item) => item.name,
        );
        defaultSkills = Array.isArray(settings.skills)
          ? settings.skills.map(String)
          : defaultSkills;
      } catch (error) {
        /* keep the cached list */
      }
      addCommandResult(
        availableSkills.length
          ? `${t("slash.skillsTitle")}\n${availableSkills
              .map((skillName) => `• /${skillName}`)
              .join("\n")}`
          : t("slash.skillsEmpty"),
      );
      return { handled: true };
    }
    case "skill": {
      const parts = rest.split(/\s+/).filter(Boolean);
      const skillName = (parts.shift() || "").toLowerCase();
      if (!skillName) {
        addCommandResult(t("slash.skillUsage"), true);
        return { handled: true };
      }
      return applySkillCommand(skillName, parts.join(" "));
    }
    default:
      addCommandResult(t("slash.unknown", { command: name }), true);
      return { handled: true, keepInput: true };
  }
}
function invalidateChatSession() {
  chatSessionToken += 1;
  historyLoadToken += 1;
  failedSend = null;
  chatBusy = false;
  removeTypingIndicator();
  $("send").textContent = "↑";
  updateSendState();
}
function startNewChat(mode = "new") {
  invalidateChatSession();
  conversationId = null;
  conversationCreatedAt = null;
  conversationTitle = null;
  persistedMessageCount = 0;
  failedSend = null;
  messages.splice(0, messages.length);
  emptyConversationMode = mode;
  clearPendingSkill();
  renderMessages();
  updatePageTitle();
  document.querySelector('[data-view="chat"]').click();
  closeSidebar();
  $("input").focus();
}
function closeSidebar() {
  document.querySelector("aside").classList.remove("open");
  $("sidebar-backdrop").classList.remove("open");
  $("mobile-menu-toggle").setAttribute("aria-expanded", "false");
}
$("mobile-menu-toggle").addEventListener("click", () => {
  const open = document.querySelector("aside").classList.toggle("open");
  $("sidebar-backdrop").classList.toggle("open", open);
  $("mobile-menu-toggle").setAttribute("aria-expanded", String(open));
});
$("sidebar-backdrop").addEventListener("click", closeSidebar);
// Laptop-width sidebar toggle. The mobile menu button keeps handling narrow
// screens, so this state only applies above 700px.
const SIDEBAR_STORAGE_KEY = "ai-control-center-sidebar-collapsed";
const appRoot = document.querySelector(".app");
let sidebarCollapsed = localStorage.getItem(SIDEBAR_STORAGE_KEY) === "1";
function applySidebarCollapsed(collapsed) {
  appRoot.classList.toggle("sidebar-collapsed", collapsed);
  const button = $("sidebar-toggle");
  button.setAttribute("aria-expanded", String(!collapsed));
  button.textContent = collapsed ? "▤" : "◧";
}
applySidebarCollapsed(sidebarCollapsed);
$("sidebar-toggle").addEventListener("click", () => {
  sidebarCollapsed = !appRoot.classList.contains("sidebar-collapsed");
  localStorage.setItem(SIDEBAR_STORAGE_KEY, sidebarCollapsed ? "1" : "0");
  applySidebarCollapsed(sidebarCollapsed);
});
// The collapsed sidebar only shows icons, so label the control under the
// pointer (or keyboard focus) instead of relying on the delayed native title.
const RAIL_ITEM_SELECTOR = ".new-chat, nav button, .history-item";
const railTooltip = $("rail-tooltip");
let railTooltipSource = null;
let railTooltipTitle = null;
let railTooltipHideTimer = 0;
function cancelRailTooltipHide() {
  if (railTooltipHideTimer) {
    clearTimeout(railTooltipHideTimer);
    railTooltipHideTimer = 0;
  }
}
function scheduleRailTooltipHide() {
  cancelRailTooltipHide();
  // A short delay lets the pointer travel from the icon onto the tooltip
  // across the gap without the tooltip disappearing on the way.
  railTooltipHideTimer = window.setTimeout(hideRailTooltip, 160);
}
function railModeActive() {
  return (
    appRoot.classList.contains("sidebar-collapsed") &&
    window.matchMedia("(min-width: 701px)").matches
  );
}
function showRailTooltip(target) {
  if (!railTooltip || !railModeActive()) return;
  cancelRailTooltipHide();
  const label =
    target.getAttribute("aria-label") || target.getAttribute("title");
  if (!label) return;
  if (railTooltipSource !== target) {
    hideRailTooltip();
    railTooltipSource = target;
    railTooltipTitle = target.getAttribute("title");
  }
  // Keep the native title off the element while the custom tooltip shows, and
  // refresh the cached copy so a language switch restores the newest text.
  const titleAttr = target.getAttribute("title");
  if (titleAttr) {
    railTooltipTitle = titleAttr;
    target.removeAttribute("title");
  }
  railTooltip.textContent = label;
  railTooltip.hidden = false;
  const rect = target.getBoundingClientRect();
  const tip = railTooltip.getBoundingClientRect();
  const top = rect.top + rect.height / 2 - tip.height / 2;
  railTooltip.style.left = `${Math.round(rect.right + 10)}px`;
  railTooltip.style.top = `${Math.round(
    Math.max(8, Math.min(window.innerHeight - tip.height - 8, top)),
  )}px`;
}
function hideRailTooltip() {
  cancelRailTooltipHide();
  // Only restore the cached title when no newer one was set in the meantime:
  // a language switch writes the translated title onto the element first, and
  // restoring the old value would leave the stale language behind.
  if (
    railTooltipSource &&
    railTooltipTitle &&
    !railTooltipSource.hasAttribute("title")
  ) {
    railTooltipSource.setAttribute("title", railTooltipTitle);
  }
  railTooltipSource = null;
  railTooltipTitle = null;
  if (railTooltip) railTooltip.hidden = true;
}
function railItemFrom(node) {
  const item = node?.closest?.(RAIL_ITEM_SELECTOR);
  return item && !item.closest(".history-actions") ? item : null;
}
document.querySelector("aside").addEventListener("pointerover", (event) => {
  const item = railItemFrom(event.target);
  if (item) showRailTooltip(item);
});
document.querySelector("aside").addEventListener("pointerout", (event) => {
  const item = railItemFrom(event.target);
  if (!item) return;
  if (event.relatedTarget && item.contains(event.relatedTarget)) return;
  scheduleRailTooltipHide();
});
document.querySelector("aside").addEventListener("focusin", (event) => {
  const item = railItemFrom(event.target);
  if (item) showRailTooltip(item);
});
document.querySelector("aside").addEventListener("focusout", hideRailTooltip);
document
  .querySelector("aside")
  .addEventListener("pointerleave", scheduleRailTooltipHide);
if (railTooltip) {
  railTooltip.addEventListener("pointerenter", cancelRailTooltipHide);
  railTooltip.addEventListener("pointerleave", scheduleRailTooltipHide);
}
$("history-list").addEventListener("scroll", hideRailTooltip);
window.addEventListener("resize", hideRailTooltip);
$("sidebar-toggle").addEventListener("click", hideRailTooltip);
// Escape dismisses the tooltip without moving focus or the pointer.
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") hideRailTooltip();
});
function formatUsage(durationMs, usage) {
  const duration = Number.isFinite(Number(durationMs))
    ? t("usage.duration", {
        duration: (Number(durationMs) / 1000).toFixed(2),
      })
    : t("usage.unknownDuration");
  const tokens =
    usage?.total_tokens != null
      ? t("usage.tokens", {
          count: usage.total_tokens.toLocaleString(),
        })
      : t("usage.unknownTokens");
  return t("usage.summary", { duration, tokens });
}
// Approval tokens expire on the server's clock, so freshness is never measured
// against the browser clock. Every payload that carries an expiry also carries
// the server's own `server_time`; the client turns that pair into a local
// deadline once and compares against the deadline from then on.
function stampApprovalDeadline(meta, serverTimeSeconds) {
  if (!meta || typeof meta !== "object") return;
  const expiresAt = Number(meta.approval_expires_at || 0);
  const serverNow = Number(serverTimeSeconds || 0);
  if (!expiresAt || !serverNow) {
    delete meta.approval_deadline;
    return;
  }
  meta.approval_deadline =
    Date.now() + Math.max(0, (expiresAt - serverNow) * 1000);
}
function isApprovalExpired(meta) {
  const deadline = Number(meta?.approval_deadline || 0);
  return deadline > 0 && deadline <= Date.now();
}
function scheduleApprovalExpiry(meta, button) {
  const deadline = Number(meta?.approval_deadline || 0);
  const remaining = deadline - Date.now();
  if (!(remaining > 0)) return;
  // The chat can sit open past the deadline, so close the control then instead
  // of waiting for a click the server would reject.
  window.setTimeout(() => {
    // Skip when the approval was consumed or the button was replaced before
    // the timer fired.
    if (!meta.approval_id || !button.isConnected || button.messageMeta !== meta) {
      return;
    }
    button.disabled = true;
    button.textContent = t("tool.expired");
  }, remaining);
}
function renderedApprovalButton(meta) {
  const id = meta?.message_id;
  if (!id) return null;
  return (
    Array.from(document.querySelectorAll("#messages .tool-approval")).find(
      (candidate) => candidate.dataset.messageId === id,
    ) || null
  );
}
function clearApprovalState(meta, conversationIdForSave = null) {
  if (!meta) return;
  const messageId = meta.message_id;
  const hadApproval = Boolean(meta.approval_id || meta.tool_request);
  delete meta.approval_running;
  meta.approval_id = "";
  meta.tool_request = null;
  delete meta.approval_expires_at;
  delete meta.approval_deadline;
  if (hadApproval && conversationIdForSave && messageId) {
    clearStoredApproval(conversationIdForSave, messageId);
  }
}
async function clearStoredApproval(id, messageId) {
  try {
    await fetch(`/api/history/${encodeURIComponent(id)}/approvals/clear`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message_id: messageId }),
    });
  } catch (error) {
    // Best effort: the token is single-use on the server anyway, so a failed
    // cleanup only leaves a button that answers 403.
  }
}
function addMessage(role, content, meta = null, messageIndex = null) {
  const el = document.createElement("div");
  el.className = `message ${role}`;
  const text = document.createElement("div");
  text.className = "message-text";
  text.textContent = content;
  if (role === "user" && meta?.tool_result) {
    // An approved tool result is context for the model, not a prompt the user
    // typed: show a short card instead of a wall of JSON.
    text.classList.add("message-tool");
    text.textContent = t("tool.resultChip", {
      name: meta.tool_name || t("tool.resultChipUnknown"),
    });
  }
  el.appendChild(text);
  if (role === "user" && meta?.tool_result) {
    const details = document.createElement("details");
    details.className = "message-tool-detail";
    const summary = document.createElement("summary");
    summary.textContent = t("tool.resultDetails");
    const output = document.createElement("pre");
    output.textContent = content;
    details.append(summary, output);
    el.appendChild(details);
  }
  if (role === "user" && meta?.attachment?.name) {
    const attachment = document.createElement("small");
    attachment.className = "message-attachment";
    attachment.textContent = `📎 ${meta.attachment.name}`;
    el.appendChild(attachment);
  }
  if (role === "user" && meta?.skill) {
    const skill = document.createElement("small");
    skill.className = "message-attachment";
    skill.textContent = `🧩 ${meta.skill}`;
    el.appendChild(skill);
  }
  const approvalRunning = Boolean(meta?.approval_running);
  if (
    role === "assistant" &&
    meta?.tool_request &&
    meta?.approval_id &&
    !isApprovalExpired(meta)
  ) {
    const approval = document.createElement("button");
    approval.type = "button";
    approval.className = "tool-approval";
    approval.textContent = approvalRunning
      ? t("tool.working")
      : t("tool.approve", {
          name: meta.tool_request.name,
        });
    approval.disabled = approvalRunning;
    approval.toolRequest = meta.tool_request;
    approval.approvalId = meta.approval_id;
    approval.messageMeta = meta;
    if (meta.message_id) approval.dataset.messageId = meta.message_id;
    approval.addEventListener("click", approveToolRequest);
    if (!approvalRunning) scheduleApprovalExpiry(meta, approval);
    el.appendChild(approval);
    const args = meta.tool_request.arguments || {};
    const summary = args.command || args.path || "";
    if (summary || args.content) {
      const detail = document.createElement("small");
      detail.className = "tool-approval-detail";
      const content = String(args.content || "");
      const preview = content
        ? `${t("tool.contentLabel")}\n${content.slice(0, 500)}${content.length > 500 ? "…" : ""}`
        : "";
      detail.textContent = [summary, preview].filter(Boolean).join("\n");
      el.appendChild(detail);
    }
  }
  if (role === "assistant" && meta) {
    const details = document.createElement("small");
    details.className = "message-meta";
    details.textContent = `${formatUsage(meta.duration_ms, meta.usage)}${meta.fallback_used ? t("chat.fallbackUsed", { model: meta.fallback_used }) : ""}`;
    el.appendChild(details);
  }
  if (role === "user" || role === "assistant") {
    const actions = document.createElement("div");
    actions.className = "message-actions";
    const copyButton = document.createElement("button");
    copyButton.type = "button";
    copyButton.className = "message-action";
    const copyLabel = t(
      role === "user" ? "message.copyPrompt" : "message.copyAnswer",
    );
    copyButton.setAttribute("aria-label", copyLabel);
    copyButton.title = copyLabel;
    copyButton.innerHTML = ICONS.copy;
    copyButton.addEventListener("click", () => copyMessageText(content));
    actions.appendChild(copyButton);
    if (role === "user" && Number.isInteger(messageIndex)) {
      const editButton = document.createElement("button");
      editButton.type = "button";
      editButton.className = "message-action";
      const editLabel = t("message.editPrompt");
      editButton.setAttribute("aria-label", editLabel);
      editButton.title = editLabel;
      editButton.innerHTML = ICONS.edit;
      editButton.addEventListener("click", () =>
        openMessageEditor(messageIndex),
      );
      actions.appendChild(editButton);
    }
    el.appendChild(actions);
  }
  $("messages").appendChild(el);
  $("messages").scrollTop = $("messages").scrollHeight;
}
async function copyMessageText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      // Plain HTTP on the LAN is not a secure context, so use the legacy path.
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      const copied = document.execCommand("copy");
      area.remove();
      if (!copied) throw new Error("copy failed");
    }
    showNotice(t("message.copied"));
  } catch (error) {
    showNotice(t("message.copyFailed"), true);
  }
}
let editingMessageIndex = null;
function openMessageEditor(index) {
  const message = messages[index];
  if (!message || message.role !== "user") return;
  editingMessageIndex = index;
  $("message-modal-input").value = message.content || "";
  $("message-modal").classList.add("open");
  $("message-modal-input").focus();
  $("message-modal-input").select();
}
function closeMessageEditor() {
  $("message-modal").classList.remove("open");
  editingMessageIndex = null;
}
async function saveMessageEdit() {
  if (editingMessageIndex === null) return;
  const nextText = $("message-modal-input").value.trim();
  if (!nextText) {
    showNotice(t("message.editEmpty"), true);
    return;
  }
  if (chatBusy) {
    showNotice(t("message.editBusy"), true);
    return;
  }
  const index = editingMessageIndex;
  const prefix = messages.slice(0, index);
  const targetConversationId = conversationId;
  if (targetConversationId) {
    // Drop queued retries first so loadHistoryList() inside updateHistory()
    // cannot write the removed answers back.
    pendingHistoryAppends.delete(targetConversationId);
    try {
      await updateHistory(targetConversationId, {
        messages: prefix.map(historyMessagePayload),
      });
    } catch (error) {
      showNotice(t("message.editFailed"), true);
      return;
    }
  }
  messages.splice(0, messages.length, ...prefix);
  persistedMessageCount = prefix.length;
  failedSend = null;
  closeMessageEditor();
  renderMessages();
  // The old answer went away with the edited prompt, so ask the AI again
  // right away instead of only putting the text back in the composer.
  await sendChatMessage(nextText, null, nextText);
}
$("message-modal-cancel").addEventListener("click", closeMessageEditor);
$("message-modal-confirm").addEventListener("click", saveMessageEdit);
$("message-modal").addEventListener("click", (event) => {
  if (event.target === $("message-modal")) closeMessageEditor();
});
function addTypingIndicator() {
  removeTypingIndicator();
  const el = document.createElement("div");
  el.className = "message assistant typing-indicator";
  el.setAttribute("role", "status");
  el.setAttribute("aria-live", "polite");
  el.setAttribute("aria-label", t("chat.typingThinking"));

  const avatar = document.createElement("span");
  avatar.className = "typing-avatar";
  avatar.setAttribute("aria-hidden", "true");
  avatar.textContent = "✦";

  const dots = document.createElement("span");
  dots.className = "typing-dots";
  dots.setAttribute("aria-hidden", "true");
  for (let i = 0; i < 3; i += 1) {
    dots.appendChild(document.createElement("span"));
  }

  const label = document.createElement("span");
  label.className = "typing-label";
  label.textContent = t("chat.typingThinking");

  const elapsed = document.createElement("span");
  elapsed.className = "typing-elapsed";
  elapsed.setAttribute("aria-hidden", "true");

  el.append(avatar, dots, label, elapsed);
  $("messages").appendChild(el);
  $("messages").scrollTop = $("messages").scrollHeight;
  $("messages").setAttribute("aria-busy", "true");
  $("send").classList.add("is-loading");

  const started = performance.now();
  el.dataset.startedAt = String(started);
  const update = () => {
    const seconds = Math.round((performance.now() - started) / 1000);
    const key =
      seconds >= 25
        ? "chat.typingStillWorking"
        : seconds >= 7
          ? "chat.typingWorking"
          : "chat.typingThinking";
    if (label.dataset.key !== key) {
      label.dataset.key = key;
      label.textContent = t(key);
      el.setAttribute("aria-label", t(key));
    }
    elapsed.textContent =
      seconds >= 2 ? t("chat.typingElapsed", { seconds }) : "";
  };
  update();
  typingTicker = setInterval(update, 1000);
  typingIndicator = el;
  return el;
}
function removeTypingIndicator() {
  if (typingTicker) {
    clearInterval(typingTicker);
    typingTicker = null;
  }
  if (typingIndicator) {
    typingIndicator.remove();
    typingIndicator = null;
  }
  $("messages").removeAttribute("aria-busy");
  $("send").classList.remove("is-loading");
}
async function approveToolRequest(event) {
  const button = event.currentTarget;
  const meta = button.messageMeta;
  const targetConversationId = conversationId;
  if (isApprovalExpired(meta)) {
    // The deadline passed while the chat stayed open: never send a request the
    // server is going to reject.
    button.disabled = true;
    button.textContent = t("tool.expired");
    clearApprovalState(meta, targetConversationId);
    return;
  }
  button.disabled = true;
  button.textContent = t("tool.working");
  // Keep the in-flight state on the message: a language switch or a history
  // refresh rebuilds the button, and it must not come back enabled with a
  // token this request is already spending.
  if (meta) meta.approval_running = true;
  // The result belongs to the chat that was open when the tool finished, so
  // hold the session and conversation until then.
  const sessionToken = chatSessionToken;
  try {
    const request = button.toolRequest;
    const response = await fetch("/api/tools/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: request.name,
        arguments: request.arguments,
        approval_id: button.approvalId,
      }),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      // The server reports the real failure in detail; the generic error text
      // alone never says why (a wrong job id, a rejected command).
      const error = new Error(data.detail || data.error || t("tool.error"));
      // 403 is a rejected or already used token. A 400 is fatal too when the
      // server reports that the token was consumed before the tool failed.
      error.consumed = Boolean(data.approval_consumed);
      error.fatal = response.status === 403 || error.consumed;
      throw error;
    }
    if (meta) delete meta.approval_running;
    // The token is single-use; drop it from the message and from the saved
    // record so a re-render or a reopened conversation cannot offer it again.
    clearApprovalState(meta, targetConversationId);
    const liveButton = renderedApprovalButton(meta) || button;
    liveButton.textContent = t("tool.done");
    liveButton.disabled = true;
    if (
      sessionToken !== chatSessionToken ||
      conversationId !== targetConversationId
    ) {
      // Another chat was opened while the tool ran: leave its composer alone.
      return;
    }
    const resultText =
      `${t("tool.resultPrefix")}\n${JSON.stringify(data.result, null, 2)}`;
    if (chatBusy) {
      // Another turn is still running: keep the result in the composer so it is
      // not lost, and remember that the next send carries it.
      $("input").value = resultText;
      resizeInput();
      updateSendState();
      pendingToolResult = { name: request.name };
      return;
    }
    // Send the output directly instead of parking the raw JSON in the composer:
    // the turn becomes a compact tool card, and the server continues the task
    // from it instead of starting a new conversation.
    pendingToolResult = { name: request.name };
    await sendChatMessage(resultText);
  } catch (error) {
    if (meta) delete meta.approval_running;
    button.disabled = Boolean(error.fatal);
    // A consumed approval whose tool then failed carries the real tool error;
    // show it and ask for a new approval instead of the expired label.
    button.textContent = error.consumed
      ? t("tool.failedAfterApproval", { message: error.message })
      : error.fatal
        ? t("tool.expired")
        : t("tool.retry", { message: error.message });
    if (error.fatal) clearApprovalState(meta, targetConversationId);
  }
}
document.querySelectorAll("nav button").forEach((button) =>
  button.addEventListener("click", () => {
    document
      .querySelectorAll("nav button")
      .forEach((b) => b.classList.remove("active"));
    button.classList.add("active");
    document
      .querySelectorAll(".view")
      .forEach((v) => v.classList.remove("active"));
    $(`${button.dataset.view}-view`).classList.add("active");
    updatePageTitle();
    if (button.dataset.view === "settings") {
      loadSettings();
      loadAuthSessions();
      loadServerStatus();
    }
    if (button.dataset.view === "schedule") {
      loadSchedules();
      startScheduleRefresh();
    } else {
      stopScheduleRefresh();
    }
    if (button.dataset.view === "memory") loadMemory();
    if (button.dataset.view === "logs") loadLogs();
    closeSidebar();
  }),
);
const SETTINGS_SECTIONS = [
  "connection",
  "agent",
  "response",
  "integrations",
  "memory",
  "security",
  "update",
  "server",
  "network",
];
let activeSettingsSection = SETTINGS_SECTIONS[0];
function activateSettingsSection(section) {
  activeSettingsSection = SETTINGS_SECTIONS.includes(section)
    ? section
    : SETTINGS_SECTIONS[0];
  document.querySelectorAll("[data-settings-section]").forEach((button) => {
    const active = button.dataset.settingsSection === activeSettingsSection;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll("[data-settings-panel]").forEach((panel) => {
    panel.classList.toggle(
      "active",
      panel.dataset.settingsPanel === activeSettingsSection,
    );
  });
  // The footer Save settings button does not apply the network mode, so the
  // Web & HTTPS panel points at its own Save mode button instead.
  const footerHint = document.querySelector(".settings-footer-hint");
  if (footerHint) {
    footerHint.dataset.i18n =
      activeSettingsSection === "network"
        ? "network.saveScopeHint"
        : "settings.saveScopeHint";
    footerHint.textContent = t(footerHint.dataset.i18n);
  }
  $("settings-view").scrollTop = 0;
}
document.querySelectorAll("[data-settings-section]").forEach((button) => {
  button.addEventListener("click", () => {
    activateSettingsSection(button.dataset.settingsSection);
    // The network panel reports live server/TLS state too; loading it keeps
    // the unsaved radio selection because renderNetworkState only reselects
    // when nothing is checked.
    if (["server", "network"].includes(button.dataset.settingsSection)) {
      loadServerStatus();
    }
  });
});
function renderLogs() {
  const list = $("logs-list");
  if (logsError) {
    list.innerHTML = `<p class="hint">${escapeHtml(t("logs.loadError", { message: logsError }))}</p>`;
    return;
  }
  if (!logsLoaded) {
    list.innerHTML = `<p class="hint">${escapeHtml(t("logs.loading"))}</p>`;
    return;
  }
  const visibleLogs = logsFilter === "agent"
    ? currentLogs.filter((item) => agentLogPrefixes.some((prefix) => String(item.event || "").startsWith(prefix)))
    : currentLogs;
  if (!visibleLogs.length) {
    list.innerHTML = `<p class="hint">${escapeHtml(t("logs.empty"))}</p>`;
    return;
  }
  list.innerHTML = visibleLogs
    .slice()
    .reverse()
    .map((item) => {
      const details = Object.entries(item.details || {})
        .map(([key, value]) => `${key}: ${value}`)
        .join(" · ");
      const lineNumber = visibleLogs.length - visibleLogs.indexOf(item);
      return `<div class="log-row ${escapeHtml(item.event || "")}">
        <span class="log-number">${lineNumber}</span>
        <span class="log-command"><span class="log-prompt">$</span> <strong>${escapeHtml(item.event || "event")}</strong> <span class="log-time">${escapeHtml(item.time || "")}</span></span>
        <span class="log-message">${escapeHtml(item.message || "")}</span>
        ${details ? `<span class="log-details">${escapeHtml(details)}</span>` : ""}
      </div>`;
    })
    .join("");
}
document.querySelectorAll("[data-logs-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    logsFilter = button.dataset.logsFilter;
    document.querySelectorAll("[data-logs-filter]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    renderLogs();
  });
});
async function loadLogs() {
  logsError = "";
  if (!logsLoaded) renderLogs();
  try {
    const response = await fetch("/api/logs");
    const data = await response.json();
    currentLogs = Array.isArray(data.items) ? data.items : [];
    logsLoaded = true;
  } catch (error) {
    logsError = error.message;
  }
  renderLogs();
}
$("refresh-logs").addEventListener("click", loadLogs);
$("save-logs").addEventListener("click", async () => {
  try {
    const response = await fetch("/api/logs");
    const data = await response.json();
    const items = Array.isArray(data.items) ? data.items : currentLogs;
    const blob = new Blob([JSON.stringify(items, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `ai-web-log-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    const button = $("save-logs");
    button.textContent = t("logs.saveFailed");
    setTimeout(() => {
      button.textContent = t("logs.saveFile");
    }, 2500);
  }
});
$("delete-logs").addEventListener("click", async () => {
  if (
    !(await confirmDialog({
      title: t("common.confirmTitle"),
      text: t("logs.deleteConfirm"),
      confirmLabel: t("common.confirm"),
    }))
  )
    return;
  const button = $("delete-logs");
  button.disabled = true;
  try {
    const response = await fetch("/api/logs", { method: "DELETE" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "delete failed");
    currentLogs = [];
    logsLoaded = true;
    renderLogs();
  } catch (error) {
    button.textContent = t("logs.deleteFailed");
    setTimeout(() => {
      button.textContent = t("logs.delete");
    }, 2500);
  } finally {
    button.disabled = false;
  }
});
$("chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const content = $("input").value.trim();
  if ((!content && !pendingAttachment) || chatBusy) return;
  hideSlashMenu();
  if (content.startsWith("/") && !pendingAttachment) {
    const submittedInput = $("input").value;
    const clearSubmittedInput = () => {
      if ($("input").value !== submittedInput) return false;
      $("input").value = "";
      resizeInput();
      updateSendState();
      return true;
    };
    try {
      const result = await runSlashCommand(content);
      if (result?.send) {
        if (!connectionState.connected) {
          addCommandResult(
            t("slash.statusOff", {
              reason:
                connectionState.reason || t("status.notConnectedReason"),
            }),
            true,
          );
          return;
        }
        await sendChatMessage(result.prompt, result.skills, submittedInput);
      } else if (clearSubmittedInput()) {
        $("input").focus();
      }
    } catch (error) {
      addCommandResult(
        t("slash.switchFailed", { error: error.message }),
        true,
      );
      clearSubmittedInput();
    }
    return;
  }
  await sendChatMessage(content);
});
function resizeInput() {
  const el = $("input");
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  el.style.overflowY = "auto";
}
// Prompt recall with ArrowUp/ArrowDown, kept per chat. Each conversation has
// its own list, seeded from its saved user messages so recall still works after
// reopening it from history.
const PROMPT_HISTORY_LIMIT = 100;
const promptHistories = new Map();
let promptHistoryKey = null;
let promptHistoryOffset = 0;
let promptHistoryDraft = "";
function promptHistoryKeyForCurrentChat() {
  return conversationId ? `chat:${conversationId}` : `session:${chatSessionToken}`;
}
function resetPromptHistoryCursor() {
  promptHistoryOffset = 0;
  promptHistoryDraft = "";
}
function trimPromptHistory(entries) {
  if (entries.length > PROMPT_HISTORY_LIMIT)
    entries.splice(0, entries.length - PROMPT_HISTORY_LIMIT);
  return entries;
}
function promptHistoryEntries() {
  const key = promptHistoryKeyForCurrentChat();
  if (key !== promptHistoryKey) {
    promptHistoryKey = key;
    resetPromptHistoryCursor();
    if (!promptHistories.has(key)) promptHistories.set(key, []);
  }
  return promptHistories.get(key);
}
function rememberPrompt(text) {
  const value = String(text ?? "").trim();
  if (!value) return;
  const entries = promptHistoryEntries();
  if (entries[entries.length - 1] !== value) entries.push(value);
  trimPromptHistory(entries);
  resetPromptHistoryCursor();
}
function seedPromptHistory(recordMessages) {
  const entries = trimPromptHistory(
    (Array.isArray(recordMessages) ? recordMessages : [])
      .filter((message) => message.role === "user" && !message.tool_result)
      .map((message) => String(message.content ?? "").trim())
      .filter(Boolean),
  );
  promptHistoryKey = promptHistoryKeyForCurrentChat();
  promptHistories.set(promptHistoryKey, entries);
  resetPromptHistoryCursor();
}
// direction 1 walks back to older prompts, -1 walks forward to the draft.
function recallPromptHistory(direction) {
  const input = $("input");
  const entries = promptHistoryEntries();
  if (!entries.length) return false;
  const value = input.value;
  const caret = input.selectionStart ?? value.length;
  if (promptHistoryOffset === 0) {
    if (direction < 0) return false;
    // Start recalling only from the first line so the arrows still move the
    // caret inside a multi-line draft.
    if (value.slice(0, caret).includes("\n")) return false;
    promptHistoryDraft = value;
  } else if (direction < 0) {
    if (value.slice(input.selectionEnd ?? caret).includes("\n")) return false;
  }
  const next = Math.min(
    Math.max(promptHistoryOffset + direction, 0),
    entries.length,
  );
  if (next === promptHistoryOffset) return false;
  promptHistoryOffset = next;
  input.value = next === 0 ? promptHistoryDraft : entries[entries.length - next];
  const end = input.value.length;
  input.setSelectionRange(end, end);
  resizeInput();
  updateSendState();
  return true;
}
$("input").addEventListener("input", () => {
  resetPromptHistoryCursor();
  resizeInput();
  updateSlashMenu();
  updateSendState();
});
$("input").addEventListener("keydown", (event) => {
  if (!$("slash-menu").hidden) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      moveSlashSelection(1);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      moveSlashSelection(-1);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      hideSlashMenu();
      return;
    }
    if (event.key === "Tab" || (event.key === "Enter" && !event.shiftKey)) {
      const selected = slashMatches[slashIndex];
      const exact = selected?.name
        ? $("input").value.trim() === `/${selected.name}`
        : false;
      event.preventDefault();
      if (exact) {
        hideSlashMenu();
        $("chat-form").requestSubmit();
      } else {
        applySlashSuggestion();
      }
      return;
    }
  }
  if (
    !event.isComposing &&
    !event.altKey &&
    !event.ctrlKey &&
    !event.metaKey &&
    !event.shiftKey
  ) {
    if (event.key === "ArrowUp" && recallPromptHistory(1)) {
      event.preventDefault();
      return;
    }
    if (event.key === "ArrowDown" && recallPromptHistory(-1)) {
      event.preventDefault();
      return;
    }
  }
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("chat-form").requestSubmit();
  } else if (event.key === "Escape") {
    clearPendingSkill();
  }
});
$("slash-menu").addEventListener("mousedown", (event) => {
  const item = event.target.closest("[data-slash-index]");
  if (!item) return;
  event.preventDefault();
  applySlashSuggestion(Number(item.dataset.slashIndex));
});
let attachmentRequestToken = 0;
function clearAttachment() {
  // Invalidate any file read still in flight so its result cannot restore a
  // cleared attachment.
  attachmentRequestToken += 1;
  pendingAttachment = null;
  $("file-input").value = "";
  $("attachment-name").textContent = "";
  $("attachment-chip").hidden = true;
}
$("attachment-cancel").addEventListener("click", clearAttachment);
$("skill-chip").addEventListener("click", () => clearPendingSkill());
$("attach-button").addEventListener("click", () => $("file-input").click());
function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("read failed"));
    reader.readAsDataURL(file);
  });
}
// Browsers do not always report a MIME type, so a known extension supplies one
// and an unknown type is rejected instead of being decoded as text.
const BINARY_EXTENSION_TYPES = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".heic": "image/heic",
  ".mp3": "audio/mpeg",
  ".m4a": "audio/mp4",
  ".wav": "audio/wav",
  ".ogg": "audio/ogg",
  ".mp4": "video/mp4",
  ".webm": "video/webm",
  ".mov": "video/quicktime",
  ".pdf": "application/pdf",
};
const TEXT_EXTENSION_TYPES = {
  ".txt": "text/plain",
  ".md": "text/plain",
  ".log": "text/plain",
  ".json": "application/json",
  ".csv": "text/plain",
  ".yaml": "text/plain",
  ".yml": "text/plain",
  ".xml": "text/plain",
  ".html": "text/plain",
  ".css": "text/plain",
  ".js": "text/plain",
  ".py": "text/plain",
  ".ts": "text/plain",
};
// Only known text types are read as text, so a ZIP reported as
// application/zip is not decoded into a text attachment.
const TEXT_MIME_TYPES = new Set([
  "application/json",
  "application/xml",
  "application/javascript",
  "application/x-yaml",
  "application/yaml",
]);
function isTextMimeType(type) {
  return type.startsWith("text/") || TEXT_MIME_TYPES.has(type);
}
function fileMimeType(file) {
  const reported = (file.type || "").toLowerCase();
  if (reported) return reported;
  const name = String(file.name || "").toLowerCase();
  const dot = name.lastIndexOf(".");
  if (dot === -1) return "";
  const extension = name.slice(dot);
  return BINARY_EXTENSION_TYPES[extension] || TEXT_EXTENSION_TYPES[extension] || "";
}
$("file-input").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  attachmentRequestToken += 1;
  const requestToken = attachmentRequestToken;
  const type = fileMimeType(file);
  // Images, audio, video and PDFs travel inline as multimodal parts; text
  // files keep the older plain-text attachment path.
  const isBinary =
    type.startsWith("image/") ||
    type.startsWith("audio/") ||
    type.startsWith("video/") ||
    type === "application/pdf";
  if (!isBinary && !isTextMimeType(type)) {
    pendingAttachment = null;
    $("attachment-name").textContent = t("attachment.unsupported");
    $("attachment-chip").hidden = false;
    event.target.value = "";
    return;
  }
  const maxBytes = isBinary ? 6 * 1024 * 1024 : 1024 * 1024;
  if (file.size > maxBytes) {
    $("attachment-name").textContent = t(
      isBinary ? "attachment.binaryTooLarge" : "attachment.tooLarge",
    );
    $("attachment-chip").hidden = false;
    event.target.value = "";
    pendingAttachment = null;
    return;
  }
  try {
    if (isBinary) {
      const dataUrl = await readFileAsDataUrl(file);
      if (requestToken !== attachmentRequestToken) return;
      pendingAttachment = {
        name: file.name,
        mime_type: type,
        data: dataUrl.split(",")[1] || "",
      };
    } else {
      const content = await file.text();
      if (requestToken !== attachmentRequestToken) return;
      pendingAttachment = { name: file.name, content };
    }
    $("attachment-name").textContent = `📎 ${file.name}`;
    $("attachment-chip").hidden = false;
  } catch (error) {
    if (requestToken !== attachmentRequestToken) return;
    pendingAttachment = null;
    $("attachment-name").textContent = t("attachment.readFailed");
    $("attachment-chip").hidden = false;
  }
});
function newMessageId() {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
  } catch (error) {
    /* fall back to a timestamp-based id */
  }
  return `msg-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
function historyMessagePayload(message = {}) {
  // Keep tool_request/approval_id: a pending approval must still be offered
  // after a reload or when the conversation is opened again from the sidebar,
  // for as long as the server-side token has not expired. approval_deadline is
  // a browser-clock value and is recomputed from the server clock on load.
  // Inline attachment bytes are not written to history; only the name and type
  // are kept, so history files do not balloon with base64 media.
  let payload = message;
  if (payload?.attachment?.data) {
    const { data: _data, ...meta } = payload.attachment;
    payload = { ...payload, attachment: meta };
  }
  if (!payload || !("approval_deadline" in payload)) return payload;
  const { approval_deadline: _deadline, ...rest } = payload;
  return rest;
}
async function appendMessagesToHistory(id, newMessages, generation) {
  if (!id || !newMessages.length) return { ok: true };
  try {
    const response = await fetch(
      `/api/history/${encodeURIComponent(id)}/messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: newMessages.map(historyMessagePayload),
          generation,
        }),
      },
    );
    if (response.status === 404) return { ok: false, missing: true };
    if (response.status === 409) {
      console.warn(t("chat.saveWarning"), "append conflict, generation mismatch");
      return { ok: false, conflict: true };
    }
    if (!response.ok) throw new Error(t("chat.saveWarning"));
    return { ok: true, record: await response.json() };
  } catch (error) {
    console.warn(t("chat.saveWarning"), error);
    return { ok: false, error };
  }
}
function queuePendingAppend(id, newMessages, generation = null) {
  if (!id || !newMessages.length) return;
  const entry = pendingHistoryAppends.get(id);
  const queued = entry?.messages ? entry.messages : [];
  const queuedIds = new Set(
    queued.map((message) => message.message_id).filter(Boolean),
  );
  for (const message of newMessages) {
    if (message.message_id && queuedIds.has(message.message_id)) continue;
    queued.push(message);
    if (message.message_id) queuedIds.add(message.message_id);
  }
  // Keep the generation captured for this conversation record so retries
  // keep validating against it even after the active chat changes.
  const targetGeneration =
    entry?.generation ||
    generation ||
    newMessages[0]?.generation ||
    (conversationId === id ? conversationGeneration : null);
  pendingHistoryAppends.set(id, {
    generation: targetGeneration,
    messages: queued,
  });
  if (conversationId === id) showNotice(t("chat.saveWarning"), true);
}
async function flushPendingAppends(id = null) {
  while (pendingAppendFlush) await pendingAppendFlush;
  const targetIds = id ? [id] : [...pendingHistoryAppends.keys()];
  if (!targetIds.some((target) => pendingHistoryAppends.has(target))) return;
  pendingAppendFlush = (async () => {
    for (const targetId of targetIds) {
      const entry = pendingHistoryAppends.get(targetId);
      if (!entry?.messages?.length) {
        pendingHistoryAppends.delete(targetId);
        continue;
      }
      const queued = entry.messages;
      // Slice an immutable batch now; newly queued messages after this
      // point stay in the entry for the next flush.
      const batch = queued.splice(0, queued.length);
      const result = await appendMessagesToHistory(
        targetId,
        batch,
        entry.generation,
      );
      if (result.ok || result.missing) {
        // Remove only the batch we just sent.
        // Re-store the remainder if anything was left (shouldn't happen often,
        // but protects against partial sends / network glitches).
        pendingHistoryAppends.set(targetId, entry);
        if (result.missing) {
          pendingHistoryAppends.delete(targetId);
        }
      } else {
        // Conflict/error – restore the batch ahead of anything queued
        // while the request was in flight so the retry resends it first.
        entry.messages.unshift(...batch);
        pendingHistoryAppends.set(targetId, entry);
      }
    }
  })();
  try {
    await pendingAppendFlush;
  } finally {
    pendingAppendFlush = null;
  }
}
async function requestGeneratedTitle(question) {
  // A failed summary is not an error the user needs to see: the first
  // message stays the title, exactly like the earlier behaviour.
  try {
    const response = await fetch("/api/history/title", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        model: $("chat-model-select")?.value || "",
        lang: currentLanguage,
      }),
    });
    if (!response.ok) return null;
    const data = await response.json();
    return typeof data.title === "string" && data.title.trim()
      ? data.title.trim()
      : null;
  } catch (error) {
    return null;
  }
}
async function applyGeneratedTitle(promise, id, fallbackTitle) {
  const generated = await promise;
  if (!generated) return;
  // A new chat, a reload or a rename means this summary is no longer wanted.
  if (conversationId !== id) return;
  if (conversationTitle !== normalizeConversationTitle(fallbackTitle)) return;
  try {
    const response = await fetch(`/api/history/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: generated, lang: currentLanguage }),
    });
    if (!response.ok) return;
  } catch (error) {
    return;
  }
  if (conversationId !== id) return;
  setConversationTitle(generated);
  await loadHistoryList();
}
async function saveConversation(sessionToken = null) {
  if (!messages.length) return null;
  const targetConversationId = conversationId;
  const isCurrent = () =>
    sessionToken === null || sessionToken === chatSessionToken;
  const firstUser = messages.find((message) => message.role === "user");
  const title = firstUser?.content || t("chat.newConversationTitle");
  // Summarising the first question costs one model call, so it runs beside
  // the save instead of delaying the reply; the question is only the fallback.
  const generatedTitle =
    !targetConversationId && firstUser?.content
      ? requestGeneratedTitle(firstUser.content)
      : null;
  if (!targetConversationId) {
    const snapshot = messages.slice();
    try {
      const response = await fetch("/api/history", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          messages: snapshot.map(historyMessagePayload),
          generation: conversationGeneration,
        }),
      });
      if (!response.ok) throw new Error(t("chat.saveWarning"));
      const saved = await response.json();
      if (isCurrent()) {
        setConversationTitle(title);
        conversationId = saved.id;
        conversationCreatedAt = saved.created_at;
        conversationGeneration = saved.generation || conversationGeneration;
        persistedMessageCount = snapshot.length;
        await loadHistoryList();
      }
      if (generatedTitle) {
        applyGeneratedTitle(generatedTitle, saved.id, title).catch(() => {});
      }
      return saved;
    } catch (error) {
      console.warn(t("chat.saveWarning"), error);
      return null;
    }
  }
  const pending = messages.slice(persistedMessageCount);
  if (!pending.length) {
    return {
      id: targetConversationId,
      created_at: conversationCreatedAt,
      title: conversationTitle,
    };
  }
  const result = await appendMessagesToHistory(
    targetConversationId,
    pending,
    conversationGeneration,
  );
  if (!result.ok) return null;
  if (isCurrent()) {
    conversationCreatedAt =
      result.record?.created_at || conversationCreatedAt;
    conversationGeneration = result.record?.generation || conversationGeneration;
    persistedMessageCount = Math.min(
      persistedMessageCount + pending.length,
      messages.length,
    );
    await loadHistoryList();
  }
  return result.record || { id: targetConversationId };
}
async function appendAssistantToHistory(
  id,
  assistantMessage,
  generation = null,
) {
  if (!id) return false;
  const result = await appendMessagesToHistory(
    id,
    [assistantMessage],
    generation,
  );
  if (result.ok) {
    await loadHistoryList();
    return true;
  }
  if (result.missing) return false;
  queuePendingAppend(id, [assistantMessage], generation);
  return false;
}
function attachmentProviderUnsupported() {
  // An OpenAI-compatible payload only carries images, so a turn holding audio,
  // video or a PDF would be saved and then rejected on every later turn.
  if (!pendingAttachment?.mime_type) return null;
  const provider = $("provider").value || activeProvider;
  if (provider === "gemini" || provider === "anthropic") return null;
  return pendingAttachment.mime_type.startsWith("image/")
    ? null
    : pendingAttachment;
}
async function sendChatMessage(
  content,
  requestedSkills = null,
  historyEntry = null,
) {
  const toolResult = pendingToolResult;
  pendingToolResult = null;
  const blockedAttachment = attachmentProviderUnsupported();
  if (blockedAttachment) {
    showNotice(
      t("attachment.providerUnsupported", {
        name: blockedAttachment.name,
        mime: blockedAttachment.mime_type,
      }),
      true,
    );
    return;
  }
  const sessionToken = chatSessionToken;
  // A previous send recorded its message but could not persist it. Retry that
  // save first, reusing the recorded message_id, so this submission does not add
  // a duplicate of it.
  if (failedSend && failedSend.sessionToken === sessionToken) {
    // Hold the composer while the retry save is in flight so a second submit
    // cannot start from the same unsaved message.
    chatBusy = true;
    $("send").disabled = true;
    const retried = await saveConversation(sessionToken);
    if (sessionToken !== chatSessionToken) {
      // invalidateChatSession() already reset the busy state for the new
      // session; leave it (and the Send button) to the newer send.
      return;
    }
    chatBusy = false;
    if (retried?.id) {
      // Clear the flag only once the message is really persisted.
      failedSend = null;
      const staleWarning = document.querySelector(
        "#messages .message.assistant:last-child",
      );
      if (staleWarning?.textContent.includes(t("chat.saveWarning"))) {
        staleWarning.remove();
      }
    }
  }
  const userMessage = {
    role: "user",
    content: content || t("chat.defaultAttachmentPrompt"),
    message_id: newMessageId(),
  };
  if (pendingAttachment) userMessage.attachment = pendingAttachment;
  const appliedSkill = requestedSkills?.[requestedSkills.length - 1] ?? pendingSkill;
  const skills = requestedSkills?.length
    ? requestedSkills
    : pendingSkill
      ? [pendingSkill]
      : null;
  if (appliedSkill) userMessage.skill = appliedSkill;
  if (toolResult) {
    userMessage.tool_result = true;
    userMessage.tool_name = toolResult.name || "";
  }
  messages.push(userMessage);
  addMessage("user", userMessage.content, userMessage, messages.length - 1);
  addTypingIndicator();
  chatBusy = true;
  $("send").disabled = true;
  $("send").textContent = "…";
  let targetConversationId = null;
  // Generation of the record these messages belong to, captured before
  // the session can change.
  let targetGeneration = null;
  try {
    const savedConversation = await saveConversation(sessionToken);
    if (sessionToken !== chatSessionToken) return;
    if (!savedConversation?.id) {
      // Initial save failed: keep the user message in messages but
      // do NOT send the AI request. Record the failure so a retry
      // can reuse the exact same message (same message_id).
      failedSend = { message: userMessage, skills, sessionToken };
      addMessage(
        "assistant",
        t("chat.errorPrefix", { message: t("chat.saveWarning") }),
      );
      return;
    }
    targetConversationId = savedConversation.id;
    targetGeneration =
      savedConversation.generation || conversationGeneration || null;
    // Recorded only once the turn is saved, so a failed send is not recalled.
    rememberPrompt(historyEntry ?? content);
    $("input").value = "";
    clearAttachment();
    resizeInput();
    const payload = {
      messages,
      thinking_level: $("chat-thinking-level").value,
      command_mode: $("chat-command-mode").value,
      model: $("chat-model-select").value,
      lang: currentLanguage,
    };
    if (skills?.length) payload.skills = skills;
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || t("chat.error"));
    const assistantMessage = {
      role: "assistant",
      content: data.answer,
      message_id: newMessageId(),
      duration_ms: data.duration_ms,
      usage: data.usage,
      tool_request: data.tool_request,
      approval_id: data.approval_id,
      approval_expires_at: data.approval_expires_at,
      fallback_used: data.fallback_used,
    };
    stampApprovalDeadline(assistantMessage, data.server_time);
    if (sessionToken !== chatSessionToken) {
      if (targetConversationId && conversationId === targetConversationId) {
        messages.push(assistantMessage);
        removeTypingIndicator();
        addMessage("assistant", data.answer, assistantMessage, messages.length - 1);
      }
      await appendAssistantToHistory(
        targetConversationId,
        assistantMessage,
        targetGeneration,
      );
      return;
    }
    messages.push(assistantMessage);
    removeTypingIndicator();
    addMessage("assistant", data.answer, assistantMessage, messages.length - 1);
    const saved = await saveConversation(sessionToken);
    if (!saved) {
      queuePendingAppend(
        targetConversationId,
        [assistantMessage],
        targetGeneration,
      );
      showNotice(t("chat.saveWarning"), true);
    }
  } catch (e) {
    // Unexpected error after a successful save – just render the error. An
    // earlier unsaved message is retried before the next submission instead.
    const errorMessage = {
      role: "assistant",
      content: t("chat.errorPrefix", { message: e.message }),
      message_id: newMessageId(),
    };
    if (sessionToken !== chatSessionToken) {
      if (targetConversationId && conversationId === targetConversationId) {
        messages.push(errorMessage);
        addMessage("assistant", errorMessage.content, null, messages.length - 1);
      }
      if (targetConversationId) {
        await appendAssistantToHistory(
          targetConversationId,
          errorMessage,
          targetGeneration,
        );
      }
      return;
    }
    messages.push(errorMessage);
    addMessage("assistant", errorMessage.content, null, messages.length - 1);
    const saved = targetConversationId
      ? await saveConversation(sessionToken)
      : null;
    if (!saved && targetConversationId) {
      queuePendingAppend(
        targetConversationId,
        [errorMessage],
        targetGeneration,
      );
      showNotice(t("chat.saveWarning"), true);
    }
    await refreshConnectionState();
  } finally {
    if (sessionToken === chatSessionToken) {
      removeTypingIndicator();
      chatBusy = false;
      pendingSkill = null;
      updateSkillChip();
      $("send").textContent = "↑";
      updateSendState();
      $("input").focus();
    }
  }
}
function scheduleStatusText(value) {
  const status = String(value || "").trim();
  if (!status) return t("schedule.neverRun");
  // Jobs saved before the upgrade kept the Thai status values on disk.
  if (status === "success" || status === "สำเร็จ")
    return t("schedule.success");
  if (status === "failed" || status === "ล้มเหลว")
    return t("schedule.failed");
  return status;
}
function scheduleRetryText(job) {
  // The server writes retry_at as an ISO time with its own offset, so the
  // browser shows the wall clock the job will actually run at. A time that has
  // already passed (or cannot be read) means no retry is pending any more.
  const raw = String((job && job.retry_at) || "").trim();
  if (!raw) return "";
  const moment = new Date(raw);
  if (Number.isNaN(moment.getTime()) || moment.getTime() <= Date.now()) return "";
  const time = `${String(moment.getHours()).padStart(2, "0")}:${String(
    moment.getMinutes(),
  ).padStart(2, "0")}`;
  return t("schedule.retryAt", { time });
}
function renderSchedules(items) {
  const list = $("schedule-list");
  if (!items.length) {
    list.innerHTML = `<p class="hint">${escapeHtml(t("schedule.empty"))}</p>`;
    return;
  }
  list.innerHTML = items
    .map(
      (job) => `
    <div class="schedule-item" data-schedule-id="${escapeHtml(job.id)}">
      <strong>${escapeHtml(job.name)}</strong>
      <small>${escapeHtml(job.schedule)} · ${job.model ? `${escapeHtml(t("schedule.modelLabel", { model: job.model }))} · ` : ""}${job.enabled ? t("schedule.enabled") : t("schedule.disabled")} · ${escapeHtml(scheduleStatusText(job.last_status))}${scheduleRetryText(job) ? ` · ${escapeHtml(scheduleRetryText(job))}` : ""}</small>
      <small>${escapeHtml(job.prompt)}</small>
      ${job.discord_channel_id ? `<small>${escapeHtml(t("schedule.discordChannel", { id: job.discord_channel_id }))}</small>` : ""}
      <div class="schedule-item-actions">
        <button type="button" data-schedule-action="run">${t("schedule.runNow")}</button>
        <button type="button" data-schedule-action="edit">${t("schedule.edit")}</button>
        <button type="button" data-schedule-action="toggle" data-enabled="${job.enabled ? "true" : "false"}">${job.enabled ? t("schedule.toggleDisable") : t("schedule.toggleEnable")}</button>
        <button type="button" class="danger" data-schedule-action="delete">${t("common.delete")}</button>
      </div>
    </div>`,
    )
    .join("");
}
function schedulesSignature(items) {
  // Only the fields the list shows: a run that merely moves last_run_at must
  // not repaint the list, while a new status or retry time must.
  return JSON.stringify(
    (items || []).map((job) => [
      job.id,
      job.name,
      job.schedule,
      job.model,
      job.enabled,
      job.last_status,
      job.retry_at,
      job.prompt,
      job.discord_channel_id,
    ]),
  );
}
function renderSchedulesIfChanged(items) {
  const signature = schedulesSignature(items);
  if (signature === scheduleListSignature) return false;
  scheduleListSignature = signature;
  renderSchedules(items);
  return true;
}
async function loadSchedules(options = {}) {
  // A background refresh must not stack requests or scold the user with a
  // notice every time the server is busy; the button and page loads still do.
  const quiet = Boolean(options.quiet);
  if (scheduleLoadInFlight) return;
  scheduleLoadInFlight = true;
  try {
    const response = await fetch("/api/schedules");
    // A 401 answers with HTML, so the failure must be reported instead of
    // leaving the old list on screen as if it were current.
    if (!response.ok) throw new Error(`${response.status}`);
    const data = await response.json();
    currentSchedules = data.items || [];
    currentScheduleTimezone =
      data.timezone || t("schedule.timezoneFallback");
    $("schedule-timezone").textContent = currentScheduleTimezone;
    renderSchedulesIfChanged(currentSchedules);
  } catch (error) {
    if (!quiet)
      showNotice(t("schedule.loadFailed", { error: error.message }), true);
  } finally {
    scheduleLoadInFlight = false;
  }
}
function stopScheduleRefresh() {
  if (scheduleRefreshTimer === null) return;
  clearInterval(scheduleRefreshTimer);
  scheduleRefreshTimer = null;
}
function startScheduleRefresh() {
  stopScheduleRefresh();
  scheduleRefreshTimer = setInterval(() => {
    // A hidden tab and a different view must not poll: the list is loaded when
    // the view is opened or the tab becomes visible again.
    if (document.hidden || activeView() !== "schedule") return;
    loadSchedules({ quiet: true });
  }, SCHEDULE_REFRESH_MS);
}
document.addEventListener("visibilitychange", () => {
  if (document.hidden || activeView() !== "schedule") return;
  loadSchedules({ quiet: true });
});
let memoryStatusCache = null;
let memoryEntriesCache = { items: [], dreams: "" };
// Two loads can finish out of order; only the newest may update the caches.
let memoryLoadGeneration = 0;
let memoryLoaded = false;
function renderMemory() {
  if (memoryStatusCache) renderMemoryStatus(memoryStatusCache);
  renderMemoryEntries(memoryEntriesCache.items);
  $("memory-dreams").textContent =
    memoryEntriesCache.dreams || t("memory.noDreams");
}
function memoryNumber(id, fallback) {
  const raw = $(id).value.trim();
  if (!raw) return fallback;
  const value = Number(raw);
  return Number.isFinite(value) ? value : fallback;
}
function memoryStatusLabel(value) {
  if (value === "ok") return t("memory.statusOk");
  if (value === "degraded") return t("memory.statusDegraded");
  if (value === "failed") return t("memory.statusFailed");
  return value || "—";
}
function renderMemoryStatus(data) {
  const caps = data.capabilities || {};
  const stats = data.last_stats || {};
  const cells = [
    [t("memory.schedule"), data.schedule || "—"],
    [t("memory.threshold"), Number(data.threshold ?? 0).toFixed(2)],
    [
      t("memory.idle"),
      t("memory.idleMinutes", { minutes: data.idle_minutes ?? 0 }),
    ],
    [t("memory.messages"), String(data.messages ?? 0)],
    [t("memory.conversations"), String(data.conversations ?? 0)],
    [t("memory.promoted"), String(data.promoted_entries ?? 0)],
    [
      t("memory.index"),
      `${caps.vector || "?"} · FTS5 ${caps.fts5 ? "✓" : "✗"}`,
    ],
  ];
  $("memory-status").innerHTML = cells
    .map(
      ([label, value]) =>
        `<div class="memory-stat"><small>${escapeHtml(label)}</small><strong>${escapeHtml(String(value))}</strong></div>`,
    )
    .join("");
  const last = data.last_run_at
    ? t("memory.lastRunLine", {
        time: data.last_run_at,
        status: memoryStatusLabel(data.last_run_status),
      })
    : t("memory.neverRun");
  const extra = `${last}${data.running ? ` · ${t("memory.running")}` : ""}${
    stats.promoted !== undefined
      ? ` · ${t("memory.lastRunPromoted", { count: stats.promoted })}`
      : ""
  }`;
  $("memory-last-run").textContent = extra;
  $("memory-capability").textContent = t("memory.capability", {
    version: caps.sqlite_version || "?",
    fts: caps.fts5 ? "✓" : "✗",
    vector: caps.vector || "?",
    embedding: caps.embedding || "?",
  });
  const paths = data.paths || {};
  $("memory-paths").textContent = t("memory.paths", {
    memory: paths.memory_file || "?",
    dreams: paths.dreams_file || "?",
    db: paths.database || "?",
  });
}
function renderMemoryEntries(items) {
  const list = $("memory-entries");
  if (!items.length) {
    list.innerHTML = `<p class="hint">${escapeHtml(t("memory.empty"))}</p>`;
    return;
  }
  list.innerHTML = items
    .map(
      (item) => `
    <div class="memory-entry">
      <div class="memory-entry-text">${escapeHtml(item.text || "")}</div>
      <div class="memory-entry-meta">
        <span>${escapeHtml(t("memory.score"))} ${Number(item.score || 0).toFixed(2)}</span>
        <span>${escapeHtml(item.date || "")}</span>
        ${item.pinned ? `<span>${escapeHtml(t("memory.pinned"))}</span>` : ""}
        <button type="button" class="memory-pin" data-memory-pin="${escapeHtml(item.id)}" data-pinned="${item.pinned ? "1" : "0"}">${escapeHtml(t(item.pinned ? "memory.unpin" : "memory.pin"))}</button>
        <button type="button" class="danger" data-memory-id="${escapeHtml(item.id)}">${escapeHtml(t("memory.forget"))}</button>
      </div>
    </div>`,
    )
    .join("");
}
async function loadMemory() {
  const generation = ++memoryLoadGeneration;
  $("memory-entries").innerHTML = `<p class="hint">${escapeHtml(t("memory.loading"))}</p>`;
  try {
    const [statusResponse, entriesResponse] = await Promise.all([
      fetch("/api/memory/status"),
      fetch("/api/memory/entries"),
    ]);
    if (!statusResponse.ok) throw new Error(`HTTP ${statusResponse.status}`);
    // A failed read is not an empty collection: report it instead of showing
    // "nothing has passed the threshold".
    if (!entriesResponse.ok) throw new Error(`HTTP ${entriesResponse.status}`);
    const status = await statusResponse.json();
    const entries = await entriesResponse.json();
    // A slower, older refresh must not restore the entries it saw first.
    if (generation !== memoryLoadGeneration) return;
    memoryStatusCache = status;
    memoryEntriesCache = { items: entries.items || [], dreams: entries.dreams || "" };
    memoryLoaded = true;
    renderMemory();
  } catch (error) {
    if (generation !== memoryLoadGeneration) return;
    // Keep the last good view (or say what failed) instead of leaving the
    // loading placeholder on screen.
    if (memoryLoaded) {
      renderMemory();
    } else {
      $("memory-entries").innerHTML = `<p class="hint">${escapeHtml(t("memory.error", { error: error.message }))}</p>`;
    }
    showNotice(t("memory.error", { error: error.message }), true);
  }
}
async function runMemory(dryRun) {
  const button = dryRun ? $("memory-dry-run") : $("memory-run");
  const original = button.textContent;
  button.disabled = true;
  button.textContent = t("memory.running");
  try {
    const response = await fetch("/api/memory/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dry_run: dryRun }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    const stats = data.stats || {};
    showNotice(
      dryRun
        ? t("memory.dryRunDone", { count: stats.promoted ?? 0 })
        : t("memory.runDone", {
            count: stats.promoted ?? 0,
            messages: stats.messages ?? 0,
          }),
    );
    await loadMemory();
  } catch (error) {
    showNotice(t("memory.error", { error: error.message }), true);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}
async function reindexMemory() {
  const button = $("memory-reindex");
  const original = button.textContent;
  button.disabled = true;
  button.textContent = t("memory.running");
  try {
    const response = await fetch("/api/memory/reindex", { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    showNotice(t("memory.reindexed"));
    await loadMemory();
  } catch (error) {
    showNotice(t("memory.error", { error: error.message }), true);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}
$("memory-run").addEventListener("click", () => runMemory(false));
$("memory-dry-run").addEventListener("click", () => runMemory(true));
$("memory-reindex").addEventListener("click", reindexMemory);
$("memory-entries").addEventListener("click", async (event) => {
  const pinButton = event.target.closest("button[data-memory-pin]");
  if (pinButton) {
    const memoryId = pinButton.dataset.memoryPin;
    const pinned = pinButton.dataset.pinned !== "1";
    pinButton.disabled = true;
    try {
      const response = await fetch(
        `/api/memory/entries/${encodeURIComponent(memoryId)}/pin`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pinned }),
        },
      );
      const data = await response.json();
      if (!response.ok)
        throw new Error(data.error || `HTTP ${response.status}`);
      await loadMemory();
    } catch (error) {
      showNotice(t("memory.error", { error: error.message }), true);
      pinButton.disabled = false;
    }
    return;
  }
  const button = event.target.closest("button[data-memory-id]");
  if (!button) return;
  if (button.dataset.confirm !== "1") {
    button.dataset.confirm = "1";
    button.textContent = t("memory.forgetConfirm");
    return;
  }
  const memoryId = button.dataset.memoryId;
  button.disabled = true;
  try {
    const response = await fetch(
      `/api/memory/entries/${encodeURIComponent(memoryId)}`,
      { method: "DELETE" },
    );
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    await loadMemory();
  } catch (error) {
    showNotice(t("memory.error", { error: error.message }), true);
    button.disabled = false;
  }
});
$("schedule-preset").addEventListener("change", () => {
  if ($("schedule-preset").value)
    $("schedule-expression").value = $("schedule-preset").value;
});
function updateScheduleFormMode() {
  const editing = Boolean(currentScheduleEditingId);
  $("schedule-submit").textContent = t(
    editing ? "schedule.saveEdit" : "schedule.add",
  );
  $("schedule-cancel").hidden = !editing;
}
function resetScheduleForm() {
  currentScheduleEditingId = "";
  $("schedule-form").reset();
  updateScheduleFormMode();
}
$("schedule-form").addEventListener("reset", () => {
  currentScheduleSelected = "";
  currentScheduleEditingId = "";
  updateScheduleFormMode();
});
$("schedule-cancel").addEventListener("click", () => {
  resetScheduleForm();
  showNotice(t("schedule.editCancelled"));
});
function updateScheduleModelOptions(models, selected = "") {
  const select = $("schedule-model");
  const options =
    `<option value="">${escapeHtml(t("schedule.useMainModel"))}</option>` +
    (models || [])
      .map(
        (model) =>
          `<option value="${escapeHtml(model.id || model)}">${escapeHtml(model.name || model.id || model)}</option>`,
      )
      .join("");
  select.innerHTML = options;
  select.value = selected || "";
  currentScheduleModels = models || [];
  currentScheduleSelected = select.value;
}
$("schedule-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const editing = Boolean(currentScheduleEditingId);
  const response = await fetch(editing ? `/api/schedules/${currentScheduleEditingId}` : "/api/schedules", {
    method: editing ? "PATCH" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: $("schedule-name").value.trim(),
      schedule: $("schedule-expression").value.trim(),
      model: $("schedule-model").value,
      discord_channel_id: $("schedule-discord-channel").value.trim(),
      prompt: $("schedule-prompt").value.trim(),
      enabled: $("schedule-enabled").checked,
    }),
  });
  const data = await response.json();
  if (!response.ok)
    return showNotice(data.error || t("schedule.addFailed"), true);
  resetScheduleForm();
  await loadSchedules();
  showNotice(t(editing ? "schedule.updated" : "schedule.added"));
});
$("schedule-list").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-schedule-action]");
  if (!button) return;
  const id = button.closest("[data-schedule-id]").dataset.scheduleId;
  if (button.dataset.scheduleAction === "edit") {
    const job = currentSchedules.find((item) => item.id === id);
    if (!job) return;
    currentScheduleEditingId = id;
    $("schedule-name").value = job.name || "";
    $("schedule-expression").value = job.schedule || "";
    const scheduleModel = $("schedule-model");
    if (
      job.model &&
      !Array.from(scheduleModel.options).some(
        (option) => option.value === job.model,
      )
    ) {
      // Keep the stored model selectable even when the provider list no longer
      // offers it, so saving an unrelated edit does not clear it.
      scheduleModel.insertAdjacentHTML(
        "beforeend",
        `<option value="${escapeHtml(job.model)}">${escapeHtml(job.model)}</option>`,
      );
    }
    scheduleModel.value = job.model || "";
    $("schedule-discord-channel").value = job.discord_channel_id || "";
    $("schedule-prompt").value = job.prompt || "";
    $("schedule-enabled").checked = job.enabled !== false;
    updateScheduleFormMode();
    $("schedule-name").focus();
    showNotice(t("schedule.editing"));
    return;
  }
  if (button.dataset.scheduleAction === "run") {
    const response = await fetch(`/api/schedules/${id}/run`, { method: "POST" });
    const data = await response.json();
    showNotice(data.error || t("schedule.started"), !response.ok);
    await loadSchedules();
    return;
  }
  if (button.dataset.scheduleAction === "delete") {
    await fetch(`/api/schedules/${id}`, { method: "DELETE" });
  } else {
    await fetch(`/api/schedules/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled: button.dataset.enabled !== "true",
      }),
    });
  }
  await loadSchedules();
});
function showNotice(text, error = false) {
  const n = $("notice");
  n.textContent = text;
  n.className = `notice${error ? " error" : ""}`;
  n.style.display = "block";
  setTimeout(() => (n.style.display = "none"), 4000);
}
const MODEL_OPTIONS = {
  openai: {
    label: "OpenAI / OpenAI-compatible",
    models: [
      "gpt-4.1-mini",
      "gpt-4.1",
      "gpt-4o-mini",
      "gpt-4o",
      "o4-mini",
      "o3",
    ],
  },
  gemini: {
    label: "Google Gemini",
    models: [
      "gemini-2.5-flash",
      "gemini-2.5-pro",
      "gemini-2.0-flash",
      "gemini-1.5-pro",
    ],
  },
  anthropic: {
    label: "Anthropic Claude",
    models: [
      "claude-sonnet-4-5",
      "claude-opus-4-1",
      "claude-3-7-sonnet-latest",
      "claude-3-5-haiku-latest",
    ],
  },
};
const PROVIDER_BASE_URLS = {
  openai: "https://api.openai.com/v1",
  gemini: "https://generativelanguage.googleapis.com/v1beta",
  anthropic: "https://api.anthropic.com/v1",
  hf: "https://router.huggingface.co/v1",
  or: "https://openrouter.ai/api/v1",
  groq: "https://api.groq.com/openai/v1",
};
function updateModelOptions(provider, selected = "", models = null) {
  const select = $("model_select");
  const choices = models?.length
    ? models
    : MODEL_OPTIONS[provider]?.models || [];
  select.innerHTML =
    choices
      .map(
        (model) =>
          `<option value="${escapeHtml(model.id || model)}">${escapeHtml(model.name || model.id || model)}</option>`,
      )
      .join("") +
    `<option value="__custom__">${escapeHtml(t("model.custom"))}</option>`;
  if (choices.some((model) => (model.id || model) === selected)) {
    select.value = selected;
    $("model_custom").style.display = "none";
  } else if (selected) {
    select.value = "__custom__";
    $("model_custom").value = selected;
    $("model_custom").style.display = "block";
  } else {
    select.value = choices[0]
      ? choices[0].id || choices[0]
      : "__custom__";
    $("model_custom").style.display = choices.length ? "none" : "block";
  }
}
let modelsRequestGeneration = 0;
async function fetchModels(provider, selected = "", apiKey = "") {
  const generation = ++modelsRequestGeneration;
  $("model_status").textContent = t("model.fetching");
  try {
    const r = apiKey
      ? await fetch("/api/models", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            provider,
            api_key: apiKey,
            base_url: $("base_url").value.trim(),
          }),
        })
      : await fetch(
          `/api/models?provider=${encodeURIComponent(provider)}`,
        );
    const data = await r.json();
    // A newer request (for example another key edit) owns the UI now.
    if (generation !== modelsRequestGeneration) return;
    if (!r.ok) {
      if (Array.isArray(data.models) && data.models.length) {
        updateModelOptions(provider, selected, data.models);
        updateChatModelOptions(data.models, selected);
        updateScheduleModelOptions(data.models, "");
      }
      throw new Error(data.error || t("model.fetchError"));
    }
    // The fallback list is owned by fetchFallbackModels and the provider chosen
    // in fallback_provider_select; a primary lookup must not overwrite it.
    updateModelOptions(provider, selected, data.models);
    updateChatModelOptions(data.models, selected);
    updateScheduleModelOptions(data.models, "");
    setModelStatus("model.fetched", { count: data.models.length });
  } catch (e) {
    if (generation !== modelsRequestGeneration) return;
    updateModelOptions(provider, selected);
    updateChatModelOptions(
      MODEL_OPTIONS[provider]?.models || [],
      selected,
    );
    updateScheduleModelOptions(MODEL_OPTIONS[provider]?.models || [], "");
    setModelStatus("model.fallback", {}, e.message);
  }
}
function updateFallbackModelOptions(models, selected = "") {
  const select = $("fallback_model_select");
  const choices = models?.length ? models : [];
  select.innerHTML =
    `<option value="">${escapeHtml(t("settings.fallbackNone"))}</option>` +
    choices
      .map(
        (model) =>
          `<option value="${escapeHtml(model.id || model)}">${escapeHtml(model.name || model.id || model)}</option>`,
      )
      .join("");
  if (
    selected &&
    !choices.some((model) => (model.id || model) === selected)
  ) {
    select.insertAdjacentHTML(
      "beforeend",
      `<option value="${escapeHtml(selected)}">${escapeHtml(selected)}</option>`,
    );
  }
  select.value = selected || "";
  currentFallbackModels = choices;
  currentFallbackSelected = select.value;
}
async function fetchFallbackModels(provider, selected = "") {
  try {
    const r = await fetch(`/api/models?provider=${encodeURIComponent(provider)}`);
    const data = await r.json();
    updateFallbackModelOptions(
      r.ok && Array.isArray(data.models) ? data.models : MODEL_OPTIONS[provider]?.models || [],
      selected,
    );
  } catch (e) {
    updateFallbackModelOptions(MODEL_OPTIONS[provider]?.models || [], selected);
  }
}
function currentModel() {
  return $("model_select").value === "__custom__"
    ? $("model_custom").value.trim()
    : $("model_select").value;
}
function confirmDialog({ title, text, confirmLabel }) {
  return new Promise((resolve) => {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop open";
    const modal = document.createElement("div");
    modal.className = "modal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    const heading = document.createElement("h3");
    heading.textContent = title;
    const body = document.createElement("p");
    body.textContent = text;
    const actions = document.createElement("div");
    actions.className = "modal-actions";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "modal-cancel";
    cancel.textContent = t("common.cancel");
    const accept = document.createElement("button");
    accept.type = "button";
    accept.className = "modal-danger";
    accept.textContent = confirmLabel;
    actions.append(cancel, accept);
    modal.append(heading, body, actions);
    backdrop.append(modal);
    const trigger = document.activeElement;
    const close = (result) => {
      document.removeEventListener("keydown", onKey);
      backdrop.remove();
      // Focus goes back to whatever opened the dialog.
      if (
        trigger &&
        typeof trigger.focus === "function" &&
        document.contains(trigger)
      ) {
        trigger.focus();
      }
      resolve(result);
    };
    const onKey = (event) => {
      if (event.key === "Escape") {
        close(false);
        return;
      }
      if (event.key !== "Tab") return;
      // Keep Tab inside the dialog while it is open.
      const focusable = [cancel, accept].filter((element) => !element.disabled);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    cancel.addEventListener("click", () => close(false));
    accept.addEventListener("click", () => close(true));
    backdrop.addEventListener("click", (event) => {
      if (event.target === backdrop) close(false);
    });
    document.addEventListener("keydown", onKey);
    document.body.append(backdrop);
    accept.focus();
  });
}

$("provider").addEventListener("change", () => {
  const provider = $("provider").value;
  const previousDefault = (PROVIDER_BASE_URLS[activeProvider] ?? "").replace(
    /\/+$/,
    "",
  );
  const currentBase = $("base_url").value.trim().replace(/\/+$/, "");
  if (currentBase && currentBase !== previousDefault) {
    customBaseUrls[activeProvider] = currentBase;
  } else {
    delete customBaseUrls[activeProvider];
  }
  $("base_url").value =
    customBaseUrls[provider] ??
    PROVIDER_BASE_URLS[provider] ??
    PROVIDER_BASE_URLS.openai;
  activeProvider = provider;
  $("api_key").value = "";
  updateApiKeyHint(provider);
  fetchModels(provider);
});
let apiKeyFetchTimer = null;
$("api_key").addEventListener("input", () => {
  // Any edit (including clearing the key) makes in-flight and debounced
  // responses stale, even before a new request is started.
  modelsRequestGeneration += 1;
  clearTimeout(apiKeyFetchTimer);
  const key = $("api_key").value.trim();
  if (key.length < 8) return;
  // Fetch with the key that was just typed, before it is saved, so the
  // model selector fills in as soon as the user finishes entering it.
  const keyProvider = $("provider").value;
  apiKeyFetchTimer = setTimeout(() => {
    if ($("provider").value !== keyProvider) return;
    fetchModels(keyProvider, currentModel(), key);
  }, 700);
});
$("fallback_provider_select").addEventListener("change", (event) => {
  fetchFallbackModels(event.target.value, "");
});
$("model_select").addEventListener("change", () => {
  $("model_custom").style.display =
    $("model_select").value === "__custom__" ? "block" : "none";
  if ($("model_select").value === "__custom__") $("model_custom").focus();
});
$("chat-model-select").addEventListener("change", (event) => {
  currentChatSelected = event.target.value;
  $("header-model-name").textContent =
    event.target.value || t("model.none");
  event.target.title = event.target.value
    ? `${t("chat.modelTitle")}: ${event.target.value}`
    : t("chat.modelTitle");
});
$("schedule-model").addEventListener("change", (event) => {
  currentScheduleSelected = event.target.value;
});
$("fallback_model_select").addEventListener("change", (event) => {
  currentFallbackSelected = event.target.value;
});
function updateChatModelOptions(models, selected = "") {
  const select = $("chat-model-select");
  const choices = models?.length ? models : [];
  if (!choices.length) {
    select.innerHTML = `<option value="${escapeHtml(selected)}">${escapeHtml(selected || t("model.none"))}</option>`;
    select.value = selected;
    currentChatModels = [];
    currentChatSelected = selected;
    return;
  }
  select.innerHTML = choices
    .map(
      (model) =>
        `<option value="${escapeHtml(model.id || model)}">${escapeHtml(model.name || model.id || model)}</option>`,
    )
    .join("");
  const selectedIsListed =
    selected && choices.some((model) => (model.id || model) === selected);
  if (selected && !selectedIsListed) {
    // Keep the configured model selectable even when the provider's list
    // does not include it, so sending never silently switches models.
    select.insertAdjacentHTML(
      "beforeend",
      `<option value="${escapeHtml(selected)}">${escapeHtml(selected)}</option>`,
    );
  }
  if (selected) select.value = selected;
  currentChatModels = choices;
  currentChatSelected = select.value;
}
function updateSendState() {
  const isCommand = $("input").value.trim().startsWith("/");
  $("send").disabled =
    chatBusy || (!connectionState.connected && !isCommand);
}
function updateConnectionUi() {
  const status = document.querySelector(".status");
  const label = $("header-model-name");
  const modelName = connectionState.model || t("model.none");
  label.textContent = modelName;
  if (status) {
    status.textContent = connectionState.connected
      ? t("status.ready")
      : t("status.notReady");
    status.classList.toggle("offline", !connectionState.connected);
    status.title = connectionState.connected
      ? t("status.connectedTitle", { model: modelName })
      : connectionState.reason || t("status.notConnectedReason");
  }
  $("input").disabled = false;
  $("input").placeholder = connectionState.connected
    ? t("chat.placeholder")
    : connectionState.reason || t("status.inputDisabled");
  updateSendState();
  $("chat-model-select").disabled = !connectionState.connected;
}
function setConnectionState(
  connected,
  model = "",
  reason = "",
  provider = "",
) {
  connectionState = {
    connected: !!connected,
    model,
    reason,
    provider: provider || connectionState.provider || "",
    known: true,
  };
  updateConnectionUi();
}
async function refreshConnectionState() {
  try {
    const r = await fetch(
      `/api/status?lang=${encodeURIComponent(currentLanguage)}`,
    );
    const data = await r.json();
    setConnectionState(
      !!data.ready,
      data.model || "",
      data.reason || "",
      data.provider || "",
    );
    return data;
  } catch (e) {
    setConnectionState(false, "", t("status.checkFailed"));
    return null;
  }
}
function applyChatMeta(settings) {
  if ("thinking_level" in settings) {
    $("chat-thinking-level").value = settings.thinking_level ?? "off";
  }
  if (Array.isArray(settings.available_skills)) {
    availableSkills = settings.available_skills.map((item) => item.name);
  }
  if (Array.isArray(settings.skills)) {
    defaultSkills = settings.skills.map(String);
  }
  if (pendingSkill && !availableSkills.includes(pendingSkill)) {
    clearPendingSkill();
  }
  if (settings.provider) {
    connectionState.provider = settings.provider;
  }
  updateChatModelOptions([], settings.model ?? "");
}
async function loadChatMeta() {
  try {
    const r = await fetch("/api/settings");
    const s = await r.json();
    applyChatMeta(s);
    await fetchModels(s.provider ?? "openai", s.model ?? "");
    await refreshConnectionState();
  } catch (e) {
    updateChatModelOptions([], t("chatModel.notConnected"));
    setConnectionState(
      false,
      t("chatModel.notConnected"),
      t("status.settingsLoadFailed"),
    );
  }
}
let currentAuthStatus = { enabled: null, authenticated: false };
let currentAuthSessions = [];
let currentAuthConfirmed = false;
let currentAuthOffline = "";
let authLoadSequence = 0;
function formatAuthTime(value) {
  if (!value) return t("auth.unknownTime");
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? t("auth.unknownTime")
    : parsed.toLocaleString();
}
function renderAuthSessions(status = null, items = null, offlineKey = "") {
  const fromLoad =
    Boolean(status) || Array.isArray(items) || Boolean(offlineKey);
  if (status) {
    currentAuthStatus = status;
    currentAuthConfirmed = typeof status.enabled === "boolean";
  }
  if (Array.isArray(items)) currentAuthSessions = items;
  if (fromLoad) currentAuthOffline = offlineKey;
  const container = $("auth-sessions");
  const keyButton = $("auth-generate-key");
  container.innerHTML = "";
  if (currentAuthOffline) {
    const failure = document.createElement("p");
    failure.className = "hint";
    failure.textContent = t(currentAuthOffline);
    container.appendChild(failure);
  }
  if (currentAuthConfirmed && currentAuthStatus.enabled === false) {
    keyButton.disabled = true;
    const note = document.createElement("p");
    note.className = "hint";
    note.textContent = t("auth.disabled");
    container.appendChild(note);
    return;
  }
  keyButton.disabled = !currentAuthConfirmed || Boolean(currentAuthOffline);
  if (!currentAuthSessions.length) {
    if (currentAuthConfirmed && !currentAuthOffline) {
      const empty = document.createElement("p");
      empty.className = "hint";
      empty.textContent = t("auth.empty");
      container.appendChild(empty);
    }
    return;
  }
  currentAuthSessions.forEach((item) => {
    const row = document.createElement("div");
    row.className = "auth-session-row";
    const info = document.createElement("div");
    info.className = "auth-session-info";
    const label = document.createElement("strong");
    label.textContent = item.label || t("auth.deviceFallback");
    const meta = document.createElement("small");
    const prefix = item.current ? `${t("auth.thisDevice")} · ` : "";
    meta.textContent = `${prefix}${t("auth.lastSeen", {
      time: formatAuthTime(item.last_seen_at),
    })}`;
    info.append(label, meta);
    const action = document.createElement("button");
    action.type = "button";
    action.className = item.current ? "danger" : "secondary";
    action.textContent = item.current
      ? t("auth.logout")
      : t("auth.revoke");
    action.addEventListener("click", () =>
      item.current ? authLogout() : revokeAuthSession(item.id),
    );
    row.append(info, action);
    container.appendChild(row);
  });
}
async function loadAuthSessions() {
  const loadId = ++authLoadSequence;
  try {
    const [statusResponse, sessionsResponse] = await Promise.all([
      fetch("/api/auth/status"),
      fetch("/api/auth/sessions"),
    ]);
    if (!statusResponse.ok || !sessionsResponse.ok) {
      throw new Error("auth.offline");
    }
    const [status, data] = await Promise.all([
      statusResponse.json(),
      sessionsResponse.json(),
    ]);
    if (
      typeof status.enabled !== "boolean" ||
      !Array.isArray(data.items)
    ) {
      throw new Error("auth.offline");
    }
    if (loadId !== authLoadSequence) return;
    renderAuthSessions(status, data.items);
  } catch (error) {
    if (loadId !== authLoadSequence) return;
    renderAuthSessions(null, null, "auth.offline");
  }
}
async function createPairingKey() {
  $("auth-generate-key").disabled = true;
  try {
    const response = await fetch("/api/auth/pairing-keys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || t("auth.keyFailed"));
    $("auth-key-output").hidden = false;
    $("auth-key-value").textContent = data.key;
    $("auth-key-expiry").textContent = t("auth.keyExpiry", {
      time: formatAuthTime(data.expires_at),
      minutes: data.ttl_minutes ?? "",
    });
    showNotice(t("auth.keyCreated"));
  } catch (error) {
    showNotice(error.message || t("auth.keyFailed"), true);
  } finally {
    $("auth-generate-key").disabled = false;
  }
}
async function revokeAuthSession(sessionId) {
  try {
    const response = await fetch(
      `/api/auth/sessions/${encodeURIComponent(sessionId)}`,
      { method: "DELETE" },
    );
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || t("auth.revokeFailed"));
    }
    showNotice(t("auth.revoked"));
    await loadAuthSessions();
  } catch (error) {
    showNotice(error.message || t("auth.revokeFailed"), true);
  }
}
async function authLogout() {
  try {
    const response = await fetch("/api/auth/logout", { method: "POST" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || t("auth.logoutFailed"));
    }
    window.location.href = data.redirect || "/pair";
  } catch (error) {
    showNotice(error.message || t("auth.logoutFailed"), true);
  }
}
$("auth-generate-key").addEventListener("click", createPairingKey);
$("auth-logout").addEventListener("click", authLogout);
let customApiKeys = [];
function renderCustomApiKeys() {
  const container = $("custom-keys");
  if (!container) return;
  container.innerHTML = "";
  if (!customApiKeys.length) {
    const empty = document.createElement("p");
    empty.className = "hint custom-key-empty";
    empty.textContent = t("settings.customKeysEmpty");
    container.appendChild(empty);
    return;
  }
  customApiKeys.forEach((item) => {
    const row = document.createElement("div");
    row.className = "custom-key-row";
    const info = document.createElement("div");
    info.className = "auth-session-info";
    const name = document.createElement("strong");
    name.textContent = item.name;
    const meta = document.createElement("small");
    meta.textContent = t("settings.customKeySaved");
    info.append(name, meta);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger";
    remove.textContent = t("settings.customKeyDelete");
    remove.setAttribute(
      "aria-label",
      t("settings.customKeyDeleteAria", { name: item.name }),
    );
    remove.addEventListener("click", () => deleteCustomApiKey(item.name));
    row.append(info, remove);
    container.appendChild(row);
  });
}
async function refreshCustomApiKeys() {
  try {
    const response = await fetch("/api/settings");
    if (!response.ok) return;
    const settings = await response.json();
    customApiKeys = Array.isArray(settings.custom_api_keys)
      ? settings.custom_api_keys
      : [];
    renderCustomApiKeys();
  } catch (error) {
    // Keep the list that is already shown when the refresh fails.
    console.warn(t("settings.customKeyAddFailed"), error);
  }
}
async function saveCustomApiKey() {
  const name = $("custom-key-name").value.trim();
  const value = $("custom-key-value").value.trim();
  if (!name || !value) {
    showNotice(t("settings.customKeyNameRequired"), true);
    return;
  }
  try {
    const response = await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ custom_api_key: { name, value } }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || t("settings.customKeyAddFailed"));
    }
    $("custom-key-name").value = "";
    $("custom-key-value").value = "";
    await refreshCustomApiKeys();
    showNotice(t("settings.customKeyAdded"));
  } catch (error) {
    showNotice(error.message || t("settings.customKeyAddFailed"), true);
  }
}
async function deleteCustomApiKey(name) {
  try {
    const response = await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ delete_custom_api_key: name }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || t("settings.customKeyAddFailed"));
    }
    await refreshCustomApiKeys();
    showNotice(t("settings.customKeyDeleted"));
  } catch (error) {
    showNotice(error.message || t("settings.customKeyAddFailed"), true);
  }
}
function updateApiKeyHint(provider) {
  const label =
    { openai: "OpenAI", gemini: "Gemini", anthropic: "Anthropic" }[
      provider
    ] || provider;
  const has = keyProviders.includes(provider);
  $("api_key").placeholder = has
    ? t("apiKey.hasPlaceholder", { provider: label })
    : t("apiKey.missingPlaceholder", { provider: label });
  $("api_key_hint").textContent = has
    ? t("apiKey.hasHint", { provider: label })
    : t("apiKey.missingHint", { provider: label });
}
function updateDiscordTokenHint() {
  $("discord_token_hint").textContent = hasDiscordToken
    ? t("settings.discordTokenHintHas")
    : t("settings.discordTokenHintMissing");
}
async function loadSettings() {
  let s;
  try {
    const r = await fetch("/api/settings");
    // An expired session answers with HTML, which json() would fail on; report
    // the status instead of an unhandled rejection.
    if (!r.ok) throw new Error(`${r.status}`);
    s = await r.json();
  } catch (error) {
    showNotice(t("settings.loadFailed", { error: error.message }), true);
    return;
  }
  availableSkills = (s.available_skills || []).map((skill) => skill.name);
  defaultSkills = Array.isArray(s.skills) ? s.skills.map(String) : [];
  connectionState.provider = s.provider ?? connectionState.provider;
  if (pendingSkill && !availableSkills.includes(pendingSkill)) {
    clearPendingSkill();
  }
  $("agent_name").value = s.agent_name ?? "Mux";
  $("agent_role").value = s.agent_role ?? "A versatile AI assistant";
  $("response_language").value = s.response_language ?? "auto";
  $("response_style").value = s.response_style ?? "Friendly, concise, and clear";
  $("use_markdown").checked = s.use_markdown !== false;
  $("ask_clarifying_questions").checked = s.ask_clarifying_questions !== false;
  keyProviders = Array.isArray(s.key_providers) ? s.key_providers : [];
  customApiKeys = Array.isArray(s.custom_api_keys) ? s.custom_api_keys : [];
  renderCustomApiKeys();
  $("provider").value = s.provider ?? "openai";
  $("base_url").value =
    s.base_url ||
    PROVIDER_BASE_URLS[s.provider ?? "openai"] ||
    PROVIDER_BASE_URLS.openai;
  activeProvider = $("provider").value;
  const loadedBase = $("base_url").value.trim().replace(/\/+$/, "");
  // A masked Base URL still carries credentials on the server; remembering it
  // as this provider's URL would send the mask back on the next provider switch.
  if (
    loadedBase &&
    !loadedBase.includes("••") &&
    loadedBase !== (PROVIDER_BASE_URLS[activeProvider] ?? "")
  ) {
    customBaseUrls[activeProvider] = loadedBase;
  }
  $("system_prompt").value = s.system_prompt ?? "";
  $("memory_review").value = s.memory_review ?? "";
  const skillsSelect = $("skills");
  skillsSelect.innerHTML = "";
  (s.available_skills || []).forEach((skill) => {
    const option = document.createElement("option");
    option.value = skill.name;
    option.textContent = skill.name;
    option.selected = Array.isArray(s.skills) && s.skills.includes(skill.name);
    skillsSelect.appendChild(option);
  });
  $("temperature").value = s.temperature ?? 0.7;
  $("max_tokens").value = s.max_tokens ?? 2048;
  $("top_p").value = s.top_p ?? 1;
  $("thinking_level").value = s.thinking_level ?? "off";
  $("chat-thinking-level").value = s.thinking_level ?? "off";
  $("stream").checked = !!s.stream;
  $("fallback_enabled").checked = !!s.fallback_enabled;
  $("fallback_provider_select").value = s.fallback_provider ?? "openai";
  geminiSettings.liveModel = s.gemini_live_model || "";
  geminiSettings.agent = s.gemini_agent || "";
  geminiSettings.decisionModel = s.gemini_decision_model || "";
  $("gemini-agent").value = geminiSettings.agent;
  $("gemini-agent-id").value =
    geminiSettings.agent || "antigravity-preview-09-2026";
  $("gemini-decision-model").value = geminiSettings.decisionModel;
  renderGeminiLiveModels([]);
  if ((s.provider ?? "openai") === "gemini") loadGeminiCapabilities();
  else renderGeminiCapabilities(geminiCapabilityReport);
  $("discord_enabled").checked = !!s.discord_enabled;
  $("machine_access").checked = s.machine_access !== false;
  $("discord_prefix").value = s.discord_prefix ?? "!ai";
  $("discord_allowed_channels").value = Array.isArray(
    s.discord_allowed_channels,
  )
    ? s.discord_allowed_channels.join(", ")
    : s.discord_allowed_channels || "";
  $("discord_allowed_users").value = Array.isArray(s.discord_allowed_users)
    ? s.discord_allowed_users.join(", ")
    : s.discord_allowed_users || "";
  const memory = s.memory || {};
  $("memory_enabled").checked = memory.enabled !== false;
  $("memory_schedule").value = memory.schedule || "0 3 * * *";
  $("memory_window_end").value = memory.window_end || "06:00";
  $("memory_lookback").value = memory.lookback_days ?? 7;
  $("memory_threshold").value = memory.threshold ?? 0.65;
  $("memory_idle").value = memory.idle_minutes ?? 15;
  $("memory_max_items").value = memory.max_items ?? 25;
  $("memory_max_entries").value = memory.max_entries ?? 200;
  $("memory_retrieval").checked = memory.retrieval !== false;
  $("memory_retrieval_items").value = memory.retrieval_items ?? 4;
  $("memory_retrieval_chars").value = memory.retrieval_chars ?? 800;
  $("memory_include_locked").checked = !!memory.include_locked;
  $("memory_llm").checked = memory.llm !== false;
  $("memory_provider").value = memory.provider || "";
  $("memory_model").value = memory.model || "";
  $("memory_base_url").value = memory.base_url || "";
  // The Memory panel shows the detected capabilities and paths; a status read
  // fills them without waiting for the user to open the Memory page.
  fetch("/api/memory/status")
    .then((response) => (response.ok ? response.json() : null))
    .then((status) => {
      if (status) renderMemoryStatus(status);
    })
    .catch(() => {});
  $("discord_token").value = "";
  hasDiscordToken = !!s.has_discord_token;
  updateDiscordTokenHint();
  updateFallbackModelOptions([], s.fallback_model ?? "");
  $("api_key").value = "";
  updateApiKeyHint($("provider").value);
  await fetchModels($("provider").value, s.model ?? "");
  await fetchFallbackModels(
    $("fallback_provider_select").value,
    s.fallback_model ?? "",
  );
  updateRanges();
}
function updateRanges() {
  $("temp-label").textContent = $("temperature").value;
  $("temperature-value").textContent = $("temperature").value;
  $("top-label").textContent = $("top_p").value;
  $("top_p-value").textContent = $("top_p").value;
}
$("temperature").addEventListener("input", updateRanges);
$("top_p").addEventListener("input", updateRanges);
function collectSettingsBody() {
  return {
    agent_name: $("agent_name").value,
    agent_role: $("agent_role").value,
    response_language: $("response_language").value,
    response_style: $("response_style").value,
    use_markdown: $("use_markdown").checked,
    ask_clarifying_questions: $("ask_clarifying_questions").checked,
    provider: $("provider").value,
    model: currentModel(),
    base_url: $("base_url").value,
    system_prompt: $("system_prompt").value,
    memory_review: $("memory_review").value,
    skills: Array.from($("skills").selectedOptions).map((option) => option.value),
    api_key: $("api_key").value,
    temperature: Number($("temperature").value),
    top_p: Number($("top_p").value),
    max_tokens: Number($("max_tokens").value),
    thinking_level: $("thinking_level").value,
    stream: $("stream").checked,
    fallback_enabled: $("fallback_enabled").checked,
    fallback_provider: $("fallback_provider_select").value,
    fallback_model: $("fallback_model_select").value,
    gemini_live_model: $("gemini-live-model").value,
    gemini_agent: $("gemini-agent").value,
    gemini_decision_model: $("gemini-decision-model").value,
    discord_enabled: $("discord_enabled").checked,
    discord_token: $("discord_token").value,
    discord_prefix: $("discord_prefix").value,
    discord_allowed_channels: $("discord_allowed_channels").value,
    discord_allowed_users: $("discord_allowed_users").value,
    machine_access: $("machine_access").checked,
    memory: {
      enabled: $("memory_enabled").checked,
      schedule: $("memory_schedule").value.trim(),
      window_end: $("memory_window_end").value.trim() || "06:00",
      lookback_days: memoryNumber("memory_lookback", 7),
      threshold: memoryNumber("memory_threshold", 0.65),
      idle_minutes: memoryNumber("memory_idle", 15),
      max_items: memoryNumber("memory_max_items", 25),
      max_entries: memoryNumber("memory_max_entries", 200),
      retrieval: $("memory_retrieval").checked,
      retrieval_items: memoryNumber("memory_retrieval_items", 4),
      retrieval_chars: memoryNumber("memory_retrieval_chars", 800),
      include_locked: $("memory_include_locked").checked,
      llm: $("memory_llm").checked,
      provider: $("memory_provider").value,
      model: $("memory_model").value.trim(),
      base_url: $("memory_base_url").value.trim(),
    },
  };
}
$("add-custom-key").addEventListener("click", saveCustomApiKey);
$("custom-key-value").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    saveCustomApiKey();
  }
});
$("save").addEventListener("click", async () => {
  const body = collectSettingsBody();
  const apiKey = body.api_key.trim();
  const restoreSaveButton = () => {
    $("save").disabled = false;
    $("save").textContent = t("settings.save");
  };
  try {
    if (apiKey && apiKey !== "••••••••") {
      $("save").disabled = true;
      $("save").textContent = t("notice.testing");
      const testResponse = await fetch("/api/settings/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const testData = await testResponse.json();
      if (!testResponse.ok || !testData.ok) {
        showNotice(
          t("notice.testFailed", {
            error: testData.error || t("notice.settingsSaveFailed"),
          }),
          true,
        );
        return;
      }
    }
    const r = await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    let result = {};
    try {
      result = await r.json();
    } catch (_error) {
      result = {};
    }
    // The server explains why a save was rejected (invalid cron, bad Discord
    // IDs); showing "Could not save" alone hides the fixable detail.
    showNotice(
      r.ok
        ? t("notice.settingsSaved")
        : result.error || t("notice.settingsSaveFailed"),
      !r.ok,
    );
    if (r.ok) {
      await loadSettings();
      applyChatMeta({
        thinking_level: $("thinking_level").value,
        model: $("model_select").value === "__custom__"
          ? $("model_custom").value.trim()
          : $("model_select").value,
      });
      await refreshConnectionState();
    }
  } catch (error) {
    showNotice(t("notice.settingsSaveFailed"), true);
  } finally {
    restoreSaveButton();
  }
});
// Update section: runs the project's update.sh through the server API.
const UPDATE_POLL_MS = 2000;
const UPDATE_POLL_ATTEMPTS = 90;
const updateState = {
  loaded: false,
  running: false,
  pending: false,
  restarting: false,
  error: "",
  job: { mode: "", started_at: "", finished_at: "", ok: null, exit_code: null },
  log: "",
  logTruncated: false,
  appUpdatedAt: "",
  scriptAvailable: false,
};
let updatePollTimer = null;
function updateJobFinished() {
  return Boolean(updateState.job && updateState.job.finished_at);
}
function updateStatusText() {
  if (updateState.restarting) return t("settings.updateRestarting");
  if (updateState.error) return updateState.error;
  if (!updateState.loaded) return t("settings.updateLoading");
  if (updateState.running) {
    return t("settings.updateRunning", {
      mode: t(
        updateState.job.mode === "check"
          ? "settings.updateModeCheck"
          : "settings.updateModeApply",
      ),
    });
  }
  if (updateJobFinished()) {
    const key =
      updateState.job.mode === "check"
        ? "settings.updateCheckDone"
        : "settings.updateDone";
    if (updateState.job.ok === true)
      return t(key, { time: updateState.job.finished_at });
    if (updateState.job.ok === false)
      return t("settings.updateError", {
        code: updateState.job.exit_code ?? "?",
      });
    return t("settings.updateFinishedUnknown");
  }
  return t("settings.updateIdle");
}
function renderUpdatePanel() {
  if (!$("update-log")) return;
  $("update-app-updated").textContent =
    updateState.appUpdatedAt || t("settings.updateUnknown");
  $("update-script-state").textContent = updateState.scriptAvailable
    ? t("settings.updateScriptReady")
    : t("settings.updateScriptMissing");
  $("update-script-state").classList.toggle(
    "is-missing",
    updateState.loaded && !updateState.scriptAvailable,
  );
  const status = $("update-status");
  status.textContent = updateStatusText();
  status.classList.toggle("restarting", updateState.restarting);
  status.classList.toggle(
    "error",
    !updateState.restarting &&
      (Boolean(updateState.error) ||
        (updateJobFinished() && updateState.job.ok === false)),
  );
  const busy = updateState.running || updateState.pending;
  $("update-check").disabled = busy;
  $("update-run").disabled =
    busy || (updateState.loaded && !updateState.scriptAvailable);
  const log = $("update-log");
  log.classList.toggle("is-empty", !updateState.log);
  log.textContent = updateState.log
    ? updateState.logTruncated
      ? `${t("settings.updateLogTruncated")}\n\n${updateState.log}`
      : updateState.log
    : t("settings.updateLogEmpty");
}
async function loadUpdateState() {
  try {
    const response = await fetch("/api/update");
    if (!response.ok) throw new Error(t("settings.updateLoadFailed"));
    const data = await response.json();
    updateState.loaded = true;
    updateState.error = "";
    updateState.restarting = false;
    updateState.running = Boolean(data.running);
    updateState.job = data.job || updateState.job;
    updateState.log = data.log || "";
    updateState.logTruncated = Boolean(data.log_truncated);
    updateState.appUpdatedAt = data.app_updated_at || "";
    updateState.scriptAvailable = Boolean(data.script_available);
  } catch (error) {
    if (updateState.pending) {
      // The updater restarts the server, so a failed request is expected here.
      updateState.restarting = true;
      updateState.error = "";
    } else {
      updateState.error = error.message || t("settings.updateLoadFailed");
    }
  }
  renderUpdatePanel();
}
function pollUpdateState(attempt = 0) {
  clearTimeout(updatePollTimer);
  updatePollTimer = setTimeout(async () => {
    await loadUpdateState();
    if (updateState.restarting || updateState.error) {
      // The server is restarting; keep retrying for a while.
      if (attempt < UPDATE_POLL_ATTEMPTS) pollUpdateState(attempt + 1);
      else {
        // Out of retries: drop the stale busy/restarting state so the section
        // shows an error and its buttons (the retry action) stay usable.
        updateState.pending = false;
        updateState.running = false;
        updateState.restarting = false;
        updateState.error = t("settings.updateLoadFailed");
        renderUpdatePanel();
      }
      return;
    }
    if (updateState.running) {
      pollUpdateState(attempt);
      return;
    }
    if (updateJobFinished()) {
      // The updater may still be writing its final line after the restart.
      if (updateState.job.ok === null && attempt < 5) {
        pollUpdateState(attempt + 1);
        return;
      }
      updateState.pending = false;
      renderUpdatePanel();
      const ok = updateState.job.ok;
      showNotice(
        ok === true
          ? t("settings.updateDone", { time: updateState.job.finished_at })
          : ok === false
            ? t("settings.updateError", {
                code: updateState.job.exit_code ?? "?",
              })
            : t("settings.updateFinishedUnknown"),
        ok === false,
      );
      return;
    }
    if (attempt < 3) pollUpdateState(attempt + 1);
    else {
      updateState.pending = false;
      renderUpdatePanel();
    }
  }, UPDATE_POLL_MS);
}
async function startUpdate(mode) {
  if (
    mode === "apply" &&
    !(await confirmDialog({
      title: t("common.confirmTitle"),
      text: t("settings.updateConfirm"),
      confirmLabel: t("common.confirm"),
    }))
  )
    return;
  updateState.error = "";
  updateState.restarting = false;
  updateState.running = true;
  updateState.pending = true;
  updateState.job = { mode, started_at: "", finished_at: "", ok: null, exit_code: null };
  renderUpdatePanel();
  try {
    const response = await fetch("/api/update/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok)
      throw new Error(data.error || t("settings.updateFailed"));
    showNotice(
      mode === "check"
        ? t("settings.updateCheckStarted")
        : t("settings.updateRunStarted"),
    );
    pollUpdateState();
  } catch (error) {
    updateState.running = false;
    updateState.pending = false;
    updateState.error = error.message || t("settings.updateFailed");
    renderUpdatePanel();
    showNotice(updateState.error, true);
  }
}
$("update-check").addEventListener("click", () => startUpdate("check"));
$("update-run").addEventListener("click", () => startUpdate("apply"));
// Keep the panel live if the page opened while an update (or its restart) runs.
loadUpdateState().then(() => {
  if (updateState.running) pollUpdateState();
});
$("create-skill").addEventListener("click", async () => {
  const name = $("new-skill-name").value.trim();
  const description = $("new-skill-description").value.trim();
  const content = $("new-skill-content").value.trim();
  if (!name || !content) return;
  if (!description) {
    showNotice(t("settings.newSkillDescriptionRequired"), true);
    $("new-skill-description").focus();
    return;
  }
  const r = await fetch("/api/skills", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description, content }),
  });
  if (!r.ok) {
    const data = await r.json();
    showNotice(data.error || t("settings.createSkillFailed"), true);
    return;
  }
  $("new-skill-name").value = "";
  $("new-skill-description").value = "";
  $("new-skill-content").value = "";
  await loadSettings();
  showNotice(t("settings.createSkillDone"));
});
$("skills").addEventListener("change", async () => {
  const name = $("skills").value;
  if (!name) return;
  const response = await fetch(`/api/skills/${encodeURIComponent(name)}`);
  if (!response.ok) return;
  const data = await response.json();
  $("new-skill-name").value = data.name;
  $("new-skill-description").value = data.description || "";
  $("new-skill-content").value = data.content;
});
$("update-skill").addEventListener("click", async () => {
  const name = $("skills").value;
  if (!name) return;
  const response = await fetch(`/api/skills/${encodeURIComponent(name)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      description: $("new-skill-description").value,
      content: $("new-skill-content").value,
    }),
  });
  if (response.ok) showNotice(t("settings.skillSaved"));
});
$("delete-skill").addEventListener("click", async () => {
  const name = $("skills").value;
  if (!name) return;
  if (
    !(await confirmDialog({
      title: t("common.confirmTitle"),
      text: t("settings.deleteSkillConfirm"),
      confirmLabel: t("common.confirm"),
    }))
  )
    return;
  const response = await fetch(`/api/skills/${encodeURIComponent(name)}`, { method: "DELETE" });
  if (response.ok) {
    await loadSettings();
    $("new-skill-name").value = "";
    $("new-skill-description").value = "";
    $("new-skill-content").value = "";
    showNotice(t("settings.skillDeleted"));
  }
});
$("test").addEventListener("click", async () => {
  $("test").disabled = true;
  $("test").textContent = t("notice.testing");
  try {
    // Send the form values so an API key that is typed but not saved yet
    // can still be tested.
    const r = await fetch("/api/settings/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectSettingsBody()),
    });
    const data = await r.json();
    showNotice(
      data.ok
        ? t("notice.testSuccess", { answer: data.answer })
        : t("notice.testFailed", { error: data.error }),
      !data.ok,
    );
    await refreshConnectionState();
  } catch (error) {
    showNotice(t("notice.testFailed", { error: error.message }), true);
  } finally {
    $("test").disabled = false;
    $("test").textContent = t("settings.test");
  }
});
function escapeHtml(value) {
  return String(value).replace(
    /[&<>'"]/g,
    (character) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "'": "&#39;",
        '\"': "&quot;",
      })[character],
  );
}
const HISTORY_ITEM_ICON =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>';
// Pinned conversations carry a red pushpin, so the state still reads in the
// icon-only rail where the "Pinned" heading is hidden.
const HISTORY_PIN_ICON =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M16 9V4h1c.55 0 1-.45 1-1s-.45-1-1-1H7c-.55 0-1 .45-1 1s.45 1 1 1h1v5c0 1.66-1.34 3-3 3v2h5.97v7l1 1 1-1v-7H19v-2c-1.66 0-3-1.34-3-3z" /></svg>';
function historyRows(items) {
  return items
    .map((item) => {
      const title = escapeHtml(item.title || t("history.untitled"));
      const ariaLabel = item.pinned
        ? `${title} · ${escapeHtml(t("history.pinned"))}`
        : title;
      const classes = [
        "history-row",
        item.id === conversationId ? "active" : "",
        item.pinned ? "is-pinned" : "",
      ]
        .filter(Boolean)
        .join(" ");
      const pin = item.pinned
        ? `<span class="history-pin">${HISTORY_PIN_ICON}</span>`
        : "";
      const lockedBadge = item.locked
        ? `<span class="history-lock">${ICONS.lock}</span>`
        : "";
      const renameLabel = escapeHtml(t("history.rename"));
      const pinLabel = escapeHtml(
        item.pinned ? t("history.unpin") : t("history.pin"),
      );
      const lockLabel = escapeHtml(
        item.locked ? t("history.unlock") : t("history.lock"),
      );
      const deleteLabel = escapeHtml(t("history.delete"));
      return `<div class="${classes}" data-history-row="${escapeHtml(item.id)}"><button class="history-item" data-history-id="${escapeHtml(item.id)}" title="${title}" aria-label="${ariaLabel}"><span class="history-icon">${HISTORY_ITEM_ICON}</span><span class="history-label">${pin}${lockedBadge}${title}</span></button><div class="history-actions"><button class="history-action" data-history-action="rename" data-history-id="${escapeHtml(item.id)}" title="${renameLabel}" aria-label="${renameLabel}">${ICONS.edit}</button><button class="history-action" data-history-action="${item.pinned ? "unpin" : "pin"}" data-history-id="${escapeHtml(item.id)}" title="${pinLabel}" aria-label="${pinLabel}">${item.pinned ? ICONS.pinFilled : ICONS.pin}</button><button class="history-action" data-history-action="${item.locked ? "unlock" : "lock"}" data-history-id="${escapeHtml(item.id)}" title="${lockLabel}" aria-label="${lockLabel}">${item.locked ? ICONS.unlock : ICONS.lock}</button><button class="history-action" data-history-action="delete" data-history-id="${escapeHtml(item.id)}" title="${deleteLabel}" aria-label="${deleteLabel}">${ICONS.trash}</button></div></div>`;
    })
    .join("");
}
function renderHistoryList(items) {
  currentHistoryItems = items;
  const pinned = items.filter((item) => item.pinned);
  const grouped = {};
  items
    .filter((item) => !item.pinned)
    .forEach((item) => {
      const day =
        (item.updated_at || "").slice(0, 10) || t("history.unknownDate");
      (grouped[day] ||= []).push(item);
    });
  const pinnedHtml = pinned.length
    ? `<div class="history-day"><span class="history-pin">${HISTORY_PIN_ICON}</span>${escapeHtml(t("history.pinned"))}</div>${historyRows(pinned)}`
    : "";
  const daysHtml = Object.entries(grouped)
    .map(
      ([day, dayItems]) =>
        `<div class="history-day">${escapeHtml(day)}</div>${historyRows(dayItems)}`,
    )
    .join("");
  $("history-list").innerHTML =
    pinnedHtml + daysHtml ||
    `<div class="history-day">${escapeHtml(t("history.empty"))}</div>`;
}
async function loadHistoryList() {
  try {
    const response = await fetch("/api/history");
    if (!response.ok) throw new Error(`${response.status}`);
    renderHistoryList((await response.json()).items || []);
    if (pendingHistoryAppends.size) flushPendingAppends();
  } catch (error) {
    showNotice(t("history.loadFailed", { error: error.message }), true);
  }
}
async function openConversation(id) {
  const loadToken = ++historyLoadToken;
  if (pendingHistoryAppends.has(id)) await flushPendingAppends(id);
  const response = await fetch(`/api/history/${id}`);
  if (!response.ok) return;
  const record = await response.json();
  if (loadToken !== historyLoadToken) return;
  invalidateChatSession();
  conversationId = record.id;
  conversationCreatedAt = record.created_at;
  conversationGeneration = record.generation || record.created_at;
  setConversationTitle(
    record.title ||
      record.messages?.find((message) => message.role === "user")
        ?.content,
  );
  const recordMessages = Array.isArray(record.messages)
    ? record.messages
    : [];
  messages.splice(0, messages.length, ...recordMessages);
  // Deadlines are rebuilt from the server clock that came with this record, so
  // a browser clock that is off cannot hide an approval the server accepts.
  recordMessages.forEach((message) =>
    stampApprovalDeadline(message, record.server_time),
  );
  persistedMessageCount = recordMessages.length;
  seedPromptHistory(recordMessages);
  const pending = pendingHistoryAppends.get(id)?.messages || [];
  if (pending.length) {
    const savedIds = new Set(
      recordMessages.map((message) => message.message_id).filter(Boolean),
    );
    const recovered = pending.filter(
      (message) =>
        !message.message_id || !savedIds.has(message.message_id),
    );
    if (recovered.length) {
      messages.push(...recovered);
      showNotice(t("chat.saveWarning"), true);
    } else {
      pendingHistoryAppends.delete(id);
    }
  }
  emptyConversationMode = "new";
  renderMessages();
  renderHistoryList(
    (await (await fetch("/api/history")).json()).items || [],
  );
  document.querySelector('[data-view="chat"]').click();
}
async function updateHistory(id, body) {
  const response = await fetch(`/api/history/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(data.error || t("history.renameFailed"));
  await loadHistoryList();
  return data;
}
async function deleteHistory(id) {
  const response = await fetch(`/api/history/${id}`, {
    method: "DELETE",
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(data.error || t("history.deleteFailed"));
  pendingHistoryAppends.delete(id);
  if (id === conversationId) {
    invalidateChatSession();
    conversationId = null;
    conversationCreatedAt = null;
    conversationGeneration = null;
    persistedMessageCount = 0;
    messages.splice(0, messages.length);
    emptyConversationMode = "deleted";
    // The deleted conversation must not keep naming the page header.
    setConversationTitle(null);
    renderMessages();
  }
  await loadHistoryList();
}
let historyModalAction = null;
let historyModalTrigger = null;
let historyModalId = null;
function refreshHistoryModalText() {
  $("history-modal-title").textContent =
    historyModalAction === "rename"
      ? t("history.renameTitle")
      : t("history.deleteTitle");
  $("history-modal-text").textContent =
    historyModalAction === "rename"
      ? t("history.renameDescription")
      : t("history.deleteConfirm");
  $("history-modal-confirm").textContent =
    historyModalAction === "rename" ? t("common.save") : t("common.delete");
  $("history-modal-confirm").className =
    historyModalAction === "rename" ? "" : "modal-danger";
  if (historyModalAction === "rename") $("history-modal-input").focus();
}
function openHistoryModal(action, id, title = "") {
  historyModalAction = action;
  historyModalId = id;
  // Remember what opened the dialog so focus can go back there on close.
  historyModalTrigger = document.activeElement;
  $("history-modal").classList.add("open");
  $("history-modal-input").style.display =
    action === "rename" ? "block" : "none";
  $("history-modal-confirm").style.display =
    action === "error" ? "none" : "block";
  $("history-modal-input").value = title;
  refreshHistoryModalText();
  // Move focus into the dialog: the name field for rename, otherwise the
  // action the user is about to confirm.
  if (action === "rename") {
    $("history-modal-input").focus();
  } else {
    const confirmButton = $("history-modal-confirm");
    (confirmButton.style.display === "none"
      ? $("history-modal-cancel")
      : confirmButton
    ).focus();
  }
}
function closeHistoryModal() {
  $("history-modal").classList.remove("open");
  historyModalAction = null;
  historyModalId = null;
  const trigger = historyModalTrigger;
  historyModalTrigger = null;
  if (
    trigger &&
    typeof trigger.focus === "function" &&
    document.contains(trigger)
  ) {
    trigger.focus();
  }
}
$("history-modal-cancel").addEventListener("click", closeHistoryModal);
$("history-modal").addEventListener("click", (event) => {
  if (event.target === $("history-modal")) closeHistoryModal();
});
$("history-modal-confirm").addEventListener("click", async () => {
  try {
    if (historyModalAction === "rename") {
      const name = $("history-modal-input").value.trim();
      if (!name) return;
      await updateHistory(historyModalId, { title: name });
    } else if (historyModalAction === "delete")
      await deleteHistory(historyModalId);
    closeHistoryModal();
  } catch (error) {
    $("history-modal-text").textContent = error.message;
  }
});
$("history-list").addEventListener("click", async (event) => {
  const action = event.target.closest("[data-history-action]");
  if (action) {
    event.stopPropagation();
    const id = action.dataset.historyId;
    if (action.dataset.historyAction === "rename") {
      const row = action.closest("[data-history-row]");
      openHistoryModal(
        "rename",
        id,
        row
          .querySelector(".history-item")
          .textContent.replace(/^🔒\s*/, ""),
      );
    } else if (action.dataset.historyAction === "delete")
      openHistoryModal("delete", id);
    else {
      try {
        await updateHistory(
          id,
          action.dataset.historyAction === "pin" ||
            action.dataset.historyAction === "unpin"
            ? { pinned: action.dataset.historyAction === "pin" }
            : { locked: action.dataset.historyAction === "lock" },
        );
      } catch (error) {
        openHistoryModal("error", id);
        $("history-modal-title").textContent = t("history.actionFailed");
        $("history-modal-text").textContent = error.message;
        $("history-modal-input").style.display = "none";
        $("history-modal-confirm").style.display = "none";
      }
    }
    return;
  }
  const item = event.target.closest("[data-history-id]");
  if (item) openConversation(item.dataset.historyId);
});
$("new-chat").addEventListener("click", () => startNewChat("new"));
window.addEventListener("online", () => {
  if (pendingHistoryAppends.size) flushPendingAppends();
});
$("reset").addEventListener("click", async () => {
  if (
    !(await confirmDialog({
      title: t("common.confirmTitle"),
      text: t("notice.resetConfirm"),
      confirmLabel: t("common.confirm"),
    }))
  )
    return;
  await fetch("/api/settings/reset", { method: "POST" });
  await loadSettings();
  showNotice(t("notice.resetDone"));
});
// Server control (Settings) and HTTP/HTTPS selection (Network page).
const serverState = {
  known: false,
  failed: false,
  running: false,
  pid: null,
  scheme: "",
  port: 5000,
  url: "",
  uptime: 0,
  scriptAvailable: false,
  tls: {
    mode: "http",
    kind: "none",
    cert_exists: false,
    key_exists: false,
    pair_available: false,
    adhoc: false,
  },
};
let activeServerAction = "";
// Address the next restart will answer on when the protocol changes. It is
// kept in sessionStorage so reloading the page before the restart still points
// at the new address instead of polling the old origin until it times out.
const PENDING_SCHEME_KEY = "ai-web-pending-scheme";
let pendingSchemeUrl = "";
try {
  pendingSchemeUrl = sessionStorage.getItem(PENDING_SCHEME_KEY) || "";
} catch (error) {
  // Storage is blocked; the restart address is kept in memory only.
}
function setPendingSchemeUrl(url) {
  pendingSchemeUrl = url || "";
  try {
    if (pendingSchemeUrl) {
      sessionStorage.setItem(PENDING_SCHEME_KEY, pendingSchemeUrl);
    } else {
      sessionStorage.removeItem(PENDING_SCHEME_KEY);
    }
  } catch (error) {
    // Storage is blocked; the in-memory value still drives this page.
  }
}
function applyServerStatus(data) {
  serverState.known = true;
  serverState.failed = false;
  serverState.running = Boolean(data.running);
  serverState.pid = data.pid ?? null;
  serverState.scheme = data.scheme || "";
  serverState.port = Number(data.port) || 5000;
  serverState.url = data.url || "";
  serverState.uptime = Number(data.uptime_seconds) || 0;
  serverState.tls = data.tls || serverState.tls;
  serverState.scriptAvailable = Boolean(data.script_available);
  // Rebuild the pending address when the server already reports another
  // protocol; a saved address is dropped once this page runs on it.
  const currentMode = location.protocol.slice(0, -1); // "http" or "https"
  if (serverState.scheme && currentMode !== serverState.scheme) {
    const port = serverState.port || Number(location.port) || 5000;
    setPendingSchemeUrl(`${serverState.scheme}://${location.hostname}:${port}/`);
  } else if (pendingSchemeUrl) {
    const pendingMode = pendingSchemeUrl.startsWith("https://") ? "https" : "http";
    const savedMode = serverState.tls?.mode || "";
    // Drop the saved address once this page already runs on it, or when the
    // mode saved in Settings no longer matches it: storage is per origin, so
    // HTTP -> HTTPS -> HTTP would otherwise keep the first switch's address.
    if (
      pendingSchemeUrl.startsWith(location.origin) ||
      (savedMode && pendingMode !== savedMode)
    ) {
      setPendingSchemeUrl("");
    }
  }
}
function serverUptimeText(seconds) {
  const totalMinutes = Math.max(0, Math.floor(Number(seconds) / 60));
  if (totalMinutes < 60) {
    return t("server.uptimeMinutes", { minutes: totalMinutes });
  }
  return t("server.uptimeValue", {
    hours: Math.floor(totalMinutes / 60),
    minutes: totalMinutes % 60,
  });
}
function renderServerStatus() {
  const state = $("server-state");
  if (!state) return;
  if (!serverState.known) {
    state.textContent = serverState.failed ? t("server.loadFailed") : "—";
    $("server-pid").textContent = "—";
    $("server-uptime").textContent = "—";
    $("server-mode").textContent = "—";
    return;
  }
  state.textContent = serverState.running
    ? t("server.running")
    : t("server.stopped");
  $("server-pid").textContent =
    serverState.running && serverState.pid ? String(serverState.pid) : "—";
  $("server-uptime").textContent = serverState.running
    ? serverUptimeText(serverState.uptime)
    : "—";
  $("server-mode").textContent = serverState.scheme
    ? serverState.scheme.toUpperCase()
    : "—";
}
function renderNetworkState() {
  const tls = serverState.tls || {};
  // Keep the option the user is about to save when the language changes.
  const selected =
    document.querySelector('input[name="tls-mode"]:checked')?.value ||
    (tls.mode === "https"
      ? tls.kind === "adhoc"
        ? "https-adhoc"
        : "https-cert"
      : "http");
  document.querySelectorAll('input[name="tls-mode"]').forEach((input) => {
    input.checked = input.value === selected;
  });
  $("network-scheme").textContent = serverState.known
    ? serverState.scheme?.toUpperCase() || "—"
    : "—";
  $("network-url").textContent =
    serverState.known && serverState.url ? serverState.url : "—";
  if (!serverState.known) {
    $("network-cert").textContent = serverState.failed
      ? t("network.loadFailed")
      : "—";
    return;
  }
  if (tls.kind === "cert") {
    $("network-cert").textContent = tls.pair_available
      ? t("network.certReady")
      : t("network.certMissing");
  } else if (tls.kind === "adhoc") {
    $("network-cert").textContent = t("network.adhocOn");
  } else {
    $("network-cert").textContent = t("network.certOff");
  }
}
async function loadServerStatus() {
  try {
    const response = await fetch("/api/server/status", { cache: "no-store" });
    if (!response.ok) throw new Error("status failed");
    applyServerStatus(await response.json());
  } catch (error) {
    serverState.known = false;
    serverState.failed = true;
  }
  renderServerStatus();
  renderNetworkState();
}
function setServerStatusText(text, isError) {
  const el = $("server-status-text");
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
  el.classList.toggle("restarting", !isError && Boolean(activeServerAction));
  // The network view has its own copy of the same state, so a restart or a
  // failed start is visible from the page that triggered it.
  const networkEl = $("network-status-text");
  if (networkEl) {
    networkEl.textContent = text;
    networkEl.classList.toggle("error", Boolean(isError));
  }
}
async function pollServerRestart(attempt = 0) {
  if (attempt > 40) {
    activeServerAction = "";
    setServerStatusText(t("server.restartSlow"), true);
    return;
  }
  await new Promise((resolve) =>
    setTimeout(resolve, attempt === 0 ? 3000 : 1000),
  );
  try {
    const response = await fetch("/api/server/status", { cache: "no-store" });
    if (!response.ok) throw new Error("down");
    const data = await response.json();
    if (!data.running) throw new Error("down");
    applyServerStatus(data);
    setPendingSchemeUrl("");
    renderServerStatus();
    renderNetworkState();
    activeServerAction = "";
    setServerStatusText(t("server.restartDone"), false);
  } catch (error) {
    pollServerRestart(attempt + 1);
  }
}
async function runServerAction(action) {
  if (action === "stop" || action === "restart") {
    const confirmed = await confirmDialog({
      title: t(
        action === "stop"
          ? "server.stopConfirmTitle"
          : "server.restartConfirmTitle",
      ),
      text: t(action === "stop" ? "server.confirmStop" : "server.confirmRestart"),
      confirmLabel: t(action === "stop" ? "server.stop" : "server.restart"),
    });
    if (!confirmed) return;
  }
  activeServerAction = action;
  setServerStatusText(
    t("server.actionPending", { action: t(`server.${action}`) }),
    false,
  );
  try {
    const response = await fetch("/api/server/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, lang: currentLanguage }),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || t("server.unknown"));
    }
  } catch (error) {
    activeServerAction = "";
    setServerStatusText(t("server.actionFailed", { error: error.message }), true);
    return;
  }
  if (action === "stop") {
    serverState.running = false;
    setServerStatusText(t("server.stoppedNow"), false);
    renderServerStatus();
    return;
  }
  setServerStatusText(t("server.restarting"), false);
  if (pendingSchemeUrl) {
    // This page cannot follow a restart that changes the protocol: the old
    // address stops answering, so polling would only time out. Point at the
    // new address instead.
    setServerStatusText(t("server.restartNewScheme", { url: pendingSchemeUrl }), false);
    activeServerAction = "";
    return;
  }
  pollServerRestart(0);
}
$("server-refresh").addEventListener("click", loadServerStatus);
$("server-start").addEventListener("click", () => runServerAction("start"));
$("server-restart").addEventListener("click", () => runServerAction("restart"));
$("server-stop").addEventListener("click", () => runServerAction("stop"));
$("network-refresh").addEventListener("click", loadServerStatus);
$("network-restart").addEventListener("click", () => runServerAction("restart"));
$("network-save").addEventListener("click", async () => {
  const selected =
    document.querySelector('input[name="tls-mode"]:checked')?.value || "http";
  const [mode, kind] = selected.split("-");
  const button = $("network-save");
  button.disabled = true;
  $("network-status-text").textContent = "";
  try {
    const response = await fetch("/api/server/tls", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode,
        https_kind: kind || "cert",
        lang: currentLanguage,
      }),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || t("network.saveFailed"));
    }
    await loadServerStatus();
    const port = serverState.port || Number(location.port) || 5000;
    const targetUrl = `${mode}://${location.hostname}:${port}/`;
    // Remember the address the restart will answer on, but only when the
    // protocol actually changes; otherwise the page can just poll as usual.
    setPendingSchemeUrl(mode === location.protocol.slice(0, -1) ? "" : targetUrl);
    $("network-status-text").textContent = t("network.needRestart", {
      url: targetUrl,
    });
    showNotice(t("network.saved"));
  } catch (error) {
    $("network-status-text").textContent = error.message;
    showNotice(t("network.saveFailed"), true);
  } finally {
    button.disabled = false;
  }
});
function renderMessages(keepTyping = false) {
  // A live "AI is thinking" indicator must survive re-renders such as a
  // language switch, so keep the same node and its running elapsed timer
  // instead of tearing it down and rebuilding it.
  const indicator = keepTyping ? typingIndicator : null;
  if (indicator) {
    indicator.remove();
  } else {
    removeTypingIndicator();
  }
  const container = $("messages");
  container.innerHTML = "";
  const restoreIndicator = () => {
    if (!indicator) return;
    const label = indicator.querySelector(".typing-label");
    const key = label?.dataset.key || "chat.typingThinking";
    if (label) label.textContent = t(key);
    indicator.setAttribute("aria-label", t(key));
    const elapsed = indicator.querySelector(".typing-elapsed");
    const startedAt = Number(indicator.dataset.startedAt || 0);
    if (elapsed && startedAt) {
      const seconds = Math.round((performance.now() - startedAt) / 1000);
      elapsed.textContent =
        seconds >= 2 ? t("chat.typingElapsed", { seconds }) : "";
    }
    container.appendChild(indicator);
    container.scrollTop = container.scrollHeight;
  };
  if (!messages.length) {
    if (emptyConversationMode === "deleted") {
      const el = document.createElement("div");
      el.className = "message assistant";
      const text = document.createElement("div");
      text.textContent = t("history.emptyHint");
      el.appendChild(text);
      container.appendChild(el);
    } else {
      const divider = document.createElement("div");
      divider.className = "session-divider";
      const span = document.createElement("span");
      span.textContent = t("history.startedNew");
      divider.appendChild(span);
      container.appendChild(divider);
    }
    restoreIndicator();
    return;
  }
  messages.forEach((message, index) =>
    addMessage(message.role, message.content, message, index),
  );
  restoreIndicator();
}
function applyStaticTranslations() {
  document.documentElement.lang = currentLanguage;
  document.title = t("app.title");
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    element.textContent = t(element.dataset.i18n);
  });
  document
    .querySelectorAll("[data-i18n-placeholder]")
    .forEach((element) => {
      element.setAttribute(
        "placeholder",
        t(element.dataset.i18nPlaceholder),
      );
    });
  document.querySelectorAll("[data-i18n-title]").forEach((element) => {
    element.setAttribute("title", t(element.dataset.i18nTitle));
  });
  document
    .querySelectorAll("[data-i18n-aria-label]")
    .forEach((element) => {
      element.setAttribute(
        "aria-label",
        t(element.dataset.i18nAriaLabel),
      );
    });
  $("language-display").textContent =
    currentLanguage === "th" ? "TH" : "EN";
}
function isConversationalLiveModel(name) {
  // Transcription and translation Live models cannot hold a voice chat.
  return Boolean(name) && !/transcribe|translate/i.test(name);
}
function renderGeminiLiveModels(models = [], defaultModel = "") {
  const select = $("gemini-live-model");
  if (!select) return;
  const current = select.value || geminiSettings.liveModel || "";
  select.innerHTML = "";
  const automatic = document.createElement("option");
  automatic.value = "";
  automatic.textContent = t("gemini.defaultModel");
  select.appendChild(automatic);
  const names = (Array.isArray(models) ? models : []).filter(
    isConversationalLiveModel,
  );
  if (
    isConversationalLiveModel(defaultModel) &&
    !names.includes(defaultModel)
  ) {
    names.unshift(defaultModel);
  }
  if (current && !names.includes(current)) names.unshift(current);
  for (const name of names) {
    if (!name) continue;
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    select.appendChild(option);
  }
  // A blank saved model keeps Automatic selected; the server resolves the
  // discovered default when a session starts.
  select.value = current && names.includes(current) ? current : "";
}
function renderGeminiCapabilities(report = geminiCapabilityReport) {
  const host = $("gemini-capabilities");
  if (!host) return;
  host.innerHTML = "";
  const message = document.createElement("p");
  message.className = "hint";
  if (!report) {
    message.textContent = t("gemini.notChecked");
    host.appendChild(message);
    return;
  }
  if (report.error) {
    message.textContent = report.error;
    host.appendChild(message);
    return;
  }
  for (const groupKey of [
    "multimodal",
    "live",
    "decisions",
    "agents",
    "other",
  ]) {
    const group = report.groups?.[groupKey];
    if (!group) continue;
    const row = document.createElement("div");
    row.className = "gemini-group";
    const label = document.createElement("span");
    label.className = "gemini-group-label";
    label.textContent = t(`gemini.group.${groupKey}`);
    const state = document.createElement("span");
    // Preset agent ids are suggestions until discovery proves the key can
    // reach them, so they are not shown as available on their own.
    const unverified = groupKey === "agents" && !group.verified;
    state.className = `gemini-status ${
      unverified ? "unknown" : group.ready ? "ready" : "missing"
    }`;
    state.textContent = unverified
      ? t("gemini.unverified")
      : group.ready
        ? t("gemini.ready")
        : t("gemini.unavailable");
    const detail = document.createElement("small");
    detail.textContent = (group.models || []).slice(0, 4).join(", ");
    row.append(label, state, detail);
    host.appendChild(row);
  }
  renderGeminiLiveModels(
    report.groups?.live?.models || [],
    report.live_default || "",
  );
}
async function loadGeminiCapabilities(force = false) {
  // A newer request supersedes a pending one, so a probe started for the
  // previous key can never render its result against the saved settings.
  const request = ++geminiCapabilityRequest;
  geminiCapabilityLoading = true;
  const host = $("gemini-capabilities");
  if (host) {
    host.innerHTML = "";
    const message = document.createElement("p");
    message.className = "hint";
    message.textContent = t("gemini.checking");
    host.appendChild(message);
  }
  try {
    const response = await fetch(
      `/api/gemini/capabilities?lang=${currentLanguage}${force ? "&refresh=1" : ""}`,
    );
    const report = await response.json();
    if (request !== geminiCapabilityRequest) return;
    geminiCapabilityReport = report;
  } catch (error) {
    if (request !== geminiCapabilityRequest) return;
    geminiCapabilityReport = { error: t("gemini.loadFailed") };
  } finally {
    if (request === geminiCapabilityRequest) {
      geminiCapabilityLoading = false;
      renderGeminiCapabilities(geminiCapabilityReport);
    }
  }
}
let geminiToolsReturnFocus = null;
function geminiToolsFocusable() {
  const modal = $("gemini-modal");
  return Array.from(
    modal.querySelectorAll(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((element) => element.offsetParent !== null);
}
function trapGeminiToolsFocus(event) {
  const modal = $("gemini-modal");
  if (!modal.classList.contains("open")) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeGeminiTools();
    return;
  }
  if (event.key !== "Tab") return;
  const items = geminiToolsFocusable();
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (!modal.contains(document.activeElement)) {
    event.preventDefault();
    (event.shiftKey ? last : first).focus();
  } else if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}
function openGeminiTools() {
  const modal = $("gemini-modal");
  geminiToolsReturnFocus =
    document.activeElement instanceof HTMLElement
      ? document.activeElement
      : $("gemini-tools-button");
  modal.classList.add("open");
  document.addEventListener("keydown", trapGeminiToolsFocus);
  const title = $("gemini-modal-title");
  if (title) {
    title.tabIndex = -1;
    title.focus();
  }
  if (!$("gemini-agent-id").value) {
    $("gemini-agent-id").value = "antigravity-preview-09-2026";
  }
  if (!$("gemini-decision-questions").value) {
    $("gemini-decision-questions").value = JSON.stringify(
      {
        route: {
          type: "choice",
          instructions: "Route the request to the most appropriate team.",
          criteria: {
            billing: "Payments, charges, refunds, or plan changes.",
            technical: "Bugs, errors, or product functionality.",
            other: "None of these teams.",
          },
        },
        urgent: {
          type: "noul",
          instructions: "Determine whether this needs immediate attention.",
        },
      },
      null,
      2,
    );
  }
  if (!geminiCapabilityReport) loadGeminiCapabilities();
}
function closeGeminiTools() {
  const modal = $("gemini-modal");
  if (!modal.classList.contains("open")) return;
  // The dialog holds the only Stop control, so closing it must not leave the
  // microphone capturing audio.
  stopGeminiLive(true);
  liveSetStatus("");
  modal.classList.remove("open");
  document.removeEventListener("keydown", trapGeminiToolsFocus);
  const target = geminiToolsReturnFocus || $("gemini-tools-button");
  geminiToolsReturnFocus = null;
  if (target && typeof target.focus === "function") target.focus();
}
async function runGeminiDecisions() {
  const button = $("gemini-decision-run");
  const output = $("gemini-decision-result");
  let questions;
  try {
    questions = JSON.parse($("gemini-decision-questions").value);
  } catch (error) {
    output.hidden = false;
    output.textContent = t("gemini.badQuestions");
    return;
  }
  button.disabled = true;
  output.hidden = false;
  output.textContent = t("gemini.running");
  try {
    const response = await fetch("/api/gemini/decisions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        input: $("gemini-decision-input").value,
        questions,
        lang: currentLanguage,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || t("gemini.loadFailed"));
    output.textContent = JSON.stringify(data.answers ?? data, null, 2);
  } catch (error) {
    output.textContent = error.message || t("gemini.loadFailed");
  } finally {
    button.disabled = false;
  }
}
async function runGeminiAgent() {
  const button = $("gemini-agent-run");
  const output = $("gemini-agent-result");
  button.disabled = true;
  output.hidden = false;
  output.textContent = t("gemini.running");
  try {
    const response = await fetch("/api/gemini/agents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        agent: $("gemini-agent-id").value,
        input: $("gemini-agent-prompt").value,
        lang: currentLanguage,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || t("gemini.loadFailed"));
    const meta = t("gemini.agentIds", {
      interaction: data.interaction_id || "-",
      environment: data.environment_id || "-",
    });
    output.textContent = `${data.answer || t("gemini.noResult")}\n\n${meta}`;
  } catch (error) {
    output.textContent = error.message || t("gemini.loadFailed");
  } finally {
    button.disabled = false;
  }
}
function base64FromBytes(bytes) {
  let binary = "";
  const chunkSize = 0x8000;
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode.apply(
      null,
      bytes.subarray(index, index + chunkSize),
    );
  }
  return btoa(binary);
}
function liveSetStatus(text) {
  const status = $("gemini-live-status");
  if (status) status.textContent = text;
}
function liveSetPhase(phase) {
  // Keep the phase itself translatable so a language switch never shows
  // Listening while the microphone permission is still pending.
  liveState.phase = phase;
  const toggle = $("gemini-live-toggle");
  const status = $("gemini-live-status");
  if (phase === "listening") {
    if (toggle) toggle.textContent = t("gemini.liveStop");
    if (status) status.textContent = t("gemini.liveListening");
  } else if (phase === "starting") {
    if (toggle) toggle.textContent = t("gemini.liveStarting");
    if (status) status.textContent = t("gemini.liveStarting");
  } else if (toggle) {
    toggle.textContent = t("gemini.liveStart");
  }
}
function liveAttemptActive(attempt) {
  return Boolean(attempt) && liveState.attempt === attempt && !attempt.cancelled;
}
function stopLivePlayback() {
  for (const source of liveState.sources.splice(0)) {
    try {
      source.stop();
    } catch (error) {
      /* already stopped */
    }
  }
  liveState.playAt = 0;
}
function liveTranscriptLine(which) {
  const box = $("gemini-live-transcript");
  box.hidden = false;
  const key = which === "input" ? "inputLine" : "outputLine";
  if (!liveState[key]) {
    const line = document.createElement("p");
    const label = document.createElement("strong");
    label.textContent = `${
      which === "input" ? t("gemini.liveYou") : t("gemini.liveAgent")
    }: `;
    const text = document.createElement("span");
    line.append(label, text);
    box.appendChild(line);
    liveState[key] = text;
  }
  return liveState[key];
}
function playLiveAudio(encoded, mimeType) {
  try {
    const match = /rate=(\d+)/.exec(mimeType || "");
    const rate = match ? Number(match[1]) : 24000;
    const bytes = Uint8Array.from(atob(encoded), (char) =>
      char.charCodeAt(0),
    );
    const samples = new Int16Array(bytes.buffer);
    const AudioCtor = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtor) return;
    if (!liveState.outCtx) liveState.outCtx = new AudioCtor();
    const context = liveState.outCtx;
    if (context.state === "suspended") {
      // Playback starts after the click that opened the dialog, so the context
      // can still be suspended; resume it rather than dropping the audio.
      context.resume().catch(() => {});
    }
    const buffer = context.createBuffer(1, samples.length, rate || 24000);
    const channel = buffer.getChannelData(0);
    for (let index = 0; index < samples.length; index += 1) {
      channel[index] = samples[index] / 32768;
    }
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    source.onended = () => {
      const index = liveState.sources.indexOf(source);
      if (index !== -1) liveState.sources.splice(index, 1);
    };
    const startAt = Math.max(context.currentTime + 0.02, liveState.playAt);
    source.start(startAt);
    liveState.sources.push(source);
    liveState.playAt = startAt + buffer.duration;
  } catch (error) {
    console.warn("live audio", error);
  }
}
function waitForLiveSetup(attempt) {
  // The Live protocol requires waiting for setupComplete before any input.
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error(t("gemini.liveError")));
    }, 15000);
    attempt.resolveSetup = () => {
      clearTimeout(timer);
      resolve();
    };
    attempt.rejectSetup = (error) => {
      clearTimeout(timer);
      reject(error);
    };
  });
}
function handleLiveMessage(data, attempt) {
  if (data?.setupComplete) {
    attempt.setupComplete = true;
    attempt.resolveSetup?.();
  }
  const content = data?.serverContent;
  if (!content) return;
  if (content.interrupted) {
    // The user interrupted the reply, so queued audio must not keep playing
    // behind the new turn.
    stopLivePlayback();
  }
  if (content.inputTranscription?.text) {
    liveTranscriptLine("input").textContent += content.inputTranscription.text;
  }
  if (content.outputTranscription?.text) {
    liveTranscriptLine("output").textContent +=
      content.outputTranscription.text;
  }
  for (const part of content.modelTurn?.parts || []) {
    if (part.inlineData?.data) {
      playLiveAudio(part.inlineData.data, part.inlineData.mimeType);
    }
    if (part.text) liveTranscriptLine("output").textContent += part.text;
  }
  if (content.turnComplete) {
    liveState.inputLine = null;
    liveState.outputLine = null;
  }
}
// A backlog this large means the link cannot keep up with live audio, so new
// frames are dropped instead of queueing stale speech.
const LIVE_MAX_BUFFERED_BYTES = 1024 * 1024;
const LIVE_OPEN_TIMEOUT_MS = 15000;
async function startLiveMicrophone(attempt) {
  const mic = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  });
  if (!liveAttemptActive(attempt)) {
    // Stop was pressed while the permission prompt was open, so this stream
    // belongs to a finished session and must not hold the microphone open.
    mic.getTracks().forEach((track) => track.stop());
    return;
  }
  attempt.mic = mic;
  liveState.mic = mic;
  const AudioCtor = window.AudioContext || window.webkitAudioContext;
  let context;
  try {
    context = new AudioCtor({ sampleRate: 16000 });
  } catch (error) {
    context = new AudioCtor();
  }
  attempt.micCtx = context;
  liveState.micCtx = context;
  if (context.state === "suspended") {
    // The context is created after the click and after the permission prompt,
    // so it can start suspended and would deliver no microphone audio.
    try {
      await context.resume();
    } catch (error) {
      /* the active check below still reports the session */
    }
  }
  const socket = attempt.ws;
  if (!liveAttemptActive(attempt) || !socket) {
    mic.getTracks().forEach((track) => track.stop());
    return;
  }
  const source = context.createMediaStreamSource(mic);
  const node = context.createScriptProcessor(4096, 1, 1);
  const rate = Math.round(context.sampleRate || 16000);
  node.onaudioprocess = (event) => {
    if (!liveAttemptActive(attempt) || !attempt.setupComplete) return;
    if (socket.readyState !== WebSocket.OPEN) return;
    if (socket.bufferedAmount > LIVE_MAX_BUFFERED_BYTES) return;
    const input = event.inputBuffer.getChannelData(0);
    const pcm = new Int16Array(input.length);
    for (let index = 0; index < input.length; index += 1) {
      const value = Math.max(-1, Math.min(1, input[index]));
      pcm[index] = value < 0 ? value * 0x8000 : value * 0x7fff;
    }
    socket.send(
      JSON.stringify({
        realtimeInput: {
          audio: {
            data: base64FromBytes(new Uint8Array(pcm.buffer)),
            mimeType: `audio/pcm;rate=${rate}`,
          },
        },
      }),
    );
  };
  source.connect(node);
  node.connect(context.destination);
  attempt.node = node;
  liveState.node = node;
}
function stopGeminiLive(silent = false) {
  const attempt = liveState.attempt;
  liveState.attempt = null;
  if (attempt) {
    attempt.cancelled = true;
    // Settle a pending setup wait so the start flow unwinds instead of
    // leaving a half-open session behind.
    attempt.rejectSetup?.(new Error("stopped"));
    // Settle a socket that is still CONNECTING too; teardown clears its
    // handlers, so the open wait needs its own cancellation.
    attempt.rejectOpen?.(new Error("stopped"));
  }
  const ws = liveState.ws;
  liveState.ws = null;
  if (ws) {
    ws.onclose = null;
    ws.onmessage = null;
    ws.onerror = null;
    try {
      ws.close();
    } catch (error) {
      /* already closed */
    }
  }
  liveState.node?.disconnect();
  liveState.node = null;
  liveState.mic?.getTracks().forEach((track) => track.stop());
  liveState.mic = null;
  liveState.micCtx?.close();
  liveState.micCtx = null;
  stopLivePlayback();
  liveState.outCtx?.close();
  liveState.outCtx = null;
  liveState.inputLine = null;
  liveState.outputLine = null;
  liveState.phase = "idle";
  const toggle = $("gemini-live-toggle");
  if (toggle) toggle.textContent = t("gemini.liveStart");
  if (!silent) liveSetStatus(t("gemini.liveStopped"));
}
async function openLiveSocket(token, attempt) {
  const ws = new WebSocket(
    `${token.ws_url}?access_token=${encodeURIComponent(token.token)}`,
  );
  attempt.ws = ws;
  liveState.ws = ws;
  await new Promise((resolve, reject) => {
    // Stop can run while the socket is CONNECTING and clears the handlers, so
    // this wait owns a cancellation callback and a deadline of its own.
    let timer = null;
    const finish = (error) => {
      if (timer === null) return; // already settled
      clearTimeout(timer);
      timer = null;
      attempt.rejectOpen = null;
      if (error) reject(error);
      else resolve();
    };
    timer = setTimeout(
      () => finish(new Error(t("gemini.liveError"))),
      LIVE_OPEN_TIMEOUT_MS,
    );
    attempt.rejectOpen = (error) => finish(error);
    ws.onopen = () => finish();
    ws.onerror = () => finish(new Error(t("gemini.liveError")));
  });
  if (!liveAttemptActive(attempt)) {
    try {
      ws.close();
    } catch (error) {
      /* already closed */
    }
    return;
  }
  // Attach the handlers before sending setup so an early server message or a
  // close during setup still reaches the transcript and stops the microphone.
  ws.onmessage = async (event) => {
    const text =
      typeof event.data === "string" ? event.data : await event.data.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch (error) {
      return; // ignore non-JSON frames
    }
    // Stop may have run while a binary frame was being decoded, so drop any
    // transcript or audio this stopped attempt would still produce.
    if (!liveAttemptActive(attempt)) return;
    handleLiveMessage(data, attempt);
  };
  ws.onclose = () => {
    if (liveAttemptActive(attempt)) stopGeminiLive();
  };
  ws.onerror = () => {
    if (!liveAttemptActive(attempt)) return;
    liveSetStatus(t("gemini.liveError"));
    stopGeminiLive(true);
  };
  const ready = waitForLiveSetup(attempt);
  ws.send(
    JSON.stringify({
      setup: {
        model: `models/${token.model}`,
        responseModalities: ["AUDIO"],
        inputAudioTranscription: {},
        outputAudioTranscription: {},
        systemInstruction: {
          parts: [
            {
              text:
                $("system_prompt").value || "You are a helpful assistant.",
            },
          ],
        },
      },
    }),
  );
  // Audio must not start before Gemini acknowledges the setup message.
  await ready;
  if (!liveAttemptActive(attempt)) return;
  await startLiveMicrophone(attempt);
  if (!liveAttemptActive(attempt)) return;
  liveSetPhase("listening");
}
async function startGeminiLive() {
  if (liveState.attempt) {
    stopGeminiLive();
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia || typeof WebSocket === "undefined") {
    liveSetStatus(t("gemini.liveUnsupported"));
    return;
  }
  // Reserve the attempt before the first await: a second click during the
  // token request would otherwise open a second socket, and Stop would have
  // nothing to cancel while the permission prompt is open.
  const attempt = { cancelled: false, ws: null, setupComplete: false };
  liveState.attempt = attempt;
  liveSetPhase("starting");
  try {
    const response = await fetch("/api/gemini/live-token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        lang: currentLanguage,
        model: $("gemini-live-model").value,
      }),
    });
    const token = await response.json();
    if (!liveAttemptActive(attempt)) return;
    if (!response.ok) throw new Error(token.error || t("gemini.liveError"));
    await openLiveSocket(token, attempt);
  } catch (error) {
    if (!liveAttemptActive(attempt)) return;
    liveSetStatus(error.message || t("gemini.liveError"));
    stopGeminiLive(true);
  }
}
$("gemini-refresh").addEventListener("click", () =>
  loadGeminiCapabilities(true),
);
$("gemini-open-tools").addEventListener("click", openGeminiTools);
$("gemini-tools-button").addEventListener("click", openGeminiTools);
$("gemini-modal-close").addEventListener("click", closeGeminiTools);
$("gemini-modal").addEventListener("click", (event) => {
  if (event.target === $("gemini-modal")) closeGeminiTools();
});
$("gemini-live-toggle").addEventListener("click", startGeminiLive);
$("gemini-decision-run").addEventListener("click", runGeminiDecisions);
$("gemini-agent-run").addEventListener("click", runGeminiAgent);
$("gemini-live-model").addEventListener("change", () => {
  geminiSettings.liveModel = $("gemini-live-model").value;
});
function applyTranslations() {
  applyStaticTranslations();
  // Refresh a visible rail tooltip so it shows the new language right away.
  if (railTooltipSource) showRailTooltip(railTooltipSource);
  updatePageTitle();
  setModelStatus(modelStatus.key, modelStatus.vars, modelStatus.title);
  const customModelOption = $("model_select").querySelector(
    'option[value="__custom__"]',
  );
  if (customModelOption)
    customModelOption.textContent = t("model.custom");
  updateChatModelOptions(currentChatModels, currentChatSelected);
  updateScheduleModelOptions(
    currentScheduleModels,
    currentScheduleSelected,
  );
  updateFallbackModelOptions(
    currentFallbackModels,
    currentFallbackSelected,
  );
  updateApiKeyHint($("provider").value);
  updateDiscordTokenHint();
  renderCustomApiKeys();
  renderGeminiCapabilities(geminiCapabilityReport);
  if (liveState.phase === "starting" || liveState.phase === "listening") {
    liveSetPhase(liveState.phase);
  }
  if (connectionState.known) updateConnectionUi();
  renderMessages(true);
  renderHistoryList(currentHistoryItems);
  renderSchedules(currentSchedules);
  updateScheduleFormMode();
  renderAuthSessions();
  renderUpdatePanel();
  renderServerStatus();
  renderNetworkState();
  renderLogs();
  // Status cells and entry labels are built from API data, so they have to be
  // rebuilt on a language switch as well.
  if (memoryLoaded) renderMemory();
  $("schedule-timezone").textContent =
    currentScheduleTimezone || t("schedule.loading");
  if (
    $("history-modal").classList.contains("open") &&
    historyModalAction &&
    historyModalAction !== "error"
  ) {
    refreshHistoryModalText();
  }
}
function setLanguage(language) {
  currentLanguage = SUPPORTED_LANGUAGES.includes(language)
    ? language
    : "en";
  localStorage.setItem(LANGUAGE_STORAGE_KEY, currentLanguage);
  applyTranslations();
  if (connectionState.known) {
    const selectedChatModel = $("chat-model-select").value;
    refreshConnectionState().then(() => {
      if (selectedChatModel)
        $("header-model-name").textContent = selectedChatModel;
    });
  }
}
$("language-toggle").addEventListener("click", () => {
  setLanguage(currentLanguage === "th" ? "en" : "th");
});
applyTranslations();
loadChatMeta();
loadHistoryList();
loadSchedules();
loadAuthSessions();
