import React from "react";

const DIFF_COLORS = { EASY: "#22C55E", MEDIUM: "#FBBF24", HARD: "#EF4444" };

const ADV_IMGS = [
  "https://images.unsplash.com/photo-1533692328991-08159ff19fca?w=800&q=80",
  "https://images.unsplash.com/photo-1551632811-561732d1e306?w=800&q=80",
  "https://images.unsplash.com/photo-1502680390469-be75c86b636f?w=800&q=80",
  "https://images.unsplash.com/photo-1520962880247-cfaf541c8724?w=800&q=80",
  "https://images.unsplash.com/photo-1533130061792-64b345e4a833?w=800&q=80",
  "https://images.unsplash.com/photo-1571744350988-3d5c1e2e9f0c?w=800&q=80",
];
function hashCode(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0;
  return Math.abs(h);
}
function advImage(adv) {
  const key = String(adv.id || adv.name || "adventure");
  return ADV_IMGS[hashCode(key) % ADV_IMGS.length];
}

export default function AdventureCard({ adv, onBook }) {
  return (
    <div
      style={{
        background: "#0F1E33",
        border: "1px solid rgba(255,255,255,0.1)",
        borderRadius: "18px",
        overflow: "hidden",
        cursor: "pointer",
        transition: "all 0.25s",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = "rgba(45,212,191,0.4)";
        e.currentTarget.style.transform = "translateY(-6px)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = "rgba(255,255,255,0.1)";
        e.currentTarget.style.transform = "translateY(0)";
      }}
    >
      <div
        style={{ height: "170px", position: "relative", overflow: "hidden" }}
      >
        <img
          src={advImage(adv)}
          alt={adv.name}
          loading="lazy"
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            display: "block",
          }}
        />
        <span
          style={{
            position: "absolute",
            top: "0.75rem",
            right: "0.75rem",
            padding: "0.3rem 0.7rem",
            borderRadius: "8px",
            fontSize: "0.72rem",
            fontWeight: 700,
            background: `${DIFF_COLORS[adv.difficulty]}dd`,
            color: adv.difficulty === "MEDIUM" ? "#3a2c00" : "#fff",
          }}
        >
          {adv.difficulty}
        </span>
      </div>
      <div style={{ padding: "1.25rem" }}>
        <div
          style={{
            fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
            fontWeight: 700,
            fontSize: "1.05rem",
            marginBottom: "0.25rem",
          }}
        >
          {adv.name}
        </div>
        <div
          style={{
            fontSize: "0.8rem",
            color: "#94A8C0",
            marginBottom: "0.875rem",
          }}
        >
          📍 {adv.city_name}
        </div>
        <div
          style={{
            display: "flex",
            gap: "1rem",
            fontSize: "0.8rem",
            color: "#94A8C0",
            marginBottom: "1rem",
          }}
        >
          <span>⏱ {adv.duration_hours}h</span>
          <span>👥 {adv.max_capacity - adv.current_bookings} spots left</span>
        </div>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            paddingTop: "0.875rem",
            borderTop: "1px solid rgba(255,255,255,0.08)",
          }}
        >
          <span
            style={{
              fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
              fontWeight: 800,
            }}
          >
            ₹{Number(adv.price_per_person).toLocaleString()}
            <span
              style={{ fontSize: "0.75rem", color: "#94A8C0", fontWeight: 400 }}
            >
              /person
            </span>
          </span>
          <button
            onClick={() => onBook(adv)}
            style={{
              padding: "0.5rem 1.1rem",
              borderRadius: "50px",
              border: "none",
              background: "#2DD4BF",
              color: "#0A1628",
              fontSize: "0.8rem",
              fontWeight: 700,
              cursor: "pointer",
            }}
          >
            Book
          </button>
        </div>
      </div>
    </div>
  );
}
