import React from "react";

const DIFF_COLORS = { EASY: "#10B981", MEDIUM: "#F59E0B", HARD: "#EF4444" };
const ICONS = { EASY: "🏄", MEDIUM: "🧗", HARD: "🪂" };

export default function AdventureCard({ adv, onBook }) {
  return (
    <div
      style={{
        background: "#141E2E",
        border: "1px solid rgba(255,255,255,0.07)",
        borderRadius: "20px",
        padding: "1.5rem",
        cursor: "pointer",
        transition: "all 0.25s",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = "#14B8A6";
        e.currentTarget.style.transform = "translateY(-3px)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = "rgba(255,255,255,0.07)";
        e.currentTarget.style.transform = "translateY(0)";
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginBottom: "1rem",
        }}
      >
        <span style={{ fontSize: "2.5rem" }}>
          {ICONS[adv.difficulty] || "🏕️"}
        </span>
        <span
          style={{
            padding: "0.25rem 0.6rem",
            borderRadius: "6px",
            fontSize: "0.7rem",
            fontWeight: 600,
            background: `${DIFF_COLORS[adv.difficulty]}22`,
            color: DIFF_COLORS[adv.difficulty],
            border: `1px solid ${DIFF_COLORS[adv.difficulty]}44`,
          }}
        >
          {adv.difficulty}
        </span>
      </div>
      <div
        style={{
          fontFamily: "Syne, sans-serif",
          fontWeight: 700,
          marginBottom: "0.25rem",
        }}
      >
        {adv.name}
      </div>
      <div
        style={{
          fontSize: "0.8rem",
          color: "#64748B",
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
          color: "#94A3B8",
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
        }}
      >
        <span
          style={{
            fontFamily: "Syne, sans-serif",
            fontWeight: 700,
            color: "#14B8A6",
          }}
        >
          ₹{Number(adv.price_per_person).toLocaleString()}/person
        </span>
        <button
          onClick={() => onBook(adv)}
          style={{
            padding: "0.4rem 0.875rem",
            borderRadius: "8px",
            border: "none",
            background: "linear-gradient(135deg, #14B8A6, #0D9488)",
            color: "white",
            fontSize: "0.8rem",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          Book
        </button>
      </div>
    </div>
  );
}
