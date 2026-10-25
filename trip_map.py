"""Trip maps: the flight path (layovers included) and the hotels near the destination."""
import math

import pydeck as pdk
import streamlit as st

import travel

MAX_HOTEL_KM = 150  # hotels farther than this from the destination airport aren't plotted

ORIGIN_RGB, LAYOVER_RGB, DEST_RGB = [22, 163, 74], [234, 179, 8], [220, 38, 38]  # start green, end red
ROUTE_RGB = [14, 124, 196]
HOTEL_RGB, RECOMMENDED_RGB, PICKED_RGB = [100, 116, 139], [234, 179, 8], [22, 163, 74]
# Flat, north-up maps: no tilting or spinning by drag, so a route never looks skewed.
_FLAT_VIEW = pdk.View(type="MapView", controller={"dragRotate": False, "touchRotate": False}, repeat=True)


def flight_path(route: list[str], origin: str, dest: str) -> list[dict]:
    """Airports to draw in order, from travel.airport_location.

    Uses the listing's route (layovers included) when it matches the searched airports;
    otherwise (sample data, or a route Google reported differently) a direct origin→dest
    line. Empty when an airport isn't in the table, so the map never draws a wrong path.
    """
    codes = route if route and route[0] == origin and route[-1] == dest else [origin, dest]
    stops = [travel.airport_location(code) for code in codes]
    return stops if len(stops) >= 2 and all(stops) else []


def esc_md(text: str) -> str:
    """Escape "$" for markdown captions (city names come from the airport table)."""
    return str(text).replace("$", "\\$")


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


