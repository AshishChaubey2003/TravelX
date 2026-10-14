import React, { createContext, useState, useContext, useEffect } from "react";

const AuthContext = createContext();

// FE-010: pull the minimum identifying claims out of a JWT. simplejwt's
// default payload includes `user_id`, `username`, `exp`, `jti`, `token_type`.
// We only expose fields the UI actually needs for display. Verification is
// NOT done here — this is a hint for rendering "Hi, <username>", not an
// authentication decision. The server validates every request.
// Returns null for any malformed input so a bad token can never crash the
// provider.
function _decodeAccess(token) {
  if (typeof token !== "string" || !token) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    // base64url -> base64
    const padded = parts[1]
      .replace(/-/g, "+")
      .replace(/_/g, "/")
      .padEnd(parts[1].length + ((4 - (parts[1].length % 4)) % 4), "=");
    const payload = JSON.parse(atob(padded));
    const user = {
      id: payload.user_id ?? null,
      username:
        typeof payload.username === "string" ? payload.username : null,
    };
    // Honour the token's own expiry: if it's already expired, treat as
    // no user. Avoids drawing stale "Hi, X" while every API call 401s.
    if (
      typeof payload.exp === "number" &&
      payload.exp * 1000 < Date.now()
    ) {
      return null;
    }
    return user.id === null && user.username === null ? null : user;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(localStorage.getItem("tx_token"));
  const [user, setUser] = useState(() => _decodeAccess(token));

  // Keep `user` in sync with the token across login/logout.
  useEffect(() => {
    setUser(_decodeAccess(token));
  }, [token]);

  const doLogin = (accessToken) => {
    setToken(accessToken);
    localStorage.setItem("tx_token", accessToken);
  };

  const doLogout = () => {
    setToken(null);
    setUser(null);
    localStorage.removeItem("tx_token");
  };

  return (
    <AuthContext.Provider value={{ token, user, doLogin, doLogout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
