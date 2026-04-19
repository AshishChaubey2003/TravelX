import React, { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { getHotels, getAdventures, getVehicles, getCities } from "../api";
import HotelCard from "../components/HotelCard";
import AdventureCard from "../components/AdventureCard";
import VehicleCard from "../components/VehicleCard";
import MapView from "../components/MapView";
import BookingModal from "../components/BookingModal";

export default function Explore() {
  const [searchParams] = useSearchParams();
  const cityId = searchParams.get("city");

  const [hotels, setHotels] = useState([]);
  const [adventures, setAdventures] = useState([]);
  const [vehicles, setVehicles] = useState([]);
  const [city, setCity] = useState(null);
  const [tab, setTab] = useState("hotels");
  const [booking, setBooking] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (cityId) loadAll();
  }, [cityId]);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [h, a, v, c] = await Promise.all([
        getHotels(cityId),
        getAdventures(cityId),
        getVehicles(cityId),
        getCities(),
      ]);
      setHotels(h.data.results || []);
      setAdventures(a.data.results || []);
      setVehicles(v.data.results || []);
      const found = (c.data.results || []).find((x) => x.id === cityId);
      setCity(found);
    } catch {
      console.error("Load failed");
    }
    setLoading(false);
  };

  const tabs = [
    { key: "hotels", label: "🏨 Hotels", count: hotels.length },
    { key: "adventures", label: "🧗 Adventures", count: adventures.length },
    { key: "vehicles", label: "🚗 Vehicles", count: vehicles.length },
    { key: "map", label: "🗺 Map", count: null },
  ];

  const EmptyState = ({ icon, msg }) => (
    <div style={{ textAlign: "center", padding: "4rem", color: "#64748B" }}>
      <div style={{ fontSize: "3rem", marginBottom: "1rem" }}>{icon}</div>
      <p>{msg}</p>
    </div>
  );

  return (
    <div style={{ paddingTop: "80px", minHeight: "100vh" }}>
      <div style={{ maxWidth: "1200px", margin: "0 auto", padding: "2rem" }}>
        {/* Header */}
        <div style={{ marginBottom: "2rem" }}>
          <div
            style={{
              fontSize: "0.75rem",
              fontWeight: 600,
              letterSpacing: "2px",
              textTransform: "uppercase",
              color: "#F97316",
              marginBottom: "0.5rem",
            }}
          >
            Exploring
          </div>
          <h1
            style={{
              fontFamily: "Syne, sans-serif",
              fontSize: "2rem",
              fontWeight: 700,
            }}
          >
            {city ? `${city.name}, ${city.state}` : "Loading..."}
          </h1>
        </div>

        {/* Tabs */}
        <div
          style={{
            display: "flex",
            gap: "0.5rem",
            marginBottom: "2rem",
            flexWrap: "wrap",
          }}
        >
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              style={{
                padding: "0.5rem 1.25rem",
                borderRadius: "8px",
                border: "none",
                cursor: "pointer",
                background: tab === t.key ? "#F97316" : "#141E2E",
                border: `1px solid ${tab === t.key ? "#F97316" : "rgba(255,255,255,0.07)"}`,
                color: tab === t.key ? "white" : "#94A3B8",
                fontSize: "0.875rem",
                fontWeight: 500,
              }}
            >
              {t.label}{" "}
              {t.count !== null && (
                <span style={{ opacity: 0.7 }}>({t.count})</span>
              )}
            </button>
          ))}
        </div>

        {/* Content */}
        {loading ? (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
              gap: "1.5rem",
            }}
          >
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                style={{
                  height: "280px",
                  background: "#141E2E",
                  borderRadius: "20px",
                  animation: "pulse 1.5s infinite",
                }}
              />
            ))}
          </div>
        ) : (
          <>
            {tab === "hotels" &&
              (hotels.length ? (
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns:
                      "repeat(auto-fill, minmax(300px, 1fr))",
                    gap: "1.5rem",
                  }}
                >
                  {hotels.map((h) => (
                    <HotelCard
                      key={h.id}
                      hotel={h}
                      onBook={() => setBooking({ type: "hotel", item: h })}
                    />
                  ))}
                </div>
              ) : (
                <EmptyState
                  icon="🏨"
                  msg="No hotels in this city yet. Add some from admin!"
                />
              ))}

            {tab === "adventures" &&
              (adventures.length ? (
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns:
                      "repeat(auto-fill, minmax(280px, 1fr))",
                    gap: "1.25rem",
                  }}
                >
                  {adventures.map((a) => (
                    <AdventureCard
                      key={a.id}
                      adv={a}
                      onBook={() => setBooking({ type: "adventure", item: a })}
                    />
                  ))}
                </div>
              ) : (
                <EmptyState
                  icon="🏔️"
                  msg="No adventures yet. Add some from admin!"
                />
              ))}

            {tab === "vehicles" &&
              (vehicles.length ? (
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns:
                      "repeat(auto-fill, minmax(240px, 1fr))",
                    gap: "1rem",
                  }}
                >
                  {vehicles.map((v) => (
                    <VehicleCard
                      key={v.id}
                      vehicle={v}
                      onBook={() => setBooking({ type: "vehicle", item: v })}
                    />
                  ))}
                </div>
              ) : (
                <EmptyState
                  icon="🚗"
                  msg="No vehicles yet. Add some from admin!"
                />
              ))}

            {tab === "map" && (
              <MapView hotels={hotels} adventures={adventures} center={city} />
            )}
          </>
        )}
      </div>

      {/* Booking Modal */}
      {booking && (
        <BookingModal
          type={booking.type}
          item={booking.item}
          onClose={() => setBooking(null)}
        />
      )}
    </div>
  );
}