def _mercator_y(lat: float) -> float:
    """Web Mercator y in degree-like units, so arrow shapes aren't squashed near the poles."""
    lat = max(-85.0, min(85.0, lat))
    return math.degrees(math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


def _lat_from_y(y: float) -> float:
    return math.degrees(2 * math.atan(math.exp(math.radians(y))) - math.pi / 2)


def route_geometry(stops: list[dict]) -> dict:
    """Straight legs between airports, with an arrowhead on each pointing the way you fly.

    Longitudes are made continuous from the first airport, so a route over the date line
    draws across the Pacific instead of around the world. Returns
    {"positions": [[lon, lat], ...], "legs": [{"path", "label"}], "arrows": [{"polygon", "label"}]}.
    """
    positions = []
    for s in stops:
        lon = s["lon"]
        if positions:
            while lon - positions[-1][0] > 180:
                lon -= 360
            while lon - positions[-1][0] < -180:
                lon += 360
        positions.append([lon, s["lat"]])

    xs = [p[0] for p in positions]
    ys = [_mercator_y(p[1]) for p in positions]
    size = max(max(xs) - min(xs), max(ys) - min(ys), 1) * 0.04  # one arrow size for the whole map
    legs, arrows = [], []
    for i, (a, b) in enumerate(zip(stops, stops[1:])):
        label = f"{a['code']} → {b['code']}"
        legs.append({"path": [positions[i], positions[i + 1]], "label": label})
        (x1, y1), (x2, y2) = (xs[i], ys[i]), (xs[i + 1], ys[i + 1])
        length = math.hypot(x2 - x1, y2 - y1)
        if length < size * 2.5:  # too short to fit an arrow (e.g. a hop to a nearby airport)
            continue
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        tip_x, tip_y = x1 + ux * length * 0.58, y1 + uy * length * 0.58
        base_x, base_y = tip_x - ux * size, tip_y - uy * size
        corners = [(tip_x, tip_y), (base_x - uy * size * 0.62, base_y + ux * size * 0.62),
                   (base_x + uy * size * 0.62, base_y - ux * size * 0.62)]
        arrows.append({"polygon": [[x, round(_lat_from_y(y), 5)] for x, y in corners], "label": label})
    return {"positions": positions, "legs": legs, "arrows": arrows}


def _airport_layers(stops: list[dict], positions: list[list[float]] | None = None) -> list[pdk.Layer]:
    """Airport markers: green start, amber layovers, red end (a lone airport is the destination)."""
    positions = positions or [[s["lon"], s["lat"]] for s in stops]
    last = len(stops) - 1
    rows = []
    for i, (s, pos) in enumerate(zip(stops, positions)):
        role = "End" if i == last else "Start" if i == 0 else "Layover"
        rows.append({"position": pos, "code": s["code"], "role": role,
                     "color": {"Start": ORIGIN_RGB, "End": DEST_RGB}.get(role, LAYOVER_RGB),
                     "radius": 6 if role == "Layover" else 9,
                     "label": f"{role}: {s['code']} · {s['city']}"})
    ends = [dict(r, color=r["color"] + [70]) for r in rows if r["role"] != "Layover"]
    # Dots only: Streamlit's deck.gl TextLayer draws empty labels in some browsers, so the
    # airport codes are in the hover tooltip and the legend under the map instead.
    return [pdk.Layer("ScatterplotLayer", rows, get_position="position", get_fill_color="color",
                      get_radius="radius", radius_units="pixels", pickable=True,
                      stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=3),
            pdk.Layer("ScatterplotLayer", ends, get_position="position", get_fill_color="color",
                      get_radius=14, radius_units="pixels")]  # soft halo on the start and the end


def render(flight_label: str, stops: list[dict], hotels_on_map: list[dict], place: str):
    """Two tabs: the selected flight's path, and the hotels around the destination."""
    path_tab, hotel_tab = st.tabs(["✈️ Flight path", "🏨 Hotels on the map"])
    with path_tab:
        if not stops:
            st.caption("No map for this route: one of the airports isn't in the airport list.")
        else:
            shape = route_geometry(stops)
            dots, halos = _airport_layers(stops, shape["positions"])
            layers = [
                # A white casing under the route keeps it readable over coastlines and borders.
                pdk.Layer("PathLayer", shape["legs"], get_path="path", get_color=[255, 255, 255],
                          get_width=8, width_units="pixels", cap_rounded=True),
                pdk.Layer("PathLayer", shape["legs"], get_path="path", get_color=ROUTE_RGB,
                          get_width=4, width_units="pixels", cap_rounded=True, pickable=True),
                pdk.Layer("PolygonLayer", shape["arrows"], get_polygon="polygon", get_fill_color=ROUTE_RGB,
                          get_line_color=[255, 255, 255], line_width_min_pixels=1, stroked=True),
                halos, dots]
            view = _view(shape["positions"], max_zoom=8)
            st.pydeck_chart(pdk.Deck(layers=layers, views=[_FLAT_VIEW], map_style="light", initial_view_state=view,
                                     tooltip={"text": "{label}"}), height=MAP_HEIGHT)
            layovers = [s["code"] for s in stops[1:-1]]
            start, end = stops[0], stops[-1]
            st.caption(f"{flight_label}: {' → '.join(s['code'] for s in stops)}"
                       + (f" (layover in {', '.join(layovers)})" if layovers else " (nonstop)") + ".  \n"
                       + f"🟢 **Start** {start['code']} · {esc_md(start['city'])}"
                       + (f"  →  🟡 {', '.join(layovers)}" if layovers else "")
                       + f"  →  🔴 **End** {end['code']} · {esc_md(end['city'])}. Arrows point the way you fly.")
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
                dots, halos = _airport_layers([dest])
                layers += [halos, dots]
                positions.append([dest["lon"], dest["lat"]])
            st.pydeck_chart(pdk.Deck(layers=layers, views=[_FLAT_VIEW], map_style="light",
                                     initial_view_state=_view(positions, max_zoom=13),
                                     tooltip={"text": "{label}"}), height=MAP_HEIGHT)
            st.caption(f"Hotels near {place}: 🟢 in your trip · 🟡 recommended · ⚪ other options. "
                       "Hover a dot for its price and rating.")
