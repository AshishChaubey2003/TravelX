import React from "react";

// Real image per city (reliable Unsplash URLs), keyed by city name.
const CITY_IMGS = {
  Goa: "https://images.unsplash.com/photo-1512343879784-a960bf40e7f2?w=600&q=80",
  Manali:
    "https://images.unsplash.com/photo-1712388430474-ace0c16051e2?w=600&q=80",
  Delhi:
    "https://images.unsplash.com/photo-1587474260584-136574528ed5?w=600&q=80",
  Mumbai:
    "https://images.unsplash.com/photo-1529253355930-ddbe423a2ac7?w=600&q=80",
  Jaipur:
    "https://images.unsplash.com/photo-1477587458883-47145ed94245?w=600&q=80",
  Shimla:
    "https://images.unsplash.com/photo-1605649487212-47bdab064df7?w=600&q=80",
  Rishikesh:
    "https://images.unsplash.com/photo-1600100397608-f5f4a2f5f5f5?w=600&q=80",
  Munnar:
    "https://images.unsplash.com/photo-1637066742971-726b2f0b0b0b?w=600&q=80",
  Darjeeling:
    "https://images.unsplash.com/photo-1622308644420-b20142dc993c?w=600&q=80",
  Leh: "https://images.unsplash.com/photo-1581791534721-e599df4417f7?w=600&q=80",
  Udaipur:
    "https://images.unsplash.com/photo-1590766940554-153a4d9f6ac9?w=600&q=80",
  Varanasi:
    "https://images.unsplash.com/photo-1561361513-2d000a50f0dc?w=600&q=80",
};
const FALLBACK =
  "https://images.unsplash.com/photo-1524492412937-b28074a5d7da?w=600&q=80";

function cityImage(city) {
  // 1) prefer whatever the database stored
  if (city.image_url) return city.image_url;
  // 2) then our curated map
  if (CITY_IMGS[city.name]) return CITY_IMGS[city.name];
  // 3) fallback
  return FALLBACK;
}

export default function CityCard({ city, selected, onClick }) {
  return (
    <div
      onClick={onClick}
      style={{
        position: "relative",
        height: "200px",
        borderRadius: "16px",
        overflow: "hidden",
        cursor: "pointer",
        border: `2px solid ${selected ? "#2DD4BF" : "rgba(255,255,255,0.08)"}`,
        transition: "all 0.25s",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = "translateY(-5px)";
        if (!selected)
          e.currentTarget.style.borderColor = "rgba(45,212,191,0.5)";
        const img = e.currentTarget.querySelector("img");
        if (img) img.style.transform = "scale(1.1)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = "translateY(0)";
        if (!selected)
          e.currentTarget.style.borderColor = "rgba(255,255,255,0.08)";
        const img = e.currentTarget.querySelector("img");
        if (img) img.style.transform = "scale(1)";
      }}
    >
      {/* City image */}
      <img
        src={cityImage(city)}
        alt={city.name}
        loading="lazy"
        onError={(e) => {
          e.currentTarget.src = FALLBACK;
        }}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transition: "transform 0.5s",
        }}
      />
      {/* Gradient overlay */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "linear-gradient(to top, rgba(10,22,40,0.95) 0%, rgba(10,22,40,0.3) 55%, rgba(10,22,40,0.1) 100%)",
        }}
      />
      {/* Text */}
      <div
        style={{
          position: "absolute",
          bottom: 0,
          left: 0,
          right: 0,
          padding: "1rem",
        }}
      >
        <div
          style={{
            fontFamily: "'Plus Jakarta Sans', Syne, sans-serif",
            fontWeight: 700,
            fontSize: "1.1rem",
            color: "#fff",
          }}
        >
          {city.name}
        </div>
        <div
          style={{ fontSize: "0.78rem", color: "#C6D4E4", marginTop: "2px" }}
        >
          {city.state}
        </div>
        <div style={{ display: "flex", gap: "1rem", marginTop: "0.6rem" }}>
          <span style={{ fontSize: "0.75rem", color: "#F1F6FB" }}>
            🏨 {city.hotel_count}
          </span>
          <span style={{ fontSize: "0.75rem", color: "#F1F6FB" }}>
            🧗 {city.adventure_count}
          </span>
        </div>
      </div>
    </div>
  );
}
