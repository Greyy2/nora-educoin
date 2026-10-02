import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSession } from "../context/SessionContext.jsx";

// Entry screen: two tabs, Admin and User. For now both open with one click
// and no credential (project owner, 2026-09-26). The admin key form is only
// shown when the server has open access switched off.
export default function AdminLoginPage() {
  const { login, adminOpenAccess } = useSession();
  const navigate = useNavigate();

  const [tab, setTab] = useState("admin");
  const [adminKey, setAdminKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function enterAdmin(key) {
    setBusy(true);
    setError(null);
    const result = await login(key);
    setBusy(false);
    if (result.ok && result.session?.role === "admin") {
      navigate("/admin", { replace: true });
    } else {
      setError(result.message || "This key does not have admin access.");
    }
  }

  function enterUser() {
    navigate("/user");
  }

  return (
    <div className="admin-login-page">
      <div className="admin-login-bg-glow" />

      <div className="admin-login-card">
        <div className="admin-login-header">
          <div className="admin-login-brand-row">
            <div className="admin-login-logo-box">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect x="3" y="3" width="7" height="7" rx="1.5" fill="currentColor" fillOpacity="0.95" />
                <rect x="14" y="3" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.8" />
                <rect x="3" y="14" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.8" />
                <rect x="14" y="14" width="7" height="7" rx="1.5" fill="#38BDF8" />
              </svg>
            </div>
            <div className="admin-login-brand-text">
              <span className="admin-login-brand-name">NORABT</span>
              <span className="admin-login-brand-tag">AI ENGINE</span>
            </div>
          </div>
          <h1 className="admin-login-title">Welcome</h1>
          <p className="admin-login-desc">Risk assessment for OKX copy-trading bots. Choose how you want to enter.</p>
        </div>

        <div className="login-tabs" role="tablist">
          <button type="button" role="tab" aria-selected={tab === "admin"}
            className={`login-tab${tab === "admin" ? " on" : ""}`} onClick={() => setTab("admin")}>
            Admin
          </button>
          <button type="button" role="tab" aria-selected={tab === "user"}
            className={`login-tab${tab === "user" ? " on" : ""}`} onClick={() => setTab("user")}>
            User
          </button>
        </div>

        {error && (
          <div className="admin-login-error" role="alert">
            <span className="admin-login-error-text">{error}</span>
          </div>
        )}

        {tab === "admin" ? (
          <div className="login-pane">
            <ul className="login-points">
              <li>Overview of every scored bot and portfolio</li>
              <li>Full reports: summary, markets, trades &amp; positions</li>
              <li>Assess any bot or portfolio</li>
            </ul>
            {adminOpenAccess ? (
              <button type="button" className="admin-login-staff-btn" onClick={() => enterAdmin("admin")} disabled={busy}>
                <span className="admin-login-staff-title">{busy ? "Opening…" : "Enter as Admin →"}</span>
                <span className="admin-login-staff-sub">OKX staff: one click, no key needed</span>
              </button>
            ) : (
              <form className="admin-login-form" onSubmit={(e) => { e.preventDefault(); if (adminKey.trim()) enterAdmin(adminKey.trim()); }}>
                <div className="admin-login-field">
                  <label htmlFor="adminKey">Admin key</label>
                  <div className="admin-login-input-wrap">
                    <input id="adminKey" type="password" value={adminKey} onChange={(e) => setAdminKey(e.target.value)}
                      placeholder="Enter the admin key" disabled={busy} autoComplete="current-password" />
                  </div>
                </div>
                <button type="submit" className="admin-login-submit-btn" disabled={busy || !adminKey.trim()}>
                  {busy ? "Signing in…" : "Log in to Admin Console →"}
                </button>
              </form>
            )}
          </div>
        ) : (
          <div className="login-pane">
            <ul className="login-points">
              <li>Check one bot, or a portfolio of 2–8 bots, by bot code</li>
              <li>Risk verdict, Monte Carlo and full report</li>
              <li>Only your own checks, no overview of other bots</li>
            </ul>
            <button type="button" className="admin-login-staff-btn login-user-btn" onClick={enterUser}>
              <span className="admin-login-staff-title">Enter as User →</span>
              <span className="admin-login-staff-sub">No sign-in needed</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
