import React, { useEffect } from "react";
import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: require("leaflet/dist/images/marker-icon-2x.png"),
  iconUrl: require("leaflet/dist/images/marker-icon.png"),
  shadowUrl: require("leaflet/dist/images/marker-shadow.png"),
});

const orangeIcon = new L.Icon({
  iconUrl:
    "https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-orange.png",
  shadowUrl:
    "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
});

export default function MapView({ hotels, adventures, center }) {
  const mapCenter = center
    ? [+center.latitude, +center.longitude]
    : [20.5937, 78.9629];

  return (
    <div
      style={{
        borderRadius: "20px",
        overflow: "hidden",
        border: "1px solid rgba(255,255,255,0.12)",
        height: "450px",
      }}
    >
      <MapContainer
        center={mapCenter}
        zoom={center ? 12 : 5}
        style={{ height: "100%", width: "100%" }}
      >
        <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        {hotels.map(
          (h) =>
            h.latitude &&
            h.longitude && (
              <Marker
                key={h.id}
                position={[+h.latitude, +h.longitude]}
                icon={orangeIcon}
              >
                <Popup>
                  <strong>🏨 {h.name}</strong>
                  <br />₹{Number(h.price_per_night).toLocaleString()}/night
                  <br />⭐ {h.rating}
                </Popup>
              </Marker>
            ),
        )}
        {adventures.map(
          (a) =>
            a.latitude &&
            a.longitude && (
              <Marker key={a.id} position={[+a.latitude, +a.longitude]}>
                <Popup>
                  <strong>🧗 {a.name}</strong>
                  <br />₹{Number(a.price_per_person).toLocaleString()}/person
                  <br />⏱ {a.duration_hours}h
                </Popup>
              </Marker>
            ),
        )}
      </MapContainer>
    </div>
  );
}
