"use client";

import { useState } from "react";
import { trackEvent } from "@/lib/firebase/analytics";
import { usePwa } from "./PwaProvider";

export function MobileAppSettings() {
  const { installState, isOnline, updateAvailable, install, applyUpdate } = usePwa();
  const [busy, setBusy] = useState(false);

  const installApp = async () => {
    setBusy(true);
    try {
      const accepted = await install();
      await trackEvent("pwa_install_prompt", {
        outcome: accepted ? "accepted" : "dismissed",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="auth-settings mobile-app-settings" aria-labelledby="mobile-app-heading">
      <div>
        <span className="eyebrow">Settings · Mobile app</span>
        <strong id="mobile-app-heading">GatePath on your phone</strong>
        <p>
          Install the same secure study space on your Home Screen. Your signed-in
          session and Firestore progress continue across devices.
        </p>
      </div>

      <div className="mobile-app-status" role="status">
        <span className={isOnline ? "online" : "offline"} aria-hidden="true" />
        <div>
          <strong>{isOnline ? "Connected" : "Offline"}</strong>
          <small>
            {isOnline
              ? "Live tests, scoring and sync are available."
              : "The app shell is available; reconnect for tests, scoring and sync."}
          </small>
        </div>
      </div>

      {updateAvailable ? (
        <button type="button" className="button primary full" onClick={applyUpdate}>
          Update GatePath
        </button>
      ) : installState === "available" ? (
        <button
          type="button"
          className="button primary full"
          disabled={busy}
          onClick={() => void installApp()}
        >
          {busy ? "Opening install…" : "Install GatePath"}
        </button>
      ) : installState === "ios" ? (
        <div className="mobile-install-help">
          <strong>Install on iPhone or iPad</strong>
          <span>Open the Share menu, then choose “Add to Home Screen”.</span>
        </div>
      ) : installState === "installed" ? (
        <div className="mobile-installed"><span>✓</span> Installed on this device</div>
      ) : (
        <p className="mobile-install-note">
          Use your browser’s “Install app” or “Add to Home Screen” menu when available.
        </p>
      )}
    </section>
  );
}
