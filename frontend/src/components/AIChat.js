import React, { useState, useRef, useEffect } from "react";
import toast from "react-hot-toast";
import { planTrip } from "../api";

export default function AIChat() {
  const [messages, setMessages] = useState([
    {
      from: "ai",
      text: "Hey! 👋 I'm your AI travel planner. Tell me where you want to go and your budget — I'll plan the perfect trip!",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const messagesRef = useRef(null);

  useEffect(() => {
    if (messagesRef.current)
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
  }, [messages]);

  const sendMsg = async () => {
    if (!input.trim() || loading) return;
    const userMsg = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { from: "user", text: userMsg }]);
    setLoading(true);

    try {
      const { data } = await planTrip(userMsg);
      setMessages((prev) => [
        ...prev,
        {
          from: "ai",
          text: data.response || data.output || "Here is your plan!",
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          from: "ai",
          text: "AI service is being configured. Meanwhile, browse cities and hotels above! 🗺️",
        },
      ]);
    }
    setLoading(false);
  };

  const suggestions = [
    "Plan Goa trip under ₹10k",
    "Best hotels in Manali",
    "Adventure in Rishikesh",
  ];

  return (
    <div
      style={{
        background: "#141E2E",
        border: "1px solid rgba(255,255,255,0.12)",
        borderRadius: "20px",
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "1rem 1.25rem",
          borderBottom: "1px solid rgba(255,255,255,0.07)",
          display: "flex",
          alignItems: "center",
          gap: "0.75rem",
        }}
      >
        <div
          style={{
            width: "36px",
            height: "36px",
            borderRadius: "10px",
            background: "linear-gradient(135deg, #F97316, #F59E0B)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: "1rem",
          }}
        >
          🤖
        </div>
        <div>
          <div style={{ fontWeight: 600, fontSize: "0.9rem" }}>TravelX AI</div>
          <div style={{ fontSize: "0.75rem", color: "#10B981" }}>● Online</div>
        </div>
      </div>

      {/* Messages */}
      <div
        ref={messagesRef}
        style={{
          height: "300px",
          overflowY: "auto",
          padding: "1.25rem",
          display: "flex",
          flexDirection: "column",
          gap: "1rem",
        }}
      >
        {messages.map((msg, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              gap: "0.75rem",
              flexDirection: msg.from === "user" ? "row-reverse" : "row",
            }}
          >
            <div
              style={{
                width: "30px",
                height: "30px",
                borderRadius: "8px",
                background:
                  msg.from === "ai"
                    ? "linear-gradient(135deg, #F97316, #F59E0B)"
                    : "#1A2540",
                border: "1px solid rgba(255,255,255,0.12)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: "0.8rem",
                flexShrink: 0,
              }}
            >
              {msg.from === "ai" ? "🤖" : "👤"}
            </div>
            <div
              style={{
                padding: "0.75rem 1rem",
                borderRadius: "12px",
                fontSize: "0.875rem",
                lineHeight: 1.55,
                maxWidth: "80%",
                background:
                  msg.from === "ai"
                    ? "#111827"
                    : "linear-gradient(135deg, #F97316, #EA580C)",
                border:
                  msg.from === "ai"
                    ? "1px solid rgba(255,255,255,0.07)"
                    : "none",
                color: msg.from === "ai" ? "#94A3B8" : "white",
              }}
            >
              {msg.text}
            </div>
          </div>
        ))}
        {loading && (
          <div style={{ display: "flex", gap: "0.75rem" }}>
            <div
              style={{
                width: "30px",
                height: "30px",
                borderRadius: "8px",
                background: "linear-gradient(135deg, #F97316, #F59E0B)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: "0.8rem",
              }}
            >
              🤖
            </div>
            <div
              style={{
                padding: "0.75rem 1rem",
                borderRadius: "12px",
                background: "#111827",
                border: "1px solid rgba(255,255,255,0.07)",
                color: "#64748B",
                fontSize: "0.875rem",
              }}
            >
              Thinking... ✨
            </div>
          </div>
        )}
      </div>

      {/* Suggestions */}
      <div
        style={{
          padding: "0 1.25rem 0.75rem",
          display: "flex",
          gap: "0.5rem",
          flexWrap: "wrap",
        }}
      >
        {suggestions.map((s) => (
          <button
            key={s}
            onClick={() => {
              setInput(s);
            }}
            style={{
              padding: "0.35rem 0.75rem",
              borderRadius: "20px",
              background: "#111827",
              border: "1px solid rgba(255,255,255,0.07)",
              fontSize: "0.75rem",
              color: "#94A3B8",
              cursor: "pointer",
            }}
          >
            {s}
          </button>
        ))}
      </div>

      {/* Input */}
      <div
        style={{
          padding: "1rem 1.25rem",
          borderTop: "1px solid rgba(255,255,255,0.07)",
          display: "flex",
          gap: "0.75rem",
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && sendMsg()}
          placeholder="Ask me anything about your trip..."
          style={{
            flex: 1,
            background: "#111827",
            border: "1px solid rgba(255,255,255,0.12)",
            borderRadius: "10px",
            padding: "0.75rem 1rem",
            color: "#F1F5F9",
            fontSize: "0.875rem",
            outline: "none",
          }}
        />
        <button
          onClick={sendMsg}
          style={{
            width: "42px",
            height: "42px",
            borderRadius: "10px",
            background: "linear-gradient(135deg, #F97316, #EA580C)",
            border: "none",
            cursor: "pointer",
            fontSize: "1rem",
          }}
        >
          ➤
        </button>
      </div>
    </div>
  );
}
