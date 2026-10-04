// Registers the service worker. A file of its own, as the content security
// policy refuses scripts written in a page.
if ("serviceWorker" in navigator) {
  // The site works the same without it, so a browser that refuses is left alone.
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
