import React, { useState } from "react";
import toast from "react-hot-toast";
import { login, register } from "../api";
import { useAuth } from "../context/AuthContext";
import API from "../api";
import Logo from "./Logo";

// FE-004/FE-006: Pull the most useful human-readable message out of an axios
// error. Handles DRF's three common error shapes without exposing stack
// traces, server internals, or raw exception text:
//   1. Network error (no response)     -> connectivity hint
//   2. 429 Too Many Requests           -> throttle wait message
//   3. Payload shape {detail: "..."}   -> DRF framework errors (auth, throttle)
//   4. Payload shape {error:  "..."}   -> this app's own view-level errors
//   5. Payload shape {field: ["..."]}  -> DRF serializer validation errors
// If none match, the caller's fallback string is used. Never returns a
// Python-looking traceback or an exception class name.
function friendlyError(e, fallback) {
  if (!e || !e.response) {
    return "Network error — check your connection and try again.";
  }
  const { status, data } = e.response;
  if (status === 429) {
    return (
      (data && typeof data.detail === "string" && data.detail) ||
      "Too many attempts. Please wait a moment and try again."
    );
  }
  if (data && typeof data === "object") {
    if (typeof data.error === "string" && data.error) return data.error;
    if (typeof data.detail === "string" && data.detail) return data.detail;
    // DRF serializer errors: pick the first field's first message and label
    // it, so the user can see which field needs fixing.
    const keys = Object.keys(data);
    for (const key of keys) {
      const val = data[key];
      let msg = null;
      if (Array.isArray(val) && val.length > 0 && typeof val[0] === "string") {
        msg = val[0];
      } else if (typeof val === "string") {
        msg = val;
      }
      if (msg) {
        if (key === "non_field_errors" || key === "detail" || key === "error") {
          return msg;
        }
        const label = key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, " ");
        return `${label}: ${msg}`;
      }
    }
  }
  return fallback;
}

