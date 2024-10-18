# HA Solcast PV Solar Forecast Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
<!--[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)-->
![GitHub Release](https://img.shields.io/github/v/release/BJReplay/ha-solcast-solar?style=for-the-badge)
![GitHub License](https://img.shields.io/github/license/BJReplay/ha-solcast-solar?style=for-the-badge)
![GitHub commit activity](https://img.shields.io/github/commit-activity/y/BJReplay/ha-solcast-solar?style=for-the-badge)
![Maintenance](https://img.shields.io/maintenance/yes/2024?style=for-the-badge)

## Installation

### Custom repository in HACS

See [detailed](#hacs-recommended) instructions below.  Now that HACS 2.0 has been released, it is going to take some time to clear the huge backlog of database inclusion requests that have built up over its development. This database allows a simple search for 'Solcast' to find this integration. That means that the quickest and easist way to install is a custom repository. This is a straightforward process, and detailed instructions are shown below.  Clicking on the button below will open this page in your Home Assistant HACS page (assuming you already have Home Assistant and HACS set up), and you can follow the [detailed](#hacs-recommended) instructions from there.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=BJReplay&repository=ha-solcast-solar&category=integration)

> [!WARNING]  
> This repository is **not** currently in HACS, awaiting [this PR](https://github.com/hacs/default/pull/2535) to be merged. Install using the [HACS *(recommended)*](#hacs-recommended) instructions below.

> [!NOTE]
>
> 
> The use of beta versions can be a simple way to fix issues. Check the releases at https://github.com/BJReplay/ha-solcast-solar/releases to see if an issue has already been resolved. If so, enable the `Solcast PV Pre-release` entity to enable beta upgrade (or for HACS v1 turn on ```Show beta versions``` when re-downloading). Your feedback from testing betas will be most welcome in the repository discussions. https://github.com/BJReplay/ha-solcast-solar/discussions.

> [!NOTE]
>
> 
> This integration can be used as a replacement for the oziee/ha-solcast-solar integration, which has been removed from GitHub and HACS.  
>
> Uninstalling the Oziee version then installing this one, or simply downloading this one over that one will preserve the history and configuration.
>
> If you **uninstalled** the Oziee version, and then installed this version, then you will likely need to re-select to use Solcast Solar as the source of forecast production for your Energy dashboard.


Version Change Notes: See [below](#changes).

Home Assistant (https://www.home-assistant.io) Integration Component.

This custom component integrates the Solcast Hobby PV Forecast API into Home Assistant.

[<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/solar_production.png">](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/solar_production.png)

> [!NOTE]
>
> 
> Solcast have altered their API limits for new account creators.
>
> Solcast now only offer new account creators a limit of 10 API calls per day (used to be 50). 
> Old account users still have 50 API calls.

## Solcast requirements:
Sign up for an API key (https://solcast.com/).

> Solcast may take up to 24hrs to create the account.

Configure your rooftop sites correctly at `solcast.com`.

Copy the API key for use with this integration (See [Configuration](#Configuration) below).

## Installation

### HACS *(recommended)*

Install as a Custom Repository using HACS. More info about HACS can be found [here](https://hacs.xyz/).  If you haven't installed HACS yet, go do it first!

The easiest way to install the integration is to click the button below (you will be prompted for your Home Assistant URL if you've never used this type of button before) to open this page in your Home Assistant HACS page.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=BJReplay&repository=ha-solcast-solar&category=integration)

You'll be prompted to confirm you want to open the repository inside HACS inside Home Assistant:

[<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/OpenPageinyourHomeAssistant.png">](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/OpenPageinyourHomeAssistant.png)

You'll see this page, with a `↓ Download` button near the bottom right - click on it:

[<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/Download.png">](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/Download.png)

You'll be prompted to download the Solcast PV Forecast component - click on `Download`:

[<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolcastPVSolar.png">](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolcastPVSolar.png)

Once it is installed, you'll probably notice a notification pop up on `Settings`:

[<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SettingsNotification.png">](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SettingsNotification.png)

Click on settings, and you should see a Repair notification for `Restart required`:

[<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/RestartRequired.png">](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/RestartRequired.png)

[<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/RestartSubmit.png">](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/RestartSubmit.png)

[<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SuccessIssueRepaired.png">](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SuccessIssueRepaired.png)

If you don't see this (you might be running an older version of Home Assistant), navigate to `System`, `Settings`, click on the power Icon, and `Restart Home Assistant`.  You need to restart Home Assistant before you can then install the custom component that you've just downloaded.

Once you've restarted, follow along at [Configuration](#configuration) to continue setting up the Solcast PV Forecast integration component.

### Installing manually in HACS  

More info [here](https://hacs.xyz/docs/faq/custom_repositories/)

1. (If using it, remove oziee/ha-solcast-solar in HACS)
1. Add custom repository (three verical dots menu, top right) `https://github.com/BJReplay/ha-solcast-solar` as an ```integration```
1. Search for 'Solcast' in HACS, open it and click the `Download` button
1. See [Configuration](#configuration) below

If previously using Oziee's ha-solcast-solar then all history and config should remain.

### Installing manually (not using HACS)

You probably **do not** want to do this! Use the HACS method above unless you know what you are doing and have a good reason as to why you are installing manually.

1. Using the tool of choice open the folder (directory) for your HA configuration (where you find `configuration.yaml`)
1. If you do not have a `custom_components` folder there, you need to create it
1. In the `custom_components` folder create a new folder called `solcast_solar`
1. Download _all_ the files from the `custom_components/solcast_solar/` folder in this repository
1. Place the files you downloaded in the new folder you created
1. *Restart HA to load the new integration*
1. See [Configuration](#configuration) below

## Configuration

1. [Click Here](https://my.home-assistant.io/redirect/config_flow_start/?domain=solcast_solar) to directly add a `Solcast Solar` integration **or**<br/>
 a. In Home Assistant, go to Settings -> [Integrations](https://my.home-assistant.io/redirect/integrations/)<br/>
 b. Click `+ Add Integrations`

[<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/AddIntegration.png">](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/AddIntegration.png)

 and start typing `Solcast PV Forecast` to bring up the Solcast PV Forecast integration, and select it.<br/>
 
 [<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/Setupanewintegration.png">](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/Setupanewintegration.png)

1. Enter your `Solcast API Key`, `API limit`, desired auto-update choice and click `Submit`. If you have more than one Solcast account because you have more than two rooftop setups, enter both account API keys separated by a comma `xxxxxxxx-xxxxx-xxxx,yyyyyyyy-yyyyy-yyyy` (_Note: this goes against Solcast T&C's by having more than one account_). If the API limit is the same for multiple accounts then enter a single value for that, or both values separated by a comma.
1. If an auto-update option was not chosen then create your own automation to call the service `solcast_solar.update_forecasts` at the times you would like to update the solar forecast.
1. Set up the Home Assistant Energy dashboard settings.
1. To change other configuration options after installation, select the integration in `Devices & services` then `CONFIGURE`.

Make sure you use your `API Key` and not your rooftop id created in Solcast. You can find your API key here [api key](https://toolkit.solcast.com.au/account).

[<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/install.png" width="500">](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/install.png)

> [!IMPORTANT]
> After the integration is started, review the Home Assistant log.
> 
> Should an error that gathering rooftop sites data has failed occur then this is almost certainly not an integration issue, rather an issue reaching the Solcast API on the Internet. The integration will repeatedly restart in this situation until the sites data can be loaded, as until configured sites data is acquired the integration cannot function.
>
> Once the sites data has been acquired at least once it is written to a cache file, and that cache will be used on subsequent startups should the Solcast API be temporarily unavailable.

### Auto-update of forecasts
Using auto-update will get forecast updates that are automatically spread across hours when the sun is up, or alternatively over a 24-hour period. It calculates the number of daily updates that will occur according to the number of Solcast sites and the API limit that is configured.

Should it be desired to fetch an update ouside of these hours, then the API limit in the integration configuration may be reduced, and an automation may then be set up to call the service `solcast_solar.force_update_forecasts` at the desired time of day. (Note that calling the service `solcast_solar.update_forecasts` will be refused if auto-update is enabled, so use force update instead.)

For example, to update just after midnight, as well as take advantage of auto-update, create the desired automation to force update, then reduce the API limit configured in the automation accordingly. (For this exmple, if the API key has ten total calls allowed per day and two rooftop sites, reduce the API limit to eight because two updates will be used when the automation runs.)

Using force update will not increment the API use counter, which is by design.

> [!NOTE]
> _Transitioning to auto-update from using an automation:_
>
> If currently using the recommended automation, which spreads updates fairly evenly between sunrise and sunset, turning on auto-update from sunrise to sunset should not cause unexpeced forecast fetch failures due to API limit exhaustion. The recommended automation is not identical to auto-update, but is fairly close in timing.
>
> If implementing a reduced API limit, plus a futher forced update at a different time of day (like midnight), then a 24-hour period of adjustment may be needed, which could possibly see API exhaustion reported even if the Solcast API usage count has not actually been exhausted. These errors will clear within 24 hours.

### Using an HA automation to poll for data
If auto-update is not enabled then create a new automation (or automations) and set up your prefered trigger times to poll for new Solcast forecast data. Use the service `solcast_solar.update_forecasts`. Examples are provided, so alter these or create your own to fit your needs.

<details><summary><i>Click here for the examples</i><p/></summary>

To make the most of the available API calls per day, you can have the automation call the API using an interval calculated by the number of daytime hours divided by the number of total API calls a day you can make.

This automation bases execution times on sunrise and sunset, which differ around the globe, so inherently spreads the load on Solcast. It is very similar to the behaviour of auto-update from sunrise to sunset, with the difference being that it also incorporates a randomised time offset, which will hopefully further avoid the likelihood that the Solcast servers get inundated by multiple callers at the same time.

```yaml
alias: Solcast update
description: ""
trigger:
  - platform: template
    value_template: >-
      {% set nr = as_datetime(state_attr('sun.sun','next_rising')) | as_local %}
      {% set ns = as_datetime(state_attr('sun.sun','next_setting')) | as_local %}
      {% set api_request_limit = 10 %}
      {% if nr > ns %}
        {% set nr = nr - timedelta(hours = 24) %} 
      {% endif %}
      {% set hours_difference = (ns - nr) %}
      {% set interval_hours = hours_difference / api_request_limit %}
      {% set ns = namespace(match = false) %}
      {% for i in range(api_request_limit) %}
        {% set start_time = nr + (i * interval_hours) %}
        {% if ((start_time - timedelta(seconds=30)) <= now()) and (now() <= (start_time + timedelta(seconds=30))) %}
          {% set ns.match = true %}
        {% endif %}
      {% endfor %}
      {{ ns.match }}
condition:
  - condition: sun
    before: sunset
    after: sunrise
action:
  - delay:
      seconds: "{{ range(30, 360)|random|int }}"
  - service: solcast_solar.update_forecasts
    data: {}
mode: single
```

> [!NOTE]
>
> 
> If you have two arrays on your roof then two api calls will be made for each update, effectively reducing the number of updates to five per day. For this case, change to: `api_request_limit = 5`

The next automation also includes a randomisation so that calls aren't made at precisely the same time, hopefully avoiding the likelihood that the Solcast servers are inundated by multiple calls at the same time, but it triggers every four hours between sunrise and sunset:

```yaml
alias: Solcast_update
description: New API call Solcast
trigger:
 - platform: time_pattern
   hours: /4
condition:
 - condition: sun
   before: sunset
   after: sunrise
action:
 - delay:
     seconds: "{{ range(30, 360)|random|int }}"
 - service: solcast_solar.update_forecasts
   data: {}
mode: single
```

The next automation triggers at 4am, 10am and 4pm, with a random delay.

```yaml
alias: Solcast update
description: ""
trigger:
  - platform: time
    at: "4:00:00"
  - platform: time
    at: "10:00:00"
  - platform: time
    at: "16:00:00"
condition: []
action:
  - delay:
      seconds: "{{ range(30, 360)|random|int }}"
  - service: solcast_solar.update_forecasts
    data: {}
mode: single
```
</details>

> [!TIP]
>
> 
> The Solcast Servers seem to occasionally be under some strain, and the servers return 429/Too busy return codes at these times. The integration will automatically pause, then retry the connection several times, but occasionally even this strategy can fail to download forecast data.
>
> Changing your API Key is not a solution, nor is uninstalling and re-installing the integration. These "tricks" might appear to work, but all that has actually happened is that you have tried again later, and the integration has worked as the Solcast servers are less busy.
> 
> To find out whether this is your issue look at the Home Assistant logs. To get detailed information (which is required when raising an issue) make sure that you have debug logging turned on.
>
> Log capture instructions are in the Bug Issue Template - you will see them if you start creating a new issue - make sure you include these logs if you want the assistance of the repository constributors.
>
> An example of busy messages and a successful retry are shown below (with debug logging enabled). In this case there is no issue, as the retry succeeds. Should ten consecutive attempts fail, then the forecast retrieval will end with an `ERROR`. If that happens, manually trigger another `solcast_solar.update_forecasts` service call (or if auto-update is enabled use `solcast_solar.force_update_forecasts`), or wait for the next scheduled update.
>
> Should the load of sites data on integration startup be the call that has failed with 429/Too busy, then the integration cannot start correctly, and it will retry continuously.

```
INFO (MainThread) [custom_components.solcast_solar.solcastapi] Getting forecast update for Solcast site 1234-5678-9012-3456
DEBUG (MainThread) [custom_components.solcast_solar.solcastapi] Polling API for rooftop_id 1234-5678-9012-3456
DEBUG (MainThread) [custom_components.solcast_solar.solcastapi] Fetch data url - https://api.solcast.com.au/rooftop_sites/1234-5678-9012-3456/forecasts
DEBUG (MainThread) [custom_components.solcast_solar.solcastapi] Fetching forecast
WARNING (MainThread) [custom_components.solcast_solar.solcastapi] Solcast API is busy, pausing 55 seconds before retry
DEBUG (MainThread) [custom_components.solcast_solar.solcastapi] Fetching forecast
DEBUG (MainThread) [custom_components.solcast_solar.solcastapi] API returned data. API Counter incremented from 35 to 36
DEBUG (MainThread) [custom_components.solcast_solar.solcastapi] Writing usage cache
DEBUG (MainThread) [custom_components.solcast_solar.solcastapi] HTTP ssession returned data type in fetch_data() is <class 'dict'>
DEBUG (MainThread) [custom_components.solcast_solar.solcastapi] HTTP session status in fetch_data() is 200/Success
```

### Set up HA energy dashboard settings

Go to `Settings`, `Dashboards`, `Energy`

Edit the `Solar Panels` `Solar production` item you have previously created (or will create now). Do not add a separate `Solar production` item, or things will just get weird.

> [!IMPORTANT]  
> If you do not have a solar generation sensor in your system then this integration will not work in the Energy dashboard. The graph, and adding the forecast integration rely on there being a generation sensor set up.

[<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolarPanels.png" width="500">](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolarPanels.png)

Select `Forecast Production` and select the `Solcast Solar` option. Click `SAVE`, and Home Assistant will do the rest for you.

[<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolcastSolar.png" width="500">](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolcastSolar.png)

### HA energy dashboard

[<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/solar_production.png">](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/solar_production.png)

### Dampening configuration

It is possible to configure periodic dampening values to account for shading. This may be configured by automation or the integration configuration for total dampening (overall hourly dampening only in configuration).

Dampening is applied to future forecasts whenever a forecast is fetched, so forecast history retains the dampening that had been applied at the time.

> [!NOTE]
>
> Retained dampened historical forecasts is a recent change, and may require automation modification to read undampened forecast history instead. See [Reading forecast values in an automation](#reading-forecast-values-in-an-automation) and [Changes](#changes) below.

Per-site and per-half hour dampening is possible only by using service calls or modifying a dampening configration file. See [Granular dampening](#granular-dampening) below.

[<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/reconfig.png">](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/reconfig.png)

[<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/damp.png" width="500">](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/damp.png)

You can change the dampening factor value for any hour. Values from 0.0 - 1.0 are valid. Setting 0.95 will dampen each Solcast forecast data value by 5%. This is reflected in the sensor values and attributes and also in the Home Assistant Energy dashboard.

[<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/dampopt.png" width="500">](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/dampopt.png)

> [!TIP]
>
> 
> Most users of dampening configuration do not enter values in the configuration settings directly. Rather, they build automations to set values that are appropriate for their location at different days or seasons, and these call the `solcast_solar.set_dampening` service.
>
> 
> Factors causing dampening to be appropriate might be when different degrees of shading occur at the start or end of a day in Winter only, where the sun is closer to the horizon and might cause nearby buildings or trees to cast a longer shadow than in other seasons.

#### Granular dampening

Setting dampening for individual Solcast sites, or using half-hour intervals is possible. This requires use of either the `solcast_solar.set_dampening` service, or creation/modification of a file in the Home Assistant config folder called `solcast-dampening.json`.

The service call accepts a string of dampening factors, and also an optional site identifier. For hourly dampening supply 24 values. For half-hourly 48. Calling the service creates or updates the file `solcast-dampening.json` when either a site is specified, or 48 factor values are specified. If setting overall dampening with 48 factors then an optional 'all' site may be specified (or simply omitted for this use case).

```
action: solcast_solar.set_dampening
data:
  damp_factor: 1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1
  #site: 1234-5678-9012-3456
```

If a site is not specified, and 24 dampening values are given then granular dampening will be removed, and the overall configured hourly dampening will apply to all sites. (Granular dampening may also be disabled using the integration `CONFIGURE` dialogue.)

If granular dampening is configured for a single site in a multi-site set up then that dampening will only apply to the forecasts for that site. Other sites will not be dampened.

Dampening for all individual sites may of course be set, and when this is the case all sites must specify the same number of dampening values, either 24 or 48.

#### Granular dampening file examples

<details><summary><i>Click for examples of dampening files</i></summary>

The following examples can be used as a starter for the format for file-based granular dampening. Make sure that you use your own site IDs rather than the examples. The file should be saved in the Home Assistant config folder and named `solcast-dampening.json`.

Example of hourly dampening for two sites:

```
{
  "1111-aaaa-bbbb-2222": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0],
  "cccc-4444-5555-dddd": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0]
}
```

Example of hourly dampening for a single site:

```
{
  "eeee-6666-7777-ffff": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0]
}
```

Example of half-hourly dampening for two sites:

```
{
  "8888-gggg-hhhh-9999": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0],
  "0000-iiii-jjjj-1111": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0]
}

Example of half-hourly dampening for all sites:

{
  "all": [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0]
}
```
</details>

#### Reading forecast values in an automation

When calculating dampening using an automation it may be beneficial to use undampened forecast values as input.

This is possible by using the service call `solcast_solar.query_forecast_data`, and including `undampened: true` in the call. If using granular dampening then the site may also be included in the call.

```
action: solcast_solar.query_forecast_data
data:
  start_date_time: 2024-10-08T12:00:00+11:00
  end_date_time: 2024-10-08T19:00:00+11:00
  undampened: true
  #site: 1111-aaaa-bbbb-2222
```

Undampened forecast history is retained for just 14 days.

#### Reading dampening values

The currently set dampening factors may be retrieved using the service call "Solcast PV Forecast: Get forecasts dampening" (`solcast_solar.get_dampening`). This may specify an optional site, or specify no site or the site 'all'. Where no site is specified then all sites with dampening set will be returned. An error is raised should a site not have dampening set.

If granular dampening is set to specify both individual site factors and an 'all' factors, then attempting retrieval of an individual site factors will result in the 'all' factors being returned, with the 'all' site being noted in the response. This is because an 'all' set of factors overrides the individual site settings in this circumstance.

Example call:

```
action: solcast_solar.get_dampening
data:
  site: b68d-c05a-c2b3-2cf9
```

Example response:

```
data:
  - site: b68d-c05a-c2b3-2cf9
    damp_factor: >-
      1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0
```

### Sensor attributes configuration

There are quite a few sensor attributes that can be used as a data source for template sensors, charts, etc., including a per-site breakdown, estimate 10/50/90 values, and per-hour and half hour detailed breakdown for each forecast day.

Many users will not use these attributes, so to cut the clutter (especially in the UI and also database statistics storage) generation all of these can be disabled if they are not needed.

By default, all of them are enabled, with the exception of per-site detailedForecast and detailedHourly. (All hourly and half-hourly detail attributes are excluded from being sent to the Home Assistant recorder, as these attributes are very large, would result in excessive database growth, and are of little use when considered long-term.)

> [!NOTE]
>
> 
> If you want to implement the sample PV graph below then you'll need to keep half-hourly detail breakdown enabled, along with `estimate10`.

### Hard limit configuration

There is an option to set a "hard limit" for projected inverter output, and this limit will 'clip' the Solcast forecasts to a maximum value.

The scenario requiring use of this limit is straightforward, but note that hardly any PV installations will need to do so. (And if you have micro-inverters, or one inverter per string then definitely not. The same goes for all panels with identical orientation in a single Solcast site.)

Consider a scenario where you have a single 6kW string inverter, and attached are two strings each of 5.5kW potential generation pointing in separate directions. This is considered "over-sized" from an inverter point of view. It is not possible to set an AC generation limit for Solcast that suits this scenario when configured as two sites, as in the mid-morning or afternoon in Summer a string may in fact be generating 5.5kW DC, with 5kW AC resulting, and the other string will probably be generating as well. So setting an AC limit in Solcast for each string to 3kW (half the inverter) does not make sense. Setting it to 6kW for each string also does not make sense, as Solcast will almost certainly over-state potential generation.

The hard limit may be set in the integration configuration, or set via a service call in `Developer Tools`.

## Key Solcast concepts

Solcast will produce a forecast of solar PV generation for today, tomorrow, the day after (day 3), ... up to day 7.
Each of these forecasts will be in a separate sensor (see [Sensors](#sensors) below) and the sensor value will be the total predicted solar generation for your Solcast account for each day.
Separate sensors contain peak solar generation power, peak solar generation time, and various forecasts of next hour, 30 minutes, etc.

If you have multiple arrays on different roof orientations, these can be configured in Solcast as separate 'sites' with differing azimuth, tilt and generation, to a maximum of two sites for a free hobbyist account.

Three solar PV generation estimates are produced by the Solcast integration:
- 'central' or 50% or most likely to occur PV forecast (or the `forecast`),
- '10%' or 1 in 10 'worst case' PV forecast assuming more cloud coverage (`forecast10`)
- '90%' or 1 in 10 'best case' PV forecast assuming less cloud coverage (`forecast90`)

The detail of these different forecast estimates can be found in sensor attributes, broken down by 30 minute and hourly invervals across the day. Separate attributes sum the different estimates for each day.

## Services, sensors, configuration, diagnostic

### Services
These are the services for this integration: ([Configuration](#configuration))

| Service | Action |
| --- | --- |
| `solcast_solar.update_forecasts` | Updates the forecast data (refused if auto-update is enabled) |
| `solcast_solar.force_update_forecasts` | Force updates the forecast data (performs an update regardless of API usage tracking or auto-update setting, and does not increment the API use counter) |
| `solcast_solar.clear_all_solcast_data` | Deletes the `solcast.json` cached file |
| `solcast_solar.query_forecast_data` | Returns a list of forecast data using a datetime range start - end |
| `solcast_solar.set_dampening` | Updates the dampening factors |
| `solcast_solar.get_dampening` | Get the currently set dampening factors |
| `solcast_solar.set_hard_limit` | Set inverter forecast hard limit |
| `solcast_solar.remove_hard_limit` | Remove inverter forecast hard limit |

### Sensors

| Name | Type | Attributes | Unit | Description |
| ------------------------------ | ----------- | ----------- | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | 
| `Today` | number | Y | `kWh` | Total forecast solar production for today |
| `Tomorrow` | number | Y | `kWh` | Total forecast solar production for day + 1 (tomorrow) |
| `D3` | number | Y | `kWh` | Total forecast solar production for day + 2 (day 3) |
| `D4` | number | Y | `kWh` | Total forecast solar production for day + 3 (day 4) |
| `D5` | number | Y | `kWh` | Total forecast solar production for day + 4 (day 5) |
| `D6` | number | Y | `kWh`| Total forecast solar production for day + 5 (day 6) |
| `D7` | number | Y | `kWh` | Total forecast solar production for day + 6 (day 7) |
| `This Hour` | number | Y | `Wh` | Forecasted solar production current hour (attributes contain site breakdown) |
| `Next Hour` | number | Y | `Wh` | Forecasted solar production next hour (attributes contain site breakdown) |
| `Forecast Next X Hours` | number | Y | `Wh` | Custom user defined forecasted solar production for next X hours<br>Note: This forecast starts at current time, it is not aligned on the hour like "This hour", "Next Hour". |
| `Remaining Today` | number | Y | `kWh` | Predicted remaining solar production today |
| `Peak Forecast Today` | number | Y | `W` | Highest predicted production within an hour period today (attributes contain site breakdown) |
| `Peak Time Today` | date/time | Y |  | Hour of max forecasted production of solar today (attributes contain site breakdown) |
| `Peak Forecast Tomorrow` | number | Y | `W` | Highest predicted production within an hour period tomorrow (attributes contain site breakdown) |
| `Peak Time Tomorrow` | date/time | Y |  | Hour of max forecasted production of solar tomorrow (attributes contain site breakdown) |
| `Power Now` | number | Y | `W` | Predicted nominal solar power this moment (attributes contain site breakdown) |
| `Power in 30 Mins` | number | Y | `W` | Predicted nominal solar power in 30 minutes (attributes contain site breakdown) |
| `Power in 1 Hour` | number | Y | `W` | Predicted nominal solar power in 1 hour (attributes contain site breakdown) |

> [!NOTE]
>
> 
> Where a site breakdown is available as an attribute, the attribute name is the Solcast site resource ID.
>
> 
> Most sensors also include an attribute for `estimate`, `estimate10` and `estimate90`. Template sensors may be created to expose their value, or the `state_attr()` can be used directly in automations.
>
> 
> Access these in a template sensor or automation using something like:
>
> 
> ```
> {{ state_attr('sensor.solcast_pv_forecast_peak_forecast_today', '1234-5678-9012-3456') | float(0) }}
> {{ state_attr('sensor.solcast_pv_forecast_peak_forecast_today', 'estimate10') | float(0) }}
> {{ state_attr('sensor.solcast_pv_forecast_peak_forecast_today', 'estimate10-1234-5678-9012-3456') | float(0) }}
> ```
>
> 
> Also see the sample PV graph below for how to chart forecast detail from the detailedForecast attribute.

> [!NOTE]
>
> 
> The values for `Next Hour` and `Forecast Next X Hours` may be different if the custom X hour setting is 1. This has a simple explanation.
>
> 
> They are calculated using a different start and end time. One is from the start of this hour, i.e. in the past, e.g. 14:00:00 to 15:00:00. The custom sensor is from now() on five minute boudaries, e.g. 14:20:00 to 15:20:00 using interpolated values.
>
> 
> This will likely yield a different result, depending on the time the value is requested, so it is not wrong. It's just different.

### Configuration

| Name | Type | Attributes | Unit | Description |
| ------------------------------ | ----------- | ----------- | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | 
| `Forecast Field` | selector | N |  | Selector to select the Solcast value field for calculations either 'estimate', 'estimate10' or 'estimate90' |

### Diagnostic

| Name | Type | Attributes | Unit | Description |
| ------------------------------ | ----------- | ----------- | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | 
| `API Last Polled` | date/time | N |  | Date/time when the API data was polled |
| `API Limit` | number | N | `integer` | Total times the API can been called in a 24 hour period[^1] |
| `API used` | number | N | `integer` | Total times the API has been called today (API counter resets to zero at midnight UTC)[^1] |  
| `Hard Limit Set` |  | N |  | `False` is not set, else set integer value in `watts`. Can only be set or removed by service ([services](#services))|
| `Rooftop(s) name` | number | Y | `kWh` | Total forecast for rooftop today (attributes contain the solcast rooftop setup)[^2] |

[^1]: API usage information is directly read from Solcast
[^2]: Each rooftop created in Solcast will be listed separately

## Sample HA dashboard graph

The following YAML produces a graph of today's PV generation, PV forecast and PV10 forecast. Requires [Apex Charts](https://github.com/RomRider/apexcharts-card) to be installed.

[<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/forecast_today.png">](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/forecast_today.png)

Customise with appropriate Home Assistant sensors for today's total solar generation and solar panel PV power output.

> [!NOTE]
>
> 
> The chart assumes that your Solar PV sensors are in kW, but if some are in W, add the line `transform: "return x / 1000;"` under the entity id to convert the sensor value to kW.

### Reveal code
<details><summary><i>Click here</i></summary>

```yaml
type: custom:apexcharts-card
header:
  title: Solar forecast
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
graph_span: 24h
span:
  start: day
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
  - entity: sensor.SOLAR_POWER
    name: Solar Power (now)
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
    name: Forecast
    color: Grey
    opacity: 0.3
    stroke_width: 0
    type: area
    time_delta: +15min
    extend_to: false
    yaxis_id: kWh
    show:
      legend_value: false
      in_header: false
    data_generator: |
      return entity.attributes.detailedForecast.map((entry) => {
            return [new Date(entry.period_start), entry.pv_estimate];
          });
  - entity: sensor.solcast_pv_forecast_forecast_today
    name: Forecast 10%
    color: Grey
    opacity: 0.3
    stroke_width: 0
    type: area
    time_delta: +15min
    extend_to: false
    yaxis_id: kWh
    show:
      legend_value: false
      in_header: false
    data_generator: |
      return entity.attributes.detailedForecast.map((entry) => {
            return [new Date(entry.period_start), entry.pv_estimate10];
          });
  - entity: sensor.SOLAR_GENERATION_ENERGY_TODAY
    yaxis_id: header_only
    name: Today Actual
    stroke_width: 2
    color: Orange
    show:
      legend_value: true
      in_header: true
      in_chart: false
  - entity: sensor.solcast_pv_forecast_forecast_today
    yaxis_id: header_only
    name: Today Forecast
    color: Grey
    show:
      legend_value: true
      in_header: true
      in_chart: false
  - entity: sensor.solcast_pv_forecast_forecast_today
    attribute: estimate10
    yaxis_id: header_only
    name: Today Forecast 10%
    color: Grey
    opacity: 0.3
    show:
      legend_value: true
      in_header: true
      in_chart: false
  - entity: sensor.solcast_pv_forecast_forecast_remaining_today
    yaxis_id: header_only
    name: Remaining
    color: Grey
    show:
      legend_value: true
      in_header: true
      in_chart: false
```
</details>


## Known issues

* None

## Changes

v4.2.1
* Fix an issue that causes changing Solcast accounts to fail by @autoSteve
* Fix an issue with multi-API key where API usage reset was not handled correctly by @autoSteve
* Fix an issue with enabled detailed site breakdown for hourly attributes by @autoSteve
* Code clean-up and some refactoring by @autoSteve

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.2.0...v4.2.1

v4.2.0
* Generally available release of v4.1.8 and v4.1.9 pre-release features
* Translations of service call error responses by @autoSteve

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.7...v4.2.0

Most recent changes: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.9...v4.2.0

v4.1.9 pre-release
* Granular dampening to dampen per half hour period by @autoSteve and @isorin
* Dampening applied at forecast fetch and not to forecast history @autoSteve and @isorin
* Retrieve un-dampened forecast values using service call by @autoSteve (thanks @Nilogax)
* Get presently set dampening factors using service call by @autoSteve (thanks @Nilogax)
* Migration of un-dampened forecast to un-dampened cache on startup by @autoSteve

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.9...v4.1.9

v4.1.8 pre-release
* Automated forecast updates that do not require an automation by @autoSteve and @BJReplay
* Add per-site dampening by @autoSteve
* Add site breakdown option for detailed forecasts by @autoSteve
* Add hard limit configuration to options by @autoSteve
* Suppress integration reload when many configuration options are changed by @autoSteve

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.7...v4.1.8

v4.1.7
* Fix issues with site breakdown for sites added at a later date by @autoSteve
* Fix issues with site breakdown for splined sensors by @autoSteve

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.6...v4.1.7

v4.1.6
* Simplify configure dialogue by @autoSteve

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.5...v4.1.6

v4.1.5 pre-release
* Bug: Timestamp stored in usage cache was wrong by @autoSteve
* Bug: Adding API key reset usage for first key by @autoSteve
* Bug: Missing iterator in new sites check by @autoSteve
* Work around a possible HA scheduling bug by @autoSteve
* Code style alignment to HA style guidelines by @autoSteve

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.4...v4.1.5

v4.1.4 pre-release
* Update Polish translation by @home409ca
* Rename integration in HACS to Solcast PV Forecast by @BJReplay
* Reduce aiofiles version requirement to >=23.2.0 by @autoSteve
* Configuration dialog improvements by @autoSteve
* Misc translation updates by @autoSteve
* Refactor moment and remaining spline build by @autoSteve
* Prevent negative forecast for X hour sensor by @autoSteve
* Suppress spline bounce for reducing spline by @autoSteve
* More careful serialisation of solcast.json by @autoSteve
* Monitor last updated timestamp for sites-usage.json by @autoSteve
* Extensive code clean-up by @autoSteve
 
Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.3...v4.1.4

v4.1.3
* Accommodate the removal of API call GetUserUsageAllowance by @autoSteve
* Halve retry delays by @autoSteve
* Readme improvements by @autoSteve

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.2...v4.1.3

v4.1.2
* Fifteen minute shift, because 30-minute averages by @autoSteve
* Increase forecast fetch attempts to ten by @autoSteve
* Move images to screenshots by @BJReplay
* Fix readme images not displaying in HACS frontend

Replaces v4.1.1

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.1.0...v4.1.2

v4.1
* First major release since v4.0.31 that wasn't tagged as a pre-release
* Those other releases have mostly been pretty stable, but we're confident that this release is ready for everyone
* Changes since v4.0.31:
  * Greatly improved stability for all, and initial start-up experience for new users
  * Additional sensor attributes
  * New configuration options to suppress sensor attributes
  * Redaction of sensitive information in debug logs
  * Improved efficiency, with many sensors calculated in five-minute intervals, some only when forecasts are fetched
  * Spline interpolation for ‘momentary’ and ‘period’ sensors
  * Fixes for multi-API key users
  * Fixes for Docker users
  * Exception handling improvements
  * Logging improvements
* @autoSteve is welcomed as a CodeOwner
* It is now apparent that it is unlikely that this repo will be added as a default repo in HACS until HACS 2.0 is out, so the installation instructions make it clear that adding via the Manual Repository flow is the preferred approach, and new instructions have been added to show how to do this.

Release Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.31...v4.1.0

Most recent changes: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.43...v4.1.0

### Prior changes
<details><summary><i>Click here for changes back to v3.0</i></summary>

v4.0.43
* Auto-fetch on startup when stale forecast data is detected by @autoSteve

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.42...v4.0.43

v4.0.42
* Initial sites load fail reporting and HA auto-retries by @autoSteve
* Suppress spline bounce in moment splines by @autoSteve
* Recalculate splines at midnight before sensors update by @autoSteve
* Readme updates by @autoSteve
* Dampening and hard limit removed from per-site forecast breakdowns (too hard, too misleading) by @autoSteve

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.41...v4.0.42

v4.0.41
* Interpolated forecast 0/30/60 fix #101 by @autoSteve
* Ensure config directory is always relative to install location #98 by @autoSteve
* Add state_class to `power_now_30m` and `power_now_1hr` to match `power_now` by @autoSteve (will remove LTS, but LTS is not useful for these sensors)
* Utilise daily splines of momentary and reducing forecast values by @autoSteve

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.40...v4.0.41

v4.0.40
* Interpolated forecast 0/30/60 power and energy X hours by @autoSteve
* Ensure config directory is always relative to install location by @autoSteve
* Sample PV chart enhancements by @gcoan

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.39...v4.0.40

v4.0.39
* Updates to sensor descriptions, and alter some sensor names by @isorin (Potentially breaking for UI/automations/etc. should these these sensors be in use. Power in 30/60 minutes, and custom X hours sensor.)
* Remove dependency on scipy library by @autoSteve
* Add granular configuration options for attributes by @autosteve

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.38...v4.0.39

v4.0.38
* Add Solcast key concepts and sample PV generation graph to readme by @gcoan
* Add PCHIP spline to forecast remaining by @autoSteve

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.37...v4.0.38

v4.0.37
* Alter attribute naming to remove "pv_" by @autoSteve (note: breaking if new attributes have already been used in templates/automations)
* Sensor attribute rounding #51 by @autoSteve
* Improve exception handling for forecast fetch by @autoSteve
* Further improve exception handling for forecast fetch by @autoSteve
* Replace exception with a warning #74 by @autoSteve
* Retry an unexplained cache/initial data load by @autoSteve
* Less shouty debug logging by @autoSteve

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.36...v4.0.37

v4.0.36
* (Enhancement) Additional sensor attributes (estimate/estimate10/estimate90) and logging improvements by @autoSteve

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.35...v4.0.36

v4.0.35
* (Enhancement) Breakdown of individual site forecast wattage and time as attributes by @autoSteve
* Do not log options version upgrade if no upgrade is required by @autoSteve
* Add info about preserving oziee history and config to banner by @iainfogg

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.34...v4.0.35

v4.0.34
* Fix query_forecast_data so that near-term historical forecasts are returned by @isorin
* Instantly fall-back to cache on reload if rooftop/usage API calls fail, which can reduce start time by @autoSteve
* An async call timeout of sites get will fall back to cache if it exists by @autoSteve
* Much logging improvements by @autoSteve
* Sites cache being sometimes incorrectly created with the API key appended, despite only having one API key by @autoSteve
* Redaction of latitude/longitude in debug logs by @autoSteve
* Likely elimination of 'tally' warnings by @autoSteve
* Fix API usage retry mechanism by @autoSteve

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.33...v4.0.34

v4.0.33
* Performance improvements for sensor updates by @isorin, including:
  * Reduced the update interval of sensors to 5 minutes
  * Split the sensors into two groups: sensors that need to be updated every 5 minutes and sensors that need to be updated only when the data is refreshed or the date changes (daily values)
  * Fixed issues with removing the past forecasts (older than 2 years), broken code
  * Improve the functionality of the forecasts, for exmaple "forecast_remaining_today" is updated every 5 minutes by calculating the remaining energy from the current 30 minute interval. Same for "now/next hour" sensors.
* Redaction of Solcast API key in logs by @isorin
* Revert Oziee '4.0.23' async_update_options #54 by @autoSteve, which was causing dampening update issues

A comment from @isorin: "_I use the forecast_remaining_today to determine the time of the day when to start charging the batteries so that they will reach a predetermined charge in the evening. With my changes, this is possible._"

To that, I say nicely done.

New Contributors
* @isorin made their first contribution in https://github.com/BJReplay/ha-solcast-solar/pull/45

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.32...v4.0.33

v4.0.32
- Bug fix: Independent API use counter for each Solcast account by @autoSteve
- Bug fix: Force all caches to /config/ for all platforms (fixes Docker deployments) #43 by @autoSteve
- Improve forecast fetch/retry logging debug, info, warning choice by @autoSteve
- Suppression of consecutive forecast fetches within fifteen minutes (fixes strange mutliple fetches should a restart occur exactly when automation for fetch is triggered) by @autoSteve
- Work-around: Prevent error when 'tally' is unavailable during retry by #autoSteve
- Fix for earlier HA versions not recognising version= for async_update_entry() #40 by autoSteve

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.31...v4.0.32

v4.0.31
- docs: Changes to README.md
- docs: Add troubleshooting notes.
- docs: Combine Changes Notes from info.md into README.md
- docs: Set up so that HACS displays README.md

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.30...v4.0.31

v4.0.30
- Bug fix: Support multiple Solcast account sites caching
- Bug fix: Retry mechanism when rooftop sites gather is actually successful was broken

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.29...v4.0.30

v4.0.29
- Bug fix: Write API usage cache on every successful poll by @autoSteve in https://github.com/BJReplay/ha-solcast-solar/pull/29
- Bug fix: Default API limit to 10 to cope with initial call fail by @autoSteve
- Increase sites GET retries from two to three by @autoSteve

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.28...v4.0.29

v4.0.28
- Add retry for rooftop sites collection #12 by @autoSteve in https://github.com/BJReplay/ha-solcast-solar/pull/26
- Full info.md changes since v4.0.25
- Re-incorporate most v4.0.23 oziee changes by @autoSteve 
- Retain cached data when API limit reached

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.27...v4.0.28

New Collaborator

- @autoSteve has made a huge contribution over the last few days - he has a sponsor button on his profile, so don't be afraid to mash it!

v4.0.27
- docs: Update info.md by @Kolbi in https://github.com/BJReplay/ha-solcast-solar/pull/19
- Use aiofiles with async open, await data_file by @autoSteve in https://github.com/BJReplay/ha-solcast-solar/pull/21
- Add support for async_get_time_zone() by @autoSteve in https://github.com/BJReplay/ha-solcast-solar/pull/25

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.26...v4.0.27

New Contributors
- @Kolbi made their first contribution in https://github.com/BJReplay/ha-solcast-solar/pull/19
- @autoSteve made their first contribution in https://github.com/BJReplay/ha-solcast-solar/pull/21

v4.0.26
- Fixes #8 #9 #10 - My HA Button category by @mZ738 in https://github.com/BJReplay/ha-solcast-solar/pull/11
- Update README.md by @wimdebruyn in https://github.com/BJReplay/ha-solcast-solar/pull/5
- Prepare for new Release by @BJReplay in https://github.com/BJReplay/ha-solcast-solar/pull/13

Full Changelog: https://github.com/BJReplay/ha-solcast-solar/compare/v4.0.25...v4.0.26
 
New Contributors
* @mZ738 made their first contribution in https://github.com/BJReplay/ha-solcast-solar/pull/11
* @wimdebruyn made their first contribution in https://github.com/BJReplay/ha-solcast-solar/pull/5  

v4.0.25
- HACS Submission

v4.0.24
- More changes to remove links to https://github.com/oziee that were missed the first time around
- More changes to prepare to submit to HACSs

v4.0.23
- Changed Owner to @BJReplay
- Changed Github Repo to https://github.com/BJReplay/ha-solcast-solar

v4.0.22
- this time weather sensor is gone.. and midnight UTC reset works
- (*)added a config for setting a hard limit for inverters with over sized solar arrays 
   *99.9999999% of users will not need to ever user and set this (0.00000001% is @CarrapiettM)

v4.0.21
- removed weather sensor as it keeps failing with errors

v4.0.20
- fixed the info error for `solcast_pv_forecast_forecast_today (<class 'custom_components.solcast_solar.sensor.SolcastSensor'>) is using state class 'measurement' which is impossible considering device class ('energy')`
- removed the midnight UTC fetch and replaced with set to zero to reduce the polling on Solcast system
⚠️ To help reduce impact on the Solcast backend, Solcast have asked that users set their automations for polling with a random min and sec timing.. if you are polling at say 10:00 set it to 10:04:10 for instance so that everyone is not polling the services at the same time

v4.0.19
- fix resetting api limit/usage not updating HA UI

v4.0.18
- fixed weather sensor value not persisting 
- reset the api limit and usage sensors at UTC midnight (reset usage)

v4.0.17
- updated Slovak translation thanks @misa1515
- added sensor for Solcast weather description

v4.0.16
- added @Zachoz idea of adding a setting to select which solcast estimate field value for the forecast calculations, either estimate, estimate10 or estimate90
    ESTIMATE - Default forecasts
    ESTIMATE10 = Forecasts 10 - cloudier than expected scenario  
    ESTIMATE90 = Forecasts 90 - less cloudy than expected scenario  

v4.0.15
- added custom 'Next X hours' sensor. You select the number of hours to be calculated as the sensor
- added French translation thanks to @Dackara
- added some sensors to be included in HA statistics data

v4.0.14
- changed attrib values from rooftop sites so pins are not added to maps (HA auto adds item to the map if attributes contain lat/long values)
- added Urdu thanks to @yousaf465

v4.0.13
- added Slovak translation thanks to @misa1515
- extended polling connection timeout from 60s to 120s
- added some more debug output points for data checking
- new forecast data attribute `dataCorrect` returns True of False if the data is complete for that day.
- removed `0 of 48` debug message for the 7th day forecast because if the api is not polled at midnight then the data is not complete for the 7th day (limitation of the max records Solcast returns)

v4.0.12
- HA 2023.11 beta forces sensors not to be listed under `Configuration`. The rooftop sensors have been moved to `Diagnostic`

v4.0.11
- better handling when data is missing pieces for some sensors

v4.0.10
- fixes for changing API key once one has previously been set

v4.0.9
- new service to update forecast hourly dampening factors

v4.0.8
- added Polish translation thanks to @home409ca
- added new `Dampening` to the Solcast Integration configuration

v4.0.7
- better handling when Solcast site does not return API data correctly

v4.0.6
- fixed divide by zero errors if there is no returned data
- fixed renaining today forecast value. now includes current 30min block forecast in the calculation

v4.0.5
- PR #192 - updated German translation.. thanks @florie1706
- fixed `Remaining Today` forecast.. it now also uses the 30min interval data
- fixed `Download diagnostic` data throwing an error when clicked

v4.0.4
- finished off the service call `query_forecast_data` to query the forecast data. Returns a list of forecast data using a datetime range start - end
- and thats all.. unless HA makes breaking changes or there is a major bug in v4.0.4, this is the last update

v4.0.3
- updated German thanks to @florie1706 PR#179 and removed all other localisation files
- added new attribute `detailedHourly` to each daily forecast sensor listing hourly forecasts in kWh
- if there is data missing, sensors will still show something but a debug log will outpout that the sensor is missing data


v4.0.2
- sensor names **have** changed!! this is due to locali(s/z)ation strings of the integration
- decimal percision changed for forecast tomorrow from 0 to 2
- fixed 7th day forecast missing data that was being ignored
- added new sensor `Power Now`
- added new sensor `Power Next 30 Mins`
- added new sensor `Power Next Hour`
- added locali(s/z)ation for all objects in the integation.. thanks to @ViPeR5000 for getting me started on thinking about this (google translate used, if you find anything wrong PR and i can update the translations)

v4.0.1
- rebased from 3.0.55
- keeps the last 730 days (2 years) of forecast data
- some sensors have have had their device_class and native_unit_of_measurement updated to a correct type
- API polling count is read directly from Solcast and is no longer calcuated
- no more auto polling.. its now up to every one to create an automation to poll for data when you want. This is due to so many users now only have 10 api calls a day
- striped out saving UTC time changing and keeping solcast data as it is so timezone data can be changed when needed
- history items went missing due to the sensor renamed. no longer using the HA history and instead just dtoring the data in the solcast.json file
- removed update actuals service.. actuals data from solcast is no longer polled (it is used on the first install to get past data so the integration works and i dont get issue reports because solcast do not give full day data, only data from when you call)
- lots of the logging messages have been updated to be debug,info,warning or errors
- some sensors **COULD** possibly no longer have extra attribute values or attribute values may have been renamed or have changed to the data storaged within
- greater in depth diagnostic data to share when needed to help debug any issues
- some of @rany2 work has been now integrated

Removed 3.1.x
- too many users could not handle the power of this release
- v4.x.x replaces 3.0.55 - 3.1.x with new changes

v3.0.47
- added attribute weekday name for sensor forecasts, today, tomorrow, D3..7
  can read the names via the template 
{{ state_attr('sensor.solcast_forecast_today', 'dayname') }}
{{ state_attr('sensor.solcast_forecast_today', 'dayname') }}
{{ state_attr('sensor.solcast_forecast_tomorrow', 'dayname') }}
{{ state_attr('sensor.solcast_forecast_D3', 'dayname') }}
{{ state_attr('sensor.solcast_forecast_D4', 'dayname') }}
{{ state_attr('sensor.solcast_forecast_D5', 'dayname') }}
{{ state_attr('sensor.solcast_forecast_D6', 'dayname') }}
{{ state_attr('sensor.solcast_forecast_D7', 'dayname') }}

v3.0.46
- possile Maria DB problem - possible fix

v3.0.45
- pre release
- currently being tested 
- wont hurt anything if you do install it

v3.0.44
- pre release
- better diagnotic data
- just for testing
- wont hurt anything if you do install it

v3.0.43
- pre release not for use!!
- do not install :) just for testing

v3.0.42
- fixed using the service to update forecasts from calling twice

v3.0.41
- recoded logging. Re-worded. More debug vs info vs error logging.
- API usage counter was not recorded when reset to zero at UTC midnight
- added a new service where you can call to update the Solcast Actuals data for the forecasts
- added the version info to the intergation UI

v3.0.40
- someone left some unused code in 3.0.39 causing problems

v3.0.39
- removed version info

v3.0.38
- error with v3.0.37 fix for updating sensors

v3.0.37
- make sure the hourly sensors update when auto polling is disabled

v3.0.36
- includes all pre release items
- actual past accurate data is now set to only poll the API at midday and last hour of the day (so only twice a day)

v3.0.35 - PRE RELEASE
- extended the internet connection timeout to 60s

v3.0.34 - PRE RELEASE
- added service to clear old solcast.json file to have a clean start
- return empty energy graph data if there is an error generating info

v3.0.33
- added sensors for forecast days 3,4,5,6,7

v3.0.32
- refactored HA setup function call requirements
- refactored some other code with typos to spell words correctly.. no biggie

v3.0.30
- merged in some work by @696GrocuttT PR into this release
- fixed code to do with using up all allowed api counts
- this release will most likely stuff up the current API counter, but after the UTC counter reset all will be right in the world of api counting again

v3.0.29
- changed Peak Time Today/Tomorrow sensor from datetime to time
- changed back the unit for peak measurement to Wh as the sensor is telling the peak/max hours generated forecast for the hour
- added new configuration option for the integration to disable auto polling. Users can then setup their own automation to poll for data when they like (mostly due to the fact that Solcast have changed the API allowance for new accounts to just 10 per day)
- API counter sensor now shows total used instead of allowance remaining as some have 10 others 50. It will 'Exceeded API Allowance' if you have none left


v3.0.27
- changed unit for peak measurement #86 tbanks Ivesvdf
- some other minor text changes for logs
- changed service call thanks 696GrocuttT
- including fix for issue #83

v3.0.26
- testing fix for issue #83

v3.0.25
- removed PR for 3.0.24 - caused errors in the forecast graph
- fixed HA 2022.11 cant add forcast to solar dashboard

v3.0.24
- merged PR from @696GrocuttT 

v3.0.23
- added more debug log code
- added the service to update forecast

v3.0.22
- added more debug log code

v3.0.21
- added more debug logs for greater info

v3.0.19
- FIX: coordinator.py", line 133, in update_forecast for update_callback in self._listeners: RuntimeError: dictionary changed size during iteration
- this version needs HA 2022.7+ now

v3.0.18
- changed api counter return value calculations

v3.0.17
- set the polling api time to 10mins after the hour to give solcast api time to calculate satellite data

v3.0.16
- fixed api polling to get actual data once in a while during the day
- added full path to data file - thanks OmenWild

v3.0.15
- works in both 2022.6 and 2022.7 beta

v3.0.14
- fixes HA 2022.7.0b2 errors (seems to :) )

v3.0.13
- past graphed data did not reset at midnight local time
- missing asyncio import

v3.0.12
- graphed data for week/month/year was not ordered so the graph was messy

v3.0.11
- added timeout for solcast api server connections
- added previous 7 day graph data to the energy dashboard (only works if you are recording data)

v3.0.9
- **users upgrading from v3.0.5 or lover, need to delete the 'solcast.json' file in the HA>config directory to stop any errors**
- renamed sensors with the prefix "solcast_" to help naming sensors easier
- ** you will get double ups of the sensors in the integration because of the naming change. these will show greyed out in the list or with the values like unknown or unavailable etc.. just delete these old sensors one by one from the integration **

v3.0.6
- **users upgrading from v3.0.x need to delete the 'solcast.json' file in the HA>config directory**
- fixed lots of little bugs and problems.
- added ability to add multiple solcast accounts. Just comma seperate the api_keys in the integration config.
- remained API Counter to API Left. shows how many is remaining rather than used count.
- 'actual forecast' data is now only called once, the last api call at sunset. OR during integration install first run.
- forecast data is still called every hour between sunrise and sunset and once at midnight every day.
*Just delete the old API Counter sensor as its not used now*

v3.0.5 beta
- fixed 'this hour' amd 'next hour' sensor values.
- slow down the api polling if more than 1 rooftop to poll.
- fix first hour graph plot data.
- possibly RC1?? will see.

v3.0.4 beta
- bug fixes.

Complete re write. v3.0 now 
**Do not update this if you like the way the older version worked**
*There are many changes to this integration*

Simple setup.. just need the API key

- This is now as it should be, a 'forecast' integration (it does not graph past data *currently*)
- Forecast includes sensors for "today" and "tomorrow" total production, max hour production and time.. this hour and next production
- Forecast graph info for the next 7 days of data available

Integration contains
  - API Counter             (int)
  - API Last Polled         (date/time)
  - Forecast Next Hour      (Wh)
  - Forecast This Hour      (Wh)
  - Forecast Today          (kWh) (Attributes calculated from 'pv_estimate')
  - Forecast Tomorrow       (kWh) (Attributes calculated from 'pv_estimate')
  - Peak Forecast Today     (Wh)
  - Peak Forecast Tomorrow  (Wh)
  - Peak Time Today         (date/time)
  - Peak Time Tomorrow      (date/time)

[<img src="https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolcastService.png">](https://github.com/BJReplay/ha-solcast-solar/blob/main/.github/SCREENSHOTS/SolcastService.png)
</details>

## Credits

Modified from the great works of
* oziee/ha-solcast-solar
* @rany2 - ranygh@riseup.net
* dannerph/homeassistant-solcast
* cjtapper/solcast-py
* home-assistant-libs/forecast_solar
