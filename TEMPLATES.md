# Jinja2 Template Examples

These example templates might help newcomers get started with Solcast template sensors and automation. Feel free to contribute.

When getting started with Jinja2 read up on its core concepts. It is a brilliant templating language where placeholders allow writing statements in a format very similar to Python syntax. If you know python this makes it fairly natural. If not, learn some python, in particular number and datetime manipulations.

This document is a collection of Solcast example templates presented in the context of scenarios. It can not teach you Jinja2 or Python, which is up to you to learn.

## General

Jinja2 templates are super handy to use when building template sensors, but don't forget that templates can be used elsewhere. For example, a Lovelace Card Templater Dashboard add-on is available in HACS that allows use of Jinja2 in all manner of things, not least of which are Apex charts. Things like that open up a world of advanced possibility.

## Some simple examples

**Scenario**: Sensors are set to use the `forecast` or 50% estimate, but you want to show the 10% estimate on a dashboard. This can be retrieved from a sensor "attribute". Note that this sensor attribute must be enabled in the integration `CONFIGURE` options. It is by default, but if that has been disabled then this template will result in a zero value.

```
{{ state_attr('sensor.solcast_pv_forecast_forecast_today', 'estimate10') | float(0) }}
```

The conversion to float (with a default value of zero) is not strictly required. So what does that bit do? If the `state_attr()` result is null, or not a number then zero will be used.

**Scenario**:  Again, sensors use `forecast` 50%, and you want to show the 10% estimate of just one Solcast site, identified by its resource ID.

```
{{ state_attr('sensor.solcast_pv_forecast_forecast_today', 'estimate10_1234_5678_9012_3456') | float(0) }}
```

## Advanced example: Virtual Power Plant adaptive battery discharge

**Scenario**: Your power utility offers a cost free period during daytime that can be used to charge a battery from the grid, plus they offer rewarding evening peak feed-in rates to give some power back for others to use, giving you cash credit.

If you use Tesla Powerwalls then you could just trust setting up your power utility rates in their app and then setting the Powerwall in "Autonomous" mode. That might do an okay job, but Solcast forecast information is probably going to be superior at forecasting how much battery charge can be depleted today (at favourable feed-in rate), while leaving enough charge to power your home until the sun kicks in tomorrow. To add to that, some power utility rate models may not be able to be adequately described in the Tesla app, throwing "Autonomous" mode off.

The aim is to not use utility power (at cost) at any time of the year if possible.

Of course that likely won't happen all year round unless you use almost no power, or have a stupid number of 15kWh Powerwalls at great expense.

So you need a sensor that provides guidance for how low the battery can go during discharge that an automation can reference to switch the Powerwall mode from "Autonomous" (where it can discharge to grid, hint: use the Tesla Fleet integration to control mode) to "Self-powered" mode (where it won't). This should leave enough in the tank to last the night based on typical average hourly night time consumption.

Will it get it right for complex and varied household power use? No. But if things are reasonably predictable from evening on it should.

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
            {{ base_minimum + (must_generate_at_least - ns.total) }}
          {% else %}
            {{ base_minimum }}
          {% endif %}

```

The first part of the template gets the time that the sun will next rise, and then calculates the first two hours of expected solar generation thereafter. When iterating the forecast values they are multiplied by 0.5, and this is because the detailed forecast breakdown values are "power" (kW) and not "energy" (kWh). Each interval is one half hour expected average, so divide by two and add two intervals per hour to get forecast _energy_ production.

The second part works out how many hours there are from sunset today to next sunrise, sets an average overnight power consumption variable (in kWh, which could be a "helper" variable or another sensor state), then calculates a "base_minimum" charge required, assuming that solar power generation will take over without any cloud cover / inclement weather.

The third part determines how much power the sun must give over the two hour period to prevent total battery discharge. If it is not expected that the sun will deliver what is required then the "base_minimum" is increased by the anticipated shortfall.

Again, will it always work? Nope. It's a forecast, and evening power usage can be quite variable. It could be improved to account for differing seasonal or daily overnight consumption averages. For example, if Friday night is Pizza Night then the oven won't be used and average overnight consumption will be less.