import React, { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { getHotels, getAdventures, getVehicles, getCities } from "../api";
import HotelCard from "../components/HotelCard";
import AdventureCard from "../components/AdventureCard";
import VehicleCard from "../components/VehicleCard";
import MapView from "../components/MapView";
import BookingModal from "../components/BookingModal";

const BG_IMAGES = {
  hotels: ["bg-hotel-1", "bg-hotel-2", "bg-hotel-3"],
  adventures: ["bg-adv-1", "bg-adv-2", "bg-adv-3"],
  vehicles: ["bg-veh-1", "bg-veh-2", "bg-veh-3"],
  map: ["bg-map-1", "bg-map-2"],
};
const bgUrl = (seed) => `https://picsum.photos/seed/${seed}/1600/900`;

export default function Explore() {
  const [searchParams, setSearchParams] = useSearchParams();
  const cityIdFromUrl = searchParams.get("city");

  const [cities, setCities] = useState([]);
  const [cityId, setCityId] = useState(cityIdFromUrl || null);

  const [hotels, setHotels] = useState([]);
  const [adventures, setAdventures] = useState([]);
  const [vehicles, setVehicles] = useState([]);
  const [city, setCity] = useState(null);
  const [tab, setTab] = useState("hotels");
  const [booking, setBooking] = useState(null);
  const [loading, setLoading] = useState(true);
  const [bgIndex, setBgIndex] = useState(0);

  useEffect(() => {
    const imgs = BG_IMAGES[tab] || BG_IMAGES.hotels;
    setBgIndex(0);
    const t = setInterval(() => {
      setBgIndex((i) => (i + 1) % imgs.length);
    }, 4000);
    return () => clearInterval(t);
  }, [tab]);

  useEffect(() => {
    const loadCities = async () => {
      try {
        const c = await getCities();
        const list = c.data.results || c.data || [];
        setCities(list);
        if (!cityId && list.length) setCityId(list[0].id);
      } catch {
        console.error("Failed to load cities");
        setLoading(false);
      }
    };
    loadCities();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (cityId) loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cityId]);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [h, a, v] = await Promise.all([
        getHotels(cityId),
        getAdventures(cityId),
        getVehicles(cityId),
      ]);
      setHotels(h.data.results || h.data || []);
      setAdventures(a.data.results || a.data || []);
      setVehicles(v.data.results || v.data || []);
      const found = cities.find((x) => x.id === cityId);
      if (found) setCity(found);
    } catch {
      console.error("Load failed");
    }
    setLoading(false);
  };

  const handleCityChange = (id) => {
    setCityId(id);
    setSearchParams({ city: id });
  };

  const tabs = [
    { key: "hotels", label: "\ud83c\udfe8 Hotels", count: hotels.length },
    {
      key: "adventures",
      label: "\ud83e\uddd7 Adventures",
      count: adventures.length,
    },
    { key: "vehicles", label: "\ud83d\ude97 Vehicles", count: vehicles.length },
    { key: "map", label: "\ud83d\uddfa Map", count: null },
  ];

  const EmptyState = ({ icon, msg }) => (
    <div style={{ textAlign: "center", padding: "4rem", color: "#94A8C0" }}>
      <div style={{ fontSize: "3rem", marginBottom: "1rem" }}>{icon}</div>
      <p>{msg}</p>
    </div>
  );

  return (
    <div style={{ position: "relative", minHeight: "100vh" }}>
      {/* Background slideshow */}
      <div
        style={{ position: "fixed", inset: 0, zIndex: 0, overflow: "hidden" }}
      >
        {(BG_IMAGES[tab] || BG_IMAGES.hotels).map((seed, i) => (
          <div
            key={seed}
            style={{
              position: "absolute",
              inset: 0,
              backgroundImage: `url(${bgUrl(seed)})`,
              backgroundSize: "cover",
              backgroundPosition: "center",
              opacity: i === bgIndex ? 1 : 0,
              transition: "opacity 1.5s ease",
            }}
          />
        ))}
        <div
          style={{
            position: "absolute",
            inset: 0,
            background:
              "linear-gradient(180deg, rgba(8,13,23,0.90) 0%, rgba(8,13,23,0.96) 100%)",
          }}
        />
      </div>

      {/* Content */}
      <div style={{ position: "relative", zIndex: 1, paddingTop: "100px" }}>
        <div
          style={{
            maxWidth: "1240px",
            margin: "0 auto",
            padding: "1rem 2.5rem 4rem",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-end",
              flexWrap: "wrap",
              gap: "1rem",
              marginBottom: "2rem",
            }}
          >
            <div>
              <div
                style={{
                  fontSize: "0.75rem",
                  fontWeight: 700,
                  letterSpacing: "2px",
                  textTransform: "uppercase",
                  color: "#2DD4BF",
                  marginBottom: "0.5rem",
                }}
              >
                Exploring
              </div>
              <h1
                style={{
                  fontFamily: "'Plus Jakarta Sans', Syne, sans-serif",
                  fontSize: "2rem",
                  fontWeight: 800,
                }}
              >
                {city ? `${city.name}, ${city.state}` : "Choose a city"}
              </h1>
            </div>

            {cities.length > 0 && (
              <select
                value={cityId || ""}
                onChange={(e) => handleCityChange(e.target.value)}
                style={{
                  background: "#16283F",
                  border: "1px solid rgba(255,255,255,0.12)",
                  borderRadius: "12px",
                  padding: "0.7rem 1rem",
                  color: "#F1F6FB",
                  fontSize: "0.9rem",
                  cursor: "pointer",
                  minWidth: "200px",
                }}
              >
                {cities.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}, {c.state}
                  </option>
                ))}
              </select>
            )}
          </div>

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
                  padding: "0.6rem 1.4rem",
                  borderRadius: "50px",
                  cursor: "pointer",
                  background: tab === t.key ? "#2DD4BF" : "rgba(22,40,63,0.8)",
                  border: `1px solid ${tab === t.key ? "#2DD4BF" : "rgba(255,255,255,0.1)"}`,
                  color: tab === t.key ? "#0A1628" : "#94A8C0",
                  fontSize: "0.9rem",
                  fontWeight: 600,
                }}
              >
                {t.label}{" "}
                {t.count !== null && (
                  <span style={{ opacity: 0.7 }}>({t.count})</span>
                )}
              </button>
            ))}
          </div>

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
                    background: "rgba(22,40,63,0.6)",
                    borderRadius: "18px",
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
                    icon="\ud83c\udfe8"
                    msg="No hotels in this city yet."
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
                        onBook={() =>
                          setBooking({ type: "adventure", item: a })
                        }
                      />
                    ))}
                  </div>
                ) : (
                  <EmptyState
                    icon="\ud83c\udfd4\ufe0f"
                    msg="No adventures in this city yet."
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
                    icon="\ud83d\ude97"
                    msg="No vehicles in this city yet."
                  />
                ))}

              {tab === "map" && (
                <MapView
                  hotels={hotels}
                  adventures={adventures}
                  center={city}
                />
              )}
            </>
          )}
        </div>
      </div>

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
