// Lightweight SPA router: intercepts same-origin nav clicks and form submits
// inside #view-root, fetches just the inner content ("partial" render) via
// X-Requested-With, swaps it in, and manages history — no full page reloads.
(function () {
  var viewRoot = document.getElementById("view-root");
  var sidebar = document.getElementById("sidebar");
  if (!viewRoot) { return; }

  var cleanupFns = [];
  window.__spaRegisterCleanup = function (fn) {
    if (typeof fn === "function") { cleanupFns.push(fn); }
  };

  function runCleanup() {
    cleanupFns.forEach(function (fn) {
      try { fn(); } catch (e) { /* ignore */ }
    });
    cleanupFns = [];
  }

  function isSameOrigin(url) {
    try {
      return new URL(url, window.location.href).origin === window.location.origin;
    } catch (e) {
      return false;
    }
  }

  function setActiveNav(pathname) {
    if (!sidebar) { return; }
    sidebar.querySelectorAll(".sidebar-nav a").forEach(function (a) {
      var linkPath = new URL(a.href, window.location.href).pathname;
      a.classList.toggle("active", linkPath === pathname);
    });
  }

  function reExecuteScripts(container) {
    container.querySelectorAll("script").forEach(function (old) {
      var fresh = document.createElement("script");
      Array.prototype.forEach.call(old.attributes, function (attr) {
        fresh.setAttribute(attr.name, attr.value);
      });
      fresh.text = old.textContent;
      old.replaceWith(fresh);
    });
  }

  function isFullDocumentHtml(html) {
    return /<html[\s>]|<body[\s>]|id=["']view-root["']|class=["']app-shell["']/.test(html);
  }

  function applyHtml(html, pushUrl, title) {
    runCleanup();
    viewRoot.innerHTML = html;
    reExecuteScripts(viewRoot);
    if (pushUrl) {
      history.pushState({ spa: true }, "", pushUrl);
    }
    if (title) {
      document.title = title + " · Detailing Ops";
    }
    setActiveNav(window.location.pathname);
    window.scrollTo(0, 0);
  }

  function navigate(url, opts) {
    opts = opts || {};
    var push = opts.push !== false;
    var titleHint = opts.title || "";

    return fetch(url, {
      method: opts.method || "GET",
      body: opts.body,
      headers: { "X-Requested-With": "fetch" },
      credentials: "same-origin",
    })
      .then(function (res) {
        if (res.status === 401 || res.status === 403) {
          window.location.href = "/login";
          return null;
        }
        if (!res.ok) {
          // Unexpected server error: fall back to a real navigation so the
          // user sees the full error page instead of a half-rendered SPA.
          window.location.href = url;
          return null;
        }
        var finalUrl = res.url || url;
        return res.text().then(function (html) {
          if (isFullDocumentHtml(html)) {
            window.location.href = finalUrl;
            return null;
          }
          return { html: html, finalUrl: finalUrl };
        });
      })
      .then(function (result) {
        if (!result) { return; }
        var finalPath = (function () {
          try { return new URL(result.finalUrl, window.location.href).pathname + new URL(result.finalUrl, window.location.href).search; }
          catch (e) { return url; }
        })();
        applyHtml(result.html, push ? finalPath : null, titleHint);
      })
      .catch(function () {
        window.location.href = url;
      });
  }
  window.__spaNavigate = navigate;

  document.addEventListener("click", function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) { return; }
    var link = e.target.closest("a");
    if (!link || !link.href) { return; }
    if (link.hasAttribute("data-no-spa") || link.target === "_blank") { return; }
    if (!isSameOrigin(link.href)) { return; }
    if (link.href.indexOf("#") !== -1 && link.href.split("#")[0] === window.location.href.split("#")[0]) { return; }

    e.preventDefault();
    navigate(link.href, { title: link.getAttribute("data-title") || "" });
  });

  document.addEventListener("submit", function (e) {
    if (e.defaultPrevented) { return; }
    var form = e.target;
    if (!(form instanceof HTMLFormElement)) { return; }
    if (form.hasAttribute("data-no-spa") || !viewRoot.contains(form)) { return; }
    var action = form.getAttribute("action") || window.location.pathname + window.location.search;
    if (!isSameOrigin(action)) { return; }

    e.preventDefault();
    var method = (form.getAttribute("method") || "GET").toUpperCase();
    // Include the clicked submit button's name/value (e.g. <button name="action"
    // value="...">), which FormData only captures when given the submitter.
    var formData = e.submitter ? new FormData(form, e.submitter) : new FormData(form);
    var titleHint = document.title.split(" · ")[0];

    if (method === "GET") {
      var params = new URLSearchParams(formData).toString();
      var url = action + (params ? (action.indexOf("?") === -1 ? "?" : "&") + params : "");
      navigate(url, { title: titleHint });
    } else {
      navigate(action, { method: method, body: formData, title: titleHint });
    }
  });

  window.addEventListener("popstate", function () {
    navigate(window.location.href, { push: false });
  });

  var toggle = document.getElementById("sidebar-toggle");
  if (toggle && sidebar) {
    toggle.addEventListener("click", function () {
      sidebar.classList.toggle("open");
    });
    sidebar.querySelectorAll("a").forEach(function (a) {
      a.addEventListener("click", function () { sidebar.classList.remove("open"); });
    });
  }

  setActiveNav(window.location.pathname);
})();
