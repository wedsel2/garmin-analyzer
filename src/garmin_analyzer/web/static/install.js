// Registers the service worker. A file of its own, as the content security
// policy refuses scripts written in a page.
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js");
}
