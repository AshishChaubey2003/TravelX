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
        background: "#080D17",
        flexDirection: "column",
      }}
    >
      <div style={{ textAlign: "center", padding: "2rem" }}>
        <div style={{ fontSize: "5rem", marginBottom: "1rem" }}>😔</div>
        <h1
          style={{
            fontFamily: "'Plus Jakarta Sans', Syne, sans-serif",
            fontSize: "2rem",
            fontWeight: 800,
            color: "#EF4444",
            marginBottom: "1rem",
          }}
        >
          Payment Cancelled
        </h1>
        <p style={{ color: "#94A8C0", fontSize: "1rem", marginBottom: "2rem" }}>
          Your booking was not completed. Please try again!
        </p>
        <button
          onClick={() => navigate("/")}
          style={{
            padding: "0.875rem 2rem",
            borderRadius: "50px",
            border: "none",
            background: "#2DD4BF",
            color: "#0A1628",
            fontSize: "1rem",
            fontWeight: 700,
            cursor: "pointer",
          }}
        >
          Back to Home →
        </button>
      </div>
    </div>
  );
}
