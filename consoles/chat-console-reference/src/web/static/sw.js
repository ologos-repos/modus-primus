// chat console — service worker.
// Minimal: enables PWA install + Web Notifications API (iOS PWA path
// requires a registered SW for `registration.showNotification`). No
// caching strategy in Phase 1; offline support is a future enhancement.

self.addEventListener("install", () => {
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(self.clients.claim());
});

self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    event.waitUntil(
        self.clients
            .matchAll({ type: "window", includeUncontrolled: true })
            .then((cls) => {
                for (const c of cls) {
                    if ("focus" in c) return c.focus();
                }
                if (self.clients.openWindow) return self.clients.openWindow("/");
            }),
    );
});
