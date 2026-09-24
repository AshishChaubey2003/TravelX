import React from "react";

const VEH_IMGS = {
  BIKE: [
    "https://images.unsplash.com/photo-1558981403-c5f9899a28bc?w=800&q=80",
    "https://images.unsplash.com/photo-1568772585407-9361f9bf3a87?w=800&q=80",
  ],
  CAR: [
    "https://images.unsplash.com/photo-1550355291-bbee04a92027?w=800&q=80",
    "https://images.unsplash.com/photo-1552519507-da3b142c6e3d?w=800&q=80",
  ],
  SCOOTER: [
    "https://images.unsplash.com/photo-1622185135505-2d795003994a?w=800&q=80",
    "https://images.unsplash.com/photo-1591637333184-19aa84b3e01f?w=800&q=80",
  ],
};
function hashCode(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0;
  return Math.abs(h);
}
function vehImage(vehicle) {
  const type = (vehicle.vehicle_type || "CAR").toUpperCase();
  const pool = VEH_IMGS[type] || VEH_IMGS.CAR;
  const key = String(vehicle.id || vehicle.name || "vehicle");
  return pool[hashCode(key) % pool.length];
}

export default function VehicleCard({ vehicle, onBook }) {
  return (
    <div
      style={{
        background: "#0F1E33",
        border: "1px solid rgba(255,255,255,0.1)",
        borderRadius: "16px",
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
        style={{ height: "150px", position: "relative", overflow: "hidden" }}
      >
        <img
          src={vehImage(vehicle)}
          alt={vehicle.name}
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
            top: "0.6rem",
            right: "0.6rem",
            padding: "0.25rem 0.6rem",
            borderRadius: "8px",
            fontSize: "0.7rem",
            fontWeight: 700,
            background: "rgba(10,22,40,0.85)",
            color: "#38BDF8",
            border: "1px solid rgba(255,255,255,0.12)",
          }}
        >
          {vehicle.vehicle_type}
        </span>
      </div>
      <div style={{ padding: "1.25rem" }}>
        <div
          style={{
            fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
            fontWeight: 700,
            fontSize: "0.98rem",
            marginBottom: "0.25rem",
          }}
        >
          {vehicle.name}
        </div>
        <div
          style={{
            fontSize: "0.8rem",
            color: "#94A8C0",
            marginBottom: "0.75rem",
          }}
        >
          📍 {vehicle.city_name}
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
              fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
              fontWeight: 800,
            }}
          >
            ₹{Number(vehicle.price_per_day).toLocaleString()}
            <span
              style={{ fontSize: "0.75rem", color: "#94A8C0", fontWeight: 400 }}
            >
              /day
            </span>
          </span>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <span
              style={{
                fontSize: "0.72rem",
                color: vehicle.is_available ? "#22C55E" : "#EF4444",
              }}
            >
              {vehicle.is_available ? "✓ Available" : "✗ Booked"}
            </span>
            {vehicle.is_available && (
              <button
                onClick={() => onBook(vehicle)}
                style={{
                  padding: "0.4rem 0.85rem",
                  borderRadius: "50px",
                  border: "none",
                  background: "#2DD4BF",
                  color: "#0A1628",
                  fontSize: "0.75rem",
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                Rent
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
