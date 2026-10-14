import React from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { protectedRouteDecision } from "./protectedRouteDecision";

/**
 * FE-011: Gate for routes that require an authenticated user.
 *
 * If the user is not logged in, they are redirected to home with
 * `location.state.needAuth = true`. Home can read that flag to open
 * the login modal automatically. `location.state.from` carries the FULL
 * react-router location object (same as before the FE-019 refactor), so
 * a future redirect-back flow has everything it needs.
 *
 * The decision itself lives in protectedRouteDecision.js (pure, unit
 * tested); this wrapper only wires the router + auth context into it.
 * The gate uses the AuthContext token, not localStorage, so a token
 * removed by the api.js 401 interceptor at least blocks the next
 * navigation. (The full state-sync fix is FE-003.)
 */
export default function ProtectedRoute({ children }) {
  const { token } = useAuth();
  const location = useLocation();

  const decision = protectedRouteDecision({
    token,
    pathname: location.pathname,
  });

  if (decision.action === "redirect") {
    return (
      <Navigate
        to={decision.to}
        // Spread the predicate's state first, then override `from` with the
        // full location object — byte-identical Navigate state to the
        // pre-refactor component ({ from: location, needAuth: true }).
        state={{ ...decision.state, from: location }}
        replace
      />
    );
  }
  return children;
}
