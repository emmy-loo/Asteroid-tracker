import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from dotenv import load_dotenv


# --------------------------------------------------
# 1. Configuration
# --------------------------------------------------

st.set_page_config(
    page_title="Near-Earth Asteroid Tracker",
    page_icon="☄️",
    layout="wide",
)

st.title("☄️ Near-Earth Asteroid Tracker")
st.caption(
    "Explore near-Earth objects tracked by NASA. "
    "Potentially hazardous is an orbital classification, "
    "not a prediction that an asteroid will hit Earth."
)

NASA_URL = "https://api.nasa.gov/neo/rest/v1/feed"
LUNAR_DISTANCE_KM = 384_400

CACHE_DIR = Path("data/asteroid_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv()


def get_api_key():
    """Read the API key from Streamlit Secrets or a local .env file."""

    try:
        key = st.secrets.get("NASA_API_KEY")
    except Exception:
        key = None

    key = key or os.environ.get("NASA_API_KEY")

    if not key:
        raise ValueError(
            "NASA_API_KEY is missing. Add it to your .env file "
            "locally or Streamlit Secrets when deploying."
        )

    return key


# --------------------------------------------------
# 2. Fetch one date chunk and cache it in a CSV
# --------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)
def get_week(start, end):
    """
    Load a date chunk from CSV if available.
    Otherwise, fetch it from NASA and save the results.

    start and end must be YYYY-MM-DD strings.
    """

    cache_file = CACHE_DIR / f"{start}_{end}.csv"

    # Reuse the local CSV
    if cache_file.exists():
        return pd.read_csv(cache_file)

    api_key = get_api_key()

    response = requests.get(
        NASA_URL,
        params={
            "start_date": start,
            "end_date": end,
            "api_key": api_key,
        },
        timeout=30,
    )
    response.raise_for_status()

    payload = response.json()
    objects_by_date = payload.get("near_earth_objects", {})

    rows = []

    for date, objects in objects_by_date.items():
        for obj in objects:
            diameter = obj["estimated_diameter"]["meters"]

            # Some objects may not have close approach data
            approaches = obj.get("close_approach_data", [])

            if not approaches:
                continue

            # Use the first approach in this feed response
            approach = approaches[0]

            rows.append({
                "Name": obj["name"],
                "Approach Date": date,
                "Min Diameter (m)": float(
                    diameter["estimated_diameter_min"]
                ),
                "Max Diameter (m)": float(
                    diameter["estimated_diameter_max"]
                ),
                "Miss Distance (km)": float(
                    approach["miss_distance"]["kilometers"]
                ),
                "Speed (km/h)": float(
                    approach["relative_velocity"]["kilometers_per_hour"]
                ),
                "Hazardous": bool(
                    obj["is_potentially_hazardous_asteroid"]
                ),
            })

    columns = [
        "Name",
        "Approach Date",
        "Min Diameter (m)",
        "Max Diameter (m)",
        "Miss Distance (km)",
        "Speed (km/h)",
        "Hazardous",
    ]

    df = pd.DataFrame(rows, columns=columns)

    # Save only after a successful API response and parsing
    temp_file = cache_file.with_suffix(".tmp")
    df.to_csv(temp_file, index=False)
    temp_file.replace(cache_file)

    return df


# --------------------------------------------------
# 3. Fetch an arbitrary date range in valid chunks
# --------------------------------------------------

def get_date_range(start_date, end_date):
    """
    NASA NeoWs allows at most 7 days between start and end.
    Each inclusive chunk can therefore contain up to 8 dates.
    """

    if end_date < start_date:
        raise ValueError("End date must be on or after start date.")

    frames = []
    current = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)

    while current <= end:
        chunk_end = min(
            current + pd.Timedelta(days=7),
            end,
        )

        start_string = current.strftime("%Y-%m-%d")
        end_string = chunk_end.strftime("%Y-%m-%d")

        frames.append(get_week(start_string, end_string))

        # Move to the next date so no dates are duplicated
        current = chunk_end + pd.Timedelta(days=1)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------
# 4. Date selection
# --------------------------------------------------

today = pd.Timestamp.now().normalize().date()

col1, col2 = st.columns(2)

with col1:
    start_date = st.date_input(
        "Start date",
        value=today,
    )

with col2:
    end_date = st.date_input(
        "End date",
        value=today + pd.Timedelta(days=6),
    )


# --------------------------------------------------
# 5. Fetch and display the dashboard
# --------------------------------------------------

if end_date < start_date:
    st.warning("The end date must be on or after the start date.")

