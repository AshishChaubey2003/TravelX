import React from "react";
import { Link } from "react-router-dom";

// TravelX logo — mountain + sun icon with "Travel" + teal "X" wordmark.
// Usage: <Logo />  or  <Logo size={22} />
export default function Logo({ size = 24, to = "/" }) {
  const icon = (
    <svg
      width={size * 1.5}
      height={size * 1.5}
      viewBox="0 0 72 72"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      style={{ flexShrink: 0 }}
    >
      {/* sun */}
      <circle cx="50" cy="20" r="8" fill="#2DD4BF" />
      {/* mountain (white so it shows on dark bg) */}
      <path d="M4 60 L26 24 L40 44 L48 34 L68 60 Z" fill="#F1F6FB" />
      {/* teal front slope */}
      <path
        d="M26 24 L40 44 L33 44 L26 33 L16 48 L9 48 Z"
        fill="#2DD4BF"
        opacity="0.85"
      />
    </svg>
  );

  const wordmark = (
    <span
      style={{
        fontFamily: "'Plus Jakarta Sans', Sora, sans-serif",
        fontWeight: 800,
        fontSize: `${size}px`,
        letterSpacing: "-0.5px",
        color: "#F1F6FB",
        lineHeight: 1,
      }}
    >
      Travel<span style={{ color: "#2DD4BF" }}>X</span>
    </span>
  );

  const content = (
    <span style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}>
      {icon}
      {wordmark}
    </span>
  );

  // If used inside nav, wrap in Link; otherwise just render
  return to ? (
    <Link to={to} style={{ textDecoration: "none" }}>
      {content}
    </Link>
  ) : (
    content
  );
}
