import hashlib
import json
import os
import re
from datetime import datetime
from html import unescape
from itertools import chain
from pathlib import Path
from urllib import request

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
from sklearn import linear_model


def download_data():
    log_file = Path("workout_log.json")
    if log_file.is_file():
        return
    request.urlretrieve(os.environ["JSON_URL"], "workout_log.json")


colors = ["#ff4e50", "#fc913a", "#f9d62e", "#eae374", "#e2f4c7"][::-1]
color_scale = alt.Scale(range=colors)


@st.cache
def get_data():
    download_data()

    with open("workout_log.json", "r", encoding="utf-8") as f:
        workout_dict = json.load(f)

    rows = list(chain(*workout_dict.values()))
    df = pd.DataFrame(rows)
    df["name"] = df["name"].apply(unescape)
    df["event_time"] = (
        df["event_time"]
        .apply(datetime.fromisoformat)
        .dt.tz_localize("Europe/Copenhagen")
    )
    df["day"] = df["event_time"].dt.day_of_week
    df["hour"] = df["event_time"].dt.hour
    df["week"] = df["event_time"].dt.isocalendar().week
    df["count"] = 1
    return df


@st.cache
def get_workouts():
    workout_dir = Path("wods/txts")
    if not workout_dir.is_dir():
        return []

    results = []
    for file in workout_dir.iterdir():
        if file.suffix != ".txt":
            continue

        week = (int(file.stem.split("-")[1]),)

        day = "unknown"
        content_lines = []
        with file.open("r", encoding="utf-8") as f:
            for line in f:
                match = re.match(r"^(\(\w+\)|Scalering)", line)
                if match:
                    if content_lines:
                        results.append(
                            {"week": week, "day": day, "wod": "\n".join(content_lines)}
                        )
                    day = match.group(0).replace("(", "").replace(")", "")
                    content_lines = []
                    continue
                content_lines.append(line)

    results = pd.DataFrame(results)
    return results


