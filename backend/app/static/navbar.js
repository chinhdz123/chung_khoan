/* ========================================
   Navbar: Dark Mode Toggle + Hamburger Menu
   ======================================== */
(function () {
  "use strict";

  // --- Dark Mode ---
  const THEME_KEY = "kyluat-dautu-theme";

  function getPreferredTheme() {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === "dark" || saved === "light") return saved;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(THEME_KEY, theme);
    // Update toggle button icon
    const btn = document.getElementById("themeToggle");
    if (btn) {
      btn.textContent = theme === "dark" ? "☀️" : "🌙";
      btn.setAttribute("title", theme === "dark" ? "Chuyển sang sáng" : "Chuyển sang tối");
    }
  }

  // Apply theme immediately to prevent flash
  applyTheme(getPreferredTheme());

  // Listen for system theme changes
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
    if (!localStorage.getItem(THEME_KEY)) {
      applyTheme(e.matches ? "dark" : "light");
    }
  });

  // --- Hamburger Menu ---
  document.addEventListener("DOMContentLoaded", () => {
    const toggle = document.getElementById("themeToggle");
    if (toggle) {
      toggle.addEventListener("click", () => {
        const current = document.documentElement.getAttribute("data-theme") || "light";
        applyTheme(current === "dark" ? "light" : "dark");
      });
    }

    const hamburger = document.getElementById("navHamburger");
    const navLinks = document.getElementById("navLinks");
    if (hamburger && navLinks) {
      hamburger.addEventListener("click", () => {
        const isOpen = navLinks.classList.toggle("open");
        hamburger.setAttribute("aria-expanded", isOpen);
        hamburger.textContent = isOpen ? "✕" : "☰";
      });

      // Close menu when clicking outside
      document.addEventListener("click", (e) => {
        if (!hamburger.contains(e.target) && !navLinks.contains(e.target)) {
          navLinks.classList.remove("open");
          hamburger.setAttribute("aria-expanded", "false");
          hamburger.textContent = "☰";
        }
      });

      // Close menu when navigating
      navLinks.querySelectorAll(".nav-link").forEach((link) => {
        link.addEventListener("click", () => {
          navLinks.classList.remove("open");
          hamburger.setAttribute("aria-expanded", "false");
          hamburger.textContent = "☰";
        });
      });
    }
  });

  // --- Collapsible Groups ---
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".holdings-group-title[data-collapsible]").forEach((title) => {
      title.addEventListener("click", () => {
        const card = title.closest(".holdings-group-card");
        if (card) card.classList.toggle("collapsed");
      });
    });
  });
})();
