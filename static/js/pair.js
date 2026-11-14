const CONFIG = {
  minutes: Number(document.body.dataset.pairingTtlMinutes || 0),
  days: Number(document.body.dataset.sessionDays || 0),
};
const THEME_KEY = "ai-control-center-theme";
const LANGUAGE_KEY = "ai-control-center-language";
const SUPPORTED_LANGUAGES = ["th", "en"];
const STRINGS = {
  en: {
    "meta.title": "Pair this device · AI Control Center",
    "control.language": "Language",
    "control.theme": "Toggle theme",
    "pair.title": "Pair this device",
    "pair.intro":
      "This web app requires a paired device. Generate a Pairing Key on the server, then enter it here. Each key is single-use and expires in {minutes} minutes.",
    "pair.keyLabel": "Pairing Key",
    "pair.labelLabel": "Device name (optional)",
    "pair.labelPlaceholder": "e.g. Phone, Laptop",
    "pair.submit": "Pair device",
    "pair.footCreate":
      "Create a key on the server that runs the app:",
    "pair.footNote":
      "Once paired, this device stays signed in for {days} days or until you revoke it in Settings.",
    "pair.success": "Paired. Opening the chat…",
    "pair.errorInvalid":
      "This Pairing Key is invalid, expired, or already used.",
    "pair.errorRateLimited":
      "Too many pairing attempts. Please wait a few minutes and try again.",
    "pair.errorGeneric": "Pairing failed. Please try again.",
  },
  th: {
    "meta.title": "จับคู่อุปกรณ์ · AI Control Center",
    "control.language": "ภาษา",
    "control.theme": "สลับธีม",
    "pair.title": "จับคู่อุปกรณ์ (Pairing)",
    "pair.intro":
      "เว็บนี้ต้องจับคู่อุปกรณ์ก่อนใช้งาน สร้าง Pairing Key จากฝั่ง server แล้วนำคีย์มาใส่ที่นี่ คีย์แต่ละใบใช้ได้ครั้งเดียวและมีอายุ {minutes} นาที",
    "pair.keyLabel": "Pairing Key",
    "pair.labelLabel": "ชื่ออุปกรณ์ (ไม่บังคับ)",
    "pair.labelPlaceholder": "เช่น มือถือ, โน้ตบุ๊ก",
    "pair.submit": "จับคู่อุปกรณ์",
    "pair.footCreate": "สร้างคีย์บนเครื่องที่รัน server:",
    "pair.footNote":
      "หลังจับคู่แล้วอุปกรณ์นี้จะเข้าใช้งานได้ {days} วัน หรือจนกว่าจะถูกยกเลิกในหน้า Settings",
    "pair.success": "จับคู่สำเร็จ กำลังเข้าสู่หน้าแชต...",
    "pair.errorInvalid":
      "Pairing Key ไม่ถูกต้อง หมดอายุ หรือถูกใช้ไปแล้ว",
    "pair.errorRateLimited":
      "พยายามจับคู่หลายครั้งเกินไป กรุณารอสักครู่แล้วลองใหม่",
    "pair.errorGeneric": "จับคู่ไม่สำเร็จ กรุณาลองใหม่",
  },
};

const form = document.getElementById("pair-form");
const keyInput = document.getElementById("pairing-key");
const labelInput = document.getElementById("pairing-label");
const submit = document.getElementById("pair-submit");
const errorBox = document.getElementById("pair-error");
const languageSelect = document.getElementById("language-select");
const themeToggle = document.getElementById("theme-toggle");

function readPreference(key) {
  try {
    return localStorage.getItem(key);
  } catch (error) {
    return null;
  }
}

function writePreference(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (error) {
    /* preferences are best-effort; pairing still works without storage */
  }
}

function savedLanguage() {
  const saved = readPreference(LANGUAGE_KEY);
  return SUPPORTED_LANGUAGES.includes(saved) ? saved : "en";
}
let language = savedLanguage();
let errorKey = "";

function t(key, vars = {}) {
  const dictionary = STRINGS[language] || STRINGS.en;
  const template = dictionary[key] ?? STRINGS.en[key] ?? key;
  return String(template).replace(/\{(\w+)\}/g, (match, name) =>
    vars[name] === undefined || vars[name] === null
      ? match
      : String(vars[name]),
  );
}

function applyLanguage() {
  document.documentElement.lang = language;
  document.title = t("meta.title");
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
  languageSelect.value = language;
  document.getElementById("pair-foot-note").textContent = t(
    "pair.footNote",
    { days: CONFIG.days },
  );
  document.querySelector('[data-i18n="pair.intro"]').textContent = t(
    "pair.intro",
    { minutes: CONFIG.minutes },
  );
  errorBox.textContent = errorKey ? t(errorKey) : "";
}

function applyTheme(theme) {
  const light = theme === "light";
  document.documentElement.classList.toggle("light-theme", light);
  themeToggle.textContent = light ? "☾" : "☼";
}

languageSelect.addEventListener("change", (event) => {
  language = SUPPORTED_LANGUAGES.includes(event.target.value)
    ? event.target.value
    : "en";
  writePreference(LANGUAGE_KEY, language);
  applyLanguage();
});

themeToggle.addEventListener("click", () => {
  const light =
    !document.documentElement.classList.contains("light-theme");
  writePreference(THEME_KEY, light ? "light" : "dark");
  applyTheme(light ? "light" : "dark");
});

applyTheme(readPreference(THEME_KEY) === "light" ? "light" : "dark");
applyLanguage();

function groupKey(value) {
  const cleaned = value
    .toUpperCase()
    .replace(/[^0-9A-Z]/g, "")
    .slice(0, 12);
  return cleaned.replace(/(.{4})(?=.)/g, "$1-");
}

keyInput.addEventListener("input", () => {
  const caretAtEnd = keyInput.selectionStart === keyInput.value.length;
  keyInput.value = groupKey(keyInput.value);
  if (caretAtEnd) {
    keyInput.setSelectionRange(
      keyInput.value.length,
      keyInput.value.length,
    );
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorKey = "";
  errorBox.textContent = "";
  errorBox.classList.remove("ok");
  submit.disabled = true;
  try {
    const response = await fetch("/api/auth/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        key: keyInput.value,
        label: labelInput.value,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      errorKey =
        response.status === 429
          ? "pair.errorRateLimited"
          : response.status === 401
            ? "pair.errorInvalid"
            : "pair.errorGeneric";
      throw new Error(t(errorKey));
    }
    errorBox.textContent = t("pair.success");
    errorBox.classList.add("ok");
    window.location.replace(data.redirect || "/");
  } catch (error) {
    if (!errorKey) errorKey = "pair.errorGeneric";
    errorBox.textContent = t(errorKey);
    submit.disabled = false;
    keyInput.select();
  }
});

keyInput.focus();
