import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { getCities } from "../api";
import Logo from "../components/Logo";
import Reveal from "../components/Reveal";

const HERO_IMGS = [
  "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=1600&q=80",
  "https://images.unsplash.com/photo-1512343879784-a960bf40e7f2?w=1600&q=80",
  "https://images.unsplash.com/photo-1561361513-2d000a50f0dc?w=1600&q=80",
  "https://images.unsplash.com/photo-1477587458883-47145ed94245?w=1600&q=80",
  "https://images.unsplash.com/photo-1626621341517-bbf3d9990a23?w=1600&q=80",
];

const CATEGORY_CARDS = [
  {
    tag: "DEVOTIONAL",
    title: "Spiritual Yatras",
    sub: "Varanasi, Ayodhya, Haridwar — aartis, ghats & darshan",
    img: "https://images.unsplash.com/photo-1561361513-2d000a50f0dc?w=600&q=80",
    color: "#FB923C",
    icon: "🕉️",
  },
  {
    tag: "ADVENTURE",
    title: "Camping & Treks",
    sub: "Rishikesh, Manali, Leh — rafting, camping & mountains",
    img: "https://images.unsplash.com/photo-1530866495561-507c9faab2ed?w=600&q=80",
    color: "#2DD4BF",
    icon: "🏕️",
  },
  {
    tag: "STUDENT SPECIAL",
    title: "Budget Trips",
    sub: "Wallet-friendly packages made for students",
    img: "https://images.unsplash.com/photo-1527631746610-bca00a040d60?w=600&q=80",
    color: "#38BDF8",
    icon: "🎒",
  },
];

