const $ = (id) => document.getElementById(id);
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
    "sidebar.newChat": "＋ แชตใหม่",
    "nav.chat": "▰ แชต",
    "nav.terminal": ">_ Terminal",
    "nav.settings": "⚙ ตั้งค่า",
    "nav.schedule": "◷ งานตามเวลา",
    "nav.logs": "▤ Log ระบบ",
    "nav.about": "ⓘ เกี่ยวกับ",
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
    "header.tagline": "ศูนย์ควบคุมการทำงาน",
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
    "settings.group.integrationsDesc": "Discord bot และแท็บ Terminal",
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
    "settings.updateCheckDone": "ตรวจสอบเสร็จแล้วเมื่อ {time}",
    "settings.updateDone": "อัปเดตเสร็จแล้วเมื่อ {time}",
    "settings.updateError": "ไม่สำเร็จ (exit {code}) — ดู log ด้านล่าง",
    "settings.updateCheckStarted": "เริ่มตรวจสอบการอัปเดตแล้ว",
    "settings.updateRunStarted": "เริ่มอัปเดตแล้ว — เซิร์ฟเวอร์อาจรีสตาร์ต",
    "settings.updateFailed": "เริ่มการอัปเดตไม่สำเร็จ",
    "settings.updateLoadFailed": "โหลดสถานะการอัปเดตไม่สำเร็จ",
    "settings.updateRestarting": "เซิร์ฟเวอร์กำลังรีสตาร์ต รอสักครู่...",
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
    "settings.memoryReview": "ทบทวนความจำ",
    "settings.memoryReviewPlaceholder": "กำหนดสิ่งที่ Agent ควรทบทวนก่อนตอบ",
    "settings.memoryReviewHint": "แนวทางนี้จะถูกส่งให้ Agent ทุกครั้งที่ตอบ เพื่อรักษาบริบทและลดความผิดพลาด",
    "settings.skills": "Skills ที่ใช้กับ Agent",
    "settings.skillsHint": "เลือกได้หลายสกิล ระบบจะส่งเนื้อหาไปเป็นแนวทางให้ Agent",
    "settings.newSkillName": "ชื่อ Skill ใหม่",
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
    "settings.terminalTitle": "Terminal",
    "settings.terminalHint":
      "เปิดหรือปิดแท็บ Terminal ในแถบด้านข้าง (เริ่มต้นในโฟลเดอร์โปรเจกต์)",
    "settings.terminalEnable": "แสดงแท็บ Terminal ในแถบด้านข้าง",
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
    "schedule.toggleEnable": "เปิดใช้งาน",
    "schedule.toggleDisable": "ปิดใช้งาน",
    "schedule.added": "เพิ่มงานตามเวลาแล้ว",
    "schedule.addFailed": "เพิ่มงานไม่สำเร็จ",
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
    "terminal.title": "Terminal",
    "terminal.hint": "พิมพ์คำสั่งเพื่อทำงานบนเครื่อง Server โดยตรง",
    "terminal.warning":
      "⚠ คำสั่งจะทำงานบน Server ด้วยสิทธิ์ของผู้ใช้ที่รันแอป และเริ่มต้นในโฟลเดอร์โปรเจกต์",
    "terminal.scope": "· เริ่มต้นที่: {scope}",
    "terminal.clear": "ล้างจอ",
    "terminal.run": "รัน",
    "terminal.placeholder": "พิมพ์คำสั่ง...",
    "terminal.connecting": "กำลังเชื่อมต่อ...",
    "terminal.ready": "พร้อมรับคำสั่ง",
    "terminal.running": "กำลังรัน...",
    "terminal.disabled": "Terminal ถูกปิดใช้งาน — เปิดได้ใน Settings",
    "terminal.welcome": "Terminal พร้อมใช้งาน พิมพ์คำสั่งแล้วกด Enter",
    "terminal.exitCode": "exit {code}",
    "terminal.timeout": "คำสั่งใช้เวลานานเกินกำหนดและถูกหยุดแล้ว",
    "terminal.truncated": "ผลลัพธ์ถูกตัดบางส่วน",
    "terminal.error": "เชื่อมต่อ Terminal ไม่สำเร็จ: {message}",
    "terminal.noOutput": "(ไม่มี output)",
    "terminal.cwd": "โฟลเดอร์: {cwd}",
    "terminal.statusIdle": "พร้อมใช้งาน",
    "terminal.statusBusy": "กำลังทำงาน",
    "terminal.statusDisabled": "ปิดใช้งาน",
    "about.title": "เกี่ยวกับระบบ",
    "about.text1":
      "เว็บแชต AI ที่รันบน Termux พร้อมหน้า settings สำหรับควบคุม provider, model, endpoint, prompt และพารามิเตอร์ต่าง ๆ",
    "about.text2":
      "API key จะเก็บฝั่งเซิร์ฟเวอร์ในไฟล์ตั้งค่าที่ไม่ถูก commit เข้า Git",
    "page.settings": "ตั้งค่าระบบ",
    "page.terminal": "Terminal",
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
    "tool.retry": "ลองอีกครั้ง ({message})",
    "tool.resultPrefix": "ผลการใช้เครื่องมือ:",
    "attachment.tooLarge": "ไฟล์ใหญ่เกิน 1 MB",
    "attachment.readFailed": "อ่านไฟล์ไม่สำเร็จ",
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
    "history.pinned": "📌 ปักหมุด",
    "history.empty": "ยังไม่มีประวัติ",
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
  },
  en: {
    "app.title": "AI Control Center",
    "sidebar.newChat": "+ New chat",
    "nav.chat": "▰ Chat",
    "nav.terminal": ">_ Terminal",
    "nav.settings": "⚙ Settings",
    "nav.schedule": "◷ Scheduled jobs",
    "nav.logs": "▤ System logs",
    "nav.about": "ⓘ About",
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
    "header.tagline": "Operational Terminal",
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
    "settings.group.integrationsDesc": "Discord bot and the Terminal tab",
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
    "settings.updateCheckDone": "Check finished at {time}",
    "settings.updateDone": "Update finished at {time}",
    "settings.updateError": "Failed (exit {code}) — see the output below",
    "settings.updateCheckStarted": "Update check started",
    "settings.updateRunStarted": "Update started — the server may restart",
    "settings.updateFailed": "Could not start the update",
    "settings.updateLoadFailed": "Could not load the update status",
    "settings.updateRestarting": "The server is restarting, waiting...",
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
    "settings.memoryReview": "Memory review",
    "settings.memoryReviewPlaceholder": "Define what the agent should review before answering",
    "settings.memoryReviewHint": "This guidance is sent to the agent on every response to preserve context and reduce errors.",
    "settings.skills": "Skills used by the agent",
    "settings.skillsHint": "Select multiple skills. Their content will guide the agent.",
    "settings.newSkillName": "New skill name",
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
    "settings.terminalTitle": "Terminal",
    "settings.terminalHint":
      "Show or hide the Terminal tab in the sidebar. It starts in the project folder.",
    "settings.terminalEnable": "Show the Terminal tab in the sidebar",
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
    "schedule.toggleEnable": "Enable",
    "schedule.toggleDisable": "Disable",
    "schedule.added": "Scheduled job added",
    "schedule.addFailed": "Could not add the scheduled job",
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
    "terminal.title": "Terminal",
    "terminal.hint": "Type commands to run directly on the server",
    "terminal.warning":
      "⚠ Commands run on the server with the permissions of the user running this app and start in the project folder.",
    "terminal.scope": "· Starts in: {scope}",
    "terminal.clear": "Clear",
    "terminal.run": "Run",
    "terminal.placeholder": "Type a command...",
    "terminal.connecting": "Connecting...",
    "terminal.ready": "Ready for commands",
    "terminal.running": "Running...",
    "terminal.disabled": "Terminal is disabled — enable it in Settings",
    "terminal.welcome": "Terminal ready. Type a command and press Enter.",
    "terminal.exitCode": "exit {code}",
    "terminal.timeout": "The command took too long and was stopped.",
    "terminal.truncated": "Output was truncated",
    "terminal.error": "Could not reach the terminal: {message}",
    "terminal.noOutput": "(no output)",
    "terminal.cwd": "Folder: {cwd}",
    "terminal.statusIdle": "Ready",
    "terminal.statusBusy": "Working",
    "terminal.statusDisabled": "Disabled",
    "about.text1":
      "A self-hosted AI chat app running on Termux, with a settings page for provider, model, endpoint, prompt, and response parameters.",
    "about.text2":
      "API keys are stored only on the server in a settings file that is not committed to Git.",
    "page.settings": "Settings",
    "page.terminal": "Terminal",
    "page.schedule": "Scheduled jobs",
    "page.logs": "System logs",
    "page.about": "About",
    "usage.duration": "Took {duration}s",
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
    "tool.retry": "Try again ({message})",
    "tool.resultPrefix": "Tool result:",
    "attachment.tooLarge": "File is larger than 1 MB",
    "attachment.readFailed": "Could not read the file",
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
    "history.pinned": "📌 Pinned",
    "history.empty": "No history yet",
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
  },
};
function getSavedLanguage() {
  const saved = localStorage.getItem(LANGUAGE_STORAGE_KEY);
  return SUPPORTED_LANGUAGES.includes(saved) ? saved : "en";
}
let currentLanguage = getSavedLanguage();
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
let terminalInfo = null;
let terminalCwd = ".";
let terminalBusy = false;
let terminalBooted = false;
const TERMINAL_HISTORY_STORAGE = "ai-control-center-terminal-history";
const terminalHistory = [];
let terminalHistoryIndex = -1;
try {
  const storedHistory = JSON.parse(
    localStorage.getItem(TERMINAL_HISTORY_STORAGE) || "[]",
  );
  if (Array.isArray(storedHistory)) {
    terminalHistory.push(
      ...storedHistory.filter((item) => typeof item === "string"),
    );
  }
} catch (error) {
  /* ignore malformed local history */
}
terminalHistoryIndex = terminalHistory.length;
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
function setConversationTitle(title) {
  conversationTitle =
    String(title || "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 80) || null;
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
        const disable = ["off", "none", "ปิด"].includes(
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
function addMessage(role, content, meta = null) {
  const el = document.createElement("div");
  el.className = `message ${role}`;
  const text = document.createElement("div");
  text.className = "message-text";
  text.textContent = content;
  el.appendChild(text);
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
  if (role === "assistant" && meta?.tool_request && meta?.approval_id) {
    const approval = document.createElement("button");
    approval.type = "button";
    approval.className = "tool-approval";
    approval.textContent = t("tool.approve", {
      name: meta.tool_request.name,
    });
    approval.toolRequest = meta.tool_request;
    approval.approvalId = meta.approval_id;
    approval.addEventListener("click", approveToolRequest);
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
  $("messages").appendChild(el);
  $("messages").scrollTop = $("messages").scrollHeight;
}
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
  button.disabled = true;
  button.textContent = t("tool.working");
  // The result belongs to the chat that was open when the tool finished, so
  // hold the session and conversation until then.
  const sessionToken = chatSessionToken;
  const targetConversationId = conversationId;
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
      const error = new Error(data.error || t("tool.error"));
      error.fatal = response.status === 403;
      throw error;
    }
    button.textContent = t("tool.done");
    if (
      sessionToken !== chatSessionToken ||
      conversationId !== targetConversationId
    ) {
      // Another chat was opened while the tool ran: leave its composer alone.
      return;
    }
    $("input").value =
      `${t("tool.resultPrefix")}\n${JSON.stringify(data.result, null, 2)}`;
    resizeInput();
    $("chat-form").requestSubmit();
  } catch (error) {
    button.disabled = Boolean(error.fatal);
    button.textContent = error.fatal
      ? t("tool.expired")
      : t("tool.retry", { message: error.message });
  }
}
document.querySelectorAll("nav button").forEach((button) =>
  button.addEventListener("click", () => {
    if (
      button.dataset.view === "terminal" &&
      terminalInfo?.enabled === false
    ) {
      showNotice(t("terminal.disabled"), true);
      return;
    }
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
    }
    if (button.dataset.view === "terminal") openTerminalView();
    if (button.dataset.view === "schedule") loadSchedules();
    if (button.dataset.view === "logs") loadLogs();
    closeSidebar();
  }),
);
const SETTINGS_SECTIONS = [
  "connection",
  "agent",
  "response",
  "integrations",
  "security",
  "update",
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
  $("settings-view").scrollTop = 0;
}
document.querySelectorAll("[data-settings-section]").forEach((button) => {
  button.addEventListener("click", () =>
    activateSettingsSection(button.dataset.settingsSection),
  );
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
function terminalPrompt() {
  if (!terminalInfo) return "$";
  const scope = terminalInfo.scope || "~";
  const cwd =
    terminalCwd && terminalCwd !== "."
      ? `${scope}/${terminalCwd}`
      : scope;
  return `${terminalInfo.user}@${terminalInfo.host}:${cwd}$`;
}
function terminalCwdLabel() {
  const scope = terminalInfo?.scope || "~";
  return terminalCwd && terminalCwd !== "."
    ? `${scope}/${terminalCwd}`
    : scope;
}
function appendTerminalLine(text, kind = "stdout") {
  const output = $("terminal-output");
  const line = document.createElement("div");
  line.className = `terminal-line terminal-${kind}`;
  line.textContent = text;
  output.appendChild(line);
  output.scrollTop = output.scrollHeight;
}
function appendTerminalBlock(text, kind) {
  const normalized = String(text ?? "")
    .replace(/\r\n?/g, "\n")
    .replace(/\n+$/, "");
  if (normalized) appendTerminalLine(normalized, kind);
}
function appendTerminalCommand(command) {
  const output = $("terminal-output");
  const line = document.createElement("div");
  line.className = "terminal-line terminal-command";
  const prompt = document.createElement("span");
  prompt.className = "terminal-prompt-mark";
  prompt.textContent = `${terminalPrompt()} `;
  line.appendChild(prompt);
  line.appendChild(document.createTextNode(command));
  output.appendChild(line);
  output.scrollTop = output.scrollHeight;
}
function updateTerminalUi() {
  if (!terminalInfo) {
    $("terminal-status-text").textContent = t("terminal.connecting");
    return;
  }
  const enabled = terminalInfo.enabled !== false;
  $("terminal-dot").className = `terminal-dot${
    !enabled ? " offline" : terminalBusy ? " busy" : ""
  }`;
  $("terminal-status-text").textContent = !enabled
    ? t("terminal.statusDisabled")
    : terminalBusy
      ? t("terminal.statusBusy")
      : t("terminal.statusIdle");
  $("terminal-prompt").textContent = enabled ? terminalPrompt() : "$";
  $("terminal-cwd").textContent = enabled
    ? t("terminal.cwd", { cwd: terminalCwdLabel() })
    : "";
  $("terminal-input").disabled = !enabled || terminalBusy;
  $("terminal-run").disabled = !enabled || terminalBusy;
  $("terminal-scope").textContent = terminalInfo.scope
    ? t("terminal.scope", { scope: terminalInfo.scope })
    : "";
}
function applyTerminalEnabled(enabled) {
  const navButton = document.querySelector('nav button[data-view="terminal"]');
  if (!navButton) return;
  const isEnabled = enabled !== false;
  if (terminalInfo) terminalInfo.enabled = isEnabled;
  navButton.hidden = !isEnabled;
  if (!isEnabled && activeView() === "terminal") {
    document.querySelector('nav button[data-view="chat"]')?.click();
  }
}
async function refreshTerminalAvailability() {
  try {
    const response = await fetch("/api/terminal/info");
    if (!response.ok) return;
    terminalInfo = await response.json();
    terminalCwd = terminalInfo.cwd || terminalCwd || ".";
    applyTerminalEnabled(terminalInfo.enabled !== false);
  } catch (error) {
    /* Keep the tab visible; openTerminalView will report the error. */
  }
}
async function openTerminalView() {
  if (!terminalInfo) {
    try {
      const response = await fetch("/api/terminal/info");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      terminalInfo = await response.json();
      terminalCwd = terminalInfo.cwd || ".";
      applyTerminalEnabled(terminalInfo.enabled !== false);
    } catch (error) {
      terminalInfo = {
        enabled: false,
        user: "user",
        host: "server",
        scope: "~",
      };
      appendTerminalLine(
        t("terminal.error", { message: error.message }),
        "error",
      );
    }
  }
  if (!terminalBooted) {
    terminalBooted = true;
    appendTerminalLine(
      terminalInfo.enabled
        ? t("terminal.welcome")
        : t("terminal.disabled"),
      "notice",
    );
  }
  updateTerminalUi();
  if (terminalInfo.enabled) $("terminal-input").focus();
}
function clearTerminal() {
  $("terminal-output").innerHTML = "";
  if (terminalInfo?.enabled) {
    appendTerminalLine(t("terminal.welcome"), "notice");
  }
}
function rememberTerminalCommand(command) {
  if (terminalHistory[terminalHistory.length - 1] !== command) {
    terminalHistory.push(command);
    if (terminalHistory.length > 100) terminalHistory.shift();
  }
  terminalHistoryIndex = terminalHistory.length;
  try {
    localStorage.setItem(
      TERMINAL_HISTORY_STORAGE,
      JSON.stringify(terminalHistory),
    );
  } catch (error) {
    /* local storage is optional */
  }
}
async function runTerminalCommand() {
  const input = $("terminal-input");
  const command = input.value.trim();
  if (!command || terminalBusy || !terminalInfo?.enabled) return;
  if (command === "clear" || command === "cls") {
    input.value = "";
    clearTerminal();
    return;
  }
  input.value = "";
  appendTerminalCommand(command);
  rememberTerminalCommand(command);
  terminalBusy = true;
  updateTerminalUi();
  try {
    const response = await fetch("/api/terminal/exec", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command, cwd: terminalCwd }),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    terminalCwd = data.cwd || terminalCwd;
    appendTerminalBlock(data.stdout, "stdout");
    appendTerminalBlock(data.stderr, "stderr");
    if (!data.stdout && !data.stderr && !data.changed_directory) {
      appendTerminalLine(t("terminal.noOutput"), "meta");
    }
    if (data.timed_out) {
      appendTerminalLine(t("terminal.timeout"), "error");
    }
    if (data.truncated) {
      appendTerminalLine(t("terminal.truncated"), "meta");
    }
    if (data.returncode !== 0) {
      appendTerminalLine(
        t("terminal.exitCode", { code: data.returncode }),
        "meta",
      );
    }
  } catch (error) {
    appendTerminalLine(
      t("terminal.error", { message: error.message }),
      "error",
    );
  } finally {
    terminalBusy = false;
    updateTerminalUi();
    if (terminalInfo?.enabled) input.focus();
  }
}
$("terminal-form").addEventListener("submit", (event) => {
  event.preventDefault();
  runTerminalCommand();
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
        await sendChatMessage(result.prompt, result.skills);
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
$("terminal-clear").addEventListener("click", clearTerminal);
$("terminal-input").addEventListener("keydown", (event) => {
  if (event.key === "ArrowUp") {
    event.preventDefault();
    if (!terminalHistory.length) return;
    terminalHistoryIndex = Math.max(0, terminalHistoryIndex - 1);
    const value = terminalHistory[terminalHistoryIndex] || "";
    $("terminal-input").value = value;
    $("terminal-input").setSelectionRange(value.length, value.length);
  } else if (event.key === "ArrowDown") {
    event.preventDefault();
    terminalHistoryIndex = Math.min(
      terminalHistory.length,
      terminalHistoryIndex + 1,
    );
    const value =
      terminalHistoryIndex >= terminalHistory.length
        ? ""
        : terminalHistory[terminalHistoryIndex] || "";
    $("terminal-input").value = value;
    $("terminal-input").setSelectionRange(value.length, value.length);
  } else if (
    (event.ctrlKey || event.metaKey) &&
    event.key.toLowerCase() === "l"
  ) {
    event.preventDefault();
    clearTerminal();
  }
});
function resizeInput() {
  const el = $("input");
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  el.style.overflowY = "auto";
}
$("input").addEventListener("input", () => {
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
$("skill-chip").addEventListener("click", () => clearPendingSkill());
$("attach-button").addEventListener("click", () => $("file-input").click());
$("file-input").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  const maxBytes = 1024 * 1024;
  if (file.size > maxBytes) {
    $("attachment-chip").textContent = t("attachment.tooLarge");
    $("attachment-chip").hidden = false;
    event.target.value = "";
    pendingAttachment = null;
    return;
  }
  try {
    const content = await file.text();
    pendingAttachment = { name: file.name, content };
    $("attachment-chip").textContent = `📎 ${file.name}`;
    $("attachment-chip").hidden = false;
  } catch (error) {
    pendingAttachment = null;
    $("attachment-chip").textContent = t("attachment.readFailed");
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
function historyMessagePayload({ tool_request, approval_id, ...rest } = {}) {
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
async function saveConversation(sessionToken = null) {
  if (!messages.length) return null;
  const targetConversationId = conversationId;
  const isCurrent = () =>
    sessionToken === null || sessionToken === chatSessionToken;
  const firstUser = messages.find((message) => message.role === "user");
  const title = firstUser?.content || t("chat.newConversationTitle");
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
async function sendChatMessage(content, requestedSkills = null) {
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
  messages.push(userMessage);
  addMessage("user", userMessage.content, userMessage);
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
    $("input").value = "";
    pendingAttachment = null;
    $("file-input").value = "";
    $("attachment-chip").hidden = true;
    resizeInput();
    const payload = {
      messages,
      thinking_level: $("chat-thinking-level").value,
      command_mode: $("chat-command-mode").value,
      model: $("chat-model-select").value,
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
      fallback_used: data.fallback_used,
    };
    if (sessionToken !== chatSessionToken) {
      if (targetConversationId && conversationId === targetConversationId) {
        messages.push(assistantMessage);
        removeTypingIndicator();
        addMessage("assistant", data.answer, assistantMessage);
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
    addMessage("assistant", data.answer, assistantMessage);
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
        addMessage("assistant", errorMessage.content);
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
    addMessage("assistant", errorMessage.content);
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
  if (status === "สำเร็จ") return t("schedule.success");
  if (status === "ล้มเหลว") return t("schedule.failed");
  return status;
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
      <small>${escapeHtml(job.schedule)} · ${job.model ? `${escapeHtml(t("schedule.modelLabel", { model: job.model }))} · ` : ""}${job.enabled ? t("schedule.enabled") : t("schedule.disabled")} · ${escapeHtml(scheduleStatusText(job.last_status))}</small>
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
async function loadSchedules() {
  const response = await fetch("/api/schedules");
  if (response.ok) {
    const data = await response.json();
    currentSchedules = data.items || [];
    currentScheduleTimezone =
      data.timezone || t("schedule.timezoneFallback");
    $("schedule-timezone").textContent = currentScheduleTimezone;
    renderSchedules(currentSchedules);
  }
}
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
  const r = await fetch("/api/settings");
  const s = await r.json();
  availableSkills = (s.available_skills || []).map((skill) => skill.name);
  defaultSkills = Array.isArray(s.skills) ? s.skills.map(String) : [];
  connectionState.provider = s.provider ?? connectionState.provider;
  if (pendingSkill && !availableSkills.includes(pendingSkill)) {
    clearPendingSkill();
  }
  $("agent_name").value = s.agent_name ?? "Mux";
  $("agent_role").value = s.agent_role ?? "ผู้ช่วย AI อเนกประสงค์";
  $("response_language").value = s.response_language ?? "auto";
  $("response_style").value = s.response_style ?? "เป็นมิตร กระชับ และชัดเจน";
  $("use_markdown").checked = s.use_markdown !== false;
  $("ask_clarifying_questions").checked = s.ask_clarifying_questions !== false;
  keyProviders = Array.isArray(s.key_providers) ? s.key_providers : [];
  $("provider").value = s.provider ?? "openai";
  $("base_url").value =
    s.base_url ||
    PROVIDER_BASE_URLS[s.provider ?? "openai"] ||
    PROVIDER_BASE_URLS.openai;
  activeProvider = $("provider").value;
  const loadedBase = $("base_url").value.trim().replace(/\/+$/, "");
  if (loadedBase && loadedBase !== (PROVIDER_BASE_URLS[activeProvider] ?? "")) {
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
  $("discord_enabled").checked = !!s.discord_enabled;
  $("terminal_enabled").checked = s.terminal_enabled !== false;
  $("machine_access").checked = s.machine_access !== false;
  applyTerminalEnabled(s.terminal_enabled !== false);
  $("discord_prefix").value = s.discord_prefix ?? "!ai";
  $("discord_allowed_channels").value = Array.isArray(
    s.discord_allowed_channels,
  )
    ? s.discord_allowed_channels.join(", ")
    : s.discord_allowed_channels || "";
  $("discord_allowed_users").value = Array.isArray(s.discord_allowed_users)
    ? s.discord_allowed_users.join(", ")
    : s.discord_allowed_users || "";
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
    discord_enabled: $("discord_enabled").checked,
    discord_token: $("discord_token").value,
    discord_prefix: $("discord_prefix").value,
    discord_allowed_channels: $("discord_allowed_channels").value,
    discord_allowed_users: $("discord_allowed_users").value,
    terminal_enabled: $("terminal_enabled").checked,
    machine_access: $("machine_access").checked,
  };
}
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
    showNotice(
      r.ok ? t("notice.settingsSaved") : t("notice.settingsSaveFailed"),
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
  if (updateState.error) return updateState.error;
  if (!updateState.loaded) return t("settings.updateLoading");
  if (updateState.running) {
    return t("settings.updateRunning", {
      mode: t(
        updateState.job.mode === "check"
          ? "settings.updateCheck"
          : "settings.updateRun",
      ),
    });
  }
  if (updateJobFinished()) {
    const key =
      updateState.job.mode === "check"
        ? "settings.updateCheckDone"
        : "settings.updateDone";
    return updateState.job.ok
      ? t(key, { time: updateState.job.finished_at })
      : t("settings.updateError", {
          code: updateState.job.exit_code ?? "?",
        });
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
  status.classList.toggle(
    "error",
    Boolean(updateState.error) ||
      (updateJobFinished() && updateState.job.ok === false),
  );
  $("update-check").disabled = updateState.running;
  $("update-run").disabled =
    updateState.running || (updateState.loaded && !updateState.scriptAvailable);
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
    updateState.running = Boolean(data.running);
    updateState.job = data.job || updateState.job;
    updateState.log = data.log || "";
    updateState.logTruncated = Boolean(data.log_truncated);
    updateState.appUpdatedAt = data.app_updated_at || "";
    updateState.scriptAvailable = Boolean(data.script_available);
  } catch (error) {
    updateState.error = error.message || t("settings.updateLoadFailed");
  }
  renderUpdatePanel();
}
function pollUpdateState(attempt = 0) {
  clearTimeout(updatePollTimer);
  updatePollTimer = setTimeout(async () => {
    await loadUpdateState();
    if (updateState.error) {
      // A real update restarts the server, so keep retrying for a while.
      if (attempt < UPDATE_POLL_ATTEMPTS) pollUpdateState(attempt + 1);
      return;
    }
    if (updateState.running) {
      pollUpdateState(attempt);
      return;
    }
    if (updateJobFinished()) {
      showNotice(
        updateState.job.ok
          ? t("settings.updateDone", { time: updateState.job.finished_at })
          : t("settings.updateError", {
              code: updateState.job.exit_code ?? "?",
            }),
        !updateState.job.ok,
      );
      return;
    }
    if (attempt < 3) pollUpdateState(attempt + 1);
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
  updateState.running = true;
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
    updateState.error = error.message || t("settings.updateFailed");
    renderUpdatePanel();
    showNotice(updateState.error, true);
  }
}
$("update-check").addEventListener("click", () => startUpdate("check"));
$("update-run").addEventListener("click", () => startUpdate("apply"));
loadUpdateState();
$("create-skill").addEventListener("click", async () => {
  const name = $("new-skill-name").value.trim();
  const content = $("new-skill-content").value.trim();
  if (!name || !content) return;
  const r = await fetch("/api/skills", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, content }),
  });
  if (!r.ok) {
    const data = await r.json();
    showNotice(data.error || t("settings.createSkillFailed"), true);
    return;
  }
  $("new-skill-name").value = "";
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
  $("new-skill-content").value = data.content;
});
$("update-skill").addEventListener("click", async () => {
  const name = $("skills").value;
  if (!name) return;
  const response = await fetch(`/api/skills/${encodeURIComponent(name)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content: $("new-skill-content").value }),
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
function historyRows(items) {
  return items
    .map(
      (item) =>
        `<div class="history-row${item.id === conversationId ? " active" : ""}" data-history-row="${escapeHtml(item.id)}"><button class="history-item" data-history-id="${escapeHtml(item.id)}" title="${escapeHtml(item.title || t("history.untitled"))}">${item.locked ? "🔒 " : ""}${escapeHtml(item.title || t("history.untitled"))}</button><div class="history-actions"><button class="history-action" data-history-action="rename" data-history-id="${escapeHtml(item.id)}" title="${escapeHtml(t("history.rename"))}">✎</button><button class="history-action" data-history-action="${item.pinned ? "unpin" : "pin"}" data-history-id="${escapeHtml(item.id)}" title="${escapeHtml(item.pinned ? t("history.unpin") : t("history.pin"))}">${item.pinned ? "📌" : "📍"}</button><button class="history-action" data-history-action="${item.locked ? "unlock" : "lock"}" data-history-id="${escapeHtml(item.id)}" title="${escapeHtml(item.locked ? t("history.unlock") : t("history.lock"))}">${item.locked ? "🔓" : "🔒"}</button><button class="history-action" data-history-action="delete" data-history-id="${escapeHtml(item.id)}" title="${escapeHtml(t("history.delete"))}">×</button></div></div>`,
    )
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
    ? `<div class="history-day">${escapeHtml(t("history.pinned"))}</div>${historyRows(pinned)}`
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
  const response = await fetch("/api/history");
  if (response.ok) {
    renderHistoryList((await response.json()).items || []);
    if (pendingHistoryAppends.size) flushPendingAppends();
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
  persistedMessageCount = recordMessages.length;
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
  messages.forEach((message) =>
    addMessage(message.role, message.content, message),
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
function applyTranslations() {
  applyStaticTranslations();
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
  if (connectionState.known) updateConnectionUi();
  renderMessages(true);
  renderHistoryList(currentHistoryItems);
  renderSchedules(currentSchedules);
  updateScheduleFormMode();
  renderAuthSessions();
  renderUpdatePanel();
  renderLogs();
  updateTerminalUi();
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
refreshTerminalAvailability();
