import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import AuthModal from "./AuthModal";

export default function Navbar() {
  const { token, doLogout } = useAuth();
  const [showAuth, setShowAuth] = useState(false);
  const [authTab, setAuthTab] = useState("login");

  const openAuth = (tab) => {
    setAuthTab(tab);
    setShowAuth(true);
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
          padding: "1rem 2rem",
          background: "rgba(8,12,20,0.85)",
          backdropFilter: "blur(20px)",
          borderBottom: "1px solid rgba(255,255,255,0.07)",
        }}
      >
        <Link
          to="/"
          style={{
            fontFamily: "Syne, sans-serif",
            fontSize: "1.4rem",
            fontWeight: 800,
            background: "linear-gradient(135deg, #F97316, #F59E0B)",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            textDecoration: "none",
          }}
        >
          ✈ TravelX
        </Link>

        <div style={{ display: "flex", gap: "2rem" }}>
          <Link
            to="/"
            style={{
              color: "#94A3B8",
              textDecoration: "none",
              fontSize: "0.9rem",
            }}
          >
            Home
          </Link>
          <Link
            to="/explore"
            style={{
              color: "#94A3B8",
              textDecoration: "none",
              fontSize: "0.9rem",
            }}
          >
            Explore
          </Link>
          <a
            href="#ai"
            style={{
              color: "#94A3B8",
              textDecoration: "none",
              fontSize: "0.9rem",
            }}
          >
            AI Planner
          </a>
        </div>

        <div style={{ display: "flex", gap: "0.75rem" }}>
          {token ? (
            <button
              onClick={doLogout}
              style={{
                padding: "0.5rem 1.2rem",
                borderRadius: "8px",
                background: "transparent",
                border: "1px solid rgba(255,255,255,0.12)",
                color: "#94A3B8",
                cursor: "pointer",
                fontSize: "0.875rem",
              }}
            >
              Logout
            </button>
          ) : (
            <>
              <button
                onClick={() => openAuth("login")}
                style={{
                  padding: "0.5rem 1.2rem",
                  borderRadius: "8px",
                  background: "transparent",
                  border: "1px solid rgba(255,255,255,0.12)",
                  color: "#94A3B8",
                  cursor: "pointer",
                  fontSize: "0.875rem",
                }}
              >
                Login
              </button>
              <button
                onClick={() => openAuth("register")}
                style={{
                  padding: "0.5rem 1.2rem",
                  borderRadius: "8px",
                  background: "linear-gradient(135deg, #F97316, #EA580C)",
                  border: "none",
                  color: "white",
                  cursor: "pointer",
                  fontSize: "0.875rem",
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
