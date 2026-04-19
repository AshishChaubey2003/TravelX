import React, { createContext, useState, useContext } from "react";

const AuthContext = createContext();

export function AuthProvider({ children }) {
  const [token, setToken] = useState(localStorage.getItem("tx_token"));
  const [user, setUser] = useState(null);

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
