import React from "react";
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useSearchParams,
} from "react-router-dom";
import { SessionProvider, useSession } from "./context/SessionContext.jsx";
import AdminLoginPage from "./pages/AdminLoginPage.jsx";
import UserHome from "./pages/UserHome.jsx";
import AdminHome from "./pages/AdminHome.jsx";
import ThemeToggle from "./components/ThemeToggle.jsx";

function RequireAdmin({ children }) {
  const [searchParams] = useSearchParams();
  const { session } = useSession();
  const botCode =
    searchParams.get("code") ||
    searchParams.get("bot_code") ||
    searchParams.get("id_bot") ||
    searchParams.get("botId");

  if (!session || session.role !== "admin") {
    // If visitor was given an old/direct link like /#/admin?tab=bot&code=...&contract=...
    // seamlessly render UserHome view without blocking them with a login screen:
    if (botCode) {
      return <UserHome />;
    }
    return <Navigate to="/login" replace />;
  }

  return children;
}

// `/#/okx`: the link handed to the OKX review team. On an open-access
// deployment it signs in exactly like the "OKX staff: click here" button and
// lands on the console; otherwise it falls back to the normal login screen.
function OkxStaffEntry() {
  const { session, login, adminOpenAccess } = useSession();
  const navigate = useNavigate();
  const [failed, setFailed] = React.useState(false);
  React.useEffect(() => {
    if (session && session.role === "admin") {
      navigate("/admin", { replace: true });
      return;
    }
    if (!adminOpenAccess) {
      setFailed(true);
      return;
    }
    login("admin").then((r) => {
      if (r.ok && r.session?.role === "admin") navigate("/admin", { replace: true });
      else setFailed(true);
    });
  }, [session, adminOpenAccess]);
  if (failed) return <Navigate to="/login" replace />;
  return <div className="msg" style={{ marginTop: 60 }}>Opening the console…</div>;
}

function RootRoute() {
  const [searchParams] = useSearchParams();
  const { session } = useSession();
  const botCode =
    searchParams.get("code") ||
    searchParams.get("bot_code") ||
    searchParams.get("id_bot") ||
    searchParams.get("botId");

  if (botCode) {
    return <UserHome />;
  }

  // A brand-new visitor with no bot code and no admin session used to land
  // here, on `/login` -- an admin-only screen with no link back to the
  // free "look up & analyze your own bot" tool. `/user` (UserHome) needs
  // no login at all, so that is the correct default landing spot, not a
  // dead end that only an admin can pass through.
  //
  // 2026-09-26 (project owner): the site opens on the entry screen, which
  // offers an Admin tab and a User tab; a bot-code link still opens its
  // report directly (above).
  return <Navigate to="/login" replace />;
}