export default function Home() {
  const [cities, setCities] = useState([]);
  const [search, setSearch] = useState("");
  const [selectedCity, setSelectedCity] = useState(null);
  const [heroIndex, setHeroIndex] = useState(0);
  const navigate = useNavigate();

  useEffect(() => {
    loadCities();
  }, []);

  useEffect(() => {
    const t = setInterval(() => {
      setHeroIndex((i) => (i + 1) % HERO_IMGS.length);
    }, 4000);
    return () => clearInterval(t);
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

  const doSearch = () => {
    const c = filtered[0];
    if (c) handleCitySelect(c);
  };

  const totalHotels = cities.reduce((s, c) => s + (c.hotel_count || 0), 0);
  const totalAdvs = cities.reduce((s, c) => s + (c.adventure_count || 0), 0);

  return (
    <div>
      {/* ===== HERO ===== */}
      <section
        style={{
          position: "relative",
          minHeight: "660px",
          display: "flex",
          alignItems: "center",
          overflow: "hidden",
          paddingTop: "80px",
          paddingBottom: "2rem",
        }}
      >
        {/* Background slideshow */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            zIndex: 0,
            background: "#0F1E33",
          }}
        >
          {HERO_IMGS.map((img, i) => (
            <div
              key={i}
              style={{
                position: "absolute",
                inset: 0,
                backgroundImage: `url(${img})`,
                backgroundSize: "cover",
                backgroundPosition: "center",
                opacity: i === heroIndex ? 1 : 0,
                transition: "opacity 1.5s ease",
              }}
            />
          ))}
        </div>
        {/* Gradient overlay */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            zIndex: 1,
            background:
              "linear-gradient(95deg, rgba(10,22,40,0.94) 0%, rgba(10,22,40,0.72) 32%, rgba(10,22,40,0.2) 58%, transparent 78%), linear-gradient(to top, rgba(10,22,40,0.85) 0%, transparent 38%)",
          }}
        />

        {/* Mountains Call accent removed */}

        <div
          style={{
            position: "relative",
            zIndex: 2,
            maxWidth: "1240px",
            margin: "0 auto",
            padding: "3rem 2.5rem",
            width: "100%",
          }}
        >
          <div style={{ maxWidth: "640px" }}>
            {/* AI pill */}
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.5rem",
                background: "rgba(45,212,191,0.12)",
                border: "1px solid rgba(45,212,191,0.35)",
                padding: "0.45rem 1rem",
                borderRadius: "50px",
                fontSize: "0.8rem",
                fontWeight: 600,
                color: "#2DD4BF",
                marginBottom: "1.5rem",
              }}
            >
              <span
                style={{
                  width: "7px",
                  height: "7px",
                  background: "#2DD4BF",
                  borderRadius: "50%",
                }}
              />
              AI-powered recommendations
            </div>

            <h1
              style={{
                fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
                fontSize: "clamp(2.4rem, 5vw, 3.8rem)",
                fontWeight: 800,
                lineHeight: 1.05,
                letterSpacing: "-1.5px",
                marginBottom: "1.25rem",
              }}
            >
              Discover India's{" "}
              <span style={{ color: "#2DD4BF" }}>Hidden Gems</span> with AI
            </h1>

            <p
              style={{
                fontSize: "1.1rem",
                color: "#C6D4E4",
                lineHeight: 1.65,
                marginBottom: "2rem",
                maxWidth: "520px",
              }}
            >
              Plan your perfect trip with intelligent recommendations. Book
              hotels, adventures, and vehicles — all in one place.
            </p>

            {/* Search (white pill) */}
            <div
              style={{
                display: "flex",
                gap: "0.5rem",
                maxWidth: "620px",
                background: "rgba(255,255,255,0.94)",
                borderRadius: "50px",
                padding: "0.5rem",
                boxShadow: "0 12px 40px rgba(0,0,0,0.35)",
              }}
            >
              <span
                style={{
                  display: "flex",
                  alignItems: "center",
                  paddingLeft: "1.1rem",
                  color: "#FB923C",
                  fontSize: "1.1rem",
                }}
              >
                📍
              </span>
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && doSearch()}
                placeholder="Search cities — Goa, Manali, Delhi..."
                style={{
                  flex: 1,
                  background: "transparent",
                  border: "none",
                  outline: "none",
                  color: "#0A1628",
                  fontSize: "1rem",
                  padding: "0.75rem",
                }}
              />
              <button
                onClick={doSearch}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "0.5rem",
                  padding: "0.85rem 2rem",
                  borderRadius: "50px",
                  border: "none",
                  background: "#FB923C",
                  color: "white",
                  fontWeight: 700,
                  cursor: "pointer",
                  fontSize: "0.95rem",
                }}
              >
                ✈ Explore
              </button>
            </div>

            {/* Stats */}
            <div
              style={{
                display: "flex",
                gap: "2.5rem",
                marginTop: "2.25rem",
                flexWrap: "wrap",
              }}
            >
              {[
                { icon: "🏙️", num: cities.length + "+", label: "Cities" },
                { icon: "🛏️", num: totalHotels + "+", label: "Hotels" },
                { icon: "⛰️", num: totalAdvs + "+", label: "Adventures" },
              ].map((s) => (
                <div
                  key={s.label}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.75rem",
                  }}
                >
                  <div
                    style={{
                      width: "42px",
                      height: "42px",
                      borderRadius: "12px",
                      background: "rgba(45,212,191,0.12)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: "1.2rem",
                    }}
                  >
                    {s.icon}
                  </div>
                  <div>
                    <div
                      style={{
                        fontFamily:
                          "'Plus Jakarta Sans', system-ui, sans-serif",
                        fontSize: "1.4rem",
                        fontWeight: 800,
                        lineHeight: 1,
                      }}
                    >
                      {s.num}
                    </div>
                    <div style={{ fontSize: "0.8rem", color: "#94A8C0" }}>
                      {s.label}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ===== CATEGORY CARDS ===== */}
      <Reveal>
        <section
          style={{
            padding: "3.5rem 2.5rem 1rem",
            position: "relative",
            overflow: "hidden",
            background:
              "radial-gradient(ellipse 60% 55% at 20% 0%, rgba(45,212,191,0.13) 0%, transparent 58%), radial-gradient(ellipse 55% 55% at 85% 100%, rgba(56,189,248,0.11) 0%, transparent 58%), linear-gradient(180deg, #0A1628 0%, #081019 100%)",
          }}
        >
          <div
            style={{
              position: "absolute",
              inset: 0,
              opacity: 0.5,
              backgroundImage:
                "radial-gradient(rgba(255,255,255,0.06) 1px, transparent 1px)",
              backgroundSize: "26px 26px",
            }}
          />
          <div
            style={{
              maxWidth: "1240px",
              margin: "0 auto",
              position: "relative",
              zIndex: 1,
            }}
          >
            <div
              style={{
                fontSize: "0.75rem",
                fontWeight: 700,
                letterSpacing: "2px",
                textTransform: "uppercase",
                color: "#FB923C",
                marginBottom: "1.25rem",
              }}
            >
              ✨ Plan your kind of trip
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
                gap: "1.25rem",
              }}
            >
              {CATEGORY_CARDS.map((c) => (
                <div
                  key={c.title}
                  style={{
                    position: "relative",
                    height: "300px",
                    borderRadius: "18px",
                    overflow: "hidden",
                    cursor: "pointer",
                    border: "1px solid rgba(255,255,255,0.1)",
                    transition: "transform 0.25s",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.transform = "translateY(-6px)";
                    const img = e.currentTarget.querySelector("img");
                    if (img) img.style.transform = "scale(1.08)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.transform = "translateY(0)";
                    const img = e.currentTarget.querySelector("img");
                    if (img) img.style.transform = "scale(1)";
                  }}
                >
                  <img
                    src={c.img}
                    alt={c.title}
                    loading="lazy"
                    style={{
                      width: "100%",
                      height: "100%",
                      objectFit: "cover",
                      transition: "transform 0.5s",
                    }}
                  />
                  <div
                    style={{
                      position: "absolute",
                      inset: 0,
                      background:
                        "linear-gradient(to top, rgba(8,13,23,0.95) 0%, rgba(8,13,23,0.4) 55%, rgba(8,13,23,0.15) 100%)",
                    }}
                  />
                  <span
                    style={{
                      position: "absolute",
                      top: "12px",
                      left: "12px",
                      background: `${c.color}22`,
                      border: `1px solid ${c.color}66`,
                      color: c.color,
                      fontSize: "10px",
                      fontWeight: 700,
                      letterSpacing: "1px",
                      padding: "4px 10px",
                      borderRadius: "999px",
                    }}
                  >
                    {c.tag}
                  </span>
                  <div
                    style={{
                      position: "absolute",
                      bottom: 0,
                      left: 0,
                      right: 0,
                      padding: "1.5rem",
                    }}
                  >
                    <div
                      style={{
                        fontFamily:
                          "'Plus Jakarta Sans', system-ui, sans-serif",
                        fontWeight: 800,
                        fontSize: "1.45rem",
                        display: "flex",
                        alignItems: "center",
                        gap: "10px",
                      }}
                    >
                      <span>{c.icon}</span> {c.title}
                    </div>
                    <p
                      style={{
                        color: "#C6D4E4",
                        fontSize: "0.92rem",
                        marginTop: "6px",
                      }}
                    >
                      {c.sub}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      </Reveal>

      {/* ===== WHY TRAVELX ===== */}
      <Reveal>
        <section
          style={{
            padding: "5rem 2.5rem",
            position: "relative",
            overflow: "hidden",
            background:
              "radial-gradient(ellipse 60% 55% at 20% 0%, rgba(45,212,191,0.13) 0%, transparent 58%), radial-gradient(ellipse 55% 55% at 85% 100%, rgba(56,189,248,0.11) 0%, transparent 58%), linear-gradient(180deg, #0A1628 0%, #081019 100%)",
          }}
        >
          <div
            style={{
              position: "absolute",
              inset: 0,
              opacity: 0.4,
              backgroundImage:
                "radial-gradient(rgba(255,255,255,0.05) 1px, transparent 1px)",
              backgroundSize: "28px 28px",
            }}
          />
          <div
            style={{
              maxWidth: "1240px",
              margin: "0 auto",
              position: "relative",
              zIndex: 1,
            }}
          >
            <div
              style={{
                fontSize: "0.75rem",
                fontWeight: 700,
                letterSpacing: "2px",
                textTransform: "uppercase",
                color: "#2DD4BF",
                marginBottom: "0.75rem",
              }}
            >
              Why TravelX
            </div>
            <h2
              style={{
                fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
                fontSize: "clamp(1.75rem, 3vw, 2.4rem)",
                fontWeight: 800,
                letterSpacing: "-0.5px",
                marginBottom: "0.75rem",
              }}
            >
              Travel planned intelligently
            </h2>
            <p
              style={{
                color: "#94A8C0",
                fontSize: "1rem",
                maxWidth: "560px",
                marginBottom: "3rem",
              }}
            >
              From spiritual yatras to mountain adventures, TravelX brings
              hotels, experiences and AI-powered planning together — so you
              spend less time planning and more time exploring.
            </p>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
                gap: "1.5rem",
              }}
            >
              {[
                {
                  icon: "✦",
                  title: "AI-powered planning",
                  desc: "Tell us your budget and style — get a personalised itinerary in seconds.",
                  color: "#2DD4BF",
                },
                {
                  icon: "🕉️",
                  title: "Spiritual & adventure",
                  desc: "Devotional yatras and thrilling escapes, thoughtfully planned in one place.",
                  color: "#FB923C",
                },
                {
                  icon: "🛏️",
                  title: "Verified stays",
                  desc: "Handpicked hotels and experiences with real ratings and clear pricing.",
                  color: "#38BDF8",
                },
                {
                  icon: "🔒",
                  title: "Secure booking",
                  desc: "Safe payments via Razorpay — UPI, cards and net banking supported.",
                  color: "#22C55E",
                },
              ].map((f) => (
                <div
                  key={f.title}
                  style={{
                    background: "#0F1E33",
                    border: "1px solid rgba(255,255,255,0.08)",
                    borderRadius: "16px",
                    padding: "1.75rem 1.5rem",
                    transition: "transform 0.25s, border-color 0.25s",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.transform = "translateY(-5px)";
                    e.currentTarget.style.borderColor = "rgba(45,212,191,0.35)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.transform = "translateY(0)";
                    e.currentTarget.style.borderColor =
                      "rgba(255,255,255,0.08)";
                  }}
                >
                  <div
                    style={{
                      width: "46px",
                      height: "46px",
                      borderRadius: "12px",
                      background: `${f.color}1a`,
                      border: `1px solid ${f.color}44`,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: "1.3rem",
                      marginBottom: "1rem",
                    }}
                  >
                    {f.icon}
                  </div>
                  <div
                    style={{
                      fontWeight: 700,
                      fontSize: "1.05rem",
                      marginBottom: "0.5rem",
                    }}
                  >
                    {f.title}
                  </div>
                  <div
                    style={{
                      color: "#94A8C0",
                      fontSize: "0.88rem",
                      lineHeight: 1.6,
                    }}
                  >
                    {f.desc}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      </Reveal>

      {/* ===== FOOTER ===== */}
      <footer
        style={{
          background: "#0A1628",
          borderTop: "1px solid rgba(255,255,255,0.08)",
          padding: "2rem",
          textAlign: "center",
        }}
      >
        <div style={{ marginBottom: "0.5rem", display: "inline-flex" }}>
          <Logo size={20} to={null} />
        </div>
        <div style={{ fontSize: "0.8rem", color: "#64748B" }}>
          © 2026 TravelX. Built with Django + React + AI ⚡
        </div>
      </footer>
    </div>
  );
}
