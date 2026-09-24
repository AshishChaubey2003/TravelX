import React, { useState } from "react";
import AIChat from "./AIChat";

export default function AIWidget() {
  const [open, setOpen] = useState(false);

  return (
    <>
      {/* Popup panel */}
      {open && (
        <div
          style={{
            position: "fixed",
            bottom: "6.5rem",
            right: "1.5rem",
            width: "min(420px, calc(100vw - 3rem))",
            maxHeight: "70vh",
            zIndex: 1200,
            background: "#0F1E33",
            border: "1px solid rgba(45,212,191,0.3)",
            borderRadius: "20px",
            overflow: "hidden",
            boxShadow: "0 25px 60px rgba(0,0,0,0.55)",
            display: "flex",
            flexDirection: "column",
          }}
        >
          {/* Header */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "0.9rem 1.1rem",
              borderBottom: "1px solid rgba(255,255,255,0.08)",
              background: "rgba(45,212,191,0.06)",
            }}
          >
            <div
              style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}
            >
              <span
                style={{
                  width: "32px",
                  height: "32px",
                  borderRadius: "10px",
                  background: "rgba(45,212,191,0.15)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "1.1rem",
                }}
              >
                ✦
              </span>
              <div>
                <div style={{ fontWeight: 700, fontSize: "0.95rem" }}>
                  TravelX AI
                </div>
                <div style={{ fontSize: "0.72rem", color: "#2DD4BF" }}>
                  ● Online
                </div>
              </div>
            </div>
            <button
              onClick={() => setOpen(false)}
              aria-label="Close chat"
              style={{
                background: "transparent",
                border: "none",
                color: "#94A8C0",
                fontSize: "1.2rem",
                cursor: "pointer",
                lineHeight: 1,
              }}
            >
              ✕
            </button>
          </div>

          {/* Chat body */}
          <div style={{ flex: 1, overflow: "auto" }}>
            <AIChat />
          </div>
        </div>
      )}

      {/* Floating button */}
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label="Open AI trip planner"
        style={{
          position: "fixed",
          bottom: "1.5rem",
          right: "1.5rem",
          zIndex: 1200,
          width: "60px",
          height: "60px",
          borderRadius: "50%",
          border: "none",
          background: "#2DD4BF",
          color: "#0A1628",
          fontSize: "1.6rem",
          cursor: "pointer",
          boxShadow: "0 10px 30px rgba(45,212,191,0.4)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          transition: "transform 0.2s",
        }}
        onMouseEnter={(e) => (e.currentTarget.style.transform = "scale(1.08)")}
        onMouseLeave={(e) => (e.currentTarget.style.transform = "scale(1)")}
      >
        {open ? "✕" : "✦"}
      </button>
    </>
  );
}
