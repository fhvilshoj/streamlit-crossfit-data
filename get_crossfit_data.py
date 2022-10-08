import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from functools import reduce
from itertools import chain
from pathlib import Path
from typing import List

import matplotlib.animation as animation
import matplotlib.pyplot as plt
import numpy as np
import requests
from dataclasses_json import config, dataclass_json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.utils import ChromeType
from webdriver_manager.firefox import GeckoDriverManager

logger = logging.getLogger(__name__)

JSON_STORAGE_FILE_NAME = Path("workout_log.json")

LOGIN_URL = "https://fitness.flexybox.com/flrmovement/Account/LogOn"
ACTIVITY_URL = (
    "https://fitness.flexybox.com/flrmovement/TeamActivity/AllActivities?lang=da"
)
TEAM_INFO_URL = "https://fitness.flexybox.com/flrmovement/Public/TeamInfo/?teamid=%s"

USERNAME = os.environ["FLEXYBOX_USERNAME"]
PASSWORD = os.environ["FLEXYBOX_PASSWORD"]

# Regex
ATTENDEE_REGEX = r"<tr>\s+<td>(?P<rank>\d+)</td>\s+<td>(?P<name>.*?)</td>\s+<td>(?P<signuptime>\d\d-\d\d-\d\d\d\d\s\d\d:\d\d:\d\d)</td>\s+(?P<waitlist><td>\s+.*\s+</td>\s+)*</tr>"
WEEK_NUM_REGEX = r"Uge\s+(?P<week>\d{1,2})\s+(?P<from>[\d-]*)\s-\s(?P<to>[\d-]*)"

# Xpath
WEEK_XPATH = '//*[@id="main"]/div[4]/table/tbody/tr[1]/td[2]/div/table/tbody/tr/td[2]'
DAY_OF_WEEK_XPATH = '//*[@id="joinForm"]/table/tbody/tr/td'
DAY_XPATH = "table/tbody/tr[1]/th"
TEAM_XPATH = "table/tbody/tr"
PREV_BTN_ID = "UCDprevBtn"

# Date format
FMT = "%d-%m-%Y"


@dataclass_json
@dataclass
class Attendee:
    name: str
    rank: int
    signup_time: str
    class_type: str
    event_time: datetime = field(
        metadata=config(
            encoder=datetime.isoformat,
            decoder=datetime.fromisoformat,
        )
    )


def get_week(dt):
    return date(dt.year, dt.month, dt.day).isocalendar()[1]


def fetch_team_data(stop_at: datetime):
    latest_week_number = get_week(stop_at)
    this_week = get_week(datetime.now())
    print(latest_week_number, this_week)

    if get_week(datetime.now()) - 1 <= latest_week_number:
        return []

    logger.info(f"Fetching latest attendees (back to {stop_at})")

    all_attendees = []

    driver = webdriver.Firefox(service=FirefoxService(GeckoDriverManager().install()))
    driver.get(LOGIN_URL)

    elem = driver.find_element(By.NAME, "UserName")
    elem.clear()
    elem.send_keys(USERNAME)

    elem = driver.find_element(By.NAME, "Password")
    elem.clear()
    elem.send_keys(PASSWORD)

    submit_button = driver.find_element(By.NAME, "login")
    submit_button.click()

    driver.get(ACTIVITY_URL)

    # Session for querying each team on a page.
    user_agent = driver.execute_script("return navigator.userAgent")
    headers = {"User-Agent": user_agent}
    s = requests.session()
    s.headers.update(headers)
    for cookie in driver.get_cookies():
        c = {cookie["name"]: cookie["value"]}
        s.cookies.update(c)

    week_num = -1

    while week_num > latest_week_number + 1 or week_num == -1:
        if week_num == -1:
            week = (
                driver.find_element(
                    By.XPATH,
                    WEEK_XPATH,
                )
                .text.strip()
                .replace("\n", " ")
            )
            week_num, from_str, to_str = re.search(WEEK_NUM_REGEX, week).groups()
            week_num = int(week_num)
            from_date = datetime.strptime(from_str, FMT)

            # Previous week.
            driver.find_element(By.ID, PREV_BTN_ID).click()
            continue
        else:
            from_date -= timedelta(days=7)
            week_num = get_week(from_date)

        print("\rWeek: %d" % week_num, end="")

        current_date = from_date - timedelta(days=1)
        for day_of_week in driver.find_elements(By.XPATH, DAY_OF_WEEK_XPATH):
            current_date += timedelta(days=1)

            day = day_of_week.find_element(By.XPATH, DAY_XPATH).text.split()[0]

            first = True
            for team in day_of_week.find_elements(By.XPATH, TEAM_XPATH):
                if first:
                    first = False
                    continue

                class_type = team.find_element(By.CLASS_NAME, "teamName").text
                hours, minutes = (
                    team.find_element(By.CLASS_NAME, "teamTime").text.strip().split(":")
                )
                hours = int(hours)
                minutes = int(minutes)
                evt_time = current_date + timedelta(hours=hours, minutes=minutes)
                data_id = team.find_element(By.CLASS_NAME, "TeamDesc").get_attribute(
                    "data-id"
                )
                res = s.get(TEAM_INFO_URL % data_id)

                attendees = res.content.decode("utf-8")
                attendees = re.findall(ATTENDEE_REGEX, attendees)
                all_attendees += [
                    Attendee(
                        class_type=class_type,
                        rank=int(a[0]),
                        name=a[1],
                        signup_time=a[2],
                        event_time=evt_time,
                    )
                    for a in attendees
                    if not a[3]
                ]

        # Previous week.
        driver.find_element(By.ID, PREV_BTN_ID).click()

    driver.quit()
    print()

    logger.info(f"Total new attendees found: {len(all_attendees)}")
    return all_attendees


