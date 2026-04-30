import React, { useEffect } from "react";
import { useNavigate } from "react-router-dom";

export default function PaymentSuccess() {
  const navigate = useNavigate();

  useEffect(() => {
    setTimeout(() => navigate("/my-bookings"), 5000);
  }, [navigate]);

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#080C14",
        flexDirection: "column",
      }}
    >
      <div style={{ textAlign: "center", padding: "2rem" }}>
        <div style={{ fontSize: "5rem", marginBottom: "1rem" }}>🎉</div>
        <h1
          style={{
            fontFamily: "Syne, sans-serif",
            fontSize: "2rem",
            fontWeight: 700,
            color: "#10B981",
            marginBottom: "1rem",
          }}
        >
          Payment Successful!
        </h1>
        <p style={{ color: "#94A3B8", fontSize: "1rem", marginBottom: "2rem" }}>
          Your booking is confirmed! Redirecting to My Bookings...
        </p>
        <div
          style={{
            width: "60px",
            height: "60px",
            border: "3px solid #10B981",
            borderTopColor: "transparent",
            borderRadius: "50%",
            animation: "spin 1s linear infinite",
            margin: "0 auto",
          }}
        />
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        <button
          onClick={() => navigate("/my-bookings")}
          style={{
            marginTop: "2rem",
            padding: "0.875rem 2rem",
            borderRadius: "12px",
            border: "none",
            background: "linear-gradient(135deg, #10B981, #059669)",
            color: "white",
            fontSize: "1rem",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          View My Bookings →
        </button>
      </div>
    </div>
  );
}