export default function AuthModal({ tab, onClose }) {
  const [activeTab, setActiveTab] = useState(tab);
  const [form, setForm] = useState({});
  const [step, setStep] = useState("form");
  const [registeredEmail, setRegisteredEmail] = useState("");
  const [otp, setOtp] = useState("");
  const [loading, setLoading] = useState(false);
  const { doLogin } = useAuth();

  const handleLogin = async () => {
    setLoading(true);
    try {
      const { data } = await login({
        username: form.username,
        password: form.password,
      });
      doLogin(data.access);
      toast.success("Welcome back! 🎉");
      onClose();
    } catch (e) {
      // FE-004: distinguish bad credentials, throttling, and network error
      // instead of one generic message. simplejwt returns 401 with a detail
      // string, DRF throttles return 429, and axios signals a network error
      // by having no `.response`.
      if (!e.response) {
        toast.error("Network error — check your connection and try again.");
      } else if (e.response.status === 401) {
        toast.error("Invalid username or password.");
      } else if (e.response.status === 429) {
        toast.error(
          (e.response.data && e.response.data.detail) ||
            "Too many attempts. Please wait a moment and try again."
        );
      } else {
        toast.error(friendlyError(e, "Login failed. Please try again."));
      }
    }
    setLoading(false);
  };

  const handleRegister = async () => {
    setLoading(true);
    try {
      await register({
        username: form.username,
        email: form.email,
        password: form.password,
      });
      // FE-013: removed `console.log("Register response:", res.data)` so the
      // register response payload (which includes the created email and may
      // in future include tokens) never reaches the browser console.
      setRegisteredEmail(form.email);
      setStep("otp");
      toast.success("OTP sent to your email! 📧");
    } catch (e) {
      // FE-006/FE-013: show the actual DRF field error so the user can fix
      // their input, instead of a generic "Registration failed". Also do
      // not log the raw error payload to the console in production.
      toast.error(friendlyError(e, "Registration failed. Please try again."));
    }
    setLoading(false);
  };

  const handleVerifyOTP = async () => {
    setLoading(true);
    try {
      await API.post("/auth/verify-otp/", {
        email: registeredEmail,
        otp: otp,
      });
      toast.success("Email verified! Please login. ✅");
      setStep("form");
      setActiveTab("login");
      setForm({});
    } catch (e) {
      toast.error(friendlyError(e, "Invalid OTP."));
    }
    setLoading(false);
  };

  const handleResendOTP = async () => {
    try {
      await API.post("/auth/resend-otp/", {
        email: registeredEmail,
      });
      toast.success("New OTP sent! 📧");
    } catch (e) {
      toast.error(friendlyError(e, "Failed to resend OTP."));
    }
  };

  const inputStyle = {
    width: "100%",
    background: "#111827",
    border: "1px solid rgba(255,255,255,0.12)",
    borderRadius: "10px",
    padding: "0.75rem 1rem",
    color: "#F1F5F9",
    fontSize: "0.9rem",
    outline: "none",
  };

  const labelStyle = {
    display: "block",
    fontSize: "0.8rem",
    fontWeight: 600,
    color: "#94A3B8",
    marginBottom: "0.5rem",
    textTransform: "uppercase",
  };

  const btnStyle = {
    width: "100%",
    padding: "0.875rem",
    borderRadius: "12px",
    border: "none",
    background: loading ? "#374151" : "#2DD4BF",
    color: loading ? "white" : "#0A1628",
    fontSize: "1rem",
    fontWeight: 700,
    cursor: loading ? "not-allowed" : "pointer",
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
            alignItems: "flex-start",
            marginBottom: "1.5rem",
          }}
        >
          <div>
            <div style={{ marginBottom: "0.75rem", display: "inline-flex" }}>
              <Logo size={18} to={null} />
            </div>
            <h2
              style={{
                fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
                fontWeight: 700,
                fontSize: "1.3rem",
              }}
            >
              {step === "otp" ? "Verify Email 📧" : "Welcome back"}
            </h2>
          </div>
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

        {step === "otp" ? (
          <>
            <div
              style={{
                background: "rgba(45,212,191,0.06)",
                border: "1px solid rgba(45,212,191,0.25)",
                borderRadius: "12px",
                padding: "1rem",
                marginBottom: "1.5rem",
                textAlign: "center",
              }}
            >
              <div style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>📬</div>
              <p style={{ color: "#94A3B8", fontSize: "0.875rem" }}>
                OTP sent to{" "}
                <strong style={{ color: "#2DD4BF" }}>{registeredEmail}</strong>
              </p>
              <p
                style={{
                  color: "#64748B",
                  fontSize: "0.8rem",
                  marginTop: "0.25rem",
                }}
              >
                Valid for 10 minutes
              </p>
            </div>

            <div style={{ marginBottom: "1rem" }}>
              <label style={labelStyle}>Enter OTP</label>
              <input
                type="text"
                maxLength={6}
                value={otp}
                onChange={(e) => setOtp(e.target.value)}
                placeholder="Enter 6-digit OTP"
                style={{
                  ...inputStyle,
                  textAlign: "center",
                  fontSize: "1.5rem",
                  letterSpacing: "0.5rem",
                }}
              />
            </div>

            <button
              onClick={handleVerifyOTP}
              disabled={loading}
              style={btnStyle}
            >
              {loading ? "Verifying..." : "Verify OTP ✅"}
            </button>

            <button
              onClick={handleResendOTP}
              style={{
                width: "100%",
                marginTop: "0.75rem",
                padding: "0.75rem",
                borderRadius: "12px",
                border: "1px solid rgba(255,255,255,0.1)",
                background: "transparent",
                color: "#94A3B8",
                cursor: "pointer",
                fontSize: "0.875rem",
              }}
            >
              Resend OTP 🔄
            </button>
          </>
        ) : (
          <>
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
                  onClick={() => {
                    // FE-005: reset form state when switching tabs so a
                    // password typed under one tab is not carried over.
                    setActiveTab(t);
                    setForm({});
                  }}
                  style={{
                    flex: 1,
                    padding: "0.6rem",
                    borderRadius: "8px",
                    border: "none",
                    cursor: "pointer",
                    background: activeTab === t ? "#2DD4BF" : "transparent",
                    color: activeTab === t ? "#0A1628" : "#94A3B8",
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
                    <label style={labelStyle}>{field}</label>
                    <input
                      type={field === "password" ? "password" : "text"}
                      onChange={(e) =>
                        setForm({ ...form, [field]: e.target.value })
                      }
                      style={inputStyle}
                      placeholder={`Enter ${field}`}
                    />
                  </div>
                ))}
                <button
                  onClick={handleLogin}
                  disabled={loading}
                  style={btnStyle}
                >
                  {loading ? "Logging in..." : "Login →"}
                </button>
              </>
            ) : (
              <>
                {["username", "email", "password"].map((field) => (
                  <div key={field} style={{ marginBottom: "1rem" }}>
                    <label style={labelStyle}>{field}</label>
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
                      style={inputStyle}
                      placeholder={`Enter ${field}`}
                    />
                  </div>
                ))}
                <button
                  onClick={handleRegister}
                  disabled={loading}
                  style={btnStyle}
                >
                  {loading ? "Creating..." : "Create Account →"}
                </button>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
