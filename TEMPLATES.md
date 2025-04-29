# Jinja2 Template Examples

These example templates might help newcomers get started with Solcast template sensors and automation. Feel free to contribute.

When getting started with Jinja2 read up on its core concepts. It is a brilliant templating language where placeholders allow writing statements in a format very similar to Python syntax. If you know Python this makes it fairly natural. If not, learn some Python, in particular number and datetime manipulations.

This document is a collection of Solcast example templates presented in the context of scenarios. It can not teach you Jinja2 or Python, which is up to you to learn, but for simple applications having a few examples to copy concepts from can avoid needing to spend hours learning.

Jinja2 templates are super handy to use when building template sensors, but don't forget that templates can be used elsewhere. For example, a Lovelace Card Templater Dashboard add-on is available in HACS that allows use of Jinja2 in all manner of things, not least of which are Apex charts. Things like that open up a world of advanced possibility.

# Contents

1. [Some simple examples](#some-simple-examples)
1. [Intermediate examples](#intermediate-exmaples)
    1. [Combining data from multiple sites](#combining-data-from-multiple-sites)
    1. [Visualising multiple days of PV generation forecast](#visualising-multiple-days-of-pv-generation-forecast)
1. [Advanced examples](#advanced-exmaples)
    1. [Virtual Power Plant adaptive battery discharge](#virtual-power-plant-adaptive-battery-discharge)
    1. [A scale-modifying Apex chart](#a-scale-modifying-apex-chart)

## Some simple examples

**Scenario**: Sensors are set to use the `forecast` or 50% estimate, but you want to show the 10% estimate on a dashboard. This can be retrieved from a sensor "attribute". Note that this sensor attribute must be enabled in the integration `CONFIGURE` options. It is by default, but if that has been disabled then this template will result in a zero value.

```
{{ state_attr('sensor.solcast_pv_forecast_forecast_today', 'estimate10') | float(0) }}
```

The conversion to float (with a default value of zero) is not strictly required. So what does that bit do? If the `state_attr()` result is null, or not a number then zero will be used. If the `| float(0)` were absent then an error would be logged should the attribute not exist.

**Scenario**:  Again, sensors use `forecast` 50%, and you want to show the 10% estimate of just one Solcast site, identified by its resource ID.

```
{{ state_attr('sensor.solcast_pv_forecast_forecast_today', 'estimate10_1234_5678_9012_3456') | float(0) }}
```

**Scenario**: You're not using the GUI to create a template sensor, rather `configuration.yaml`. You would like to display the peak PV generation expected today for just one rooftop site.

``` yaml
template
  - sensor:
      - name: "West array peak solar forecast today"
        unique_id: "solcast_pv_forecast_peak_forecast_today_west_array"
        unit_of_measurement: "W"
        state: >
          {{ state_attr('sensor.solcast_pv_forecast_peak_forecast_today', 'b68d_c05a_c2b3_2cf9') | float(0) }}
        availability: >
          {{ states('sensor.solcast_pv_forecast_peak_forecast_today') | is_number }}
```

If the `availability` is not set then the log will likely be spammed with errors should the sensor entity be unavailable.

## Intermediate examples

### Combining data from multiple sites

**Scenario**: You have two Solcast API keys, with two rooftop sites on one main location, plus two rooftop sites at a holiday house. You want to see all the data in a single Home Assistant deployment at the main location.

It is possible to exclude sites from the sensor total from v4.3.3 of the integration, so you do so from the `CONFIGURE` dialogue for the integration. This leaves the sensor states and Energy dashboard data being for just the two rooftop sites at the main residence.

To visualise the holiday house you are going to create an Apex chart on a dashboard, as well as show some entity states like 'forecast today'.

Here is how to combine the two holiday house sites

``` yaml
  - sensor:
      - name: "Holiday house forecast today"
        unique_id: "solcast_holiday_house_forecast_today"
        state: >
          {% set sensor1 = state_attr('sensor.solcast_pv_forecast_forecast_today', 'b68d_c05a_c2b3_2cf9') %}
          {% set sensor2 = state_attr('sensor.solcast_pv_forecast_forecast_today', '83d5_ab72_2a9a_2397') %}
          {{ sensor1 + sensor2 }}
        unit_of_measurement: "kWh"
        attributes:
          detailedForecast: >
            {% set sensor1 = state_attr('sensor.solcast_pv_forecast_forecast_today', 'detailedForecast_b68d_c05a_c2b3_2cf9') %}
            {% set sensor2 = state_attr('sensor.solcast_pv_forecast_forecast_today', 'detailedForecast_83d5_ab72_2a9a_2397') %}
            {% set ns = namespace(i=0, combined=[]) %}
            {% for interval in sensor1 %}
              {% set ns.combined = ns.combined + [
                {
                  'period_start': interval['period_start'].isoformat(),
                  'pv_estimate': (interval['pv_estimate'] + sensor2[ns.i]['pv_estimate']),
                  'pv_estimate10': (interval['pv_estimate10'] + sensor2[ns.i]['pv_estimate10']),
                  'pv_estimate90': (interval['pv_estimate90'] + sensor2[ns.i]['pv_estimate90']),
                }
              ] %}
              {% set ns.i = ns.i + 1 %}
            {% endfor %}
            {{ ns.combined | to_json() }}
        availability: >
          {{ states('sensor.solcast_pv_forecast_forecast_today') | is_number }}
```

Using a `namespace` for the looped addition is significant. If `i` and `combined` were simple variables then this would not work.

### Visualising multiple days of PV generation forecast

**Scenario**: You want to visualise expected PV generation for today, tomorrow and the day after in a single chart.

There are many ways to do this, and this is just one approach.

In this approach, create a template sensor to both combine the total expected generation, as well as create a `detailedForecast` attribute for the sensor that can be visualised by an Apex chart.

An alternative approach could be to utilise the intent of the attribute generation of this template in a `data_generator` section directly in the chart definition. As said, there are other approaches to get this done, but this is the only approach that both calculates the expected three-day total and builds three days of time-series data for charting.

```yaml
template:
  - sensor:
      - name: "Solcast Three Days"
        unique_id: "solcast_three_day"
        state: >
        state: >
          {{
            states('sensor.solcast_pv_forecast_forecast_today') | float(0) +
            states('sensor.solcast_pv_forecast_forecast_tomorrow') | float(0) +
            states('sensor.solcast_pv_forecast_forecast_day_3') | float(0)
          }}
        unit_of_measurement: "kWh"
        attributes:
          detailedForecast: >
            {%
              set days = state_attr('sensor.solcast_pv_forecast_forecast_today', 'detailedForecast') +
              state_attr('sensor.solcast_pv_forecast_forecast_tomorrow', 'detailedForecast') +
              state_attr('sensor.solcast_pv_forecast_forecast_day_3', 'detailedForecast')
            %}
            {% set ns = namespace(combined_list=[]) %}
            {% for interval in days %}
              {% set ns.combined_list = ns.combined_list + [
                {
                  'period_start': interval['period_start'].isoformat(),
                  'pv_estimate': interval['pv_estimate'],
                  'pv_estimate10': interval['pv_estimate10'],
                  'pv_estimate90': interval['pv_estimate90'],
                }
              ] %}
            {% endfor %}
            {{ ns.combined_list | to_json() }}
```

## Advanced examples

### Virtual Power Plant adaptive battery discharge

**Scenario**: Your power utility offers a cost free period during daytime that can be used to charge a battery from the grid, plus they offer rewarding evening peak feed-in rates to give some power back for others to use, giving you cash credit.

If you use Tesla Powerwalls then you could just trust setting up your power utility rates in their app and then setting the Powerwall in "Autonomous" mode. That might do an okay job, but Solcast forecast information is probably going to be superior at forecasting how much battery charge can be depleted today (at favourable feed-in rate), while leaving enough charge to power your home until the sun kicks in tomorrow. To add to that, some power utility rate models may not be able to be adequately described in the Tesla app, throwing "Autonomous" mode off.

The aim is to not use utility power (at cost) at any time of the year if possible.

Of course that likely won't happen all year round unless you use almost no power, or have a stupid number of 15kWh Powerwalls at great expense.

So you need a sensor that provides guidance for how low the battery can go during discharge that an automation can reference to switch the Powerwall mode from "Autonomous" to "Self-powered" mode (Autonomous can discharge to grid, while self-powered will not). Use the Tesla Fleet integration to control mode for Powerwalls, as the standard Powerwall integration can't do this as at the time of writing.

This template sensor should leave enough in the tank to last the night based on typical average hourly night time consumption. Will it get it right for complex and varied household power use? No. But if things are reasonably predictable from evening on it should get close.

This example relies on the Sun integration and also the HACS-installed Sun2 custom repository integration ([pnbruckner/ha-sun2](https://github.com/pnbruckner/ha-sun2)). Explanation of the template below.

``` yaml
template:
  - sensor:
      - name: "Battery dump minimum remaining"
        unique_id: "battery_dump_minimum_remaining"
        device_class: energy
        unit_of_measurement: "kWh"
        state: >
          {% set next_rise = states('sensor.sun_next_rising') | as_datetime %}
          {% set from_interval = next_rise.replace(minute=int(next_rise.minute / 30)*30, second=0) | as_local %}
          {% set to_interval = from_interval + timedelta(hours=2) %}
          {% set tomorrow = state_attr('sensor.solcast_pv_forecast_forecast_tomorrow', 'detailedForecast') %}
          {% set ns = namespace(total=0) %}
          {% for interval in tomorrow %}
            {% if interval['period_start'] > from_interval and interval['period_start'] <= to_interval %}
              {% set ns.total = ns.total + interval['pv_estimate'] * 0.5 %}
            {% endif %}
          {% endfor %}

          {% set sunset_to_sunrise_hours = (states('sensor.sun_next_rising') | as_datetime - states('sensor.home_sun_setting') | as_datetime).total_seconds() / 3600 %}
          {% set avg_hourly_use_overnight = 1.345 %}
          {% set base_minimum = sunset_to_sunrise_hours * avg_hourly_use_overnight %}

          {% set must_generate_at_least = avg_hourly_use_overnight * 2 %}
          {% if ns.total < must_generate_at_least %}
            {{ [base_minimum + (must_generate_at_least - ns.total), 0] | max }}
          {% else %}
            {{ [base_minimum, 0] | max }}
          {% endif %}
        availability: >
          {% set now_minutes = now().hour * 60 + now().minute %}
          {{ now() > states('sensor.home_sun_rising') | as_datetime and now_minutes > 5 and now_minutes < 1435 }}
```

The first part of the template gets the time that the sun will next rise, and then calculates the first two hours of expected solar generation thereafter. When iterating the forecast values they are multiplied by 0.5, and this is because the detailed forecast breakdown values are "power" (kW) and not "energy" (kWh). Each interval is one half hour expected average, so divide by two and add two intervals per hour to get forecast _energy_ production.

The second part works out how many hours there are from sunset today to next sunrise, sets an average overnight power consumption variable (in kWh, which could be a "helper" variable or another sensor state), then calculates a "base_minimum" charge required, assuming that solar power generation will take over without any cloud cover / inclement weather.

The third part determines how much power the sun must give over the two hour period to prevent total battery discharge. If it is not expected that the sun will deliver what is required then the "base_minimum" is increased by the anticipated shortfall.

The sensor becomes unavailable between midnight and sunrise. If it did not have the availability template then the sensor state would become a nonsensical negative number until sunrise next occurs. That would not impact any battery discharging (because early morning is never considered a peak time for power export) but it would mess with the state history of the sensor.

Again, will it always work? Nope. It's a forecast, and evening power usage can be quite variable. It could be improved to account for differing seasonal or daily overnight consumption averages. For example, if Friday night is Pizza Night then the oven won't be used and average overnight consumption will be less.

### A scale-modifying Apex chart

This example varies the X axis scale of an Apex chart showing forecast and solar production with offset and span based on the time of day. During the middle of the day the offset/span will match sunrise to sunset, and early in the morning or later in the evening the chart will expand as hours pass.

It utilises the Sun2 and Lovelace Card Templater HACS add-ons. Plus a per-five-minute template sensor to cause it to update. Some sensors used are implementation specific. Change them.

Sun2 is a HACS-installed custom repository integration ([pnbruckner/ha-sun2](https://github.com/pnbruckner/ha-sun2))

[<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/example_span_offset_modifier.png">](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/example_span_offset_modifier.png)

``` yaml
type: custom:card-templater
card:
  type: custom:apexcharts-card
  graph_span_template: |-
    {% set sunrise = as_datetime(states('sensor.home_sun_rising'))  %}
    {% set sunset = as_datetime(states('sensor.home_sun_setting'))  %}
    {% if sunrise != none and sunset != none %}
      {% set compressed = (
        (as_local(sunset).hour - as_local(sunrise).hour) + 1 +
        (
          (
            max(now().hour - as_local(sunset).hour, 0)
          )
          if now().hour > as_local(sunrise).hour
          else (as_local(sunrise).hour - now().hour + 2)
        ) * 2
      ) %}
      {{ compressed if compressed <= 24 else 24 }}h
    {% else %}
      24h
    {% endif %}
  span:
    start: day
    offset_template: |-
      {% set sunrise = as_datetime(states('sensor.home_sun_rising'))  %}
      {% set sunset = as_datetime(states('sensor.home_sun_setting'))  %}
      {% if sunrise != none and sunset != none %}
        +{{
          (
            as_local(sunrise).hour - max((now().hour - as_local(sunset).hour), 0)
          )
          if now().hour > as_local(sunrise).hour else now().hour
        }}h
      {% else %}
        +0h
      {% endif %}
  header:
    title: Solar
    show: true
    show_states: true
    colorize_states: true
  apex_config:
    chart:
      height: 300px
    tooltip:
      enabled: true
      shared: true
      followCursor: true
  yaxis:
    - id: capacity
      show: true
      opposite: true
      decimals: 0
      max: 100
      min: 0
      apex_config:
        tickAmount: 10
    - id: kWh
      show: true
      min: 0
      apex_config:
        tickAmount: 10
    - id: header_only
      show: false
  series:
    - entity: sensor.my_home_solar_power
      name: Solar power (5 min avg)
      type: line
      stroke_width: 2
      float_precision: 2
      color: Orange
      yaxis_id: kWh
      unit: kW
      extend_to: now
      show:
        legend_value: true
        in_header: false
      group_by:
        func: avg
        duration: 5m
    - entity: sensor.solcast_pv_forecast_forecast_today
      name: Forecast 10-50%
      color: LightGrey
      opacity: 0.5
      stroke_width: 2
      type: area
      time_delta: +15min
      curve: monotoneCubic
      extend_to: false
      yaxis_id: kWh
      show:
        legend_value: false
        in_legend: true
        in_header: false
      data_generator: |
        return entity.attributes.detailedForecast.map((entry) => {
              return [new Date(entry.period_start), entry.pv_estimate];
            });
    - entity: sensor.powerwall_charge_actual
      name: Battery
      yaxis_id: capacity
      type: line
      stroke_width: 1
      float_precision: 2
      color: DarkGreen
      extend_to: now
      group_by:
        func: avg
        duration: 1s
      show:
        in_legend: true
        legend_value: false
        in_header: false
    - entity: sensor.solcast_pv_forecast_forecast_today
      name: Forecast 10%
      color: White
      opacity: 1
      stroke_width: 0
      type: area
      time_delta: +15min
      curve: monotoneCubic
      extend_to: false
      yaxis_id: kWh
      show:
        in_legend: false
        in_header: false
      data_generator: |
        return entity.attributes.detailedForecast.map((entry) => {
              return [new Date(entry.period_start), entry.pv_estimate10];
            });
    - entity: sensor.solar_generation_today
      yaxis_id: header_only
      name: Actual today
      stroke_width: 2
      color: Orange
      show:
        legend_value: true
        in_header: true
        in_chart: false
    - entity: sensor.solcast_pv_forecast_forecast_today
      yaxis_id: header_only
      name: Forecast today
      color: Grey
      float_precision: 1
      show:
        legend_value: true
        in_header: true
        in_chart: false
    - entity: sensor.solcast_pv_forecast_forecast_today
      attribute: estimate10
      yaxis_id: header_only
      name: Forecast today 10%
      color: Grey
      float_precision: 1
      opacity: 0.3
      show:
        legend_value: true
        in_header: true
        in_chart: false
    - entity: sensor.solcast_pv_forecast_forecast_remaining_today
      yaxis_id: header_only
      name: Forecast remaining
      color: Grey
      show:
        legend_value: true
        in_header: true
        in_chart: false
entities:
  - entity: sensor.five_minute_update
```

And the per-five-minute template sensor updater...

``` yaml
template:
  - trigger:
      - platform: time_pattern
        minutes: "/5"
    sensor:
      - name: "Five Minute Update"
        unique_id: "five_minute_update"
        state: "{{ now().minute }}"
        unit_of_measurement: "Minutes"
```
