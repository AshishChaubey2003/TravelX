import React from "react";

const VEH_ICONS = { BIKE: "🏍️", CAR: "🚗", SCOOTER: "🛵" };

export default function VehicleCard({ vehicle, onBook }) {
  return (
    <div
      style={{
        background: "#141E2E",
        border: "1px solid rgba(255,255,255,0.07)",
        borderRadius: "12px",
        padding: "1.25rem",
        cursor: "pointer",
        transition: "all 0.25s",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = "#F59E0B";
        e.currentTarget.style.transform = "translateY(-3px)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = "rgba(255,255,255,0.07)";
        e.currentTarget.style.transform = "translateY(0)";
      }}
    >
      <div style={{ fontSize: "2rem", marginBottom: "0.75rem" }}>
        {VEH_ICONS[vehicle.vehicle_type] || "🚗"}
      </div>
      <div
        style={{
          fontFamily: "Syne, sans-serif",
          fontWeight: 700,
          fontSize: "0.95rem",
          marginBottom: "0.25rem",
        }}
      >
        {vehicle.name}
      </div>
      <div
        style={{
          fontSize: "0.8rem",
          color: "#64748B",
          marginBottom: "0.75rem",
        }}
      >
        {vehicle.vehicle_type} • {vehicle.city_name}
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
            color: "#F59E0B",
          }}
        >
          ₹{Number(vehicle.price_per_day).toLocaleString()}/day
        </span>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <span
            style={{
              fontSize: "0.75rem",
              color: vehicle.is_available ? "#10B981" : "#EF4444",
            }}
          >
            {vehicle.is_available ? "✓ Available" : "✗ Booked"}
          </span>
          {vehicle.is_available && (
            <button
              onClick={() => onBook(vehicle)}
              style={{
                padding: "0.35rem 0.75rem",
                borderRadius: "6px",
                border: "none",
                background: "linear-gradient(135deg, #F59E0B, #D97706)",
                color: "white",
                fontSize: "0.75rem",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              Rent
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
