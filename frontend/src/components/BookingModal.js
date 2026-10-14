import React, { useRef, useState } from "react";
import toast from "react-hot-toast";
import API from "../api";
import { useAuth } from "../context/AuthContext";

// FE-009: generate a UUID per booking attempt the user starts. We keep the
// same key for every retry inside this modal lifecycle so a double-click,
// react-strict-mode re-run, or flaky network does NOT create duplicate
// bookings — the backend recognises the key and replays the original
// Booking with the `Idempotent-Replay: true` response header. A new modal
// instance gets a new key, which is correct: that's a genuinely new
// booking attempt the user made deliberately.
function _generateIdempotencyKey() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // Fallback for older browsers (no secure RNG — collision risk is extremely
  // low across one modal lifecycle, but we never want to fall through here
  // on a modern target).
  return (
    Math.random().toString(36).slice(2) +
    "-" +
    Date.now().toString(36) +
    "-" +
    Math.random().toString(36).slice(2)
  );
}

export default function BookingModal({ type, item, onClose }) {
  const { token } = useAuth();
  const today = new Date().toISOString().split("T")[0];
  const tomorrow = new Date(Date.now() + 86400000).toISOString().split("T")[0];
  // Stable for the whole lifetime of this modal, so retries use the same key.
  const idempotencyKeyRef = useRef(_generateIdempotencyKey());

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
    // FE-014: client-side date validation. The backend also enforces this
    // (apps/bookings/serializers.py validate_check_in + validate), but
    // catching it here avoids a round-trip and a confusing API error toast.
    if (form.check_in < today) {
      toast.error("Check-in date cannot be in the past.");
      return;
    }
    if (type !== "adventure" && form.check_out <= form.check_in) {
      toast.error("Check-out must be after check-in.");
      return;
    }
    if (type === "adventure" && (!form.spots || form.spots < 1)) {
      toast.error("Please choose at least one spot.");
      return;
    }
    setLoading(true);
    try {
      // Step 1 — create the booking record. The backend's BookingCreateSerializer
      // computes nights from the dates and no longer accepts a client-supplied
      // `nights` (F-017), so we do not send it.
      const body = {
        check_in: form.check_in,
        check_out: form.check_out,
      };
      if (type === "hotel") body.hotel_id = item.id;
      if (type === "adventure") {
        body.adventure_id = item.id;
        body.spots = form.spots;
      }
      if (type === "vehicle") body.vehicle_id = item.id;

      // FE-009: send the Idempotency-Key so a repeated submission within
      // this modal (double-click, retry) returns the ORIGINAL booking with
      // the `Idempotent-Replay: true` header instead of creating a second
      // booking + decrementing inventory a second time.
      const { data: booking } = await API.post("/bookings/", body, {
        headers: { "Idempotency-Key": idempotencyKeyRef.current },
      });
      toast.success("Booking created! Opening payment...");

      // Step 2 — Razorpay order create karo
      const { data: order } = await API.post(
        "/payments/razorpay/create-order/",
        { booking_id: booking.id },
      );

      // Step 3 — Razorpay checkout open karo
      const options = {
        key: order.key_id,
        amount: order.amount,
        currency: order.currency,
        name: "TravelX",
        description: `Booking #${booking.id.slice(0, 8).toUpperCase()}`,
        order_id: order.order_id,
        prefill: {
          email: order.user_email,
          name: order.user_name,
        },
        theme: { color: "#2DD4BF" },
        handler: async (response) => {
          // Step 4 — Payment verify karo
          try {
            const { data } = await API.post("/payments/razorpay/verify/", {
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature,
              booking_id: booking.id,
            });
            if (data.success) {
              toast.success("Payment successful! 🎉");
              onClose();
              window.location.href = "/payment-success";
            }
          } catch (e) {
            toast.error("Payment verification failed!");
          }
        },
        modal: {
          ondismiss: () => {
            toast.error("Payment cancelled!");
            setLoading(false);
          },
        },
      };

      const rzp = new window.Razorpay(options);
      rzp.open();
    } catch (e) {
      toast.error(e.response?.data?.error || "Booking failed");
    }
    setLoading(false);
  };

  const inputStyle = {
    width: "100%",
    background: "#16283F",
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
          background: "#0F1E33",
          border: "1px solid rgba(255,255,255,0.12)",
          borderRadius: "20px",
          padding: "2rem",
          width: "100%",
          maxWidth: "480px",
        }}
      >
        {/* Header */}
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
              background: "#16283F",
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
            background: "#16283F",
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
              color: "#2DD4BF",
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
              min={today}
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
                min={form.check_in || today}
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

        {/* Payment Info */}
        <div
          style={{
            background: "rgba(249,115,22,0.05)",
            border: "1px solid rgba(249,115,22,0.15)",
            borderRadius: "10px",
            padding: "0.75rem 1rem",
            marginBottom: "1.25rem",
            display: "flex",
            alignItems: "center",
            gap: "0.5rem",
          }}
        >
          <span>🔒</span>
          <span style={{ fontSize: "0.8rem", color: "#94A3B8" }}>
            Secure payment via Razorpay — UPI, Cards, Net Banking supported
          </span>
        </div>

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
              : "linear-gradient(135deg, #2DD4BF, #14B8A6)",
            color: loading ? "white" : "#0A1628",
            fontSize: "1rem",
            fontWeight: 700,
            cursor: loading ? "not-allowed" : "pointer",
          }}
        >
          {loading ? "Processing..." : "Confirm & Pay via Razorpay →"}
        </button>
      </div>
    </div>
  );
}
