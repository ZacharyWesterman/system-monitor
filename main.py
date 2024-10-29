#!/usr/bin/env python3

from dataclasses import dataclass
from typing import Generator
import subprocess
import socket
import time
import json

import skrunk_api

#Intentionally fail if API key does not exist.
with open('config.json', 'r') as fp:
    CONFIG = json.load(fp)
    API_KEY = CONFIG['skrunk_api']
    API_URL = CONFIG['skrunk_url']
    API_NOTIFY_USERS = CONFIG['skrunk_notify_users']
    API = skrunk_api.Session(API_KEY, API_URL)

HOSTNAME = socket.gethostname()

@dataclass
class MountPoint:
    location: str
    used: int
    free: int

    @property
    def size(self) -> int:
        return self.used + self.free
    
    @property
    def ratio(self) -> float:
        return self.used / self.size

def mount_points() -> Generator[MountPoint, None, None]:
    past_headers = False

    for line in subprocess.getoutput('df').split('\n'):
        if not past_headers:
            past_headers = True
            continue

        info = line.split()
        yield MountPoint(info[5], int(info[2]), int(info[3]))


THRESHOLDS = [
    .999,
    .998,
    .997,
    .996,
    .995,
    .99,
    .985,
    .98,
    .95,
    .9,
    .8,
    0, #This bottom threshold will not get notified about.
]

#If alert history file exists, load it.
ALERT_HIST = {}
try:
    with open('/var/tmp/system-monitor.json', 'r') as fp:
        ALERT_HIST = json.load(fp)
except FileNotFoundError:
    pass
except json.JSONDecodeError:
    pass


def check_for_alerts() -> list[str]:
    alerts = []

    for disk in mount_points():
        #If this mount point has hit a disk usage threshold,
        #Alert about it, but ONLY ONCE PER THRESHOLD.
        #If disk usage goes increases, wait till next threshold before alerting.
        #If disk usage goes down, allow alerting about this threshold again (if it goes up again).

        for thresh in THRESHOLDS:
            if disk.ratio >= thresh:
                #Don't alert about zero threshold
                if thresh == 0:
                    if disk.location in ALERT_HIST:
                        del ALERT_HIST[disk.location]
                    break

                #If usage used to be lower, alert.
                if ALERT_HIST.get(disk.location, 0) < thresh:
                    alerts += [f'DISK "{disk.location}" is at {int(disk.ratio * 100)}%']
                
                ALERT_HIST[disk.location] = thresh
                break

    return alerts


while True:
    # print('Checking disk usage...')
    alerts = check_for_alerts()
    if len(alerts):
        print('\n'.join(alerts))

        #Write alert history to file, so it persists across reboots.
        with open('/var/tmp/system-monitor.json', 'w') as fp:
            json.dump(ALERT_HIST, fp)

        try:
            for user in API_NOTIFY_USERS:
                API.call('sendNotification', {
                    'username': user,
                    'title': 'Server Disk Usage Alert',
                    'body': f'{HOSTNAME.upper()}:\n' + '\n'.join(alerts),
                    'category': 'system',
                })
        except skrunk_api.SessionError as e:
            print(e)

    time.sleep(60)