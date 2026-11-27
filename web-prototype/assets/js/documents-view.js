(function () {
  "use strict";
  var AP = window.AP || (window.AP = {});
  AP.views = AP.views || {};

  var PAGE_SIZE = 5;
  var MAX_SIZE = 50 * 1024 * 1024;
  var ALLOWED = ["pdf", "md", "txt"];

  function statusClass(status) {
    var meta = AP.data.STATUS_META[status] || { tone: "idle", label: status };
    return { tone: meta.tone, label: meta.label };
  }

  function isActiveStatus(status) {
    return ["uploaded", "parsing", "chunking", "embedding"].indexOf(status) >= 0;
  }

  function progressFor(status) {
    return { uploaded: 12, parsing: 38, chunking: 62, embedding: 86 }[status] || 0;
  }

  function filteredDocuments(state) {
    var q = state.docQuery.trim().toLowerCase();
    return state.documents.filter(function (doc) {
      var matchText = !q || doc.name.toLowerCase().indexOf(q) >= 0;
      var matchStatus = true;
      if (state.docFilter === "ready") matchStatus = doc.status === "ready";
      if (state.docFilter === "processing") matchStatus = isActiveStatus(doc.status);
      if (state.docFilter === "failed") matchStatus = doc.status === "failed";
      return matchText && matchStatus;
    });
  }

  AP.views.documents = function (root) {
    var timers = [];
    var state = AP.store.state;

    root.innerHTML = [
      '<section class="page">',
        '<header class="page-header">',
          '<div>',
            '<span class="page-eyebrow">Knowledge Base</span>',
            '<h1 class="page-title">文档管理</h1>',
            '<p class="page-subtitle">上传资料、跟踪入库进度，并挑选文档作为提问的检索范围。</p>',
          '</div>',
          '<div class="page-actions">',
            '<button class="btn btn--outline" id="demo-upload" type="button">' + AP.icon("sparkles") + '添加演示文件</button>',
          '</div>',
        '</header>',
        '<div id="global-error-region"></div>',
        '<div class="upload" id="upload-zone" tabindex="0" role="button" aria-label="上传文档，可拖放文件到此处">',
          '<div class="upload__icon">' + AP.icon("upload") + '</div>',
          '<div class="upload__title">拖拽文件到此处，或点击选择</div>',
          '<div class="upload__hint">支持 PDF / Markdown / TXT，单个文件不超过 50 MB</div>',
          '<div class="upload__meta">上传后自动进入解析 → 切片 → 向量化流程</div>',
          '<div class="upload__actions">',
            '<button class="btn btn--primary btn--sm" id="pick-files" type="button">' + AP.icon("plus") + '选择文件</button>',
            '<span class="text-xs text-subtle">不会发起真实网络请求</span>',
          '</div>',
          '<input class="sr-only" id="file-input" type="file" multiple accept=".pdf,.md,.txt" />',
        '</div>',
        '<div class="processing" id="processing-list"></div>',
        '<div class="card" id="document-card">',
          '<div class="card__header">',
            '<div class="card__title">' + AP.icon("docs") + '文档列表</div>',
            '<span class="text-xs text-subtle" id="doc-total"></span>',
          '</div>',
          '<div class="table-toolbar">',
            '<label class="search-field">',
              AP.icon("search"),
              '<input class="search-input" id="doc-search" type="search" placeholder="搜索文档名称" aria-label="搜索文档名称" />',
            '</label>',
            '<label class="select" style="display:inline-flex;align-items:center;gap:8px">',
              AP.icon("filter"),
              '<select class="select" id="doc-filter" style="border:0;padding:0;height:32px" aria-label="按状态筛选文档">',
                '<option value="all">全部状态</option>',
                '<option value="ready">就绪</option>',
                '<option value="processing">处理中</option>',
                '<option value="failed">失败</option>',
              '</select>',
            '</label>',
          '</div>',
          '<div id="table-region"></div>',
        '</div>',
        '<div id="selection-region"></div>',
      '</section>',
    ].join("");

    var uploadZone = root.querySelector("#upload-zone");
    var fileInput = root.querySelector("#file-input");
    var searchInput = root.querySelector("#doc-search");
    var filterSelect = root.querySelector("#doc-filter");

    searchInput.value = state.docQuery;
    filterSelect.value = state.docFilter;

    function renderTable() {
      var region = root.querySelector("#table-region");
      var totalLabel = root.querySelector("#doc-total");
      var visible = filteredDocuments(state);
      var totalPages = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
      if (state.docPage > totalPages) state.docPage = totalPages;
      var pageDocs = visible.slice((state.docPage - 1) * PAGE_SIZE, state.docPage * PAGE_SIZE);
      totalLabel.textContent = "共 " + state.documents.length + " 篇文档";

      if (state.documents.length === 0) {
        region.innerHTML =
          '<div class="empty">' +
            '<div class="empty__art">' + AP.icon("docs") + '</div>' +
            '<h3 class="empty__title">还没有文档</h3>' +
            '<p class="empty__desc">上传第一篇 PDF、Markdown 或 TXT 文档，系统会自动解析切片并建立可检索索引。</p>' +
            '<div class="empty__actions"><button class="btn btn--primary" type="button" data-action="focus-upload">' + AP.icon("upload") + '上传第一篇文档</button></div>' +
          '</div>';
        return;
      }

      if (visible.length === 0) {
        region.innerHTML =
          '<div class="empty">' +
            '<div class="empty__art">' + AP.icon("search") + '</div>' +
            '<h3 class="empty__title">没有匹配的文档</h3>' +
            '<p class="empty__desc">试试更换关键词或清除状态筛选。</p>' +
            '<div class="empty__actions"><button class="btn btn--outline" type="button" data-action="clear-filters">清除筛选</button></div>' +
          '</div>';
        return;
      }

      var rows = pageDocs
        .map(function (doc) {
          var selected = state.selectedDocIds.indexOf(doc.id) >= 0;
          var deleting = state.ui.deleting && state.ui.deleting[doc.id];
          var statusMarkup = deleting
            ? '<span class="status status--idle"><span class="status__dot"></span>删除中</span>'
            : AP.h.status(doc.status);
          var selectable = doc.status === "ready" && !deleting;
          var expanded = state.ui.expandedFailure[doc.id];
          var row = [
            '<tr class="' + (selected ? "is-selected" : "") + '" data-row="' + doc.id + '">',
              '<td data-label="选择"><input class="table__check" type="checkbox" data-action="select-doc" data-id="' + doc.id + '" ' + (selected ? "checked" : "") + ' ' + (selectable ? "" : "disabled") + ' aria-label="选择 ' + AP.h.escape(doc.name) + '" /></td>',
              '<td data-label="文件名"><div class="table__name"><span class="table__file-icon">' + AP.icon("file") + '</span><span class="table__name-text"><strong>' + AP.h.escape(doc.name) + '</strong><span class="text-2xs text-subtle">' + doc.id + '</span></span></div></td>',
              '<td data-label="格式"><span class="tag">' + doc.format + '</span></td>',
              '<td data-label="大小" class="text-sm text-secondary">' + doc.size + '</td>',
              '<td data-label="状态">' + statusMarkup + '</td>',
              '<td data-label="切片" class="text-sm text-secondary">' + (doc.chunks === null ? "—" : doc.chunks) + '</td>',
              '<td data-label="操作"><div class="table__actions">',
                doc.status === "failed" ? '<button class="table__expand" type="button" data-action="toggle-error" data-id="' + doc.id + '">' + (expanded ? "收起原因" : "查看原因") + '</button>' : "",
                doc.status === "failed" ? '<button class="icon-btn" type="button" data-action="retry" data-id="' + doc.id + '" aria-label="重试处理 ' + AP.h.escape(doc.name) + '">' + AP.icon("retry") + '</button>' : "",
                '<button class="icon-btn icon-btn--danger" type="button" data-action="delete-doc" data-id="' + doc.id + '" aria-label="删除 ' + AP.h.escape(doc.name) + '">' + AP.icon("trash") + '</button>',
              '</div></td>',
            '</tr>',
          ];
          if (expanded && doc.error) {
            row.push('<tr class="table__expanded" data-error-row="' + doc.id + '"><td colspan="7">' + AP.icon("alert") + ' ' + AP.h.escape(doc.error) + '</td></tr>');
          }
          return row.join("");
        })
        .join("");

      region.innerHTML =
        '<div class="table-wrap"><table class="table">' +
          '<thead><tr><th>选择</th><th>文件名</th><th>格式</th><th>大小</th><th>状态</th><th>切片</th><th>操作</th></tr></thead>' +
          '<tbody>' + rows + '</tbody>' +
        '</table></div>' +
        '<div class="pagination"><span>第 ' + state.docPage + ' / ' + totalPages + ' 页 · 显示 ' + pageDocs.length + ' 条</span>' +
          '<span class="row gap-2">' +
            '<button class="btn btn--ghost btn--sm" type="button" data-action="prev-page" ' + (state.docPage <= 1 ? "disabled" : "") + '>上一页</button>' +
            '<button class="btn btn--ghost btn--sm" type="button" data-action="next-page" ' + (state.docPage >= totalPages ? "disabled" : "") + '>下一页</button>' +
          '</span></div>';
    }

    function renderProcessing() {
      var region = root.querySelector("#processing-list");
      var active = state.documents.filter(function (doc) {
        return isActiveStatus(doc.status) && !(state.ui.deleting && state.ui.deleting[doc.id]);
      });
      if (active.length === 0) {
        region.innerHTML = "";
        return;
      }
      region.innerHTML =
        '<div class="card"><div class="card__header"><div class="card__title">' + AP.icon("clock") + '处理中</div>' +
        '<span class="text-xs text-subtle">' + active.length + ' 个任务</span></div>' +
        '<div class="card__body processing">' +
          active.map(function (doc) {
            return '<div class="processing__item">' +
              '<div class="processing__name">' + AP.icon("file") + '<span class="truncate">' + AP.h.escape(doc.name) + '</span></div>' +
              AP.h.status(doc.status) +
              '<div class="progress" role="progressbar" aria-label="' + AP.h.escape(doc.name) + '处理进度" aria-valuenow="' + progressFor(doc.status) + '" aria-valuemin="0" aria-valuemax="100"><div class="progress__bar" style="width:' + progressFor(doc.status) + '%"></div></div>' +
              '<span class="processing__stage text-xs text-subtle">' + Math.round(progressFor(doc.status)) + '%</span>' +
            '</div>';
          }).join("") +
        '</div></div>';
    }

    function renderSelection() {
      var region = root.querySelector("#selection-region");
      var selected = state.documents.filter(function (doc) {
        return state.selectedDocIds.indexOf(doc.id) >= 0 && doc.status === "ready";
      });
      region.innerHTML =
        '<div class="selection-bar">' +
          '<div class="selection-bar__count">' +
            '<strong>' + selected.length + '</strong><span>篇就绪文档已选择</span>' +
            (selected.length ? '<button class="btn btn--ghost btn--sm" type="button" data-action="clear-selection">清空</button>' : '<span class="text-xs text-subtle">仅就绪文档可加入检索范围</span>') +
          '</div>' +
          '<button class="btn btn--primary" type="button" data-action="ask-selected" ' + (selected.length ? "" : "disabled") + '>' +
            '基于选中文档发起提问' + AP.icon("arrowRight") +
          '</button>' +
        '</div>';
    }

    function renderError() {
      var region = root.querySelector("#global-error-region");
      if (state.scenario !== "upload-failed") {
        region.innerHTML = "";
        return;
      }
      region.innerHTML =
        '<div class="error-banner">' + AP.icon("alert") +
        '<span>文档入库失败：文件疑似扫描件或已加密，无法提取可检索文本。</span>' +
        '<button class="btn btn--ghost btn--sm" type="button" data-action="dismiss-error">知道了</button></div>';
    }

    function renderAll() {
      renderTable();
      renderProcessing();
      renderSelection();
    }

    function simulateProcessing(docId, shouldFail) {
      var flow = AP.data.STATUS_FLOW;
      var step = 0;
      var run = function () {
        if (!root.isConnected) return;
        if (step >= flow.length) return;
        var status = flow[step];
        var finalFail = shouldFail && step === flow.length - 1;
        AP.store.update(function (s) {
          var doc = s.documents.find(function (item) { return item.id === docId; });
          if (!doc) return;
          doc.status = finalFail ? "failed" : status;
          doc.chunks = finalFail ? null : (status === "ready" ? Math.max(12, Math.round(doc.size.length * 7)) : null);
          if (finalFail) doc.error = "未能提取到可检索的文本：文件疑似扫描件或已损坏。";
        });
        renderAll();
        step += 1;
        if (finalFail || step >= flow.length) return;
        timers.push(window.setTimeout(run, AP.h.reducedMotion() ? 40 : 520));
      };
      timers.push(window.setTimeout(run, AP.h.reducedMotion() ? 40 : 360));
    }

    function addFiles(files) {
      var list = Array.prototype.slice.call(files || []);
      if (!list.length) return;
      var added = 0;
      list.forEach(function (file) {
        var ext = (file.name.split(".").pop() || "").toLowerCase();
        if (ALLOWED.indexOf(ext) < 0) {
          AP.ui.toast("error", "不支持的格式：" + file.name);
          return;
        }
        if (file.size > MAX_SIZE) {
          AP.ui.toast("error", "文件超过 50 MB：" + file.name);
          return;
        }
        var duplicate = AP.store.state.documents.some(function (doc) { return doc.name === file.name; });
        if (duplicate) {
          AP.ui.toast("info", "该文件已上传过，已复用原记录：" + file.name);
          return;
        }
        var id = "d-" + Date.now() + "-" + added;
        var shouldFail = AP.store.state.scenario === "upload-failed" || /扫描|加密|damaged/i.test(file.name);
        AP.store.update(function (s) {
          s.documents.unshift({
            id: id,
            name: file.name,
            format: ext.toUpperCase(),
            size: AP.h.formatSize(file.size),
            status: "uploaded",
            chunks: null,
            createdAt: AP.h.timeNow(),
          });
        });
        added += 1;
        simulateProcessing(id, shouldFail);
      });
      if (added) {
        renderAll();
        AP.ui.toast("success", "已加入处理队列：" + added + " 个文件");
      }
      fileInput.value = "";
    }

    function handleClick(event) {
      var target = event.target.closest("[data-action]");
      if (target) {
        var action = target.getAttribute("data-action");
        var id = target.getAttribute("data-id");
        if (action === "focus-upload") {
          uploadZone.classList.add("is-dragging");
          fileInput.click();
          window.setTimeout(function () { uploadZone.classList.remove("is-dragging"); }, 300);
          return;
        }
        if (action === "clear-filters") {
          AP.store.update(function (s) { s.docQuery = ""; s.docFilter = "all"; s.docPage = 1; });
          searchInput.value = "";
          filterSelect.value = "all";
          renderAll();
          return;
        }
        if (action === "dismiss-error") {
          root.querySelector("#global-error-region").innerHTML = "";
          return;
        }
        if (action === "toggle-error") {
          AP.store.update(function (s) { s.ui.expandedFailure[id] = !s.ui.expandedFailure[id]; });
          renderTable();
          return;
        }
        if (action === "clear-selection") {
          AP.store.update(function (s) { s.selectedDocIds = []; });
          renderTable();
          renderSelection();
          return;
        }
        if (action === "prev-page" || action === "next-page") {
          AP.store.update(function (s) { s.docPage += action === "next-page" ? 1 : -1; });
          renderTable();
          return;
        }
        if (action === "retry") {
          AP.store.update(function (s) {
            var doc = s.documents.find(function (item) { return item.id === id; });
            if (doc) { doc.status = "uploaded"; doc.error = null; }
          });
          AP.ui.toast("info", "已重新加入处理队列");
          simulateProcessing(id, false);
          return;
        }
        if (action === "delete-doc") {
          var doc = AP.store.state.documents.find(function (item) { return item.id === id; });
          if (!doc) return;
          AP.ui.confirm({
            title: "删除文档",
            message: "确定删除「" + doc.name + "」吗？删除后该文档将不再出现在检索范围中。",
            confirmText: "删除",
          }).then(function (ok) {
            if (!ok) return;
            AP.store.update(function (s) {
              s.ui.deleting = s.ui.deleting || {};
              s.ui.deleting[id] = true;
              s.selectedDocIds = s.selectedDocIds.filter(function (item) { return item !== id; });
            });
            timers.push(window.setTimeout(function () {
              AP.store.update(function (s) {
                s.documents = s.documents.filter(function (item) { return item.id !== id; });
                if (s.ui.deleting) delete s.ui.deleting[id];
              });
              AP.ui.toast("success", "已删除：" + doc.name);
            }, AP.h.reducedMotion() ? 20 : 700));
          });
          return;
        }
        if (action === "ask-selected") {
          var selected = AP.store.state.documents.filter(function (doc) {
            return AP.store.state.selectedDocIds.indexOf(doc.id) >= 0 && doc.status === "ready";
          });
          if (!selected.length) return;
          var sessionId = "s-" + Date.now();
          AP.store.update(function (s) {
            s.sessions.unshift({
              id: sessionId,
              title: "新会话 · " + selected.length + " 篇文档",
              summary: "尚未提问",
              documentIds: selected.map(function (doc) { return doc.id; }),
              messageCount: 0,
              createdAt: AP.h.timeNow().slice(5),
            });
            s.messages[sessionId] = [];
            s.currentSessionId = sessionId;
            s.selectedDocIds = [];
          });
          AP.ui.toast("success", "已创建会话，检索范围包含 " + selected.length + " 篇文档");
          AP.navigate("#/chat/" + sessionId);
          return;
        }
      }

      if (event.target.closest("#demo-upload")) {
        var suffix = String(Date.now()).slice(-4);
        addFiles([{ name: "新上传的研究资料_" + suffix + ".pdf", size: 3.6 * 1024 * 1024 }]);
        return;
      }
      if (event.target.closest("#pick-files")) {
        fileInput.click();
      }
    }

    function handleChange(event) {
      if (event.target.id === "doc-filter") {
        AP.store.update(function (s) { s.docFilter = event.target.value; s.docPage = 1; });
        renderTable();
        return;
      }
      if (event.target.matches('[data-action="select-doc"]')) {
        var id = event.target.getAttribute("data-id");
        var checked = event.target.checked;
        AP.store.update(function (s) {
          if (checked && s.selectedDocIds.indexOf(id) < 0) s.selectedDocIds.push(id);
          if (!checked) s.selectedDocIds = s.selectedDocIds.filter(function (item) { return item !== id; });
        });
        renderTable();
        renderSelection();
      }
    }

    function handleInput(event) {
      if (event.target.id === "doc-search") {
        AP.store.update(function (s) { s.docQuery = event.target.value; s.docPage = 1; });
        renderTable();
      }
    }

    function handleDrag(event) {
      event.preventDefault();
      uploadZone.classList.add("is-dragging");
    }

    function handleDragLeave(event) {
      if (!uploadZone.contains(event.relatedTarget)) uploadZone.classList.remove("is-dragging");
    }

    function handleDrop(event) {
      event.preventDefault();
      uploadZone.classList.remove("is-dragging");
      addFiles(event.dataTransfer && event.dataTransfer.files);
    }

    root.addEventListener("click", handleClick);
    root.addEventListener("change", handleChange);
    root.addEventListener("input", handleInput);
    uploadZone.addEventListener("dragover", handleDrag);
    uploadZone.addEventListener("dragleave", handleDragLeave);
    uploadZone.addEventListener("drop", handleDrop);

    renderAll();
    renderError();

    return function cleanup() {
      timers.forEach(function (id) { window.clearTimeout(id); });
      root.removeEventListener("click", handleClick);
      root.removeEventListener("change", handleChange);
      root.removeEventListener("input", handleInput);
      uploadZone.removeEventListener("dragover", handleDrag);
      uploadZone.removeEventListener("dragleave", handleDragLeave);
      uploadZone.removeEventListener("drop", handleDrop);
    };
  };
})();
