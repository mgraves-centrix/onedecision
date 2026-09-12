/* A model call takes tens of seconds. Without this the page is a dead wait and
   the app looks hung, which on a phone reads as broken.

   The form is posted with fetch rather than as a navigation. That is not for
   the sake of being a single-page app: a browser stops running timers on a
   document it is navigating away from, so a page that submitted normally can
   show a panel but can never update it. Keeping the document alive is what lets
   the panel report the run's real steps, polled from /progress.

   Progressive enhancement: without fetch, or if anything here throws, the form
   submits normally and the server answers exactly as it did before. */
(function () {
  "use strict";

  var POLL_MS = 600;
  var TICK_MS = 100;

  if (!window.fetch || !window.FormData || !window.URLSearchParams || !window.URL) return;

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }

  function overlay(title, note) {
    var scrim = el("div", "waiting");
    var panel = el("div", "waiting-panel");
    panel.setAttribute("role", "status");
    panel.setAttribute("aria-live", "polite");
    panel.appendChild(el("p", "waiting-title", title));
    var list = el("ol", "waiting-steps");
    // Seeded so the panel is never blank in the gap before the POST is served.
    var first = el("li", "running");
    first.appendChild(el("span", "waiting-step-text", "Starting"));
    first.appendChild(el("span", "waiting-step-at"));
    list.appendChild(first);
    panel.appendChild(list);
    panel.appendChild(el("p", "waiting-note", note));
    scrim.appendChild(panel);
    document.body.appendChild(scrim);
    return { scrim: scrim, panel: panel, list: list };
  }

  function render(list, steps, elapsed, settled) {
    while (list.childElementCount > steps.length) list.removeChild(list.lastChild);
    steps.forEach(function (step, i) {
      var item = list.children[i];
      if (!item) {
        item = el("li");
        item.appendChild(el("span", "waiting-step-text"));
        item.appendChild(el("span", "waiting-step-at"));
        list.appendChild(item);
      }
      var last = i === steps.length - 1;
      item.className = last && !settled ? "running" : "done";
      item.firstChild.textContent = step.text;
      item.lastChild.textContent = last
        ? elapsed.toFixed(0) + "s"
        : (steps[i + 1].at - step.at).toFixed(1) + "s";
    });
  }

  function go(next) {
    var url = new URL(next, window.location.href);
    if (url.pathname === window.location.pathname && url.search === window.location.search) {
      // Same document. Assigning a URL that differs only by its fragment does
      // not reload, and the page behind this panel is now out of date.
      if (url.hash) window.location.hash = url.hash;
      window.location.reload();
      return;
    }
    window.location.assign(url.href);
  }

  function finished(view, steps, elapsed) {
    render(view.list, steps, elapsed, true);
    var item = el("li", "done");
    item.appendChild(el("span", "waiting-step-text", "Done"));
    item.appendChild(el("span", "waiting-step-at"));
    view.list.appendChild(item);
  }

  function failed(view, message) {
    view.list.innerHTML = "";
    var item = el("li", "failed");
    item.appendChild(el("span", "waiting-step-text", message));
    item.appendChild(el("span", "waiting-step-at"));
    view.list.appendChild(item);
    var again = el("button", "btn ghost waiting-retry", "Reload the page");
    again.type = "button";
    again.addEventListener("click", function () { window.location.reload(); });
    view.panel.appendChild(again);
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-wait")) return;
    if (event.defaultPrevented) return;

    event.preventDefault();
    Array.prototype.forEach.call(
      document.querySelectorAll("form button[type=submit]"),
      function (b) { b.disabled = true; }
    );

    var view = overlay(
      form.getAttribute("data-wait-title") || "Working",
      form.getAttribute("data-wait-note") || ""
    );
    var key = form.getAttribute("data-wait");
    var settled = false;
    var started = Date.now();
    var steps = [];

    // The clock belongs to the client. Server elapsed arrives only with a poll
    // and stops when the run does, so on its own the panel looks stuck.
    var ticking = setInterval(function () {
      if (settled || !steps.length) return;
      render(view.list, steps, (Date.now() - started) / 1000, false);
    }, TICK_MS);

    function poll() {
      if (settled || !key) return;
      fetch("/progress/" + encodeURIComponent(key), { headers: { Accept: "application/json" } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (settled || !data || !data.steps || !data.steps.length) return;
          steps = data.steps;
          render(view.list, steps, (Date.now() - started) / 1000, false);
        })
        .catch(function () { /* the panel is cosmetic; a failed poll changes nothing */ })
        .then(function () { if (!settled) setTimeout(poll, POLL_MS); });
    }
    setTimeout(poll, POLL_MS);

    fetch(form.action, {
      method: "POST",
      body: new URLSearchParams(new FormData(form)),
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        // Asks for the destination instead of the page, so it is loaded once.
        "X-OneDecision-Wait": "1",
        Accept: "application/json",
      },
      credentials: "same-origin",
    })
      .then(function (response) {
        if (!response.ok) return Promise.reject(new Error(String(response.status)));
        return response.json();
      })
      .then(function (body) {
        settled = true;
        clearInterval(ticking);
        finished(view, steps, (Date.now() - started) / 1000);
        go(body.next);
      })
      .catch(function (err) {
        settled = true;
        clearInterval(ticking);
        failed(view, /^[45]\d\d$/.test(err && err.message)
          ? "That did not go through (" + err.message + ")."
          : "The connection dropped before the answer came back.");
      });
  });
})();
