(function () {
  "use strict";
  var AP = window.AP || (window.AP = {});

  var STATUS_META = {
    uploaded: { label: "已上传", tone: "idle" },
    parsing: { label: "解析中", tone: "progress" },
    chunking: { label: "切片中", tone: "progress" },
    embedding: { label: "向量化中", tone: "progress" },
    ready: { label: "就绪", tone: "ready" },
    failed: { label: "失败", tone: "failed" },
  };

  var STATUS_FLOW = ["uploaded", "parsing", "chunking", "embedding", "ready"];

  var DOCUMENTS = [
    { id: "d-001", name: "2026_ai_industry_report.pdf", format: "PDF", size: "2.4 MB", status: "ready", chunks: 235, createdAt: "2026-11-26 14:32" },
    { id: "d-002", name: "数据合规实践指引.md", format: "MD", size: "86 KB", status: "ready", chunks: 82, createdAt: "2026-11-26 11:08" },
    { id: "d-003", name: "供应链风险评估.pdf", format: "PDF", size: "5.8 MB", status: "ready", chunks: 164, createdAt: "2026-11-25 16:45" },
    { id: "d-004", name: "产品技术白皮书.txt", format: "TXT", size: "128 KB", status: "ready", chunks: 47, createdAt: "2026-11-24 09:21" },
    { id: "d-005", name: "年度财务附录.pdf", format: "PDF", size: "12.6 MB", status: "parsing", chunks: null, createdAt: "2026-11-27 10:12" },
    { id: "d-006", name: "用户访谈纪要.md", format: "MD", size: "64 KB", status: "embedding", chunks: null, createdAt: "2026-11-27 10:09" },
    { id: "d-007", name: "扫描版合同.pdf", format: "PDF", size: "1.1 MB", status: "failed", chunks: null, createdAt: "2026-11-23 18:02", error: "未能提取到可检索的文本：文件疑似扫描件或已损坏，请提供可复制文本的版本。" },
    { id: "d-008", name: "竞品研究草稿.txt", format: "TXT", size: "32 KB", status: "uploaded", chunks: null, createdAt: "2026-11-27 10:14" },
  ];

  var CITATIONS = {
    c1: { id: "c1", documentId: "d-001", documentName: "2026_ai_industry_report.pdf", page: "第 5 页", section: "3.2 行业风险", snippet: "本项目可能面临数据合规风险、供应链中断风险以及模型迭代带来的不确定性，需建立持续监控机制。" },
    c2: { id: "c2", documentId: "d-003", documentName: "供应链风险评估.pdf", page: "第 7 页", section: "4.1 中断情景", snippet: "若关键供应商交付延迟超过 30 天，将直接影响下游产品交付节奏，建议分散采购来源。" },
    c3: { id: "c3", documentId: "d-002", documentName: "数据合规实践指引.md", page: "第 3 页", section: "2.4 处理原则", snippet: "对个人信息的处理应遵循最小必要原则，明确保留期限与访问范围。" },
  };

  var ROUNDS = {
    risk: [
      { id: "r-1", title: "第 1 轮 · 生成查询", query: "文档中提到的主要风险因素有哪些", hits: 10, newHits: 10, topScore: 0.82, decision: "continue", reason: "缺少风险等级与触发条件的说明", state: "done" },
      { id: "r-2", title: "第 2 轮 · 追加检索", query: "风险等级 高 中 低 触发条件", hits: 14, newHits: 9, topScore: 0.77, decision: "continue", reason: "已有风险描述，但缺少跨文档交叉验证", state: "done" },
      { id: "r-3", title: "第 3 轮 · 交叉验证", query: "数据合规 供应链中断 风险 证据", hits: 8, newHits: 5, topScore: 0.86, decision: "stop", reason: "证据已覆盖主要风险类别与依据", state: "done" },
    ],
    compliance: [
      { id: "r-1", title: "第 1 轮 · 生成查询", query: "个人信息处理 最小必要原则", hits: 6, newHits: 6, topScore: 0.74, decision: "continue", reason: "命中片段集中在原则性描述", state: "done" },
      { id: "r-2", title: "第 2 轮 · 追加检索", query: "保留期限 访问范围 合规检查清单", hits: 4, newHits: 2, topScore: 0.61, decision: "stop", reason: "证据不足，未找到具体的执行记录", state: "done" },
    ],
    supply: [
      { id: "r-1", title: "第 1 轮 · 生成查询", query: "供应链中断 交付延迟 替代方案", hits: 12, newHits: 12, topScore: 0.79, decision: "continue", reason: "缺少量化影响数据", state: "done" },
      { id: "r-2", title: "第 2 轮 · 追加检索", query: "关键供应商 交付周期 备份供应商", hits: 7, newHits: 4, topScore: 0.72, decision: "stop", reason: "达到最大轮次，结论可能不完整", state: "done" },
    ],
  };

  var SESSIONS = [
    { id: "s-001", title: "AI 行业报告研读", summary: "主要风险有哪些？", documentIds: ["d-001", "d-002"], messageCount: 2, createdAt: "11-26 14:32" },
    { id: "s-002", title: "数据合规问题清单", summary: "个人信息处理原则是什么？", documentIds: ["d-002"], messageCount: 2, createdAt: "11-26 11:10" },
    { id: "s-003", title: "供应链风险对比", summary: "关键供应商的交付风险？", documentIds: ["d-003", "d-004"], messageCount: 2, createdAt: "11-25 16:48" },
  ];

  var MESSAGES = {
    "s-001": [
      { id: "m-001", role: "user", content: "这份报告提到的主要风险有哪些？", createdAt: "14:32" },
      {
        id: "m-002",
        role: "assistant",
        createdAt: "14:33",
        answer: {
          text: "根据材料，主要风险集中在三类：\n1. 数据合规风险：个人信息处理需遵循最小必要原则，并明确保留期限与访问范围。\n2. 供应链中断风险：关键供应商交付延迟超过 30 天会影响下游交付。\n3. 模型迭代风险：技术路线变化可能带来持续适配成本。\n建议建立季度复核机制，对高风险项设置责任人。",
          confidence: "medium",
          stopReason: "sufficient",
          rounds: ROUNDS.risk,
          citations: [CITATIONS.c1, CITATIONS.c2, CITATIONS.c3],
        },
      },
    ],
    "s-002": [
      { id: "m-003", role: "user", content: "个人信息处理原则是什么？", createdAt: "11:10" },
      {
        id: "m-004",
        role: "assistant",
        createdAt: "11:11",
        answer: {
          text: "文档中明确提到个人信息处理应遵循最小必要原则，并限定保留期限与访问范围。但未提供具体的执行记录或检查清单，因此无法判断落地程度。",
          confidence: "insufficient",
          stopReason: "insufficient",
          rounds: ROUNDS.compliance,
          citations: [CITATIONS.c3],
        },
      },
    ],
    "s-003": [
      { id: "m-005", role: "user", content: "关键供应商的交付风险有哪些？", createdAt: "16:48" },
      {
        id: "m-006",
        role: "assistant",
        createdAt: "16:50",
        answer: {
          text: "当前证据指向交付延迟风险：关键供应商若延迟超过 30 天，将影响产品交付节奏。建议分散采购来源，并为核心物料设置备份供应商。已达最大调研轮次，结论可能不完整。",
          confidence: "low",
          stopReason: "max_iterations",
          rounds: ROUNDS.supply,
          citations: [CITATIONS.c2],
        },
      },
    ],
  };

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  AP.data = {
    STATUS_META: STATUS_META,
    STATUS_FLOW: STATUS_FLOW,
    CITATIONS: CITATIONS,
    ROUNDS: ROUNDS,

    createInitialState: function () {
      return {
        scenario: "normal",
        documents: clone(DOCUMENTS),
        sessions: clone(SESSIONS),
        messages: clone(MESSAGES),
        processing: [],
        currentSessionId: "s-001",
        selectedDocIds: [],
        docFilter: "all",
        docQuery: "",
        docPage: 1,
        ui: {
          sidebarOpen: false,
          railOpen: false,
          expandedFailure: {},
          openCitations: {},
          mobileNavOpen: false,
        },
      };
    },

    scenarios: [
      { id: "normal", label: "标准演示" },
      { id: "empty-docs", label: "空文档库" },
      { id: "upload-failed", label: "上传失败" },
      { id: "insufficient", label: "证据不足" },
      { id: "stopped", label: "调研已停止" },
    ],

    applyScenario: function (state, scenarioId) {
      state.scenario = scenarioId;
      if (scenarioId === "empty-docs") {
        state.documents = [];
        state.processing = [];
        state.selectedDocIds = [];
      }
      if (scenarioId === "upload-failed") {
        state.documents.unshift({
          id: "d-fail",
          name: "加密的合同扫描件.pdf",
          format: "PDF",
          size: "3.2 MB",
          status: "failed",
          chunks: null,
          createdAt: "2026-11-27 10:20",
          error: "文件已加密或为纯扫描图片，无法提取可检索文本。",
        });
      }
      if (scenarioId === "insufficient") {
        state.currentSessionId = "s-002";
      }
      if (scenarioId === "stopped") {
        state.currentSessionId = "s-003";
      }
      return state;
    },
  };
})();
