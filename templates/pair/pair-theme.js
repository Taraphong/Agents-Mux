/* Apply the saved theme before first paint to avoid a flash. */
(function () {
  try {
    var theme = localStorage.getItem("ai-control-center-theme");
    if (theme === "light") {
      document.documentElement.classList.add("light-theme");
    }
  } catch (error) {
    /* ignore unavailable storage */
  }
})();
