import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { getCities } from "../api";
import CityCard from "../components/CityCard";
import AIChat from "../components/AIChat";

export default function Home() {
  const [cities, setCities] = useState([]);
  const [search, setSearch] = useState("");
  const [selectedCity, setSelectedCity] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    loadCities();
  }, []);

  const loadCities = async () => {
    try {
      const { data } = await getCities();
      setCities(data.results || []);
    } catch {
      console.error("Failed to load cities");
    }
  };

  const filtered = cities.filter((c) =>
    c.name.toLowerCase().includes(search.toLowerCase()),
  );

  const handleCitySelect = (city) => {
    setSelectedCity(city);
    navigate(`/explore?city=${city.id}`);
  };

  const totalHotels = cities.reduce((s, c) => s + c.hotel_count, 0);
  const totalAdvs = cities.reduce((s, c) => s + c.adventure_count, 0);

  return (
    <div style={{ paddingTop: "80px" }}>
      {/* HERO */}
      <section
        style={{
          minHeight: "90vh",
          display: "flex",
          alignItems: "center",
          padding: "4rem 2rem",
          background:
            "radial-gradient(ellipse 80% 60% at 70% 50%, rgba(249,115,22,0.06) 0%, transparent 70%)",
          position: "relative",
          overflow: "hidden",
        }}
      >
        {/* Grid bg */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            opacity: 0.03,
            backgroundImage:
              "linear-gradient(rgba(255,255,255,0.1) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.1) 1px, transparent 1px)",
            backgroundSize: "60px 60px",
          }}
        />

        <div
          style={{
            maxWidth: "1200px",
            margin: "0 auto",
            width: "100%",
            position: "relative",
            zIndex: 1,
          }}
        >
          <div style={{ maxWidth: "650px" }}>
            {/* Badge */}
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.5rem",
                background: "rgba(249,115,22,0.1)",
                border: "1px solid rgba(249,115,22,0.2)",
                padding: "0.35rem 0.875rem",
                borderRadius: "50px",
                fontSize: "0.8rem",
                fontWeight: 500,
                color: "#FB923C",
                marginBottom: "1.5rem",
              }}
            >
              <span
                style={{
                  width: "6px",
                  height: "6px",
                  background: "#F97316",
                  borderRadius: "50%",
                }}
              />
              AI-Powered Travel Platform
            </div>

            <h1
              style={{
                fontFamily: "Syne, sans-serif",
                fontSize: "clamp(2.5rem, 5vw, 4rem)",
                fontWeight: 800,
                lineHeight: 1.05,
                letterSpacing: "-1.5px",
                marginBottom: "1.25rem",
              }}
            >
              Discover India's
              <br />
              <span
                style={{
                  background: "linear-gradient(135deg, #F97316, #F59E0B)",
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                }}
              >
                Hidden Gems
              </span>
              <br />
              with AI ✨
            </h1>

            <p
              style={{
                fontSize: "1.05rem",
                color: "#94A3B8",
                lineHeight: 1.7,
                marginBottom: "2rem",
              }}
            >
              Plan your perfect trip with AI recommendations. Book hotels,
              adventures, and vehicles — all in one place.
            </p>

            {/* Search */}
            <div
              style={{
                display: "flex",
                gap: "0.5rem",
                background: "#141E2E",
                border: "1px solid rgba(255,255,255,0.12)",
                borderRadius: "20px",
                padding: "0.5rem",
                boxShadow: "0 25px 50px rgba(0,0,0,0.5)",
              }}
            >
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search cities — Goa, Manali, Delhi..."
                style={{
                  flex: 1,
                  background: "transparent",
                  border: "none",
                  outline: "none",
                  color: "#F1F5F9",
                  fontSize: "0.95rem",
                  padding: "0.5rem 0.75rem",
                }}
              />
              <button
                onClick={() => {
                  const c = filtered[0];
                  if (c) handleCitySelect(c);
                }}
                style={{
                  padding: "0.625rem 1.5rem",
                  borderRadius: "14px",
                  border: "none",
                  background: "linear-gradient(135deg, #F97316, #EA580C)",
                  color: "white",
                  fontWeight: 600,
                  cursor: "pointer",
                  fontSize: "0.9rem",
                }}
              >
                Explore →
              </button>
            </div>

            {/* Stats */}
            <div style={{ display: "flex", gap: "2rem", marginTop: "2.5rem" }}>
              {[
                { num: cities.length + "+", label: "Cities" },
                { num: totalHotels + "+", label: "Hotels" },
                { num: totalAdvs + "+", label: "Adventures" },
              ].map((s) => (
                <div key={s.label}>
                  <div
                    style={{
                      fontFamily: "Syne, sans-serif",
                      fontSize: "1.5rem",
                      fontWeight: 700,
                    }}
                  >
                    {s.num}
                  </div>
                  <div
                    style={{
                      fontSize: "0.8rem",
                      color: "#64748B",
                      marginTop: "2px",
                    }}
                  >
                    {s.label}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* CITIES */}
      <section style={{ padding: "5rem 2rem", background: "#0D1421" }}>
        <div style={{ maxWidth: "1200px", margin: "0 auto" }}>
          <div style={{ marginBottom: "2.5rem" }}>
            <div
              style={{
                fontSize: "0.75rem",
                fontWeight: 600,
                letterSpacing: "2px",
                textTransform: "uppercase",
                color: "#F97316",
                marginBottom: "0.75rem",
              }}
            >
              Destinations
            </div>
            <h2
              style={{
                fontFamily: "Syne, sans-serif",
                fontSize: "clamp(1.75rem, 3vw, 2.5rem)",
                fontWeight: 700,
                letterSpacing: "-0.5px",
              }}
            >
              Where do you want to go?
            </h2>
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
              gap: "1rem",
            }}
          >
            {filtered.map((c) => (
              <CityCard
                key={c.id}
                city={c}
                selected={selectedCity?.id === c.id}
                onClick={() => handleCitySelect(c)}
              />
            ))}
          </div>
        </div>
      </section>

      {/* AI CHAT */}
      <section id="ai" style={{ padding: "5rem 2rem", background: "#080C14" }}>
        <div style={{ maxWidth: "1200px", margin: "0 auto" }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1.2fr",
              gap: "3rem",
              alignItems: "start",
            }}
          >
            <div>
              <div
                style={{
                  fontSize: "0.75rem",
                  fontWeight: 600,
                  letterSpacing: "2px",
                  textTransform: "uppercase",
                  color: "#F97316",
                  marginBottom: "0.75rem",
                }}
              >
                AI Planner
              </div>
              <h2
                style={{
                  fontFamily: "Syne, sans-serif",
                  fontSize: "clamp(1.75rem, 3vw, 2.5rem)",
                  fontWeight: 700,
                  letterSpacing: "-0.5px",
                  marginBottom: "1rem",
                }}
              >
                Plan your trip with AI
              </h2>
              <p
                style={{
                  color: "#94A3B8",
                  fontSize: "1rem",
                  marginBottom: "2rem",
                }}
              >
                Just tell us what you want — our AI will find the best hotels,
                adventures, and vehicles for you.
              </p>
              {[
                {
                  icon: "🧠",
                  title: "Smart Planning",
                  desc: "AI understands your budget, duration, and preferences.",
                  color: "rgba(249,115,22,0.1)",
                  border: "rgba(249,115,22,0.2)",
                },
                {
                  icon: "📡",
                  title: "Real Data Only",
                  desc: "AI fetches live data from our APIs — no fake results.",
                  color: "rgba(20,184,166,0.1)",
                  border: "rgba(20,184,166,0.2)",
                },
                {
                  icon: "⚡",
                  title: "Instant Booking",
                  desc: "Confirm and AI triggers the booking directly.",
                  color: "rgba(245,158,11,0.1)",
                  border: "rgba(245,158,11,0.2)",
                },
              ].map((f) => (
                <div
                  key={f.title}
                  style={{
                    display: "flex",
                    gap: "1rem",
                    padding: "1rem",
                    background: "#141E2E",
                    border: "1px solid rgba(255,255,255,0.07)",
                    borderRadius: "12px",
                    marginBottom: "0.75rem",
                  }}
                >
                  <div
                    style={{
                      width: "40px",
                      height: "40px",
                      borderRadius: "10px",
                      background: f.color,
                      border: `1px solid ${f.border}`,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: "1.1rem",
                      flexShrink: 0,
                    }}
                  >
                    {f.icon}
                  </div>
                  <div>
                    <div
                      style={{
                        fontWeight: 600,
                        fontSize: "0.9rem",
                        marginBottom: "0.25rem",
                      }}
                    >
                      {f.title}
                    </div>
                    <div
                      style={{
                        fontSize: "0.8rem",
                        color: "#94A3B8",
                        lineHeight: 1.5,
                      }}
                    >
                      {f.desc}
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <AIChat />
          </div>
        </div>
      </section>

      {/* FOOTER */}
      <footer
        style={{
          background: "#0D1421",
          borderTop: "1px solid rgba(255,255,255,0.07)",
          padding: "2rem",
          textAlign: "center",
        }}
      >
        <div
          style={{
            fontFamily: "Syne, sans-serif",
            fontSize: "1.2rem",
            fontWeight: 800,
            background: "linear-gradient(135deg, #F97316, #F59E0B)",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            marginBottom: "0.5rem",
          }}
        >
          ✈ TravelX
        </div>
        <div style={{ fontSize: "0.8rem", color: "#64748B" }}>
          © 2026 TravelX. Built with Django + React + AI ⚡
        </div>
      </footer>
    </div>
  );
}
