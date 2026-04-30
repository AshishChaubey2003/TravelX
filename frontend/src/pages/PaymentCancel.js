import React from "react";
import { useNavigate } from "react-router-dom";

export default function PaymentCancel() {
  const navigate = useNavigate();

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
        <div style={{ fontSize: "5rem", marginBottom: "1rem" }}>😔</div>
        <h1
          style={{
            fontFamily: "Syne, sans-serif",
            fontSize: "2rem",
            fontWeight: 700,
            color: "#EF4444",
            marginBottom: "1rem",
          }}
        >
          Payment Cancelled
        </h1>
        <p style={{ color: "#94A3B8", fontSize: "1rem", marginBottom: "2rem" }}>
          Your booking was not completed. Please try again!
        </p>
        <button
          onClick={() => navigate("/")}
          style={{
            padding: "0.875rem 2rem",
            borderRadius: "12px",
            border: "none",
            background: "linear-gradient(135deg, #F97316, #EA580C)",
            color: "white",
            fontSize: "1rem",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          Back to Home →
        </button>
      </div>
    </div>
  );
}
