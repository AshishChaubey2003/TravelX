import React, { useState } from "react";
import toast from "react-hot-toast";
import { login, register } from "../api";
import { useAuth } from "../context/AuthContext";

export default function AuthModal({ tab, onClose }) {
  const [activeTab, setActiveTab] = useState(tab);
  const [form, setForm] = useState({});
  const { doLogin } = useAuth();

  const handleLogin = async () => {
    try {
      const { data } = await login({
        username: form.username,
        password: form.password,
      });
      doLogin(data.access);
      toast.success("Welcome back! 🎉");
      onClose();
    } catch {
      toast.error("Invalid credentials");
    }
  };

  const handleRegister = async () => {
    try {
      await register({
        username: form.username,
        email: form.email,
        password: form.password,
      });
      toast.success("Account created! Please login.");
      setActiveTab("login");
    } catch {
      toast.error("Registration failed");
    }
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 2000,
        background: "rgba(0,0,0,0.8)",
        backdropFilter: "blur(10px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "1rem",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#141E2E",
          border: "1px solid rgba(255,255,255,0.12)",
          borderRadius: "20px",
          padding: "2rem",
          width: "100%",
          maxWidth: "420px",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            marginBottom: "1.5rem",
          }}
        >
          <h2 style={{ fontFamily: "Syne, sans-serif", fontWeight: 700 }}>
            Welcome to TravelX
          </h2>
          <button
            onClick={onClose}
            style={{
              background: "none",
              border: "none",
              color: "#94A3B8",
              cursor: "pointer",
              fontSize: "1.2rem",
            }}
          >
            ✕
          </button>
        </div>

        <div
          style={{
            display: "flex",
            background: "#111827",
            borderRadius: "10px",
            padding: "4px",
            marginBottom: "1.5rem",
          }}
        >
          {["login", "register"].map((t) => (
            <button
              key={t}
              onClick={() => setActiveTab(t)}
              style={{
                flex: 1,
                padding: "0.6rem",
                borderRadius: "8px",
                border: "none",
                cursor: "pointer",
                background: activeTab === t ? "#F97316" : "transparent",
                color: activeTab === t ? "white" : "#94A3B8",
                fontWeight: 500,
                fontSize: "0.875rem",
                textTransform: "capitalize",
              }}
            >
              {t === "login" ? "Login" : "Sign Up"}
            </button>
          ))}
        </div>

        {activeTab === "login" ? (
          <>
            {["username", "password"].map((field) => (
              <div key={field} style={{ marginBottom: "1rem" }}>
                <label
                  style={{
                    display: "block",
                    fontSize: "0.8rem",
                    fontWeight: 600,
                    color: "#94A3B8",
                    marginBottom: "0.5rem",
                    textTransform: "uppercase",
                  }}
                >
                  {field}
                </label>
                <input
                  type={field === "password" ? "password" : "text"}
                  onChange={(e) =>
                    setForm({ ...form, [field]: e.target.value })
                  }
                  style={{
                    width: "100%",
                    background: "#111827",
                    border: "1px solid rgba(255,255,255,0.12)",
                    borderRadius: "10px",
                    padding: "0.75rem 1rem",
                    color: "#F1F5F9",
                    fontSize: "0.9rem",
                    outline: "none",
                  }}
                  placeholder={`Enter ${field}`}
                />
              </div>
            ))}
            <button
              onClick={handleLogin}
              style={{
                width: "100%",
                padding: "0.875rem",
                borderRadius: "12px",
                border: "none",
                background: "linear-gradient(135deg, #F97316, #EA580C)",
                color: "white",
                fontSize: "1rem",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              Login →
            </button>
          </>
        ) : (
          <>
            {["username", "email", "password"].map((field) => (
              <div key={field} style={{ marginBottom: "1rem" }}>
                <label
                  style={{
                    display: "block",
                    fontSize: "0.8rem",
                    fontWeight: 600,
                    color: "#94A3B8",
                    marginBottom: "0.5rem",
                    textTransform: "uppercase",
                  }}
                >
                  {field}
                </label>
                <input
                  type={
                    field === "password"
                      ? "password"
                      : field === "email"
                        ? "email"
                        : "text"
                  }
                  onChange={(e) =>
                    setForm({ ...form, [field]: e.target.value })
                  }
                  style={{
                    width: "100%",
                    background: "#111827",
                    border: "1px solid rgba(255,255,255,0.12)",
                    borderRadius: "10px",
                    padding: "0.75rem 1rem",
                    color: "#F1F5F9",
                    fontSize: "0.9rem",
                    outline: "none",
                  }}
                  placeholder={`Enter ${field}`}
                />
              </div>
            ))}
            <button
              onClick={handleRegister}
              style={{
                width: "100%",
                padding: "0.875rem",
                borderRadius: "12px",
                border: "none",
                background: "linear-gradient(135deg, #F97316, #EA580C)",
                color: "white",
                fontSize: "1rem",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              Create Account →
            </button>
          </>
        )}
      </div>
    </div>
  );
}
