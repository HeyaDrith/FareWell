"""Trip maps: the flight path (layovers included) and the hotels near the destination."""
import math

import pydeck as pdk
import streamlit as st

import travel

MAX_HOTEL_KM = 150  # hotels farther than this from the destination airport aren't plotted

ORIGIN_RGB, LAYOVER_RGB, DEST_RGB = [37, 99, 235], [234, 179, 8], [220, 38, 38]
HOTEL_RGB, RECOMMENDED_RGB, PICKED_RGB = [100, 116, 139], [234, 179, 8], [22, 163, 74]


def flight_path(route: list[str], origin: str, dest: str) -> list[dict]:
    """Airports to draw in order, from travel.airport_location.

    Uses the listing's route (layovers included) when it matches the searched airports;
    otherwise (sample data, or a route Google reported differently) a direct origin→dest
    line. Empty when an airport isn't in the table, so the map never draws a wrong path.
    """
    codes = route if route and route[0] == origin and route[-1] == dest else [origin, dest]
    stops = [travel.airport_location(code) for code in codes]
    return stops if len(stops) >= 2 and all(stops) else []


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def hotel_points(hotels: list[dict], dest: dict | None, picked: set[str], recommended: str | None) -> list[dict]:
    """Map points for hotels that have coordinates and are near the destination airport."""
    points = []
    for h in hotels:
        lat, lon = h.get("lat"), h.get("lon")
        if lat is None or lon is None:
            continue
        if dest and distance_km(lat, lon, dest["lat"], dest["lon"]) > MAX_HOTEL_KM:
            continue
        status = "picked" if h["name"] in picked else "recommended" if h["name"] == recommended else ""
        color = {"picked": PICKED_RGB, "recommended": RECOMMENDED_RGB}.get(status, HOTEL_RGB)
        points.append({"position": [lon, lat], "color": color, "status": status,
                       "label": f"{h['name']} · ${h['total']:,.0f} total · {h['rating']}★"
                                + {"picked": " · in your trip", "recommended": " · recommended"}.get(status, "")})
    return points


MAP_HEIGHT = 360
_FIT_WIDTH, _FIT_PADDING = 560, 48  # conservative chart width (it stretches wider); edge margin


def _view(positions: list[list[float]], max_zoom: float) -> pdk.ViewState:
    """Center and zoom that fit every [lon, lat] inside the chart, in Web Mercator.

    (pydeck's compute_view assumes a square viewport, which cuts off tall routes in a
    wide, short chart.) Routes over the date line are fit across it, not around the world.
    """
    lons, lats = [p[0] for p in positions], [p[1] for p in positions]
    if max(lons) - min(lons) > 180:
        lons = [lon + 360 if lon < 0 else lon for lon in lons]
    if len(positions) == 1:
        return pdk.ViewState(latitude=lats[0], longitude=lons[0], zoom=min(11, max_zoom))

    def mercator_y(lat: float) -> float:
        lat = max(-85.0, min(85.0, lat))
        return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))

    x_span = (max(lons) - min(lons)) / 360
    y_span = (mercator_y(max(lats)) - mercator_y(min(lats))) / (2 * math.pi)
    fits = [math.log2((size - 2 * _FIT_PADDING) / (512 * span))
            for size, span in ((_FIT_WIDTH, x_span), (MAP_HEIGHT, y_span)) if span > 0]
    zoom = max(1.0, min(fits + [max_zoom]))
    mid_y = (mercator_y(max(lats)) + mercator_y(min(lats))) / 2
    center_lat = math.degrees(2 * math.atan(math.exp(mid_y)) - math.pi / 2)
    center_lon = (max(lons) + min(lons)) / 2
    center_lon = center_lon - 360 if center_lon > 180 else center_lon
    return pdk.ViewState(latitude=round(center_lat, 4), longitude=round(center_lon, 4), zoom=round(zoom, 2))


def _airport_layers(stops: list[dict]) -> list[pdk.Layer]:
    rows = [{"position": [s["lon"], s["lat"]], "code": s["code"],
             # A lone airport (the hotels map) is the destination.
             "color": DEST_RGB if i == len(stops) - 1 else ORIGIN_RGB if i == 0 else LAYOVER_RGB,
             "label": f"{s['code']} · {s['city']}" + (" (layover)" if 0 < i < len(stops) - 1 else "")}
            for i, s in enumerate(stops)]
    # Dots only: Streamlit's deck.gl TextLayer draws empty labels in some browsers, so the
    # airport codes are in the hover tooltip and the caption under the map instead.
    return [pdk.Layer("ScatterplotLayer", rows, get_position="position", get_fill_color="color",
                      radius_min_pixels=6, radius_max_pixels=10, pickable=True,
                      stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=1)]


def render(flight_label: str, stops: list[dict], hotels_on_map: list[dict], place: str):
    """Two tabs: the selected flight's path, and the hotels around the destination."""
    path_tab, hotel_tab = st.tabs(["✈️ Flight path", "🏨 Hotels on the map"])
    with path_tab:
        if not stops:
            st.caption("No map for this route: one of the airports isn't in the airport list.")
        else:
            arcs = [{"from": [a["lon"], a["lat"]], "to": [b["lon"], b["lat"]], "label": f"{a['code']} → {b['code']}"}
                    for a, b in zip(stops, stops[1:])]
            layers = [pdk.Layer("ArcLayer", arcs, get_source_position="from", get_target_position="to",
                                get_source_color=ORIGIN_RGB, get_target_color=DEST_RGB, get_width=4,
                                great_circle=True, pickable=True)] + _airport_layers(stops)
            view = _view([[s["lon"], s["lat"]] for s in stops], max_zoom=8)
            st.pydeck_chart(pdk.Deck(layers=layers, map_style="light", initial_view_state=view, tooltip={"text": "{label}"}),
                            height=MAP_HEIGHT)
            layovers = [s["code"] for s in stops[1:-1]]
            st.caption(f"{flight_label}: {' → '.join(s['code'] for s in stops)}"
                       + (f" (layover in {', '.join(layovers)})" if layovers else " (nonstop)")
                       + ". Arcs show the outbound trip.")
    with hotel_tab:
        if not hotels_on_map:
            st.caption("No hotel locations to show for this search.")
        else:
            dest = stops[-1] if stops else None
            layers = [pdk.Layer("ScatterplotLayer", hotels_on_map, get_position="position", get_fill_color="color",
                                radius_min_pixels=7, radius_max_pixels=12, pickable=True,
                                stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=1)]
            positions = [p["position"] for p in hotels_on_map]
            if dest:
                layers += _airport_layers([dest])
                positions.append([dest["lon"], dest["lat"]])
            st.pydeck_chart(pdk.Deck(layers=layers, map_style="light", initial_view_state=_view(positions, max_zoom=13),
                                     tooltip={"text": "{label}"}), height=MAP_HEIGHT)
            st.caption(f"Hotels near {place}: 🟢 in your trip · 🟡 recommended · ⚪ other options. "
                       "Hover a dot for its price and rating.")
