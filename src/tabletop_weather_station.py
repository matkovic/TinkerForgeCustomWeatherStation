#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import time
import logging as log
log.basicConfig(level=log.INFO)

from tinkerforge.ip_connection import IPConnection
from tinkerforge.ip_connection import Error
from tinkerforge.brick_master import BrickMaster
from tinkerforge.bricklet_lcd_128x64 import BrickletLCD128x64
from tinkerforge.bricklet_air_quality import BrickletAirQuality, GetAllValues
from tinkerforge.bricklet_particulate_matter import BrickletParticulateMatter
from tinkerforge.bricklet_co2_v2 import BrickletCO2V2, GetAllValues as GAV_CO2
from screens import screen_set_lcd, screen_tab_selected, screen_touch_gesture, screen_update, screen_slider_value, Screen, TIME_SECONDS
from value_db import ValueDB
from datetime import datetime

import queue
import threading
import socket



# import gspread
# from oauth2client.service_account import ServiceAccountCredentials
# from requests import get
# import datetime

# scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
# creds = ServiceAccountCredentials.from_json_keyfile_name('./files/iper-247520.json', scope)
# client = gspread.authorize(creds)


class WeatherStation:
    HOST = "localhost"
    PORT = 4223

    ipcon = None
    lcd = None
    air_quality = None
    pm = None
    co2 = None

    outdoor_weather_station_last_value = {}
    outdoor_weather_sensor_last_value = {}

    air_quality_last_value = None
    co2_last_value = None
    pm_last_value = None
    pm_count_last_value = None



    graph_resolution_index = None
    logging_period_index = None


    def __init__(self, vdb):
        self.vdb = vdb

        self.update_logging_period()
        self.update_graph_resolution()

        self.last_air_quality_time = 0
        self.last_co2_time = 0
        self.last_pm_time = 0
        self.last_pm_concentration_time = 0
        self.last_pm_count_time = 0

        self.pm_last_time_enable = 0
        self.pm_enable_seconds = 30
        self.pm_enable_pause_seconds = 300

        # We use this lock to make sure that there is never an update at the
        # same time as a gesture or GUI callback. Otherwise we might draw two
        # different GUI elements at the same time.
        self.update_lock = threading.Lock()
        

        self.ipcon = IPConnection() # Create IP connection

        # Connect to brickd (retry if not possible)
        while True:
            try:
                self.ipcon.connect(WeatherStation.HOST, WeatherStation.PORT)
                break
            except Error as e:
                log.error('Connection Error: ' + str(e.description))
                time.sleep(1)
            except socket.error as e:
                log.error('Socket error: ' + str(e))
                time.sleep(1)

        self.ipcon.register_callback(IPConnection.CALLBACK_ENUMERATE,
                                     self.cb_enumerate)
        self.ipcon.register_callback(IPConnection.CALLBACK_CONNECTED,
                                     self.cb_connected)

        # Enumerate Bricks and Bricklets (retry if not possible)
        while True:
            try:
                self.ipcon.enumerate()
                break
            except Error as e:
                log.error('Enumerate Error: ' + str(e.description))
                time.sleep(1)


    def update_graph_resolution(self):
        index = self.vdb.get_setting('graph_resolution')
        if index == None:
            index = 0
            self.vdb.set_setting('graph_resolution', '1')
        self.graph_resolution_index = int(index)


    def update_logging_period(self):
        index = self.vdb.get_setting('logging_period')
        if index == None:
            index = 0
            self.vdb.set_setting('logging_period', '1')
        self.logging_period_index = int(index)
    
    def cb_touch_gesture(self, gesture, duration, pressure_max, x_start, x_end, y_start, y_end, age):
        self.update_lock.acquire()
        screen_touch_gesture(gesture, duration, pressure_max, x_start, x_end, y_start, y_end, age)
        self.update_lock.release()
    
    def cb_gui_tab_selected(self, index):
        self.update_lock.acquire()
        screen_tab_selected(index)
        self.update_lock.release()

    def cb_gui_slider_value(self, index, value):
        self.update_lock.acquire()
        screen_slider_value(index, value)
        self.update_lock.release()


    def cb_all_values(self, iaq_index, iaq_index_accuracy, temperature, humidity, air_pressure):
        if self.lcd is not None:
            self.lcd.write_line(1, 0, 'IAQ:      {0:6}'.format(iaq_index))
            # 0xF8 == ° on LCD 128x64 charset
            self.lcd.write_line(2, 0, 'Temp:     {0:6.2f} {1}C'.format(temperature/100.0, chr(0xF8)))
            self.lcd.write_line(3, 0, 'Humidity: {0:6.2f} %RH'.format(humidity/100.0))
            self.lcd.write_line(4, 0, 'Air Pres: {0:6.1f} hPa'.format(air_pressure/100.0))

    def cb_air_quality_all_values(self, iaq_index, iaq_index_accuracy, temperature, humidity, air_pressure):
        self.air_quality_last_value = GetAllValues(iaq_index, iaq_index_accuracy, temperature, humidity, air_pressure)

        now = time.time()
        if now - self.last_air_quality_time >= TIME_SECONDS[self.logging_period_index]:
            self.vdb.add_data_air_quality(iaq_index, iaq_index_accuracy, temperature, humidity, air_pressure)
            self.last_air_quality_time = now
            
            # sheet = client.open('TinkerForge_DataCollector').worksheet('AirQuality')
            # timestamp = datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')
            # sheet.append_row([timestamp, iaq_index, iaq_index_accuracy, temperature, humidity, air_pressure])



    def cb_pm_concentration(self, pm10, pm25, pm100):
        self.pm_last_value = (pm10, pm25, pm100)

        now = time.time()
        if now - self.last_pm_concentration_time >= TIME_SECONDS[self.logging_period_index] and self.pm.get_enable():
            self.vdb.add_data_pm_concentration(pm10,pm25,pm100)
            self.last_pm_concentration_time = now
        

        # turn of and turn on again for specific time, to increase lifetime of the sensor
        if self.pm_last_time_enable==0:
            self.pm_last_time_enable = now
            self.pm.set_enable(True)
        elif not self.pm.get_enable() and now > self.pm_last_time_enable + self.pm_enable_seconds + self.pm_enable_pause_seconds:
            self.pm_last_time_enable = now
            self.pm.set_enable(True)
        elif self.pm.get_enable() and now > self.pm_last_time_enable + self.pm_enable_seconds: 
            self.pm.set_enable(False)


    def cb_pm_count(self, greater03um, greater05um, greater10um, greater25um, greater50um, greater100um):
        self.pm_count_last_value = (greater03um, greater05um, greater10um, greater25um, greater50um, greater100um)

        now = time.time()
        if now - self.last_pm_count_time >= TIME_SECONDS[self.logging_period_index] and self.pm.get_enable():
            self.vdb.add_data_pm_count(greater03um, greater05um, greater10um, greater25um, greater50um, greater100um)
            self.last_pm_count_time = now

        # turn of and turn on again for specific time, to increase lifetime of the sensor
        if self.pm_last_time_enable==0:
            self.pm_last_time_enable = now
            self.pm.set_enable(True)
        elif not self.pm.get_enable() and now > self.pm_last_time_enable + self.pm_enable_seconds + self.pm_enable_pause_seconds:
            self.pm_last_time_enable = now
            self.pm.set_enable(True)
        elif self.pm.get_enable() and now > self.pm_last_time_enable + self.pm_enable_seconds: 
            self.pm.set_enable(False)
        

    def cb_co2_values(self, co2_concentration, temperature, humidity):
        self.co2_last_value = GAV_CO2(co2_concentration, temperature, humidity)

        now = time.time()
        if now - self.last_co2_time >= TIME_SECONDS[self.logging_period_index]:
            self.vdb.add_data_co2(co2_concentration, temperature, humidity)
            self.last_co2_time = now



    def cb_enumerate(self, uid, connected_uid, position, hardware_version,
                     firmware_version, device_identifier, enumeration_type):
        if enumeration_type == IPConnection.ENUMERATION_TYPE_CONNECTED or \
           enumeration_type == IPConnection.ENUMERATION_TYPE_AVAILABLE:
            if device_identifier == BrickletLCD128x64.DEVICE_IDENTIFIER:
                try:
                    # Initialize newly enumerated LCD128x64 Bricklet
                    self.lcd = BrickletLCD128x64(uid, self.ipcon)
                    self.lcd.set_display_configuration(14, 50, False, True)
                    self.lcd.set_status_led_config(0) # turn off status light
                    self.lcd.clear_display()
                    #self.lcd.write_line(0, 0, "   Weather Station")

                    self.lcd.set_response_expected_all(True)

                    self.lcd.register_callback(self.lcd.CALLBACK_TOUCH_GESTURE, self.cb_touch_gesture)
                    self.lcd.register_callback(self.lcd.CALLBACK_GUI_TAB_SELECTED, self.cb_gui_tab_selected)
                    self.lcd.register_callback(self.lcd.CALLBACK_GUI_SLIDER_VALUE, self.cb_gui_slider_value)
                    self.lcd.set_touch_gesture_callback_configuration(10, True)
                    self.lcd.set_gui_tab_selected_callback_configuration(100, True)
                    self.lcd.set_gui_slider_value_callback_configuration(100, True)
                    
                    screen_set_lcd(self.lcd)

                    log.info('LCD 128x64 initialized')
                except Error as e:
                    log.error('LCD 128x64 init failed: ' + str(e.description))
                    self.lcd = None
            elif device_identifier == BrickletAirQuality.DEVICE_IDENTIFIER:
                try:
                    # Initialize newly enumaratedy Air Quality Bricklet and configure callbacks
                    self.air_quality = BrickletAirQuality(uid, self.ipcon)
                    self.air_quality.set_status_led_config(0) # turn off status light
                    self.cb_air_quality_all_values(*self.air_quality.get_all_values())

                    self.air_quality.set_all_values_callback_configuration(2000, False)
                    self.air_quality.register_callback(self.air_quality.CALLBACK_ALL_VALUES,self.cb_air_quality_all_values)
                    log.info('Air Quality initialized')
                except Error as e:
                    log.error('Air Quality init failed: ' + str(e.description))
                    self.air_quality = None
            elif device_identifier == BrickletParticulateMatter.DEVICE_IDENTIFIER:
                try:
                    self.pm = BrickletParticulateMatter(uid, self.ipcon)
                    self.pm.set_status_led_config(0) # turn off status light
                    self.pm.set_pm_concentration_callback_configuration(2000, False)
                    self.pm.register_callback(self.pm.CALLBACK_PM_CONCENTRATION, self.cb_pm_concentration)
                    
                    self.pm.set_pm_count_callback_configuration(2000, False)
                    self.pm.register_callback(self.pm.CALLBACK_PM_COUNT, self.cb_pm_count)
                    log.info('PM initialized')
                except Error as e:
                    log.error('PM initialization failed: ' + str(e.description))
                    self.pm = None
            elif device_identifier == BrickletCO2V2.DEVICE_IDENTIFIER:
                try:
                    self.co2 = BrickletCO2V2(uid, self.ipcon)
                    self.co2.set_status_led_config(0) # turn off status light
                    self.co2.set_all_values_callback_configuration(2000, False)
                    self.co2.register_callback(self.co2.CALLBACK_ALL_VALUES, self.cb_co2_values)
                    log.info('CO2 initialized')
                except Error as e:
                    log.error('CO2 initialization failed: ' + str(e.description))
                    self.co2 = None
            elif device_identifier == BrickMaster.DEVICE_IDENTIFIER:
                try:
                    self.master = BrickMaster(uid, self.ipcon)
                    self.master.disable_status_led()
                    log.info('Master initialized')
                except Error as e:
                    log.error('Master initialization failed: ' + str(e.description))
                    self.master = None




    def cb_connected(self, connected_reason):
        # Eumerate again after auto-reconnect
        if connected_reason == IPConnection.CONNECT_REASON_AUTO_RECONNECT:
            log.info('Auto Reconnect')

            while True:
                try:
                    self.ipcon.enumerate()
                    break
                except Error as e:
                    log.error('Enumerate Error: ' + str(e.description))
                    time.sleep(1)



