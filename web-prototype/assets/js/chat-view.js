(function () {
  "use strict";
  var AP = window.AP || (window.AP = {});
  AP.views = AP.views || {};

  var STOP_REASON = {
    sufficient: { tone: "success", icon: "check", label: "证据充分", text: "证据已覆盖主要问题，可逐条核对下方引用。" },
    insufficient: { tone: "danger", icon: "alert", label: "证据不足", text: "未找到足够证据支撑结论，请补充文档或调整问题。" },
    max_iterations: { tone: "warn", icon: "info", label: "达到最大轮次", text: "已达最大调研轮次，结论可能不完整。" },
    user_stopped: { tone: "warn", icon: "stop", label: "调研已停止", text: "你已中止本次调研，以下内容可能不完整。" },
    researching: { tone: "info", icon: "brain", label: "调研中", text: "正在逐轮检索、判断证据是否充分，请稍候。" },
  };

  function getSession(state, id) {
    return state.sessions.find(function (session) { return session.id === id; }) || state.sessions[0];
  }

  function renderAnswerText(text) {
    var lines = String(text || "").split("\n");
    var html = "";
    var inList = false;
    lines.forEach(function (line) {
      var match = line.match(/^\d+\.\s*(.*)$/);
      if (match) {
        if (!inList) { html += "<ol>"; inList = true; }
        html += "<li>" + AP.h.escape(match[1]) + "</li>";
        return;
      }
      if (inList) { html += "</ol>"; inList = false; }
      if (line.trim()) html += "<p>" + AP.h.escape(line) + "</p>";
    });
    if (inList) html += "</ol>";
    return html;
  }

  function citationMarkup(citation) {
    return [
      '<div class="citation">',
        '<div class="citation__head"><span class="row gap-1">' + AP.icon("file") + AP.h.escape(citation.documentName) + '</span><span class="text-2xs text-subtle">' + AP.h.escape(citation.page) + '</span></div>',
        '<div class="citation__meta">' + AP.h.escape(citation.section) + ' · 引用编号 ' + AP.h.escape(citation.id.toUpperCase()) + '</div>',
        '<div class="citation__snippet">' + AP.h.escape(citation.snippet) + '</div>',
      '</div>',
    ].join("");
  }

  function answerMarkup(message, state) {
    var answer = message.answer || {};
    var reason = STOP_REASON[answer.stopReason] || STOP_REASON.sufficient;
    var citations = answer.citations || [];
    var open = !!state.ui.openCitations[message.id];
    return [
      '<div class="answer-card">',
        '<div class="answer-card__head">',
          '<span class="answer-card__title">' + AP.icon("sparkles") + '调研答案</span>',
          '<span class="row gap-2">' +
            AP.h.confidence(answer.confidence || "medium") +
            '<button class="btn btn--ghost btn--sm rail-toggle" type="button" data-action="open-rail">' + AP.icon("panelRight") + '过程</button>' +
          '</span>',
        '</div>',
        '<div class="answer-card__body">',
          '<div class="notice notice--' + reason.tone + '">' + AP.icon(reason.icon) + '<span><strong>' + reason.label + '：</strong>' + reason.text + '</span></div>',
          '<div class="answer-text">' + renderAnswerText(answer.text) + '</div>',
          citations.length
            ? '<div class="citations ' + (open ? "is-open" : "") + '">' +
                '<button class="citations__summary" type="button" data-action="toggle-citations" data-id="' + message.id + '" aria-expanded="' + open + '">' +
                  AP.icon("chevronRight") + '查看 ' + citations.length + ' 条证据引用' +
                '</button>' +
                '<div class="citations__list">' + citations.map(citationMarkup).join("") + '</div>' +
              '</div>'
            : "",
          '<div class="answer-card__meta">' +
            '<span class="text-2xs text-subtle">' + AP.icon("clock") + ' 更新于 ' + AP.h.escape(message.createdAt) + '</span>' +
            '<span class="text-2xs text-subtle">调研轮次 ' + ((answer.rounds || []).length) + '</span>' +
          '</div>',
        '</div>',
      '</div>',
    ].join("");
  }

  function roundMarkup(round) {
    var isDone = round.state === "done";
    var decisionClass = round.decision === "stop" ? "timeline__decision--stop" : "timeline__decision--continue";
    var decisionLabel = round.decision === "stop" ? "判定：收尾" : "判定：继续";
    return [
      '<div class="timeline__item ' + (isDone ? "is-done" : "is-active") + '">',
        '<span class="timeline__node"></span>',
        '<div class="timeline__head"><span class="timeline__title">' + AP.h.escape(round.title) + '</span><span class="timeline__time">' + (isDone ? "已完成" : "进行中") + '</span></div>',
        '<div class="timeline__query">' + AP.h.escape(round.query) + '</div>',
        '<div class="timeline__stats">' +
          '<span>命中 ' + round.hits + ' 条</span><span>新增 ' + round.newHits + ' 条</span><span>最高分 ' + round.topScore.toFixed(2) + '</span>' +
        '</div>',
        '<div class="timeline__decision ' + decisionClass + '">' + decisionLabel + ' · ' + AP.h.escape(round.reason) + '</div>',
      '</div>',
    ].join("");
  }

  AP.views.chat = function (root, sessionId) {
    var timers = [];
    var state = AP.store.state;
    var session = getSession(state, sessionId);
    var currentId = session ? session.id : null;
    var sessionQuery = "";
    var running = AP.stream.isRunning();
    var assistantId = null;

    root.innerHTML = [
      '<section class="chat-shell">',
        '<aside class="session-sidebar" id="session-sidebar">',
          '<div class="sidebar__header">',
            '<div class="sidebar__title"><span>会话</span><button class="icon-btn" type="button" data-action="new-session" aria-label="新建会话">' + AP.icon("plus") + '</button></div>',
            '<label class="search-field">' + AP.icon("search") +
              '<input class="search-input" id="session-search" type="search" placeholder="搜索会话" aria-label="搜索会话" />' +
            '</label>',
          '</div>',
          '<div class="session-list" id="session-list"></div>',
        '</aside>',
        '<div class="chat-main">',
          '<div class="scope-bar">',
            '<button class="icon-btn mobile-menu-btn" type="button" data-action="toggle-sidebar" aria-label="打开会话列表">' + AP.icon("menu") + '</button>',
            '<span class="scope-bar__label">' + AP.icon("layers") + '检索范围</span>',
            '<div class="scope-tags" id="scope-tags"></div>',
            '<label class="row gap-1 text-xs text-subtle nowrap">添加<select class="select" id="scope-add" aria-label="添加文档到检索范围"></select></label>',
          '</div>',
          '<div class="messages" id="messages" aria-live="polite"></div>',
          '<div class="composer">',
            '<div class="composer__box">',
              '<textarea class="composer__textarea" id="question-input" rows="2" placeholder="基于当前检索范围提问，例如：报告提到的主要风险有哪些？" aria-label="输入问题"></textarea>',
              '<div class="composer__footer">',
                '<span class="composer__hint">Enter 发送 · Shift + Enter 换行 · 研究过程中可随时停止</span>',
                '<div class="composer__actions">',
                  '<button class="btn btn--outline" id="stop-btn" type="button" data-action="stop">' + AP.icon("stop") + '停止</button>',
                  '<button class="btn btn--primary" id="send-btn" type="button" data-action="send">' + AP.icon("send") + '发送</button>',
                '</div>',
              '</div>',
            '</div>',
          '</div>',
        '</div>',
        '<aside class="research-rail" id="research-rail">',
          '<div class="rail__header">',
            '<div class="rail__title">' + AP.icon("brain") + '调研过程</div>',
            '<div class="rail__subtitle">逐轮展示查询、命中与继续/收尾判定</div>',
            '<button class="btn btn--ghost btn--sm" type="button" data-action="close-rail" style="margin-top:8px">' + AP.icon("close") + '收起</button>',
          '</div>',
          '<div class="timeline" id="timeline"></div>',
          '<div class="rail__footer">证据来自检索切片，点击答案中的引用可核对原文片段。</div>',
        '</aside>',
      '</section>',
      '<div class="drawer-backdrop" id="drawer-backdrop" hidden></div>',
    ].join("");

    var sidebar = root.querySelector("#session-sidebar");
    var rail = root.querySelector("#research-rail");
    var backdrop = root.querySelector("#drawer-backdrop");
    var input = root.querySelector("#question-input");
    var sendBtn = root.querySelector("#send-btn");
    var stopBtn = root.querySelector("#stop-btn");
    var sessionSearch = root.querySelector("#session-search");

    function currentSession() {
      return AP.store.state.sessions.find(function (item) { return item.id === currentId; });
    }

    function currentMessages() {
      return AP.store.state.messages[currentId] || [];
    }

    function latestAssistant() {
      var list = currentMessages();
      for (var i = list.length - 1; i >= 0; i -= 1) {
        if (list[i].role === "assistant") return list[i];
      }
      return null;
    }

    function renderSidebar() {
      var q = sessionQuery.trim().toLowerCase();
      var sessions = AP.store.state.sessions.filter(function (item) {
        return !q || (item.title + " " + item.summary).toLowerCase().indexOf(q) >= 0;
      });
      var list = root.querySelector("#session-list");
      if (!sessions.length) {
        list.innerHTML = '<div class="empty"><div class="empty__art">' + AP.icon("chat") + '</div><h3 class="empty__title">没有会话</h3><p class="empty__desc">点击上方加号新建会话。</p></div>';
        return;
      }
      list.innerHTML = sessions.map(function (item) {
        return [
          '<div class="session-item-wrap">',
            '<button class="session-item ' + (item.id === currentId ? "is-active" : "") + '" type="button" data-action="switch-session" data-id="' + item.id + '">',
              '<span class="session-item__icon">' + AP.icon("chat") + '</span>',
              '<span class="session-item__body">',
                '<span class="session-item__title">' + AP.h.escape(item.title) + '</span>',
                '<span class="session-item__meta">' + AP.h.escape(item.summary) + ' · ' + AP.h.escape(item.createdAt) + '</span>',
              '</span>',
            '</button>',
            '<button class="icon-btn icon-btn--danger session-item__delete" type="button" data-action="delete-session" data-id="' + item.id + '" aria-label="删除会话 ' + AP.h.escape(item.title) + '">' + AP.icon("trash") + '</button>',
          '</div>',
        ].join("");
      }).join("");
    }

    function renderScope() {
      var session = currentSession();
      var stateNow = AP.store.state;
      var ids = session ? session.documentIds : [];
      var tags = ids.map(function (id) {
        var doc = stateNow.documents.find(function (item) { return item.id === id; });
        if (!doc) return "";
        return '<span class="tag tag--removable">' + AP.icon("file") + '<span class="truncate" style="max-width:150px">' + AP.h.escape(doc.name) + '</span>' +
          '<button class="tag__x" type="button" data-action="remove-scope" data-id="' + id + '" aria-label="移除 ' + AP.h.escape(doc.name) + '">' + AP.icon("close") + '</button></span>';
      }).filter(Boolean);

      root.querySelector("#scope-tags").innerHTML = tags.length
        ? tags.join("")
        : '<span class="tag">' + AP.icon("layers") + '全部文档</span>';

      var select = root.querySelector("#scope-add");
      select.innerHTML = '<option value="">+ 添加</option>' + stateNow.documents
        .filter(function (doc) { return doc.status === "ready" && ids.indexOf(doc.id) < 0; })
        .map(function (doc) { return '<option value="' + doc.id + '">' + AP.h.escape(doc.name) + '</option>'; })
        .join("");
    }

    function renderMessages() {
      var messages = currentMessages();
      var region = root.querySelector("#messages");
      if (!currentSession()) {
        region.innerHTML = '<div class="empty"><div class="empty__art">' + AP.icon("chat") + '</div><h3 class="empty__title">还没有会话</h3><p class="empty__desc">新建一个会话后即可开始提问。</p></div>';
        return;
      }
      if (!messages.length) {
        region.innerHTML = '<div class="empty">' +
          '<div class="empty__art">' + AP.icon("sparkles") + '</div>' +
          '<h3 class="empty__title">开始一次可核验的调研</h3>' +
          '<p class="empty__desc">提问后，系统会逐轮生成查询、检索证据、判断是否继续，并给出带引用的答案。</p>' +
          '</div>';
        return;
      }
      region.innerHTML = messages.map(function (message) {
        if (message.role === "user") {
          return '<div class="message message--user">' +
            '<span class="message__avatar">我</span>' +
            '<div class="message__body"><div class="bubble bubble--user">' + AP.h.escape(message.content) + '</div><span class="message__time">' + AP.h.escape(message.createdAt) + '</span></div>' +
          '</div>';
        }
        return '<div class="message message--assistant">' +
          '<span class="message__avatar">' + AP.icon("sparkles") + '</span>' +
          '<div class="message__body">' + answerMarkup(message, AP.store.state) + '<span class="message__time">' + AP.h.escape(message.createdAt) + '</span></div>' +
        '</div>';
      }).join("");
      region.scrollTop = region.scrollHeight;
    }

    function renderTimeline() {
      var answer = latestAssistant();
      var rounds = answer && answer.answer ? answer.answer.rounds || [] : [];
      var region = root.querySelector("#timeline");
      if (!rounds.length) {
        region.innerHTML = '<div class="timeline__empty empty"><div class="empty__art">' + AP.icon("brain") + '</div><h3 class="empty__title">调研过程尚未开始</h3><p class="empty__desc">发起提问后，每一轮的查询、召回与判定会在这里逐步呈现。</p></div>';
        return;
      }
      region.innerHTML = rounds.map(roundMarkup).join("");
      region.scrollTop = region.scrollHeight;
    }

    function renderComposer() {
      sendBtn.disabled = running;
      sendBtn.style.display = running ? "none" : "inline-flex";
      stopBtn.style.display = running ? "inline-flex" : "none";
      input.disabled = running;
      input.placeholder = running ? "调研进行中，可点击停止中止…" : "基于当前检索范围提问，例如：报告提到的主要风险有哪些？";
    }

    function renderDrawers() {
      var ui = AP.store.state.ui;
      sidebar.classList.toggle("is-open", !!ui.sidebarOpen);
      rail.classList.toggle("is-open", !!ui.railOpen);
      backdrop.hidden = !(ui.sidebarOpen || ui.railOpen);
    }

    function renderAll() {
      renderSidebar();
      renderScope();
      renderMessages();
      renderTimeline();
      renderComposer();
      renderDrawers();
    }

    function setSession(id) {
      if (running) AP.stream.stop("superseded");
      currentId = id;
      assistantId = null;
      AP.store.update(function (s) {
        s.currentSessionId = id;
        s.ui.sidebarOpen = false;
        s.ui.railOpen = false;
      });
      renderAll();
    }

    function submitQuestion() {
      var text = input.value.trim();
      if (!text || running) return;
      var session = currentSession();
      if (!session) {
        AP.ui.toast("error", "请先新建会话");
        return;
      }
      var scope = session.documentIds.map(function (id) {
        var doc = AP.store.state.documents.find(function (item) { return item.id === id; });
        return doc ? doc.name : "";
      }).filter(Boolean);
      var time = AP.h.timeNow().slice(11, 16);
      var userId = "m-" + Date.now() + "-u";
      var answerId = "m-" + Date.now() + "-a";
      assistantId = answerId;

      AP.store.update(function (s) {
        s.messages[currentId] = s.messages[currentId] || [];
        s.messages[currentId].push({ id: userId, role: "user", content: text, createdAt: time });
        s.messages[currentId].push({
          id: answerId,
          role: "assistant",
          createdAt: time,
          answer: { text: "正在整理调研结论…", confidence: "medium", stopReason: "researching", rounds: [], citations: [] },
        });
        var current = s.sessions.find(function (item) { return item.id === currentId; });
        if (current) {
          current.summary = text;
          current.messageCount += 2;
        }
      });
      input.value = "";
      running = true;
      renderAll();

      AP.stream.start({
        question: text,
        documentNames: scope,
        onEvent: function (event) {
          AP.store.update(function (s) {
            var list = s.messages[currentId] || [];
            var message = list.find(function (item) { return item.id === answerId; });
            if (!message || !message.answer) return;
            if (event.type === "round-start") message.answer.rounds.push(event.round);
            if (event.type === "round-done") {
              var round = message.answer.rounds.find(function (item) { return item.id === event.round.id; });
              if (round) { round.state = "done"; round.reason = event.round.reason; round.decision = event.round.decision; }
            }
            if (event.type === "answer") {
              message.answer.text = event.answer.text;
              message.answer.confidence = event.answer.confidence;
              message.answer.stopReason = event.answer.stopReason;
              message.answer.citations = event.answer.citations;
              message.answer.rounds = event.answer.rounds;
            }
            if (event.type === "stopped") {
              message.answer.stopReason = "user_stopped";
              message.answer.text = message.answer.text === "正在整理调研结论…"
                ? "调研已中止，尚未形成完整答案。你仍可查看上方已完成的轮次。"
                : message.answer.text;
            }
            if (event.type === "done" || event.type === "stopped") running = false;
          });
          renderMessages();
          renderTimeline();
          renderComposer();
        },
      });
    }

    function handleClick(event) {
      var target = event.target.closest("[data-action]");
      if (!target) return;
      var action = target.getAttribute("data-action");
      var id = target.getAttribute("data-id");

      if (action === "send") return submitQuestion();
      if (action === "stop") {
        AP.stream.stop("user_stopped");
        AP.ui.toast("info", "已停止本次调研");
        return;
      }
      if (action === "new-session") {
        if (running) AP.stream.stop("superseded");
        var scopeIds = currentSession() ? currentSession().documentIds.slice() : [];
        var newId = "s-" + Date.now();
        AP.store.update(function (s) {
          s.sessions.unshift({ id: newId, title: "新会话", summary: "尚未提问", documentIds: scopeIds, messageCount: 0, createdAt: AP.h.timeNow().slice(5, 16) });
          s.messages[newId] = [];
          s.currentSessionId = newId;
          s.ui.sidebarOpen = false;
        });
        AP.navigate("#/chat/" + newId);
        return;
      }
      if (action === "switch-session") return setSession(id);
      if (action === "delete-session") {
        AP.ui.confirm({ title: "删除会话", message: "确定删除这个会话及其历史消息吗？", confirmText: "删除" }).then(function (ok) {
          if (!ok) return;
          AP.store.update(function (s) {
            s.sessions = s.sessions.filter(function (item) { return item.id !== id; });
            delete s.messages[id];
            if (s.currentSessionId === id && s.sessions.length) s.currentSessionId = s.sessions[0].id;
          });
          if (!AP.store.state.sessions.length) {
            AP.store.update(function (s) {
              s.sessions.push({ id: "s-empty", title: "新会话", summary: "尚未提问", documentIds: [], messageCount: 0, createdAt: AP.h.timeNow().slice(5, 16) });
              s.messages["s-empty"] = [];
              s.currentSessionId = "s-empty";
            });
          }
          AP.navigate("#/chat/" + AP.store.state.currentSessionId);
          AP.ui.toast("success", "会话已删除");
        });
        return;
      }
      if (action === "toggle-sidebar") {
        AP.store.update(function (s) { s.ui.sidebarOpen = !s.ui.sidebarOpen; s.ui.railOpen = false; });
        renderDrawers();
        return;
      }
      if (action === "open-rail") {
        AP.store.update(function (s) { s.ui.railOpen = true; s.ui.sidebarOpen = false; });
        renderDrawers();
        return;
      }
      if (action === "close-rail") {
        AP.store.update(function (s) { s.ui.railOpen = false; });
        renderDrawers();
        return;
      }
      if (action === "remove-scope") {
        AP.store.update(function (s) {
          var sessionNow = s.sessions.find(function (item) { return item.id === currentId; });
          if (sessionNow) sessionNow.documentIds = sessionNow.documentIds.filter(function (item) { return item !== id; });
        });
        renderScope();
        return;
      }
      if (action === "toggle-citations") {
        AP.store.update(function (s) { s.ui.openCitations[id] = !s.ui.openCitations[id]; });
        renderMessages();
      }
    }

    function handleChange(event) {
      if (event.target.id === "scope-add") {
        var docId = event.target.value;
        if (!docId) return;
        AP.store.update(function (s) {
          var sessionNow = s.sessions.find(function (item) { return item.id === currentId; });
          if (sessionNow && sessionNow.documentIds.indexOf(docId) < 0) sessionNow.documentIds.push(docId);
        });
        renderScope();
      }
    }

    function handleInput(event) {
      if (event.target.id === "session-search") {
        sessionQuery = event.target.value;
        renderSidebar();
      }
    }

    function handleKeydown(event) {
      if (event.target === input && event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        submitQuestion();
      }
      if (event.key === "Escape") {
        AP.store.update(function (s) { s.ui.sidebarOpen = false; s.ui.railOpen = false; });
        renderDrawers();
      }
    }

    root.addEventListener("click", handleClick);
    root.addEventListener("change", handleChange);
    root.addEventListener("input", handleInput);
    document.addEventListener("keydown", handleKeydown);
    backdrop.addEventListener("click", function () {
      AP.store.update(function (s) { s.ui.sidebarOpen = false; s.ui.railOpen = false; });
      renderDrawers();
    });

    renderAll();

    return function cleanup() {
      timers.forEach(function (id) { window.clearTimeout(id); });
      AP.stream.stop("superseded");
      root.removeEventListener("click", handleClick);
      root.removeEventListener("change", handleChange);
      root.removeEventListener("input", handleInput);
      document.removeEventListener("keydown", handleKeydown);
    };
  };
})();
