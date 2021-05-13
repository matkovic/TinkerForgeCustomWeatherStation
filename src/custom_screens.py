# -*- coding: utf-8 -*-

import time
from screens import Screen

# Simple example for a custom screen.
# In this example we show the time in HH:MM:SS format.
# To try this example out add it to CUSTOM_SCREENS below.
class ClockScreen(Screen):
    # text/icon: Text is taken if no icon is available
    text = "Clock" # Text shown on tab
    icon = None    # Icon shown on tab (see icons.py and data/ sub-directory)

    # Called when tab is selected
    def draw_init(self):
        self.lcd.draw_text(40, 5, self.lcd.FONT_12X16, self.lcd.COLOR_BLACK, 'Time')
        self.draw_update()
    
    # Called when new data is available (usually once per second)
    def draw_update(self):
        # Get current time in HH:MM:SS format
        current_time = time.strftime("%H:%M:%S")
        self.lcd.draw_text(16, 30, self.lcd.FONT_12X16, self.lcd.COLOR_BLACK, current_time)


class CO2Screen(Screen):
    # text/icon: Text is taken if no icon is available
    text = "CO2" # Text shown on tab
    icon = None    # Icon shown on tab (see icons.py and data/ sub-directory)

    # Called when tab is selected
    def draw_init(self):
        #self.lcd.draw_text(40, 5, self.lcd.FONT_12X16, self.lcd.COLOR_BLACK, 'CO2')
        self.draw_update()
    
    # Called when new data is available (usually once per second)
    def draw_update(self):
        if self.tws.co2_last_value == None:
            return

        last_value = self.tws.co2_last_value

        co2_concentration = last_value.co2_concentration
        temperature = last_value.temperature
        humidity = last_value.humidity

        self.lcd.write_line(1, 0, "CO2 Conc.: " + str(co2_concentration) + " ppm")
        self.lcd.write_line(2, 0, "Temperature: " + str(temperature/100.0) + " \xF8C")
        self.lcd.write_line(3, 0, "Humidity: " + str(humidity/100.0) + " %RH")
  
class PMScreen(Screen):
    # text/icon: Text is taken if no icon is available
    text = "PM" # Text shown on tab
    icon = None    # Icon shown on tab (see icons.py and data/ sub-directory)

    # Called when tab is selected
    def draw_init(self):
        #self.lcd.draw_text(40, 5, self.lcd.FONT_12X16, self.lcd.COLOR_BLACK, 'CO2')
        self.draw_update()
    
    # Called when new data is available (usually once per second)
    def draw_update(self):
        if self.tws.pm_last_value == None:
            return

        last_value = self.tws.pm_last_value

        pm10 = last_value[0]
        pm25 = last_value[1]
        pm100 = last_value[2]

        self.lcd.write_line(0, 0, 'Enabled: ' + str(self.tws.pm.get_enable()))
        self.lcd.write_line(1, 0, 'PM 1.0: ' + str(pm10))
        self.lcd.write_line(2, 0, 'PM 2.5: ' + str(pm25))
        self.lcd.write_line(3, 0, 'PM 10.0: ' + str(pm100))
        
        



class PMCountScreen(Screen):
    # text/icon: Text is taken if no icon is available
    text = "PM_Count" # Text shown on tab
    icon = None    # Icon shown on tab (see icons.py and data/ sub-directory)

    # Called when tab is selected
    def draw_init(self):
        #self.lcd.draw_text(40, 5, self.lcd.FONT_12X16, self.lcd.COLOR_BLACK, 'CO2')
        self.draw_update()
    
    # Called when new data is available (usually once per second)
    def draw_update(self):
        if self.tws.pm_count_last_value == None:
            return

        last_value = self.tws.pm_count_last_value

        greater03um = last_value[0]
        greater05um = last_value[1]
        greater05um = last_value[2]
        greater25um = last_value[3]
        greater50um = last_value[4]
        greater100um = last_value[5]

        self.lcd.write_line(0, 0, 'Enabled: ' + str(self.tws.pm.get_enable()))
        self.lcd.write_line(1, 0, 'PM count > 03um: ' + str(greater03um))
        self.lcd.write_line(2, 0, 'PM count > 05um: ' + str(greater05um))
        self.lcd.write_line(3, 0, 'PM count > 10um: ' + str(greater05um))
        self.lcd.write_line(4, 0, 'PM count > 25um: ' + str(greater25um))
        self.lcd.write_line(5, 0, 'PM count > 50um: ' + str(greater50um))
        self.lcd.write_line(6, 0, 'PM count > 100um: ' + str(greater100um))

################################################
# Add your custom screens and tab position here:

#CUSTOM_SCREENS          = [] 
#CUSTOM_SCREENS_POSITION = 0 

#
# An example for a custom screen can be found above (ClockScreen).
# Comment in below to try it out. It will show a "Clock"-Tab on second
# position that prints the time in HH:MM:SS format.
#
CUSTOM_SCREENS          = [ClockScreen(), CO2Screen(), PMScreen(), PMCountScreen()] 
CUSTOM_SCREENS_POSITION = 1  
#
#################################################
