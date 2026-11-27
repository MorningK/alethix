(function () {
  "use strict";
  var AP = window.AP || (window.AP = {});

  var paths = {
    logo: '<path d="M12 2.8 20 7v10l-8 4.2L4 17V7l8-4.2Z"/><path d="m9 15 3-7 3 7"/><path d="M10 13h4"/>',
    docs: '<path d="M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h4"/>',
    chat: '<path d="M20 15a3 3 0 0 1-3 3H8l-4 3v-4.5A3 3 0 0 1 3 14V7a3 3 0 0 1 3-3h11a3 3 0 0 1 3 3v8Z"/><path d="M8 10h8M8 13h5"/>',
    upload: '<path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
    file: '<path d="M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z"/><path d="M14 3v5h5"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    trash: '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/><path d="M10 11v5M14 11v5"/>',
    close: '<path d="m6 6 12 12M18 6 6 18"/>',
    chevronRight: '<path d="m9 6 6 6-6 6"/>',
    chevronDown: '<path d="m6 9 6 6 6-6"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    alert: '<path d="M12 3 2.8 20h18.4L12 3Z"/><path d="M12 9v5M12 17.5h.01"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5h.01"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/>',
    send: '<path d="m4 12 16-8-5 16-3.5-6L4 12Z"/><path d="m11.5 14 8.5-10"/>',
    filter: '<path d="M4 5h16M7 12h10M10 19h4"/>',
    sparkles: '<path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z"/><path d="m19 16 .8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8L19 16Z"/>',
    layers: '<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 13 9 5 9-5"/>',
    quote: '<path d="M8 11H5V8h5v5c0 4-2 6-5 6v-2c2 0 3-1 3-3V11Z"/><path d="M18 11h-3V8h5v5c0 4-2 6-5 6v-2c2 0 3-1 3-3v-3Z"/>',
    shield: '<path d="M12 3 5 6v5c0 5 3 8.5 7 10 4-1.5 7-5 7-10V6l-7-3Z"/><path d="m9 12 2 2 4-4"/>',
    arrowRight: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    retry: '<path d="M20 11a8 8 0 1 0-2.3 6"/><path d="M20 4v7h-7"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    panelRight: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>',
    panelLeft: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
    brain: '<path d="M9.5 4A3.5 3.5 0 0 0 6 7.5 3.5 3.5 0 0 0 4 11c0 1.2.6 2.3 1.6 3A3.5 3.5 0 0 0 8 20h1.5V4Z"/><path d="M14.5 4A3.5 3.5 0 0 1 18 7.5 3.5 3.5 0 0 1 20 11c0 1.2-.6 2.3-1.6 3A3.5 3.5 0 0 1 16 20h-1.5V4Z"/><path d="M10 8h4M10 12h4"/>',
    external: '<path d="M14 4h6v6"/><path d="m20 4-9 9"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>',
    circle: '<circle cx="12" cy="12" r="8"/>',
  };

  AP.icon = function (name, className) {
    var body = paths[name] || paths.circle;
    return (
      '<svg class="' +
      (className || "") +
      '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
      'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
      body +
      "</svg>"
    );
  };
})();
