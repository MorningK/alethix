(function () {
  "use strict";
  var AP = window.AP || (window.AP = {});

  var current = null;
  var timer = null;

  function reducedMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function pickRounds(question) {
    if (/合规|隐私|个人信息|数据/.test(question)) return AP.data.ROUNDS.compliance;
    if (/供应链|供应商|交付|采购/.test(question)) return AP.data.ROUNDS.supply;
    return AP.data.ROUNDS.risk;
  }

  function buildAnswer(question, documentNames) {
    var scope = documentNames.length ? documentNames.join("、") : "全部文档";
    var insufficient = /证据不足|没有依据|无法确认/.test(question);
    if (insufficient) {
      return {
        text: "在「" + scope + "」中没有找到足够的直接证据支撑这一结论。现有材料仅能说明原则性要求，缺少具体执行记录与量化数据，建议补充相关文档后再提问。",
        confidence: "insufficient",
        stopReason: "insufficient",
        rounds: pickRounds(question).slice(0, 2),
        citations: [AP.data.CITATIONS.c3],
      };
    }
    return {
      text: "基于「" + scope + "」的调研，可以得到以下结论：\n1. 数据合规是首要风险，应落实最小必要原则与访问范围控制。\n2. 供应链交付延迟会影响下游节奏，建议设置备份供应商。\n3. 技术路线迭代需要持续跟踪，并建立季度复核机制。\n以上结论来自多轮检索与交叉验证，可展开引用逐条核对。",
      confidence: "medium",
      stopReason: "sufficient",
      rounds: pickRounds(question),
      citations: [AP.data.CITATIONS.c1, AP.data.CITATIONS.c2, AP.data.CITATIONS.c3],
    };
  }

  function clearTimer() {
    if (timer !== null) {
      window.clearTimeout(timer);
      timer = null;
    }
  }

  AP.stream = {
    isRunning: function () {
      return current !== null;
    },

    start: function (options) {
      this.stop("superseded");
      clearTimer();

      var runId = "run-" + Date.now();
      var emit = options.onEvent || function () {};
      var delay = reducedMotion() ? 60 : 620;

      current = {
        runId: runId,
        options: options,
        rounds: pickRounds(options.question || ""),
        index: 0,
      };

      emit({ type: "start", runId: runId });

      var step = function () {
        if (!current || current.runId !== runId) return;
        var active = current;
        if (active.index < active.rounds.length) {
          var round = JSON.parse(JSON.stringify(active.rounds[active.index]));
          round.state = "active";
          emit({ type: "round-start", runId: runId, round: round });
          timer = window.setTimeout(function () {
            if (!current || current.runId !== runId) return;
            round.state = "done";
            emit({ type: "round-done", runId: runId, round: round });
            current.index += 1;
            timer = window.setTimeout(step, delay);
          }, Math.round(delay * 0.75));
          return;
        }

        var answer = buildAnswer(options.question || "", options.documentNames || []);
        emit({ type: "answer", runId: runId, answer: answer });
        emit({ type: "done", runId: runId, answer: answer });
        current = null;
      };

      timer = window.setTimeout(step, delay);
    },

    stop: function (reason) {
      clearTimer();
      if (!current) return;
      var active = current;
      current = null;
      if (active.options.onEvent) {
        active.options.onEvent({
          type: "stopped",
          runId: active.runId,
          reason: reason || "user_stopped",
        });
      }
    },
  };
})();
