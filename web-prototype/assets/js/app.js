(function () {
  "use strict";
  var AP = window.AP || (window.AP = {});

  AP.h = {
    escape: function (value) {
      return String(value === null || value === undefined ? "" : value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    },

    status: function (status) {
      var meta = AP.data.STATUS_META[status] || { tone: "idle", label: status };
      return '<span class="status status--' + meta.tone + '"><span class="status__dot"></span>' + meta.label + "</span>";
    },

    confidence: function (level) {
      var labels = { high: "高", medium: "中等", low: "低", insufficient: "不足" };
      return '<span class="confidence confidence--' + level + '">置信度 ' + (labels[level] || level) + "</span>";
    },

    formatSize: function (bytes) {
      if (bytes < 1024) return bytes + " B";
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
      return (bytes / (1024 * 1024)).toFixed(1) + " MB";
    },

    timeNow: function () {
      var d = new Date();
      var pad = function (n) { return String(n).padStart(2, "0"); };
      return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
        " " + pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
    },

    reducedMotion: function () {
      return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    },
  };

  AP.ui = {
    toast: function (type, message) {
      var region = document.getElementById("toast-region");
      if (!region) return;
      var icons = { success: "check", info: "info", error: "alert" };
      var node = document.createElement("div");
      node.className = "toast toast--" + (icons[type] ? type : "info");
      node.innerHTML = AP.icon(icons[type] || "info") + "<span>" + AP.h.escape(message) + "</span>";
      region.appendChild(node);
      window.setTimeout(function () {
        node.style.opacity = "0";
        node.style.transform = "translateY(6px)";
        window.setTimeout(function () { node.remove(); }, 200);
      }, 2800);
    },

    confirm: function (options) {
      var dialog = document.getElementById("confirm-dialog");
      var title = document.getElementById("confirm-title");
      var message = document.getElementById("confirm-message");
      var icon = document.getElementById("confirm-icon");
      var okBtn = dialog.querySelector("[data-confirm-ok]");
      var cancelBtn = dialog.querySelector("[data-confirm-cancel]");

      title.textContent = options.title || "确认操作";
      message.textContent = options.message || "";
      okBtn.textContent = options.confirmText || "确认";
      icon.innerHTML = AP.icon("alert");

      return new Promise(function (resolve) {
        function cleanup() {
          okBtn.removeEventListener("click", onOk);
          cancelBtn.removeEventListener("click", onCancel);
          dialog.removeEventListener("cancel", onDialogCancel);
        }
        function finish(value) {
          cleanup();
          if (dialog.open) dialog.close();
          resolve(value);
        }
        function onOk() { finish(true); }
        function onCancel() { finish(false); }
        function onDialogCancel(event) { event.preventDefault(); finish(false); }

        okBtn.addEventListener("click", onOk);
        cancelBtn.addEventListener("click", onCancel);
        dialog.addEventListener("cancel", onDialogCancel);
        dialog.showModal();
      });
    },
  };

  AP.navigate = function (hash) {
    if (window.location.hash === hash) render();
    else window.location.hash = hash;
  };

  var root = document.getElementById("app");
  var cleanupView = null;

  function topbarMarkup(active) {
    var themes = [
      { id: "blue-gray", label: "蓝灰" },
      { id: "dark-lab", label: "深色" },
      { id: "paper", label: "纸感" },
    ];
    return [
      '<header class="topbar">',
        '<div class="topbar__inner">',
          '<a class="brand" href="#/documents" aria-label="Alethix 探赜首页">',
            '<span class="brand__mark">' + AP.icon("logo") + '</span>',
            '<span class="brand__text"><span class="brand__name">Alethix · 探赜</span><span class="brand__sub">Evidence-first reading</span></span>',
          '</a>',
          '<nav class="nav" id="primary-nav" aria-label="主导航">',
            '<a class="nav-link ' + (active === "documents" ? "is-active" : "") + '" href="#/documents">' + AP.icon("docs") + '文档管理</a>',
            '<a class="nav-link ' + (active === "chat" ? "is-active" : "") + '" href="#/chat">' + AP.icon("chat") + '智能问答</a>',
          '</nav>',
          '<span class="topbar__spacer"></span>',
          '<div class="topbar__actions">',
            '<div class="theme-switch" role="group" aria-label="视觉风格切换">' +
              themes.map(function (theme) {
                return '<button type="button" class="theme-switch__btn ' + (AP.store.theme === theme.id ? "is-active" : "") + '" data-theme-btn="' + theme.id + '" aria-pressed="' + (AP.store.theme === theme.id) + '">' + theme.label + '</button>';
              }).join("") +
            '</div>',
            '<select class="demo-select" id="scenario-select" aria-label="演示场景">' +
              AP.data.scenarios.map(function (s) {
                return '<option value="' + s.id + '" ' + (AP.store.state.scenario === s.id ? "selected" : "") + '>' + s.label + '</option>';
              }).join("") +
            '</select>',
            '<button class="icon-btn mobile-menu-btn" id="mobile-menu" type="button" aria-label="切换导航菜单">' + AP.icon("menu") + '</button>',
          '</div>',
        '</div>',
      '</header>',
    ].join("");
  }

  function ensureSession() {
    var state = AP.store.state;
    if (state.currentSessionId && state.sessions.some(function (s) { return s.id === state.currentSessionId; })) {
      return state.currentSessionId;
    }
    if (state.sessions.length) return state.sessions[0].id;
    var id = "s-" + Date.now();
    AP.store.update(function (s) {
      s.sessions.push({ id: id, title: "新会话", summary: "尚未提问", documentIds: [], messageCount: 0, createdAt: AP.h.timeNow().slice(5, 16) });
      s.messages[id] = [];
      s.currentSessionId = id;
    });
    return id;
  }

  function renderNotFound(main) {
    main.innerHTML =
      '<section class="page"><div class="card"><div class="empty">' +
        '<div class="empty__art">' + AP.icon("search") + '</div>' +
        '<h2 class="empty__title">页面不存在</h2>' +
        '<p class="empty__desc">这个原型只包含文档管理与智能问答两个页面。</p>' +
        '<div class="empty__actions"><a class="btn btn--primary" href="#/documents">返回文档管理</a></div>' +
      '</div></div></section>';
  }

  function render() {
    if (cleanupView) {
      cleanupView();
      cleanupView = null;
    }

    var hash = window.location.hash || "#/documents";
    var route = "documents";
    var sessionId = null;

    if (hash.indexOf("#/chat") === 0) {
      route = "chat";
      sessionId = hash.split("/")[2] || null;
    } else if (hash !== "#/documents") {
      route = "notfound";
    }

    if (route === "chat" && !sessionId) {
      sessionId = ensureSession();
      window.location.replace("#/chat/" + sessionId);
      return;
    }
    if (route === "chat" && !AP.store.state.sessions.some(function (s) { return s.id === sessionId; })) {
      sessionId = ensureSession();
      window.location.replace("#/chat/" + sessionId);
      return;
    }

    root.innerHTML = topbarMarkup(route) + '<main class="main" id="main-content"></main>';
    var main = document.getElementById("main-content");

    document.querySelectorAll("[data-theme-btn]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var next = btn.getAttribute("data-theme-btn");
        AP.store.setTheme(next);
        document.querySelectorAll("[data-theme-btn]").forEach(function (item) {
          var active = item.getAttribute("data-theme-btn") === next;
          item.classList.toggle("is-active", active);
          item.setAttribute("aria-pressed", String(active));
        });
      });
    });

    var scenarioSelect = document.getElementById("scenario-select");
    scenarioSelect.addEventListener("change", function () {
      AP.store.setScenario(scenarioSelect.value);
      render();
      AP.ui.toast("info", "已切换演示场景：" + scenarioSelect.options[scenarioSelect.selectedIndex].text);
    });

    document.getElementById("mobile-menu").addEventListener("click", function () {
      document.getElementById("primary-nav").classList.toggle("is-open");
    });

    try {
      if (route === "documents") cleanupView = AP.views.documents(main);
      else if (route === "chat") cleanupView = AP.views.chat(main, sessionId);
      else renderNotFound(main);
    } catch (error) {
      console.error("[prototype] render error", error);
      main.innerHTML =
        '<section class="page"><div class="card"><div class="empty">' +
          '<div class="empty__art">' + AP.icon("alert") + '</div>' +
          '<h2 class="empty__title">页面渲染遇到问题</h2>' +
          '<p class="empty__desc">' + AP.h.escape(error && error.message ? error.message : "未知错误") + '</p>' +
          '<div class="empty__actions"><button class="btn btn--primary" type="button" id="retry-render">重新加载</button></div>' +
        '</div></div></section>';
      document.getElementById("retry-render").addEventListener("click", render);
    }
  }

  window.addEventListener("hashchange", render);

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", render);
  } else {
    render();
  }
})();
