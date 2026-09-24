import React from "react";

const HOTEL_IMGS = [
  "https://images.unsplash.com/photo-1566073771259-6a8506099945?w=800&q=80",
  "https://images.unsplash.com/photo-1571896349842-33c89424de2d?w=800&q=80",
  "https://images.unsplash.com/photo-1551882547-ff40c63fe5fa?w=800&q=80",
  "https://images.unsplash.com/photo-1618773928121-c32242e63f39?w=800&q=80",
  "https://images.unsplash.com/photo-1590490360182-c33d57733427?w=800&q=80",
  "https://images.unsplash.com/photo-1611892440504-42a792e24d32?w=800&q=80",
];
function hashCode(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0;
  return Math.abs(h);
}
function hotelImage(hotel) {
  const key = String(hotel.id || hotel.name || "hotel");
  return HOTEL_IMGS[hashCode(key) % HOTEL_IMGS.length];
}

export default function HotelCard({ hotel, onBook }) {
  return (
    <div
      style={{
        background: "#0F1E33",
        border: "1px solid rgba(255,255,255,0.1)",
        borderRadius: "18px",
        overflow: "hidden",
        transition: "all 0.25s",
        cursor: "pointer",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = "translateY(-6px)";
        e.currentTarget.style.borderColor = "rgba(45,212,191,0.4)";
        e.currentTarget.style.boxShadow = "0 22px 44px rgba(0,0,0,0.45)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = "translateY(0)";
        e.currentTarget.style.borderColor = "rgba(255,255,255,0.1)";
        e.currentTarget.style.boxShadow = "none";
      }}
    >
      <div
        style={{ height: "190px", position: "relative", overflow: "hidden" }}
      >
        <img
          src={hotelImage(hotel)}
          alt={hotel.name}
          loading="lazy"
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            display: "block",
          }}
        />
        <div
          style={{
            position: "absolute",
            top: "0.75rem",
            right: "0.75rem",
            background: "rgba(10,22,40,0.85)",
            backdropFilter: "blur(8px)",
            border: "1px solid rgba(255,255,255,0.12)",
            padding: "0.3rem 0.6rem",
            borderRadius: "8px",
            fontSize: "0.8rem",
            fontWeight: 700,
            color: "#FBBF24",
          }}
        >
          ⭐ {hotel.rating}
        </div>
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
          {hotel.name}
        </div>
        <div
          style={{
            fontSize: "0.8rem",
            color: "#94A8C0",
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
                background: "#16283F",
                border: "1px solid rgba(255,255,255,0.08)",
                padding: "0.2rem 0.55rem",
                borderRadius: "6px",
                fontSize: "0.7rem",
                color: "#94A8C0",
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
            borderTop: "1px solid rgba(255,255,255,0.08)",
          }}
        >
          <div>
            <span
              style={{
                fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
                fontSize: "1.25rem",
                fontWeight: 800,
              }}
            >
              ₹{Number(hotel.price_per_night).toLocaleString()}
            </span>
            <span style={{ fontSize: "0.75rem", color: "#94A8C0" }}>
              {" "}
              /night
            </span>
          </div>
          <button
            onClick={() => onBook(hotel)}
            style={{
              padding: "0.55rem 1.1rem",
              borderRadius: "50px",
              border: "none",
              background: "#2DD4BF",
              color: "#0A1628",
              fontSize: "0.8rem",
              fontWeight: 700,
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