def loop(run_ref, stop_queue):
    gui = False
    packaged = False

    save_to_google_spreadsheet = None #60*60*8
    vdb = ValueDB(gui, packaged, save_to_google_spreadsheet=save_to_google_spreadsheet)
    tws = WeatherStation(vdb)
    Screen.tws = tws
    Screen.vdb = vdb

    now = datetime.now()
    if now.hour < 8:
        backlight = True
    else:
        backlight = False

    while run_ref[0]:
        tws.update_lock.acquire()

        try:
            screen_update()
        except:
            log.exception('Error during screen update')

        tws.update_lock.release()

        try:
            stop_queue.get(timeout=1.0)
            break
        except queue.Empty:
            pass

        # turn off screen backlight at dark
        now = datetime.now()

        if now.hour < 8 and backlight:
            tws.lcd.set_display_configuration(14, 0, False, True)
            backlight = False
        elif now.hour >= 8 and not backlight:
            tws.lcd.set_display_configuration(14, 30, False, True)
            backlight = True
    
    vdb.stop()

    if tws.ipcon != None:
        try:
            tws.ipcon.disconnect()
        except Error:
            pass




if __name__ == "__main__":
    log.info('Weather Station: Start')

    #weather_station = WeatherStation()

    run_ref = [True]
    stop_queue = queue.Queue()

    thread = threading.Thread(target=loop, args=(run_ref, stop_queue))
    thread.daemon = True
    thread.start()

    while True:
        True

    #if sys.version_info < (3, 0):
    #    input = raw_input # Compatibility for Python 2.x
    #input('Press key to exit\n')


    #log.info('Weather Station: End')
