import React from "react";

const ICONS = {
  Goa: "🏖️",
  Manali: "🏔️",
  Delhi: "🏛️",
  Mumbai: "🌆",
  Jaipur: "🏰",
  Shimla: "❄️",
  Rishikesh: "🌊",
  Kerala: "🌴",
  Lucknow: "🕌",
};

export default function CityCard({ city, selected, onClick }) {
  return (
    <div
      onClick={onClick}
      style={{
        background: selected ? "#1A2540" : "#141E2E",
        border: `1px solid ${selected ? "#F97316" : "rgba(255,255,255,0.07)"}`,
        borderRadius: "12px",
        padding: "1.5rem",
        cursor: "pointer",
        transition: "all 0.25s",
        position: "relative",
        overflow: "hidden",
      }}
      onMouseEnter={(e) => {
        if (!selected)
          e.currentTarget.style.borderColor = "rgba(249,115,22,0.5)";
      }}
      onMouseLeave={(e) => {
        if (!selected)
          e.currentTarget.style.borderColor = "rgba(255,255,255,0.07)";
      }}
    >
      <div style={{ fontSize: "2rem", marginBottom: "0.75rem" }}>
        {ICONS[city.name] || "🏙️"}
      </div>
      <div
        style={{
          fontFamily: "Syne, sans-serif",
          fontWeight: 700,
          fontSize: "1rem",
        }}
      >
        {city.name}
      </div>
      <div
        style={{ fontSize: "0.8rem", color: "#64748B", marginTop: "0.25rem" }}
      >
        {city.state}
      </div>
      <div style={{ display: "flex", gap: "1rem", marginTop: "0.75rem" }}>
        <span style={{ fontSize: "0.75rem", color: "#94A3B8" }}>
          🏨 {city.hotel_count}
        </span>
        <span style={{ fontSize: "0.75rem", color: "#94A3B8" }}>
          🧗 {city.adventure_count}
        </span>
      </div>
    </div>
  );
}
