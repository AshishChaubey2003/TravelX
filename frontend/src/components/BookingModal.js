import React, { useState } from "react";
import toast from "react-hot-toast";
import { createBooking, createCheckout } from "../api";
import { useAuth } from "../context/AuthContext";

export default function BookingModal({ type, item, onClose }) {
  const { token } = useAuth();
  const today = new Date().toISOString().split("T")[0];
  const tomorrow = new Date(Date.now() + 86400000).toISOString().split("T")[0];

  const [form, setForm] = useState({
    check_in: today,
    check_out: tomorrow,
    nights: 1,
    spots: 1,
  });
  const [loading, setLoading] = useState(false);

  const getTotal = () => {
    if (type === "hotel") return item.price_per_night * form.nights;
    if (type === "adventure") return item.price_per_person * form.spots;
    if (type === "vehicle") return item.price_per_day * form.nights;
    return 0;
  };

  const handleBook = async () => {
    if (!token) {
      toast.error("Please login first!");
      return;
    }
    setLoading(true);
    try {
      const body = {
        check_in: form.check_in,
        check_out: form.check_out,
        nights: form.nights,
      };
      if (type === "hotel") body.hotel_id = item.id;
      if (type === "adventure") {
        body.adventure_id = item.id;
        body.spots = form.spots;
      }
      if (type === "vehicle") body.vehicle_id = item.id;

      const { data } = await createBooking(body);
      toast.success("Booking created! Redirecting to payment...");

      const { data: payData } = await createCheckout(data.id);
      if (payData.checkout_url) window.open(payData.checkout_url, "_blank");
      onClose();
    } catch (e) {
      toast.error(e.response?.data?.error || "Booking failed");
    }
    setLoading(false);
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

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 2000,
        background: "rgba(0,0,0,0.85)",
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
          maxWidth: "480px",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: "1.5rem",
          }}
        >
          <h2
            style={{
              fontFamily: "Syne, sans-serif",
              fontWeight: 700,
              fontSize: "1.25rem",
            }}
          >
            {type === "hotel" ? "🏨" : type === "adventure" ? "🧗" : "🚗"} Book{" "}
            {item.name}
          </h2>
          <button
            onClick={onClose}
            style={{
              background: "#111827",
              border: "1px solid rgba(255,255,255,0.12)",
              color: "#94A3B8",
              width: "32px",
              height: "32px",
              borderRadius: "8px",
              cursor: "pointer",
              fontSize: "1rem",
            }}
          >
            ✕
          </button>
        </div>

        {/* Summary */}
        <div
          style={{
            background: "#111827",
            border: "1px solid rgba(255,255,255,0.07)",
            borderRadius: "12px",
            padding: "1rem",
            marginBottom: "1.25rem",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontSize: "0.875rem",
              color: "#94A3B8",
              marginBottom: "0.5rem",
            }}
          >
            <span>{item.name}</span>
            <span>
              {type === "hotel" &&
                `₹${Number(item.price_per_night).toLocaleString()}/night`}
              {type === "adventure" &&
                `₹${Number(item.price_per_person).toLocaleString()}/person`}
              {type === "vehicle" &&
                `₹${Number(item.price_per_day).toLocaleString()}/day`}
            </span>
          </div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontSize: "1rem",
              fontWeight: 700,
              color: "#F97316",
              borderTop: "1px solid rgba(255,255,255,0.07)",
              paddingTop: "0.75rem",
              marginTop: "0.5rem",
            }}
          >
            <span>Total</span>
            <span>₹{Number(getTotal()).toLocaleString()}</span>
          </div>
        </div>

        {/* Form */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: "1rem",
            marginBottom: "1rem",
          }}
        >
          <div>
            <label style={labelStyle}>Check In</label>
            <input
              type="date"
              style={inputStyle}
              value={form.check_in}
              onChange={(e) => setForm({ ...form, check_in: e.target.value })}
            />
          </div>
          {type !== "adventure" ? (
            <div>
              <label style={labelStyle}>Check Out</label>
              <input
                type="date"
                style={inputStyle}
                value={form.check_out}
                onChange={(e) =>
                  setForm({ ...form, check_out: e.target.value })
                }
              />
            </div>
          ) : (
            <div>
              <label style={labelStyle}>Spots</label>
              <input
                type="number"
                min="1"
                style={inputStyle}
                value={form.spots}
                onChange={(e) => setForm({ ...form, spots: +e.target.value })}
              />
            </div>
          )}
        </div>

        {type !== "adventure" && (
          <div style={{ marginBottom: "1.25rem" }}>
            <label style={labelStyle}>
              {type === "vehicle" ? "Days" : "Nights"}
            </label>
            <input
              type="number"
              min="1"
              style={inputStyle}
              value={form.nights}
              onChange={(e) => setForm({ ...form, nights: +e.target.value })}
            />
          </div>
        )}

        <button
          onClick={handleBook}
          disabled={loading}
          style={{
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
          }}
        >
          {loading ? "Processing..." : "Confirm & Pay →"}
        </button>
      </div>
    </div>
  );
}
