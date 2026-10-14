/**
 * Regression tests for AuthContext (FE-010).
 *
 * These are the first real frontend tests in the project — adding
 * src/setupTests.js wires @testing-library/jest-dom into every Jest run
 * started by react-scripts. Running `npm test -- --watchAll=false` with
 * this file present should now report 1 test file / 4 passing cases.
 *
 * What's covered:
 *  - A malformed access token must NOT crash the provider: `user` stays null.
 *  - A valid access token populates `user.id` / `user.username` from the
 *    JWT payload.
 *  - A token whose `exp` claim is already in the past is treated as no
 *    user, so the UI never shows a stale "Hi, X" while every API call
 *    400s.
 *  - doLogout clears user back to null.
 */
import React from "react";
import { act, render } from "@testing-library/react";
import { AuthProvider, useAuth } from "./AuthContext";

// Build a token with ONLY the payload field we care about. react-scripts
// uses jest-environment-jsdom which provides `atob`.
function _b64url(obj) {
  return btoa(JSON.stringify(obj)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
}
function makeToken(payload) {
  return `${_b64url({ alg: "HS256", typ: "JWT" })}.${_b64url(payload)}.sig`;
}

function Probe({ onReady }) {
  const auth = useAuth();
  React.useEffect(() => {
    onReady(auth);
  }, [auth, onReady]);
  return null;
}

function renderWithProvider() {
  let seen = null;
  const onReady = (auth) => {
    seen = auth;
  };
  render(
    <AuthProvider>
      <Probe onReady={onReady} />
    </AuthProvider>
  );
  return () => seen;
}

beforeEach(() => {
  try {
    localStorage.clear();
  } catch (e) {
    /* noop */
  }
});

test("malformed token does not crash the provider; user is null", () => {
  localStorage.setItem("tx_token", "not-a-jwt");
  const get = renderWithProvider();
  const auth = get();
  expect(auth.token).toBe("not-a-jwt");
  expect(auth.user).toBeNull();
});

test("valid token populates user fields from payload", () => {
  const future = Math.floor(Date.now() / 1000) + 3600;
  const token = makeToken({
    user_id: 42,
    username: "ashish01",
    exp: future,
    token_type: "access",
  });
  localStorage.setItem("tx_token", token);
  const get = renderWithProvider();
  const auth = get();
  expect(auth.user).not.toBeNull();
  expect(auth.user.id).toBe(42);
  expect(auth.user.username).toBe("ashish01");
});

test("expired token is treated as no user", () => {
  const past = Math.floor(Date.now() / 1000) - 60;
  const token = makeToken({
    user_id: 99,
    username: "x",
    exp: past,
  });
  localStorage.setItem("tx_token", token);
  const get = renderWithProvider();
  const auth = get();
  expect(auth.user).toBeNull();
});

test("doLogout clears user back to null", async () => {
  const future = Math.floor(Date.now() / 1000) + 3600;
  const token = makeToken({ user_id: 1, username: "u", exp: future });
  localStorage.setItem("tx_token", token);
  const get = renderWithProvider();
  const auth = get();
  expect(auth.user).not.toBeNull();
  await act(async () => {
    auth.doLogout();
  });
  const after = get();
  expect(after.token).toBeNull();
  expect(after.user).toBeNull();
});
