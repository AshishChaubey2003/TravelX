import React, { useState } from "react";
import toast from "react-hot-toast";
import { login, register } from "../api";
import { useAuth } from "../context/AuthContext";
import axios from "axios";

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
    } catch {
      toast.error("Invalid credentials");
    }
    setLoading(false);
  };

  const handleRegister = async () => {
    setLoading(true);
    try {
      const res = await register({
        username: form.username,
        email: form.email,
        password: form.password,
      });
      console.log("Register response:", res.data);
      setRegisteredEmail(form.email);
      setStep("otp");
      toast.success("OTP sent to your email! 📧");
    } catch (e) {
      console.log("Register error:", e.response?.data);
      toast.error(e.response?.data?.error || "Registration failed");
    }
    setLoading(false);
  };

  const handleVerifyOTP = async () => {
    setLoading(true);
    try {
      await axios.post("http://localhost:8000/api/v1/auth/verify-otp/", {
        email: registeredEmail,
        otp: otp,
      });
      toast.success("Email verified! Please login. ✅");
      setStep("form");
      setActiveTab("login");
      setForm({});
    } catch (e) {
      toast.error(e.response?.data?.error || "Invalid OTP!");
    }
    setLoading(false);
  };

  const handleResendOTP = async () => {
    try {
      await axios.post("http://localhost:8000/api/v1/auth/resend-otp/", {
        email: registeredEmail,
      });
      toast.success("New OTP sent! 📧");
    } catch {
      toast.error("Failed to resend OTP");
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
    background: loading
      ? "#374151"
      : "linear-gradient(135deg, #F97316, #EA580C)",
    color: "white",
    fontSize: "1rem",
    fontWeight: 600,
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
            marginBottom: "1.5rem",
          }}
        >
          <h2 style={{ fontFamily: "Syne, sans-serif", fontWeight: 700 }}>
            {step === "otp" ? "Verify Email 📧" : "Welcome to TravelX"}
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

        {step === "otp" ? (
          <>
            <div
              style={{
                background: "rgba(249,115,22,0.05)",
                border: "1px solid rgba(249,115,22,0.2)",
                borderRadius: "12px",
                padding: "1rem",
                marginBottom: "1.5rem",
                textAlign: "center",
              }}
            >
              <div style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>📬</div>
              <p style={{ color: "#94A3B8", fontSize: "0.875rem" }}>
                OTP sent to{" "}
                <strong style={{ color: "#F97316" }}>{registeredEmail}</strong>
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