def get_first_date(people_lists):
    return reduce(
        lambda a, b: min(a, b.event_time),
        chain(*list(people_lists.values())),
        datetime.now(),
    )


def get_latest_date(people_lists):
    return reduce(
        lambda a, b: max(a, b.event_time),
        chain(*list(people_lists.values())),
        datetime(2021, 3, 1),
    )


def plot_num_classes_participated_in(people_lists, top_k=10):
    print(f"Number of unique names: {len(people_lists)}")
    people_counts = map(lambda x: (x[0], len(x[1])), people_lists.items())
    people_counts = sorted(people_counts, key=lambda x: x[1])

    for i, (k, v) in enumerate(people_counts[-top_k:]):
        print(f"{top_k - i}\t{k}: {v}")

    counts = list(map(lambda x: x[1], people_counts))
    fig, ax = plt.subplots()
    ax.hist(counts)
    ax.set_xlabel("Antal WODs")
    ax.set_ylabel("Antal deltagere")

    fig.tight_layout()
    fig.savefig("plot.png")

    return fig


def __to_time(dt):
    return time(dt.hour, dt.minute, dt.second)


def plot_week_diagram(people_lists):
    first_week = get_week(get_first_date(people_lists))
    last_week = get_week(get_latest_date(people_lists))

    time_slots = list(
        {__to_time(a.event_time) for a in chain(*list(people_lists.values()))}
    )
    time_slots = sorted(time_slots, key=lambda x: x.hour)

    frame_to_week = lambda f: f + first_week

    counts = {}
    for a in chain(*list(people_lists.values())):

        week_counts = counts.setdefault(get_week(a.event_time), {})

        t = __to_time(a.event_time)
        week_counts[t] = week_counts.setdefault(t, 0) + 1

    for w in counts:
        counts[w] = [counts[w].get(k, 0) for k in time_slots]

    y = counts[first_week]

    def prepare_animation(bc, ttl):
        def animate(frame_num):
            week_num = frame_to_week(frame_num)
            cnts = counts[week_num]
            title[0].set_text(f"Uge {week_num}")

            for c, rect in zip(cnts, bc.patches):
                rect.set_height(c)

            # return bar_container.patches
            # return bc.patches, title[0]

        return animate

    max_count = max(chain(*list(counts.values())))
    time_slots = list(map(str, time_slots))

    fig, ax = plt.subplots()
    title = (
        ax.text(
            0.5,
            0.95,
            f"Uge {first_week}",
            ha="center",
            va="top",
            transform=ax.transAxes,
        ),
    )
    ax.set_xlabel("Tidspunkt på dagen")
    ax.set_ylabel("Gennemsnitlig deltagelse")

    bar_container = ax.bar(time_slots, y)
    ax.set_ylim(top=max_count)
    ani = animation.FuncAnimation(
        fig,
        prepare_animation(bar_container, title),
        last_week - first_week,
        repeat=False,
        blit=False,
    )

    return ani


def store_people_lists(people_lists):
    clone_lists = {}
    for k in people_lists:
        clone_lists[k] = [a.to_dict() for a in people_lists[k]]

    with JSON_STORAGE_FILE_NAME.open("w", encoding="utf-8") as f:
        json.dump(clone_lists, f, indent=2)


def main():
    people_lists = {}
    if JSON_STORAGE_FILE_NAME.exists():
        with JSON_STORAGE_FILE_NAME.open("r", encoding="utf-8") as f:
            people_lists = json.load(f)

    print(people_lists)

    for k in people_lists:
        people_lists[k] = [Attendee.from_dict(a) for a in people_lists[k]]

    stop_date = get_latest_date(people_lists)
    print(stop_date)
    new_attendees = fetch_team_data(stop_date)

    for a in new_attendees:
        people_lists.setdefault(a.name, []).append(a)
    store_people_lists(people_lists)

    # plot_num_classes_participated_in(people_lists)
    # ani = plot_week_diagram(people_lists)
    # ani.save("popularity.gif")

    # plt.show()


if __name__ == "__main__":
    main()
