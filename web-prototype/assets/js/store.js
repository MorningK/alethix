(function () {
  "use strict";
  var AP = window.AP || (window.AP = {});

  var THEME_KEY = "alethix.prototype.theme";
  var SCENARIO_KEY = "alethix.prototype.scenario";
  var THEMES = ["blue-gray", "dark-lab", "paper"];

  function read(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (e) {
      return null;
    }
  }

  function write(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (e) {}
  }

  var storedTheme = read(THEME_KEY);
  var theme = THEMES.indexOf(storedTheme) >= 0 ? storedTheme : "blue-gray";
  document.documentElement.setAttribute("data-theme", theme);

  var state = AP.data.createInitialState();
  var storedScenario = read(SCENARIO_KEY);
  var validScenario = AP.data.scenarios.some(function (s) {
    return s.id === storedScenario;
  });
  AP.data.applyScenario(state, validScenario ? storedScenario : "normal");

  var listeners = [];

  AP.store = {
    get state() {
      return state;
    },

    theme: theme,

    subscribe: function (fn) {
      if (typeof fn !== "function") return function () {};
      listeners.push(fn);
      return function () {
        listeners = listeners.filter(function (item) {
          return item !== fn;
        });
      };
    },

    emit: function () {
      listeners.slice().forEach(function (fn) {
        try {
          fn(state);
        } catch (err) {
          console.error("[prototype] listener error", err);
        }
      });
    },

    update: function (mutator) {
      if (typeof mutator === "function") mutator(state);
      this.emit();
    },

    set: function (patch) {
      Object.assign(state, patch);
      this.emit();
    },

    reset: function (scenarioId) {
      var next = AP.data.createInitialState();
      var valid = AP.data.scenarios.some(function (s) {
        return s.id === scenarioId;
      });
      AP.data.applyScenario(next, valid ? scenarioId : "normal");
      state = next;
      write(SCENARIO_KEY, valid ? scenarioId : "normal");
      this.emit();
    },

    setTheme: function (nextTheme) {
      if (THEMES.indexOf(nextTheme) < 0) return;
      theme = nextTheme;
      this.theme = nextTheme;
      document.documentElement.setAttribute("data-theme", nextTheme);
      write(THEME_KEY, nextTheme);
      this.emit();
    },

    setScenario: function (scenarioId) {
      this.reset(scenarioId);
    },
  };
})();