def plot_week_heatmap(data):
    tmp = data[["event_time", "count"]].groupby("event_time").sum().reset_index()
    chart = (
        alt.Chart(tmp, title="Weekly Distribution")
        .mark_rect()
        .encode(
            alt.X(
                "day(event_time)",
                title="Day",
                axis=alt.Axis(values=["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]),
            ),
            alt.Y("hours(event_time)", title="Hour"),
            color=alt.Color("mean(count):Q", scale=color_scale),
            tooltip=[
                alt.Tooltip("day(event_time):O", title="Day"),
                alt.Tooltip("hours(event_time):O", title="Hour"),
                alt.Tooltip(
                    "mean(count):Q", title="Mean Num. Attendees", format=",.2f"
                ),
                alt.Tooltip("count():Q", title="Total sessions"),
            ],
        )
        .properties(width=600, height=300)
    )
    st.altair_chart(chart, use_container_width=True)


def plot_year_heatmap(data):
    tmp = data[["event_time", "count"]].groupby("event_time").sum().reset_index()
    chart = (
        alt.Chart(tmp, title="Year Heatmap")
        .mark_rect()
        .encode(
            alt.X("day(event_time):O", title="Date"),
            alt.Y("month(event_time):O", title="Hour"),
            color=alt.Color("mean(count):Q", scale=color_scale),
            tooltip=[
                alt.Tooltip("day(event_time):O", title="Day"),
                alt.Tooltip("month(event_time):O", title="Hour"),
                alt.Tooltip(
                    "mean(count):Q", title="Mean Num. Attendees", format=",.2f"
                ),
            ],
        )
    )
    chart2 = chart.encode(
        color=alt.Color("sum(count)", scale=color_scale),
        tooltip=[alt.Tooltip("sum(count):Q", title="Total Attendees")],
    )
    st.altair_chart(chart, use_container_width=True)
    st.altair_chart(chart2, use_container_width=True)


def plot_attendees_per_week(data):
    _data = data.copy()
    _data["legend"] = "Weekly Mean"
    chart = (
        alt.Chart(_data, title="Attendees pr. week")
        .mark_line()
        .encode(
            alt.X("week:Q", title="Week"),
            alt.Y("sum(count):Q", title="Numb. Attendees"),
            color=alt.Color("legend:N", sort=["Weekly Mean"]),
            tooltip=[
                alt.Tooltip("week:Q", title="Week"),
                # alt.Tooltip("day(event_time):O", title="Day"),
                alt.Tooltip("sum(count):Q", title="Num. workouts"),
            ],
        )
    )

    tmp = data[["week", "count"]].groupby("week").sum().reset_index()
    tmp.head()
    regress = linear_model.LinearRegression()
    regress.fit(
        tmp["week"].to_numpy().reshape(-1, 1), tmp["count"].to_numpy().reshape(-1, 1)
    )

    vals = np.array(tmp["week"].unique()).reshape(-1, 1)
    preds = regress.predict(vals)
    xy = np.concatenate([vals, preds], axis=1)
    tmp = pd.DataFrame(xy, columns=["week", "count"])
    tmp["legend"] = "Trend"
    chart2 = (
        alt.Chart(tmp)
        .mark_line(color="salmon")
        .encode(
            alt.X("week:Q"),
            alt.Y("count:Q"),
            strokeDash=alt.value([5, 5]),
            color=alt.Color("legend:N"),
            tooltip=[
                alt.Tooltip("week:Q", title="Week"),
                alt.Tooltip("count:Q", title="Trend", format=",.2f"),
            ],
        )
    )

    st.altair_chart(chart + chart2, use_container_width=True)


def plot_top_20_participants(data):
    tmp = data[["name", "count"]].groupby("name").sum().reset_index()
    tmp = tmp.sort_values("count", axis=0, ascending=False).iloc[:20]
    chart = (
        alt.Chart(tmp, title="Top 20 members")
        .mark_bar(cornerRadiusEnd=12)
        .encode(
            alt.X("count:Q"),
            alt.Y("name:N", sort="-x"),
            color=alt.Color("count:Q", scale=alt.Scale(range=colors, rangeMin=0)),
            tooltip=[
                alt.Tooltip("name", title="Name"),
                alt.Tooltip("count:Q", title="Num. workouts"),
            ],
        )
    )
    st.altair_chart(chart, use_container_width=True)


def plot_num_unique_names_over_time(data):
    people = data[["name", "event_time", "count"]].groupby("name").min().reset_index()
    people = people.sort_values("event_time", axis=0)
    people["cumsum"] = people["count"].cumsum()

    bar_chart = (
        alt.Chart(people, title="New names coming in".title())
        .mark_bar(size=20, cornerRadiusEnd=6, align="left")
        .encode(
            alt.X("yearmonth(event_time)", title="Time"),
            alt.Y("sum(count):Q", title="Member growth".title()),
            color=alt.Color("sum(count):Q", scale=color_scale),
            tooltip=[
                alt.Tooltip("yearmonth(event_time)", title="Month"),
                alt.Tooltip("sum(count):Q", title="Member growth".title()),
            ],
        )
    )
    chart = (
        alt.Chart(people, title="Unique names seen so far".title())
        .mark_line(point=True)
        .encode(
            # alt.X("yearmonthdate(event_time):O", title="Time"),
            alt.X("yearmonth(event_time):O", title="Time"),
            alt.Y("max(cumsum):Q", title="Unique members year to date".title()),
            tooltip=[
                alt.Tooltip("yearmonth(event_time):O", title="Date"),
                alt.Tooltip("max(cumsum):Q", title="Unique Names y2d".title()),
            ],
        )
    )
    st.altair_chart(bar_chart + chart, use_container_width=True)


def main():
    password = st.text_input("Password", type="password")
    if password == "":
        return

    sha = hashlib.sha256(str.encode(password)).hexdigest()

    if sha != "64565515ea24f8dcdf6ae9cdd364cdf0e2b3eaa7261cfa24dfce61db7574fcf0":
        st.warning("Wrong password")
        return

    data = get_data()
    part_col, member_col = st.columns(2)
    with part_col:
        st.markdown("# Attendance statistics")
        plot_week_heatmap(data)
        plot_year_heatmap(data)
        plot_attendees_per_week(data)

    with member_col:
        st.markdown("# Member statistics")
        plot_top_20_participants(data)
        plot_num_unique_names_over_time(data)

    workouts = get_workouts()
    if workouts.shape[0] > 0:
        with st.container():
            st.title("WOD statistics")
            burpee_rows = workouts[workouts["wod"].str.lower().str.contains("burpee")]
            st.metric(
                "Days with Burpees", f"{burpee_rows.shape[0]}/{workouts.shape[0]}"
            )

    st.write("Last data update: ")
    st.write(data["event_time"].max())


if __name__ == "__main__":
    st.set_page_config(layout="wide")
    main()