else:
    try:
        with st.spinner("Loading asteroid data..."):
            df = get_date_range(start_date, end_date)

        if df.empty:
            st.info("No asteroid data was found for this date range.")

        else:
            # Add lunar distances
            df["Lunar Distances (LD)"] = (
                df["Miss Distance (km)"] / LUNAR_DISTANCE_KM
            )

            # ------------------------------------------
            # Filters
            # ------------------------------------------

            show_hazardous_only = st.toggle(
                "Show potentially hazardous asteroids only",
                value=False,
            )

            filtered_df = df.copy()

            if show_hazardous_only:
                filtered_df = filtered_df[
                    filtered_df["Hazardous"]
                ].copy()

            # ------------------------------------------
            # Summary metrics
            # ------------------------------------------

            total_objects = len(filtered_df)
            hazardous_count = int(filtered_df["Hazardous"].sum())

            largest_diameter = (
                filtered_df["Max Diameter (m)"].max()
                if not filtered_df.empty
                else 0
            )

            closest_distance = (
                filtered_df["Miss Distance (km)"].min()
                if not filtered_df.empty
                else 0
            )

            m1, m2, m3, m4 = st.columns(4)

            m1.metric("Asteroids shown", f"{total_objects:,}")
            m2.metric("Potentially hazardous", f"{hazardous_count:,}")
            m3.metric("Largest estimated diameter", f"{largest_diameter:,.1f} m")
            m4.metric("Closest approach", f"{closest_distance:,.0f} km")

            st.caption(
                f"Showing {start_date} through {end_date}. "
                "Diameters are estimates, not exact measurements."
            )

            if filtered_df.empty:
                st.info("No asteroids match the selected filter.")

            else:
                # --------------------------------------
                # Sortable asteroid table
                # --------------------------------------

                st.subheader("📋 Asteroid data")

                sorted_df = filtered_df.sort_values(
                    "Max Diameter (m)",
                    ascending=False,
                )

                st.dataframe(
                    sorted_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Min Diameter (m)": st.column_config.NumberColumn(
                            "Min diameter (m)",
                            format="%.2f",
                        ),
                        "Max Diameter (m)": st.column_config.NumberColumn(
                            "Max diameter (m)",
                            format="%.2f",
                        ),
                        "Miss Distance (km)": st.column_config.NumberColumn(
                            "Miss distance (km)",
                            format="%,.0f",
                        ),
                        "Speed (km/h)": st.column_config.NumberColumn(
                            "Relative speed (km/h)",
                            format="%,.0f",
                        ),
                        "Lunar Distances (LD)": st.column_config.NumberColumn(
                            "Lunar distances (LD)",
                            format="%.2f",
                        ),
                    },
                )

                # --------------------------------------
                # Scatter plot with diameter uncertainty
                # --------------------------------------

                st.subheader("📊 Miss distance vs. asteroid size")

                plot_df = filtered_df.copy()

                # Plotly's asymmetric error bars show the estimated
                # minimum-to-maximum diameter interval.
                plot_df["Diameter error below (m)"] = (
                    plot_df["Max Diameter (m)"]
                    - plot_df["Min Diameter (m)"]
                )

                plot_df["Diameter error above (m)"] = 0.0

                fig = px.scatter(
                    plot_df,
                    x="Lunar Distances (LD)",
                    y="Max Diameter (m)",
                    color="Hazardous",
                    hover_name="Name",
                    hover_data={
                        "Approach Date": True,
                        "Min Diameter (m)": ":.2f",
                        "Max Diameter (m)": ":.2f",
                        "Miss Distance (km)": ":,.0f",
                        "Speed (km/h)": ":,.0f",
                        "Lunar Distances (LD)": ":.2f",
                        "Hazardous": True,
                    },
                    error_y="Diameter error above (m)",
                    error_y_minus="Diameter error below (m)",
                    labels={
                        "Lunar Distances (LD)": "Miss distance (lunar distances)",
                        "Max Diameter (m)": "Estimated diameter (m)",
                        "Hazardous": "Potentially hazardous",
                    },
                    title="Asteroid size estimates and approach distances",
                )

                fig.update_layout(
                    legend_title_text="Potentially hazardous",
                    hovermode="closest",
                )

                st.plotly_chart(fig, use_container_width=True)

                st.caption(
                    "Diameter error bars represent the estimated range "
                    "from minimum to maximum diameter. The hazardous flag "
                    "does not mean an impact is predicted."
                )

                # --------------------------------------
                # Download filtered data
                # --------------------------------------

                csv_data = sorted_df.to_csv(index=False).encode("utf-8")

                st.download_button(
                    "Download asteroid data as CSV",
                    data=csv_data,
                    file_name="asteroid_tracker.csv",
                    mime="text/csv",
                )

    except requests.RequestException as error:
        st.error(
            f"NASA API request failed: {error}. "
            "Please try again later."
        )

    except (ValueError, KeyError) as error:
        st.error(f"Unable to process asteroid data: {error}")

    except Exception as error:
        st.error(f"Something went wrong: {error}")