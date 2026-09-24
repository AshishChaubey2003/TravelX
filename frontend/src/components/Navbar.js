import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import AuthModal from "./AuthModal";
import Logo from "./Logo";

export default function Navbar() {
  const { token, doLogout } = useAuth();
  const [showAuth, setShowAuth] = useState(false);
  const [authTab, setAuthTab] = useState("login");

  const openAuth = (tab) => {
    setAuthTab(tab);
    setShowAuth(true);
  };

  const linkStyle = {
    color: "#94A8C0",
    textDecoration: "none",
    fontSize: "0.95rem",
    fontWeight: 500,
    transition: "color 0.2s",
  };

  return (
    <>
      <nav
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          right: 0,
          zIndex: 1000,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "1rem 2.5rem",
          background: "rgba(10,22,40,0.72)",
          backdropFilter: "blur(16px)",
          borderBottom: "1px solid rgba(255,255,255,0.1)",
        }}
      >
        {/* Logo */}
        <Logo />

        {/* Links */}
        <div style={{ display: "flex", gap: "2rem", alignItems: "center" }}>
          <Link to="/" style={linkStyle}>
            Home
          </Link>
          <Link to="/explore" style={linkStyle}>
            Explore
          </Link>
          {token && (
            <Link
              to="/my-bookings"
              style={{ ...linkStyle, color: "#F1F6FB", fontWeight: 600 }}
            >
              My Bookings
            </Link>
          )}
        </div>

        {/* Auth buttons */}
        <div style={{ display: "flex", gap: "0.75rem" }}>
          {token ? (
            <button
              onClick={doLogout}
              style={{
                padding: "0.55rem 1.3rem",
                borderRadius: "50px",
                background: "transparent",
                border: "1px solid rgba(255,255,255,0.15)",
                color: "#F1F6FB",
                cursor: "pointer",
                fontSize: "0.875rem",
                fontWeight: 600,
              }}
            >
              Logout
            </button>
          ) : (
            <>
              <button
                onClick={() => openAuth("login")}
                style={{
                  padding: "0.55rem 1.3rem",
                  borderRadius: "50px",
                  background: "transparent",
                  border: "1px solid rgba(255,255,255,0.15)",
                  color: "#F1F6FB",
                  cursor: "pointer",
                  fontSize: "0.875rem",
                  fontWeight: 600,
                }}
              >
                Login
              </button>
              <button
                onClick={() => openAuth("register")}
                style={{
                  padding: "0.55rem 1.4rem",
                  borderRadius: "50px",
                  background: "#2DD4BF",
                  border: "none",
                  color: "#0A1628",
                  cursor: "pointer",
                  fontSize: "0.875rem",
                  fontWeight: 700,
                }}
              >
                Sign Up
              </button>
            </>
          )}
        </div>
      </nav>
      {showAuth && (
        <AuthModal tab={authTab} onClose={() => setShowAuth(false)} />
      )}
    </>
  );
}