function AppHeader() {
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const currentTab = searchParams.get("tab") || "overview";
  const { session, logout } = useSession();
  const navigate = useNavigate();

  const isLoginPage = location.pathname === "/login";
  const isAdmin = session && session.role === "admin";

  const botCode =
    searchParams.get("code") ||
    searchParams.get("bot_code") ||
    searchParams.get("id_bot") ||
    searchParams.get("botId");

  // User view is active when not authenticated as admin, or explicit user paths:
  const isUserView =
    !isAdmin &&
    (location.pathname === "/user" ||
      location.pathname === "/bot" ||
      location.pathname === "/view" ||
      !!botCode ||
      searchParams.has("contract") ||
      searchParams.has("contract_id"));

  // Contract ID display resolution:
  const rawContract =
    searchParams.get("contract") ||
    searchParams.get("contract_id") ||
    searchParams.get("id") ||
    searchParams.get("user_ref");

  const contractDisplay = rawContract
    ? rawContract
    : botCode
    ? botCode.length > 8
      ? botCode.slice(-6).toUpperCase()
      : botCode
    : "CLIENT";

  React.useEffect(() => {
    if (isLoginPage) {
      document.title = "Nora - Sign in";
    } else if (botCode) {
      document.title = `Nora - Risk Management · ${botCode}`;
    } else if (isAdmin) {
      if (currentTab === "overview") {
        document.title = "Nora - Risk Management · Overview";
      } else if (currentTab === "bots" || currentTab === "portfolio") {
        document.title = currentTab === "portfolio" ? "Nora - Portfolio Correlation" : "Nora - Bot List";
      } else if (currentTab === "analyze") {
        document.title = "Nora - Analyze Bot";
      } else {
        document.title = "Nora - Risk Management · Admin";
      }
    } else {
      document.title = "Nora - Risk Management";
    }
  }, [isLoginPage, botCode, isAdmin, currentTab]);

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  function handleTabClick(tabKey) {
    setSearchParams({ tab: tabKey });
  }

  return (
    <header className="top-header">
      <div className="header-left">
        {/* Brand & Monogram Logo */}
        <div
          className="brand"
          onClick={isAdmin ? () => handleTabClick("overview") : undefined}
          style={{ cursor: isAdmin ? "pointer" : "default" }}
          title={isAdmin ? "Back to Admin Overview" : "Nora Risk Engine"}
        >
          <div className="brand-logo-box">
            {/* OKX-inspired geometric matrix glyph */}
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <rect x="3" y="3" width="7" height="7" rx="1.5" fill="currentColor" fillOpacity="0.95" />
              <rect x="14" y="3" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.8" />
              <rect x="3" y="14" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.8" />
              <rect x="14" y="14" width="7" height="7" rx="1.5" fill="#38BDF8" />
            </svg>
          </div>
          <div className="brand-title-wrap">
            <div className="brand-name-row">
              <span className="brand-name">NORABT</span>
              <span className="brand-badge-fintech">
                AI Engine
              </span>
            </div>
            <span className="brand-sub">OKX quant risk protocol</span>
          </div>
        </div>

        {/* OKX-style Segmented Control Navigation Tabs - ONLY SHOWN FOR AUTHENTICATED ADMIN */}
        {isAdmin && !isLoginPage && (
          <>
            <div className="header-divider" />
            <nav className="header-nav-tabs">
              <button
                type="button"
                className={`header-tab ${currentTab === "overview" ? "on" : ""}`}
                onClick={() => handleTabClick("overview")}
              >
                <svg className="tab-svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="3" width="7" height="7" rx="1" />
                  <rect x="14" y="3" width="7" height="7" rx="1" />
                  <rect x="14" y="14" width="7" height="7" rx="1" />
                  <rect x="3" y="14" width="7" height="7" rx="1" />
                </svg>
                <span>Overview</span>
              </button>

              <button
                type="button"
                className={`header-tab ${currentTab === "bots" || currentTab === "bot" || currentTab === "portfolio" ? "on" : ""}`}
                onClick={() => handleTabClick("bots")}
              >
                <svg className="tab-svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="8" y1="6" x2="21" y2="6" />
                  <line x1="8" y1="12" x2="21" y2="12" />
                  <line x1="8" y1="18" x2="21" y2="18" />
                  <line x1="3" y1="6" x2="3.01" y2="6" />
                  <line x1="3" y1="12" x2="3.01" y2="12" />
                  <line x1="3" y1="18" x2="3.01" y2="18" />
                </svg>
                <span>Bot List</span>
              </button>

              <button
                type="button"
                className={`header-tab ${currentTab === "analyze" ? "on" : ""}`}
                onClick={() => handleTabClick("analyze")}
              >
                <svg className="tab-svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="11" cy="11" r="8" />
                  <line x1="21" y1="21" x2="16.65" y2="16.65" />
                </svg>
                <span>Analyze Bot</span>
              </button>
            </nav>
          </>
        )}
      </div>

      {/* Header Right Actions */}
      <div className="header-actions">
        {isLoginPage ? (
          <div className="user-badge-capsule">
            <span className="user-badge-pulse" style={{ background: "#38BDF8", boxShadow: "0 0 8px #38BDF8" }} />
            <span className="user-badge-label">SIGN IN</span>
          </div>
        ) : isUserView ? (
          <div className="user-badge-capsule user-badge-client">
            <span className="user-badge-pulse" />
            <span className="user-badge-label">
              USER · #{contractDisplay}
            </span>
          </div>
        ) : isAdmin ? (
          <div className="user-badge-capsule user-badge-admin">
            <span className="user-badge-pulse" />
            <span className="user-badge-label">Admin</span>
          </div>
        ) : null}

        <ThemeToggle />

        {(isAdmin || isUserView) && !isLoginPage && (
          <button
            type="button"
            className="btn-logout"
            onClick={handleLogout}
            title={isAdmin ? "Log out of the Admin role" : "Log out and return to the entry screen"}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <polyline points="16 17 21 12 16 7" />
              <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
            <span className="btn-logout-text">Log out</span>
          </button>
        )}
      </div>
    </header>
  );
}

function AppRoutes() {
  const { configLoaded } = useSession();

  if (!configLoaded) {
    return (
      <div className="msg" style={{ marginTop: 60 }}>
        Initializing system...
      </div>
    );
  }

  return (
    <Routes>
      <Route path="/login" element={<AdminLoginPage />} />
      <Route path="/okx" element={<OkxStaffEntry />} />
      <Route
        path="/admin"
        element={
          <RequireAdmin>
            <AdminHome />
          </RequireAdmin>
        }
      />
      <Route path="/user" element={<UserHome />} />
      <Route path="/bot" element={<UserHome />} />
      <Route path="/view" element={<UserHome />} />
      <Route path="/" element={<RootRoute />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <SessionProvider>
      <div className="app-shell">
        <AppHeader />
        <main className="main-content">
          <AppRoutes />
        </main>
      </div>
    </SessionProvider>
  );
}
