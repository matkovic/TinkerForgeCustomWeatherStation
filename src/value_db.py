# -*- coding: utf-8 -*-

"""
Tabletop Weather Station
Copyright (C) 2018 Olaf Lüke <olaf@tinkerforge.com>

value_db.py: Functions for easy access of sqlite database

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public
License along with this program; if not, write to the
Free Software Foundation, Inc., 59 Temple Place - Suite 330,
Boston, MA 02111-1307, USA.
"""

import sqlite3
import os
import threading
import time
import datetime
import logging as log
import sys

try:
    import Queue as queue
except:
    import queue

class ValueDB:
    air_quality_first_data = None
    gs_timer = 0
    gs_inter = 0

    def stop(self):
        self.run = False
        self.func_queue.put(None)
        self.thread.join(2)

    def is_packaged(self):
        if self.packaged:
            return True
        try:
            # PyInstaller stores data files in a tmp folder refered to as _MEIPASS
            #pylint: disable=protected-access
            base_path = sys._MEIPASS
            return True
        except:
            pass

        return False

    def loop(self):
        db_name = '.weather_station.db'

        if self.gui or self.is_packaged():
            db_path = os.path.join(os.path.expanduser('~'), db_name)
        else:
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), db_name)

        log.info('Using database: {0}'.format(db_path))

        self.db = sqlite3.connect(db_path)
        self.dbc = self.db.cursor()
        self.create()

        self.init_handshake.release()

        while self.run:
            func_data = self.func_queue.get()


            if self.gs_timer==0:
                self.gs_timer = time.time()
            elif self.gs_save_to_google_spreadsheet is not None and int(time.time() - self.gs_timer) >= self.gs_save_to_google_spreadsheet:
                self.gs_timer = time.time()
                if self.gs_inter == 0:  # push data to speadsheet periodically for different sensors
                    self.dbc.execute('SELECT * FROM air_quality_day ORDER BY id')
                    gs_values = self.dbc.fetchall()
                    sheet = self.gs_client.open('TinkerForge_DataCollector').worksheet('AirQuality')
                    sheet.update('A1',gs_values)
                elif self.gs_inter == 1:
                    self.dbc.execute('SELECT * FROM pm_concentration_day ORDER BY id')
                    gs_values = self.dbc.fetchall()
                    sheet = self.gs_client.open('TinkerForge_DataCollector').worksheet('PM_Concentration')
                    sheet.update('A1',gs_values)
                elif self.gs_inter == 2:
                    self.dbc.execute('SELECT * FROM pm_count_day ORDER BY id')
                    gs_values = self.dbc.fetchall()
                    sheet = self.gs_client.open('TinkerForge_DataCollector').worksheet('PM_Count')
                    sheet.update('A1',gs_values)
                elif self.gs_inter == 3:
                    self.dbc.execute('SELECT * FROM co2_day ORDER BY id')
                    gs_values = self.dbc.fetchall()
                    sheet = self.gs_client.open('TinkerForge_DataCollector').worksheet('CO2')
                    sheet.update('A1',gs_values)

                self.gs_inter += 1
                self.gs_inter = self.gs_inter%4


            

            if func_data == None:
                break

            func, data = func_data
            func(*data)

        # unblock all pending calls
        while True:
            try:
                self.func_queue.get(block=False)
                self.func_queue_ret.put(None)
            except queue.Empty:
                break

    def set_setting(self, key, value):
        if threading.current_thread() != self.thread:
            self.func_queue.put((self.set_setting, (key, value)))
            return

        self.dbc.execute('REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        self.db.commit()

    def get_setting(self, key):
        if threading.current_thread() != self.thread:
            self.func_queue.put((self.get_setting, (key,)))
            return self.func_queue_ret.get()

        try:
            self.dbc.execute('SELECT value FROM settings WHERE key = ?', (key,))
            value = self.dbc.fetchone()[0]
            self.func_queue_ret.put(value)
        except:
            self.func_queue_ret.put(None)

    def get_data(self, num, time_resolution, field, table, identifier = None, is_rain = False):
        if threading.current_thread() != self.thread:
            self.func_queue.put((self.get_data, (num, time_resolution, field, table, identifier, is_rain)))
            return self.func_queue_ret.get()

        count_str = 'count'
        if time_resolution < 60:
            count_str = '1'
            limit = num*time_resolution
        elif time_resolution < 60*60:
            limit = num*(time_resolution//60)
            table += '_minute'
        elif time_resolution < 60*60*24:
            limit = num*(time_resolution//(60*60))
            table += '_hour'
        else:
            limit = num*(time_resolution//(60*60*24))
            table += '_day'

        if identifier == None:
            self.dbc.execute('SELECT {0}, {1} FROM {2} ORDER BY id DESC LIMIT ?'.format(field, count_str, table), (limit,))
        else:
            self.dbc.execute('SELECT {0}, {1} FROM {2} WHERE identifier = ? ORDER BY id DESC LIMIT ?'.format(field, count_str, table), (identifier, limit))

        values = self.dbc.fetchall()

        data_per_num = limit//num
        averaged_values = []

        try:
            for i in range(num):
                v = 0.0
                for j in range(data_per_num):
                    index = i*data_per_num + j
                    if is_rain:
                        v = max(v, values[index][0])
                    else:
                        v += float(values[index][0]) / values[index][1]

                if is_rain:
                    averaged_values.append(v)
                else:
                    averaged_values.append(v/data_per_num)
        except:
            if j != 0:
                if is_rain:
                    averaged_values.append(v)
                else:
                    averaged_values.append(v/j)

        if len(averaged_values) == 0:
            averaged_values.append(0)

        ret = [averaged_values[-1]]*(num-len(averaged_values))
        for value in reversed(averaged_values):
            ret.append(value)

        self.func_queue_ret.put(ret)

    def get_data_air_quality(self, num, time_resolution, field):
        return self.get_data(num, time_resolution, field, 'air_quality')

    def get_data_station(self, num, time_resolution, field, identifier):
        return self.get_data(num, time_resolution, field, 'station', identifier)

    def get_data_sensor(self, num, time_resolution, field, identifier):
        return self.get_data(num, time_resolution, field, 'sensor', identifier)

    def get_data_rain_period_list(self, num, rain_period, identifier):
        values = self.get_data(num+1, rain_period, 'rain', 'station', identifier, True)
        rain_values = []
        for i in range(1, len(values)):
            rain_values.append(values[i] - values[i-1])

        return rain_values

    def get_data_rain_period(self, identifier, rain_period):
        if threading.current_thread() != self.thread:
            self.func_queue.put((self.get_data_rain_period, (identifier, rain_period)))
            return self.func_queue_ret.get()

        try:
            self.dbc.execute('SELECT rain FROM station WHERE identifier = ? ORDER BY id DESC LIMIT 1', (identifier, ))
            period_end_rain = self.dbc.fetchone()[0]

            t = time.time() - rain_period
            self.dbc.execute('SELECT rain, time FROM station WHERE identifier = ? AND time > ? ORDER BY time ASC LIMIT 1', (identifier, t))
            period_start_rain = self.dbc.fetchone()[0]

            period_rain = max(0, period_end_rain - period_start_rain)
            self.func_queue_ret.put(period_rain)
        except:
            self.func_queue_ret.put(None)

    def add_data_air_quality(self, iaq_index, iaq_index_accuracy, temperature, humidity, air_pressure):
        if threading.current_thread() != self.thread:
            self.func_queue.put((self.add_data_air_quality, (iaq_index, iaq_index_accuracy, temperature, humidity, air_pressure)))
            return

        self.dbc.execute("""
            INSERT INTO air_quality (iaq_index, iaq_index_accuracy, temperature, humidity, air_pressure)
            VALUES (?, ?, ?, ?, ?)""",
            (iaq_index, iaq_index_accuracy, temperature, humidity, air_pressure)
        )

        self.dbc.execute("""
            UPDATE air_quality_minute
            SET iaq_index          = iaq_index + ?,
                iaq_index_accuracy = iaq_index_accuracy + ?,
                temperature        = temperature + ?,
                humidity           = humidity + ?,
                air_pressure       = air_pressure + ?,
                count              = count + 1
            WHERE time = (strftime('%s', 'now') - (strftime('%s', 'now') % 60))""",
            (iaq_index, iaq_index_accuracy, temperature, humidity, air_pressure)
        )

        self.dbc.execute("""
            INSERT OR IGNORE INTO air_quality_minute (iaq_index, iaq_index_accuracy, temperature, humidity, air_pressure)
            VALUES (?, ?, ?, ?, ?)""",
            (iaq_index, iaq_index_accuracy, temperature, humidity, air_pressure)
        )

        self.dbc.execute("""
            UPDATE air_quality_hour
            SET iaq_index          = iaq_index + ?,
                iaq_index_accuracy = iaq_index_accuracy + ?,
                temperature        = temperature + ?,
                humidity           = humidity + ?,
                air_pressure       = air_pressure + ?,
                count              = count + 1
            WHERE time = (strftime('%s', 'now') - (strftime('%s', 'now') % 3600))""",
            (iaq_index, iaq_index_accuracy, temperature, humidity, air_pressure)
        )

        self.dbc.execute("""
            INSERT OR IGNORE INTO air_quality_hour (iaq_index, iaq_index_accuracy, temperature, humidity, air_pressure)
            VALUES (?, ?, ?, ?, ?)""",
            (iaq_index, iaq_index_accuracy, temperature, humidity, air_pressure)
        )

        self.dbc.execute("""
            UPDATE air_quality_day
            SET iaq_index          = iaq_index + ?,
                iaq_index_accuracy = iaq_index_accuracy + ?,
                temperature        = temperature + ?,
                humidity           = humidity + ?,
                air_pressure       = air_pressure + ?,
                count              = count + 1
            WHERE time = (strftime('%s', 'now') - (strftime('%s', 'now') % 86400))""",
            (iaq_index, iaq_index_accuracy, temperature, humidity, air_pressure)
        )

        self.dbc.execute("""
            INSERT OR IGNORE INTO air_quality_day (iaq_index, iaq_index_accuracy, temperature, humidity, air_pressure)
            VALUES (?, ?, ?, ?, ?)""",
            (iaq_index, iaq_index_accuracy, temperature, humidity, air_pressure)
        )

        self.db.commit()


    def add_data_pm_concentration(self, pm10, pm25, pm100):
        if threading.current_thread() != self.thread:
            self.func_queue.put((self.add_data_pm_concentration, (pm10, pm25, pm100)))
            return

        self.dbc.execute("""
            INSERT INTO pm_concentration (pm10, pm25, pm100)
            VALUES (?, ?, ?)""",
            (pm10, pm25, pm100)
        )

        self.dbc.execute("""
            UPDATE pm_concentration_minute
            SET pm10          = pm10 + ?,
                pm25 = pm25 + ?,
                pm100        = pm100 + ?,
                count              = count + 1
            WHERE time = (strftime('%s', 'now') - (strftime('%s', 'now') % 60))""",
            (pm10, pm25, pm100)
        )

        self.dbc.execute("""
            INSERT OR IGNORE INTO pm_concentration_minute (pm10, pm25, pm100)
            VALUES (?, ?, ?)""",
            (pm10, pm25, pm100)
        )

        self.dbc.execute("""
            UPDATE pm_concentration_hour
            SET pm10          = pm10 + ?,
                pm25 = pm25 + ?,
                pm100        = pm100 + ?,
                count              = count + 1
            WHERE time = (strftime('%s', 'now') - (strftime('%s', 'now') % 3600))""",
            (pm10, pm25, pm100)
        )

        self.dbc.execute("""
            INSERT OR IGNORE INTO pm_concentration_hour (pm10, pm25, pm100)
            VALUES (?, ?, ?)""",
            (pm10, pm25, pm100)
        )

        self.dbc.execute("""
            UPDATE pm_concentration_day
            SET pm10          = pm10 + ?,
                pm25 = pm25 + ?,
                pm100        = pm100 + ?,
                count              = count + 1
            WHERE time = (strftime('%s', 'now') - (strftime('%s', 'now') % 86400))""",
            (pm10, pm25, pm100)
        )

        self.dbc.execute("""
            INSERT OR IGNORE INTO pm_concentration_day (pm10, pm25, pm100)
            VALUES (?, ?, ?)""",
            (pm10, pm25, pm100)
        )

        self.db.commit()


    def add_data_pm_count(self, greater03um, greater05um, greater10um, greater25um, greater50um, greater100um):
        if threading.current_thread() != self.thread:
            self.func_queue.put((self.add_data_pm_count, (greater03um, greater05um, greater10um, greater25um, greater50um, greater100um)))
            return

        self.dbc.execute("""
            INSERT INTO pm_count (greater03um, greater05um, greater10um, greater25um, greater50um, greater100um)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (greater03um, greater05um, greater10um, greater25um, greater50um, greater100um)
        )

        self.dbc.execute("""
            UPDATE pm_count_minute
            SET greater03um          = greater03um + ?,
                greater05um = greater05um + ?,
                greater10um        = greater10um + ?,
                greater25um        = greater25um + ?,
                greater50um        = greater50um + ?,
                greater100um        = greater100um + ?,
                count              = count + 1
            WHERE time = (strftime('%s', 'now') - (strftime('%s', 'now') % 60))""",
            (greater03um, greater05um, greater10um, greater25um, greater50um, greater100um)
        )

        self.dbc.execute("""
            INSERT OR IGNORE INTO pm_count_minute (greater03um, greater05um, greater10um, greater25um, greater50um, greater100um)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (greater03um, greater05um, greater10um, greater25um, greater50um, greater100um)
        )

        self.dbc.execute("""
            UPDATE pm_count_hour
            SET greater03um          = greater03um + ?,
                greater05um = greater05um + ?,
                greater10um        = greater10um + ?,
                greater25um        = greater25um + ?,
                greater50um        = greater50um + ?,
                greater100um        = greater100um + ?,
                count              = count + 1
            WHERE time = (strftime('%s', 'now') - (strftime('%s', 'now') % 3600))""",
            (greater03um, greater05um, greater10um, greater25um, greater50um, greater100um)
        )

        self.dbc.execute("""
            INSERT OR IGNORE INTO pm_count_hour (greater03um, greater05um, greater10um, greater25um, greater50um, greater100um)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (greater03um, greater05um, greater10um, greater25um, greater50um, greater100um)
        )

        self.dbc.execute("""
            UPDATE pm_count_day
            SET greater03um          = greater03um + ?,
                greater05um = greater05um + ?,
                greater10um        = greater10um + ?,
                greater25um        = greater25um + ?,
                greater50um        = greater50um + ?,
                greater100um        = greater100um + ?,
                count              = count + 1
            WHERE time = (strftime('%s', 'now') - (strftime('%s', 'now') % 86400))""",
            (greater03um, greater05um, greater10um, greater25um, greater50um, greater100um)
        )

        self.dbc.execute("""
            INSERT OR IGNORE INTO pm_count_day (greater03um, greater05um, greater10um, greater25um, greater50um, greater100um)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (greater03um, greater05um, greater10um, greater25um, greater50um, greater100um)
        )

        self.db.commit()

    def add_data_co2(self, co2_concentration, temperature, humidity):
        if threading.current_thread() != self.thread:
            self.func_queue.put((self.add_data_co2, (co2_concentration, temperature, humidity)))
            return

        self.dbc.execute("""
            INSERT INTO co2 (co2_concentration, temperature, humidity)
            VALUES (?, ?, ?)""",
            (co2_concentration, temperature, humidity)
        )


        self.dbc.execute("""
            UPDATE co2_minute
            SET co2_concentration          = co2_concentration + ?,
                temperature = temperature + ?,
                humidity        = humidity + ?,
                count              = count + 1
            WHERE time = (strftime('%s', 'now') - (strftime('%s', 'now') % 60))""",
            (co2_concentration, temperature, humidity)
        )

        self.dbc.execute("""
            INSERT OR IGNORE INTO co2_minute (co2_concentration, temperature, humidity)
            VALUES (?, ?, ?)""",
            (co2_concentration, temperature, humidity)
        )

        self.dbc.execute("""
            UPDATE co2_hour
            SET co2_concentration          = co2_concentration + ?,
                temperature = temperature + ?,
                humidity        = humidity + ?,
                count              = count + 1
            WHERE time = (strftime('%s', 'now') - (strftime('%s', 'now') % 3600))""",
            (co2_concentration, temperature, humidity)
        )

        self.dbc.execute("""
            INSERT OR IGNORE INTO co2_hour (co2_concentration, temperature, humidity)
            VALUES (?, ?, ?)""",
            (co2_concentration, temperature, humidity)
        )

        self.dbc.execute("""
            UPDATE co2_day
            SET co2_concentration          = co2_concentration + ?,
                temperature = temperature + ?,
                humidity        = humidity + ?,
                count              = count + 1
            WHERE time = (strftime('%s', 'now') - (strftime('%s', 'now') % 86400))""",
            (co2_concentration, temperature, humidity)
        )

        self.dbc.execute("""
            INSERT OR IGNORE INTO co2_day (co2_concentration, temperature, humidity)
            VALUES (?, ?, ?)""",
            (co2_concentration, temperature, humidity)
        )

        self.db.commit()

    def add_data_station(self, identifier, temperature, humidity, wind_speed, gust_speed, rain, wind_direction, battery_low):
        if threading.current_thread() != self.thread:
            self.func_queue.put((self.add_data_station, (identifier, temperature, humidity, wind_speed, gust_speed, rain, wind_direction, battery_low)))
            return

        self.dbc.execute("""
            INSERT INTO station (identifier, temperature, humidity, wind_speed, gust_speed, rain, wind_direction, battery_low)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (identifier, temperature, humidity, wind_speed, gust_speed, rain, wind_direction, battery_low)
        )

        self.dbc.execute("""
            UPDATE station_minute
            SET temperature = temperature + ?,
                humidity    = humidity + ?,
                wind_speed  = wind_speed + ?,
                gust_speed  = MAX(gust_speed, ?),
                rain        = ?,
                count       = count + 1
            WHERE (time = (strftime('%s', 'now') - (strftime('%s', 'now') % 60))) AND (identifier = ?)""",
            (temperature, humidity, wind_speed, gust_speed, rain, identifier)
        )

        self.dbc.execute("""
            INSERT OR IGNORE INTO station_minute (identifier, temperature, humidity, wind_speed, gust_speed, rain)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (identifier, temperature, humidity, wind_speed, gust_speed, rain)
        )

        self.dbc.execute("""
            UPDATE station_hour
            SET temperature = temperature + ?,
                humidity    = humidity + ?,
                wind_speed  = wind_speed + ?,
                gust_speed  = MAX(gust_speed, ?),
                rain        = ?,
                count       = count + 1
            WHERE (time = (strftime('%s', 'now') - (strftime('%s', 'now') % 3600))) AND (identifier = ?)""",
            (temperature, humidity, wind_speed, gust_speed, rain, identifier)
        )

        self.dbc.execute("""
            INSERT OR IGNORE INTO station_hour (identifier, temperature, humidity, wind_speed, gust_speed, rain)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (identifier, temperature, humidity, wind_speed, gust_speed, rain)
        )

        self.dbc.execute("""
            UPDATE station_day
            SET temperature = temperature + ?,
                humidity    = humidity + ?,
                wind_speed  = wind_speed + ?,
                gust_speed  = MAX(gust_speed, ?),
                rain        = ?,
                count       = count + 1
            WHERE (time = (strftime('%s', 'now') - (strftime('%s', 'now') % 86400))) AND (identifier = ?)""",
            (temperature, humidity, wind_speed, gust_speed, rain, identifier)
        )

        self.dbc.execute("""
            INSERT OR IGNORE INTO station_day (identifier, temperature, humidity, wind_speed, gust_speed, rain)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (identifier, temperature, humidity, wind_speed, gust_speed, rain)
        )

        self.db.commit()

    def add_data_sensor(self, identifier, temperature, humidity):
        if threading.current_thread() != self.thread:
            self.func_queue.put((self.add_data_sensor, (identifier, temperature, humidity)))
            return

        self.dbc.execute("""
            INSERT INTO sensor (identifier, temperature, humidity)
            VALUES (?, ?, ?)""",
            (identifier, temperature, humidity)
        )

        self.dbc.execute("""
            UPDATE sensor_minute
            SET temperature = temperature + ?,
                humidity    = humidity + ?,
                count       = count + 1
            WHERE (time = (strftime('%s', 'now') - (strftime('%s', 'now') % 60))) AND (identifier = ?)""",
            (temperature, humidity, identifier)
        )

        self.dbc.execute("""
            INSERT OR IGNORE INTO sensor_minute (identifier, temperature, humidity)
            VALUES (?, ?, ?)""",
            (identifier, temperature, humidity)
        )

        self.dbc.execute("""
            UPDATE sensor_hour
            SET temperature = temperature + ?,
                humidity    = humidity + ?,
                count       = count + 1
            WHERE (time = (strftime('%s', 'now') - (strftime('%s', 'now') % 3600))) AND (identifier = ?)""",
            (temperature, humidity, identifier)
        )

        self.dbc.execute("""
            INSERT OR IGNORE INTO sensor_hour (identifier, temperature, humidity)
            VALUES (?, ?, ?)""",
            (identifier, temperature, humidity)
        )

        self.dbc.execute("""
            UPDATE sensor_day
            SET temperature = temperature + ?,
                humidity    = humidity + ?,
                count       = count + 1
            WHERE (time = (strftime('%s', 'now') - (strftime('%s', 'now') % 86400))) AND (identifier = ?)""",
            (temperature, humidity, identifier)
        )

        self.dbc.execute("""
            INSERT OR IGNORE INTO sensor_day (identifier, temperature, humidity)
            VALUES (?, ?, ?)""",
            (identifier, temperature, humidity)
        )

        self.db.commit()

    def create(self):
        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS air_quality (
                id integer primary key,
                time timestamp default (strftime('%s', 'now')),
                iaq_index integer,
                iaq_index_accuracy integer,
                temperature integer,
                humidity integer,
                air_pressure integer
            )"""
        )

        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS air_quality_minute (
                id integer primary key,
                time timestamp unique default (strftime('%s', 'now') - (strftime('%s', 'now')%60)),
                iaq_index integer,
                iaq_index_accuracy integer,
                temperature integer,
                humidity integer,
                air_pressure integer,
                count integer default 1
            )"""
        )

        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS air_quality_hour (
                id integer primary key,
                time timestamp unique default (strftime('%s', 'now') - (strftime('%s', 'now')%3600)),
                iaq_index integer,
                iaq_index_accuracy integer,
                temperature integer,
                humidity integer,
                air_pressure integer,
                count integer default 1
            )"""
        )

        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS air_quality_day (
                id integer primary key,
                time timestamp unique default (strftime('%s', 'now') - (strftime('%s', 'now')%86400)),
                iaq_index integer,
                iaq_index_accuracy integer,
                temperature integer,
                humidity integer,
                air_pressure integer,
                count integer default 1
            )"""
        )


        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS pm_concentration (
                id integer primary key,
                time timestamp default (strftime('%s', 'now')),
                pm10 integer,
                pm25 integer,
                pm100 integer
            )"""
        )

        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS pm_concentration_minute (
                id integer primary key,
                time timestamp unique default (strftime('%s', 'now') - (strftime('%s', 'now')%60)),
                pm10 integer,
                pm25 integer,
                pm100 integer,
                count integer default 1
            )"""
        )

        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS pm_concentration_hour (
                id integer primary key,
                time timestamp unique default (strftime('%s', 'now') - (strftime('%s', 'now')%3600)),
                pm10 integer,
                pm25 integer,
                pm100 integer,
                count integer default 1
            )"""
        )

        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS pm_concentration_day (
                id integer primary key,
                time timestamp unique default (strftime('%s', 'now') - (strftime('%s', 'now')%86400)),
                pm10 integer,
                pm25 integer,
                pm100 integer,
                count integer default 1
            )"""
        )


        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS pm_count (
                id integer primary key,
                time timestamp default (strftime('%s', 'now')),
                greater03um integer, 
                greater05um integer,
                greater10um integer,
                greater25um integer,
                greater50um integer,
                greater100um integer
            )"""
        )

        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS pm_count_minute (
                id integer primary key,
                time timestamp unique default (strftime('%s', 'now') - (strftime('%s', 'now')%60)),
                greater03um integer, 
                greater05um integer,
                greater10um integer,
                greater25um integer,
                greater50um integer,
                greater100um integer,
                count integer default 1
            )"""
        )

        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS pm_count_hour (
                id integer primary key,
                time timestamp unique default (strftime('%s', 'now') - (strftime('%s', 'now')%3600)),
                greater03um integer, 
                greater05um integer,
                greater10um integer,
                greater25um integer,
                greater50um integer,
                greater100um integer,
                count integer default 1
            )"""
        )

        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS pm_count_day (
                id integer primary key,
                time timestamp unique default (strftime('%s', 'now') - (strftime('%s', 'now')%86400)),
                greater03um integer, 
                greater05um integer,
                greater10um integer,
                greater25um integer,
                greater50um integer,
                greater100um integer,
                count integer default 1
            )"""
        )



        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS co2 (
                id integer primary key,
                time timestamp default (strftime('%s', 'now')),
                co2_concentration integer,
                temperature integer,
                humidity integer
            )"""
        )

        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS co2_minute (
                id integer primary key,
                time timestamp unique default (strftime('%s', 'now') - (strftime('%s', 'now')%60)),
                co2_concentration integer,
                temperature integer,
                humidity integer,
                count integer default 1
            )"""
        )

        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS co2_hour (
                id integer primary key,
                time timestamp unique default (strftime('%s', 'now') - (strftime('%s', 'now')%3600)),
                co2_concentration integer,
                temperature integer,
                humidity integer,
                count integer default 1
            )"""
        )

        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS co2_day (
                id integer primary key,
                time timestamp unique default (strftime('%s', 'now') - (strftime('%s', 'now')%86400)),
                co2_concentration integer,
                temperature integer,
                humidity integer,
                count integer default 1
            )"""
        )






        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS station (
                id integer primary key,
                time timestamp default (strftime('%s', 'now')),
                identifier integer,
                temperature integer,
                humidity integer,
                wind_speed integer,
                gust_speed integer,
                rain integer,
                wind_direction integer,
                battery_low integer
            )"""
        )

        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS station_minute (
                id integer primary key,
                time timestamp default (strftime('%s', 'now') - (strftime('%s', 'now')%60)),
                identifier integer,
                temperature integer,
                humidity integer,
                wind_speed integer,
                gust_speed integer,
                rain integer,
                count integer default 1,
                UNIQUE(time, identifier)
            )"""
        )

        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS station_hour (
                id integer primary key,
                time timestamp default (strftime('%s', 'now') - (strftime('%s', 'now')%3600)),
                identifier integer,
                temperature integer,
                humidity integer,
                wind_speed integer,
                gust_speed integer,
                rain integer,
                count integer default 1,
                UNIQUE(time, identifier)
            )"""
        )

        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS station_day (
                id integer primary key,
                time timestamp default (strftime('%s', 'now') - (strftime('%s', 'now')%86400)),
                identifier integer,
                temperature integer,
                humidity integer,
                wind_speed integer,
                gust_speed integer,
                rain integer,
                count integer default 1,
                UNIQUE(time, identifier)
            )"""
        )

        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS sensor (
                id integer primary key,
                time timestamp default (strftime('%s', 'now')),
                identifier integer,
                temperature integer,
                humidity integer
            )"""
        )

        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS sensor_minute (
                id integer primary key,
                time timestamp default (strftime('%s', 'now') - (strftime('%s', 'now')%60)),
                identifier integer,
                temperature integer,
                humidity integer,
                count integer default 1,
                UNIQUE(time, identifier)
            )"""
        )

        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS sensor_hour (
                id integer primary key,
                time timestamp default (strftime('%s', 'now') - (strftime('%s', 'now')%3600)),
                identifier integer,
                temperature integer,
                humidity integer,
                count integer default 1,
                UNIQUE(time, identifier)
            )"""
        )

        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS sensor_day (
                id integer primary key,
                time timestamp default (strftime('%s', 'now') - (strftime('%s', 'now')%86400)),
                identifier integer,
                temperature integer,
                humidity integer,
                count integer default 1,
                UNIQUE(time, identifier)
            )"""
        )

        self.dbc.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                id integer primary key,
                key text NOT NULL UNIQUE,
                value text
            )"""
        )

        self.db.commit()

    def __init__(self, gui, packaged, save_to_google_spreadsheet=None):
        self.gui = gui
        self.packaged = packaged
        self.gs_save_to_google_spreadsheet = save_to_google_spreadsheet
        if save_to_google_spreadsheet is not None:
            import gspread
            from oauth2client.service_account import ServiceAccountCredentials
            self.gs_scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
            self.gs_creds = ServiceAccountCredentials.from_json_keyfile_name('./files/iper-247520.json', self.gs_scope)
            self.gs_client = gspread.authorize(self.gs_creds)
        self.run = True
        self.func_queue = queue.Queue()
        self.func_queue_ret = queue.Queue()
        self.init_handshake = threading.Semaphore(value=0)
        self.thread = threading.Thread(target=self.loop)
        self.thread.daemon = True
        self.thread.start()
        self.init_handshake.acquire()
