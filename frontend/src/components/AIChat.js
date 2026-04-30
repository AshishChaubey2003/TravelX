import React, { useState, useRef, useEffect } from "react";
import { planTrip } from "../api";

export default function AIChat() {
  const [messages, setMessages] = useState([
    {
      from: "ai",
      text: "Hey! 👋 I'm your AI travel planner. Tell me where you want to go and your budget — I'll plan the perfect trip!",
      options: [
        {
          label: "Plan Goa trip under ₹10k",
          value: "Plan Goa trip under ₹10k",
        },
        { label: "Best hotels in Manali", value: "Plan Manali trip" },
        { label: "Adventure in Jaipur", value: "Plan Jaipur trip" },
      ],
      type: "options",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [session, setSession] = useState({ step: "initial" });
  const messagesRef = useRef(null);

  useEffect(() => {
    if (messagesRef.current)
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
  }, [messages]);

  const sendMsg = async (text, optionName, optionPrice) => {
    const userMsg = text || input.trim();
    if (!userMsg || loading) return;
    setInput("");

    setMessages((prev) => [
      ...prev,
      { from: "user", text: optionName || userMsg },
    ]);
    setLoading(true);

    try {
      const { data } = await planTrip({
        query: userMsg,
        session: {
          ...session,
          option_name: optionName,
          option_price: optionPrice,
        },
      });

      setSession(data.session || { step: "initial" });

      if (userMsg === "restart") {
        setSession({ step: "initial" });
        setMessages([
          {
            from: "ai",
            text: "Hey! 👋 Where would you like to go next?",
            options: [
              { label: "Plan Goa trip", value: "Plan Goa trip" },
              { label: "Plan Manali trip", value: "Plan Manali trip" },
              { label: "Plan Jaipur trip", value: "Plan Jaipur trip" },
            ],
            type: "options",
          },
        ]);
        setLoading(false);
        return;
      }

      setMessages((prev) => [
        ...prev,
        {
          from: "ai",
          text: data.response,
          options: data.options || [],
          type: data.type || "text",
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          from: "ai",
          text: "AI service error. Please try again! 🔄",
          options: [],
          type: "text",
        },
      ]);
    }
    setLoading(false);
  };

  const renderText = (text) => {
    return text.split("\n").map((line, i) => {
      const bold = line.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
      return (
        <div key={i} dangerouslySetInnerHTML={{ __html: bold || "&nbsp;" }} />
      );
    });
  };

  return (
    <div
      style={{
        background: "#141E2E",
        border: "1px solid rgba(255,255,255,0.12)",
        borderRadius: "20px",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        height: "520px",
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
          background: "#0D1421",
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
        <button
          onClick={() => {
            setSession({ step: "initial" });
            setMessages([
              {
                from: "ai",
                text: "Hey! 👋 Where would you like to go?",
                options: [],
                type: "text",
              },
            ]);
          }}
          style={{
            marginLeft: "auto",
            background: "transparent",
            border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: "8px",
            color: "#64748B",
            padding: "0.25rem 0.75rem",
            cursor: "pointer",
            fontSize: "0.75rem",
          }}
        >
          🔄 Reset
        </button>
      </div>

      {/* Messages */}
      <div
        ref={messagesRef}
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "1.25rem",
          display: "flex",
          flexDirection: "column",
          gap: "1rem",
        }}
      >
        {messages.map((msg, i) => (
          <div key={i}>
            <div
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
                  lineHeight: 1.65,
                  maxWidth: "85%",
                  background:
                    msg.from === "ai"
                      ? "#111827"
                      : "linear-gradient(135deg, #F97316, #EA580C)",
                  border:
                    msg.from === "ai"
                      ? "1px solid rgba(255,255,255,0.07)"
                      : "none",
                  color: msg.from === "ai" ? "#CBD5E1" : "white",
                }}
              >
                {renderText(msg.text)}
              </div>
            </div>

            {/* Option Buttons */}
            {msg.from === "ai" &&
              msg.options &&
              msg.options.length > 0 &&
              i === messages.length - 1 &&
              !loading && (
                <div
                  style={{
                    marginTop: "0.75rem",
                    marginLeft: "42px",
                    display: "flex",
                    flexWrap: "wrap",
                    gap: "0.5rem",
                  }}
                >
                  {msg.options.map((opt, j) => (
                    <button
                      key={j}
                      onClick={() => sendMsg(opt.value, opt.label, opt.price)}
                      style={{
                        padding: "0.5rem 1rem",
                        borderRadius: "20px",
                        background: "#1A2540",
                        border: "1px solid rgba(249,115,22,0.3)",
                        color: "#FB923C",
                        fontSize: "0.8rem",
                        cursor: "pointer",
                        fontWeight: 500,
                        transition: "all 0.2s",
                      }}
                      onMouseEnter={(e) =>
                        (e.target.style.background = "rgba(249,115,22,0.15)")
                      }
                      onMouseLeave={(e) =>
                        (e.target.style.background = "#1A2540")
                      }
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              )}
          </div>
        ))}

        {loading && (
          <div
            style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}
          >
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
                display: "flex",
                gap: "4px",
                alignItems: "center",
              }}
            >
              <span style={{ animation: "pulse 1s infinite" }}>●</span>
              <span style={{ animation: "pulse 1s infinite 0.2s" }}>●</span>
              <span style={{ animation: "pulse 1s infinite 0.4s" }}>●</span>
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div
        style={{
          padding: "1rem 1.25rem",
          borderTop: "1px solid rgba(255,255,255,0.07)",
          display: "flex",
          gap: "0.75rem",
          background: "#0D1421",
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && sendMsg()}
          placeholder="Ask me anything about your trip..."
          style={{
            flex: 1,
            background: "#141E2E",
            border: "1px solid rgba(255,255,255,0.12)",
            borderRadius: "10px",
            padding: "0.75rem 1rem",
            color: "#F1F5F9",
            fontSize: "0.875rem",
            outline: "none",
          }}
        />
        <button
          onClick={() => sendMsg()}
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
