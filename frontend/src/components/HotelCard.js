import React from "react";

export default function HotelCard({ hotel, onBook }) {
  return (
    <div
      style={{
        background: "#141E2E",
        border: "1px solid rgba(255,255,255,0.07)",
        borderRadius: "20px",
        overflow: "hidden",
        transition: "all 0.25s",
        cursor: "pointer",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = "translateY(-4px)";
        e.currentTarget.style.boxShadow = "0 25px 50px rgba(0,0,0,0.5)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = "translateY(0)";
        e.currentTarget.style.boxShadow = "none";
      }}
    >
      <div
        style={{
          height: "160px",
          background:
            "linear-gradient(135deg, rgba(249,115,22,0.1), rgba(20,184,166,0.1))",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: "3rem",
          position: "relative",
        }}
      >
        🏨
        <div
          style={{
            position: "absolute",
            top: "0.75rem",
            right: "0.75rem",
            background: "rgba(8,12,20,0.85)",
            backdropFilter: "blur(10px)",
            border: "1px solid rgba(255,255,255,0.12)",
            padding: "0.25rem 0.6rem",
            borderRadius: "6px",
            fontSize: "0.75rem",
            fontWeight: 600,
            color: "#F59E0B",
          }}
        >
          ⭐ {hotel.rating}
        </div>
      </div>
      <div style={{ padding: "1.25rem" }}>
        <div
          style={{
            fontFamily: "Syne, sans-serif",
            fontWeight: 700,
            marginBottom: "0.25rem",
          }}
        >
          {hotel.name}
        </div>
        <div
          style={{
            fontSize: "0.8rem",
            color: "#64748B",
            marginBottom: "0.75rem",
          }}
        >
          📍 {hotel.city_name}
        </div>
        <div
          style={{
            display: "flex",
            gap: "0.5rem",
            flexWrap: "wrap",
            marginBottom: "0.875rem",
          }}
        >
          {(hotel.amenities || []).slice(0, 3).map((a) => (
            <span
              key={a}
              style={{
                background: "#111827",
                border: "1px solid rgba(255,255,255,0.07)",
                padding: "0.2rem 0.5rem",
                borderRadius: "4px",
                fontSize: "0.7rem",
                color: "#94A3B8",
              }}
            >
              {a}
            </span>
          ))}
        </div>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            paddingTop: "0.875rem",
            borderTop: "1px solid rgba(255,255,255,0.07)",
          }}
        >
          <div>
            <span
              style={{
                fontFamily: "Syne, sans-serif",
                fontSize: "1.25rem",
                fontWeight: 700,
                color: "#F97316",
              }}
            >
              ₹{Number(hotel.price_per_night).toLocaleString()}
            </span>
            <span style={{ fontSize: "0.75rem", color: "#64748B" }}>
              {" "}
              /night
            </span>
          </div>
          <button
            onClick={() => onBook(hotel)}
            style={{
              padding: "0.5rem 1rem",
              borderRadius: "8px",
              border: "none",
              background: "linear-gradient(135deg, #F97316, #EA580C)",
              color: "white",
              fontSize: "0.8rem",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Book Now
          </button>
        </div>
      </div>
    </div>
  );
}
