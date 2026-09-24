import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import API from "../api";
import toast from "react-hot-toast";

const BG_IMGS = [
  "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=1600&q=80",
  "https://images.unsplash.com/photo-1512343879784-a960bf40e7f2?w=1600&q=80",
  "https://images.unsplash.com/photo-1477587458883-47145ed94245?w=1600&q=80",
  "https://images.unsplash.com/photo-1626621341517-bbf3d9990a23?w=1600&q=80",
];

export default function MyBookings() {
  const [bookings, setBookings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [bgIndex, setBgIndex] = useState(0);
  const { token } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    const t = setInterval(() => {
      setBgIndex((i) => (i + 1) % BG_IMGS.length);
    }, 4000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (!token) {
      navigate("/");
      return;
    }
    loadBookings();
  }, [token]);

  const loadBookings = async () => {
    try {
      const { data } = await API.get("/bookings/my/");
      setBookings((data.results || []).filter((b) => b.status !== "CANCELLED"));
    } catch {
      console.error("Failed to load bookings");
    }
    setLoading(false);
  };

  const handleRefund = async (bookingId) => {
    if (!window.confirm("Are you sure you want to cancel and get refund?"))
      return;
    try {
      await API.post("/payments/refund/", { booking_id: bookingId });
      toast.success("Refund processed! 💰");
      loadBookings();
    } catch (e) {
      toast.error(e.response?.data?.error || "Refund failed");
    }
  };

  const handleCancel = async (bookingId) => {
    if (!window.confirm("Cancel this booking? This cannot be undone.")) return;
    try {
      await API.post(`/bookings/${bookingId}/cancel/`);
      toast.success("Booking cancelled");
      loadBookings();
    } catch (e) {
      toast.error(e.response?.data?.error || "Could not cancel booking");
    }
  };

  const getStatusColor = (status) => {
    const colors = {
      PENDING: "#FBBF24",
      CONFIRMED: "#14B8A6",
      PAID: "#10B981",
      CANCELLED: "#EF4444",
    };
    return colors[status] || "#94A3B8";
  };

  const getStatusEmoji = (status) => {
    const emojis = {
      PENDING: "⏳",
      CONFIRMED: "✅",
      PAID: "💳",
      CANCELLED: "❌",
    };
    return emojis[status] || "❓";
  };

  return (
    <div
      style={{
        paddingTop: "80px",
        minHeight: "100vh",
        background: "#080D17",
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* Background slideshow */}
      <div style={{ position: "fixed", inset: 0, zIndex: 0 }}>
        {BG_IMGS.map((img, i) => (
          <div
            key={i}
            style={{
              position: "absolute",
              inset: 0,
              backgroundImage: `url(${img})`,
              backgroundSize: "cover",
              backgroundPosition: "center",
              opacity: i === bgIndex ? 0.18 : 0,
              transition: "opacity 1.5s ease",
            }}
          />
        ))}
        <div
          style={{
            position: "absolute",
            inset: 0,
            background:
              "linear-gradient(180deg, rgba(8,13,23,0.85) 0%, #080D17 60%)",
          }}
        />
      </div>

      <div
        style={{
          maxWidth: "900px",
          margin: "0 auto",
          padding: "2rem",
          position: "relative",
          zIndex: 1,
        }}
      >
        {/* Header */}
        <div style={{ marginBottom: "2rem" }}>
          <div
            style={{
              fontSize: "0.75rem",
              fontWeight: 600,
              letterSpacing: "2px",
              textTransform: "uppercase",
              color: "#2DD4BF",
              marginBottom: "0.5rem",
            }}
          >
            My Account
          </div>
          <h1
            style={{
              fontFamily: "system-ui, sans-serif",
              fontSize: "2rem",
              fontWeight: 700,
            }}
          >
            My Bookings
          </h1>
          <p style={{ color: "#94A3B8", marginTop: "0.5rem" }}>
            {bookings.length} booking{bookings.length !== 1 ? "s" : ""} found
          </p>
        </div>

        {loading ? (
          <div
            style={{ textAlign: "center", padding: "4rem", color: "#64748B" }}
          >
            <div style={{ fontSize: "2rem", marginBottom: "1rem" }}>⏳</div>
            Loading bookings...
          </div>
        ) : bookings.length === 0 ? (
          <div
            style={{ textAlign: "center", padding: "4rem", color: "#64748B" }}
          >
            <div style={{ fontSize: "3rem", marginBottom: "1rem" }}>🎒</div>
            <p>No bookings yet!</p>
            <button
              onClick={() => navigate("/")}
              style={{
                marginTop: "1rem",
                padding: "0.75rem 1.5rem",
                borderRadius: "10px",
                background: "linear-gradient(135deg, #2DD4BF, #14B8A6)",
                border: "none",
                color: "white",
                cursor: "pointer",
                fontWeight: 600,
              }}
            >
              Explore Now →
            </button>
          </div>
        ) : (
          <div
            style={{ display: "flex", flexDirection: "column", gap: "1rem" }}
          >
            {bookings.map((booking) => (
              <div
                key={booking.id}
                style={{
                  background: "#0F1E33",
                  border: `1px solid rgba(255,255,255,0.07)`,
                  borderLeft: `4px solid ${getStatusColor(booking.status)}`,
                  borderRadius: "16px",
                  padding: "1.5rem",
                }}
              >
                {/* Booking Header */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    marginBottom: "1rem",
                  }}
                >
                  <div>
                    <div
                      style={{
                        fontFamily: "system-ui, sans-serif",
                        fontWeight: 700,
                        fontSize: "1rem",
                        marginBottom: "0.25rem",
                      }}
                    >
                      Booking #{booking.id.slice(0, 8).toUpperCase()}
                    </div>
                    <div style={{ fontSize: "0.8rem", color: "#64748B" }}>
                      {new Date(booking.created_at).toLocaleDateString(
                        "en-IN",
                        {
                          day: "numeric",
                          month: "long",
                          year: "numeric",
                        },
                      )}
                    </div>
                  </div>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "0.5rem",
                      padding: "0.35rem 0.875rem",
                      borderRadius: "20px",
                      background: `${getStatusColor(booking.status)}22`,
                      border: `1px solid ${getStatusColor(booking.status)}44`,
                      color: getStatusColor(booking.status),
                      fontSize: "0.8rem",
                      fontWeight: 600,
                    }}
                  >
                    {getStatusEmoji(booking.status)} {booking.status}
                  </div>
                </div>

                {/* Booking Items */}
                <div style={{ marginBottom: "1rem" }}>
                  {booking.items?.map((item, i) => (
                    <div
                      key={i}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        padding: "0.5rem 0",
                        borderBottom:
                          i < booking.items.length - 1
                            ? "1px solid rgba(255,255,255,0.05)"
                            : "none",
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: "0.5rem",
                        }}
                      >
                        <span>
                          {item.item_type === "HOTEL"
                            ? "🏨"
                            : item.item_type === "ADVENTURE"
                              ? "🧗"
                              : "🚗"}
                        </span>
                        <span
                          style={{ fontSize: "0.875rem", color: "#F1F5F9" }}
                        >
                          {item.item_name}
                        </span>
                        {item.nights && (
                          <span
                            style={{ fontSize: "0.75rem", color: "#64748B" }}
                          >
                            ({item.nights} nights)
                          </span>
                        )}
                      </div>
                      <span
                        style={{
                          fontSize: "0.875rem",
                          color: "#2DD4BF",
                          fontWeight: 600,
                        }}
                      >
                        ₹{Number(item.price_at_booking).toLocaleString()}
                      </span>
                    </div>
                  ))}
                </div>

                {/* Booking Footer */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    paddingTop: "1rem",
                    borderTop: "1px solid rgba(255,255,255,0.07)",
                  }}
                >
                  <div>
                    <div
                      style={{
                        fontSize: "0.75rem",
                        color: "#64748B",
                        marginBottom: "0.5rem",
                      }}
                    >
                      📅 {booking.check_in} → {booking.check_out}
                    </div>
                    {/* Refund Button */}
                    {booking.status === "PAID" && (
                      <button
                        onClick={() => handleRefund(booking.id)}
                        style={{
                          padding: "0.4rem 0.875rem",
                          borderRadius: "8px",
                          border: "none",
                          background:
                            "linear-gradient(135deg, #EF4444, #DC2626)",
                          color: "white",
                          fontSize: "0.75rem",
                          fontWeight: 600,
                          cursor: "pointer",
                        }}
                      >
                        ❌ Cancel & Refund
                      </button>
                    )}
                    {booking.status === "PENDING" && (
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: "0.75rem",
                          flexWrap: "wrap",
                        }}
                      >
                        <span style={{ fontSize: "0.75rem", color: "#FBBF24" }}>
                          ⏳ Payment pending
                        </span>
                        <button
                          onClick={() => handleCancel(booking.id)}
                          style={{
                            padding: "0.35rem 0.9rem",
                            borderRadius: "50px",
                            border: "1px solid rgba(239,68,68,0.4)",
                            background: "transparent",
                            color: "#EF4444",
                            fontSize: "0.72rem",
                            fontWeight: 700,
                            cursor: "pointer",
                          }}
                        >
                          Cancel Booking
                        </button>
                      </div>
                    )}
                    {booking.status === "CONFIRMED" && (
                      <span style={{ fontSize: "0.75rem", color: "#14B8A6" }}>
                        ✓ Confirmed
                      </span>
                    )}
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div style={{ fontSize: "0.75rem", color: "#64748B" }}>
                      Total Amount
                    </div>
                    <div
                      style={{
                        fontFamily: "system-ui, sans-serif",
                        fontSize: "1.25rem",
                        fontWeight: 700,
                        color: "#10B981",
                      }}
                    >
                      ₹{Number(booking.total_amount).toLocaleString()}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
