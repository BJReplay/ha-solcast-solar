# Troubleshooting FAQ

## Contents
* Q: When should I change my API key, and will this help fix problems?
* Q: I've just got **lots of 429 errors reported**, and I'm not getting forecasts.  Should I raise an issue, or continue one of the long running discussions?
* Q: I'm trying to set up (or re-set up) the integration, and **I'm getting 429 errors** and can't get any further.  What's happening?
* Solcast's API status page at [https://status.solcast.com/](https://status.solcast.com/) says that the API status is all green, but **I'm getting 429 errors**.  What should I do?
* Q: You asked for DEBUG logs to be provided when raising issues. How do I get these?
* Q: I don't understand the README, and it's too long. Can it be simplified?
* Q: Is submitting debug logging going to expose my API key or location to the world?
* Q: I get a timeout connecting to api.solcast.com.au!!! What the heck is happening? (...raises issue...)
* Q: I've just had a shiny new PV string attached to my inverter, and I've gone to Solcast, added the new rooftop site details, but it's not being included in the forecast results. What's up?
* Q: I just restored Home Assistant from backup, and when it started the Solcast integration updated the forecast! Why?
* Q: Does the integration cope with daylight savings time / Summer time transitions?
* Q: Why are certain sensors Watt, while others are Watt-hour or kilo-Watt-hour? Shouldn't these be the same? Why?
* Q: Why have my historical forecasts disappeared from the energy dashboard? I now only see 10/14 days!
* Q: I have a Solcast API limit of 50 calls. Why is the integration now limiting me to 10?
* Q: What polls to Solcast happen, when do they happen, and are they important?
* Q: A follow-up question: If I restart the integration will it use API quota?

### Q: When should I change my API key, and will this help fix problems?

Only change your API key when you think the key has been leaked publicly or somehow compromised.

Only change your API key when the Solcast service is _**HEALTHY**_ for Hobbyist users. NEVER CHANGE YOUR KEY WHEN `429` errors are occurring, because when you update the integration configuration with the new key it needs to contact the Solcast API to read site details. It will likely get a `429` error and will not be able to fully complete the configuration change.

Changing your API key will NEVER fix any problem other than resolving a compromise, like if you have posted a screen grab of your integration configuration in a discussion topic. The last six characters of the key only are logged.

### Q: I've just got lots of 429 errors reported, and I'm not getting forecasts.  Should I raise an issue, or continue one of the long running discussions?

or

### Q: I'm trying to set up (or re-set up) the integration, and I'm getting 429 errors and can't get any further.  What's happening?

or

### Solcast's API status page at [https://status.solcast.com/](https://status.solcast.com/) says that the API status is all green, but I'm getting 429 errors.  What should I do?

As the [Solcast API Status](https://status.solcast.com/) page says: **_Don't agree with what's reported here? Contact_ [them] _at [support@solcast.com](mailto:support@solcast.com?subject=Report%20Incident)._** Do note that the status page generally **doesn't report the hobbyist API status** because the information there is for **paying customers**, not you.

This integration reports 429 errors returned by the Solcast Legacy Rooftop Site API as received.  If that's what Solcast is sending us, then that's what we report.

There is nothing that the integration maintainers can do to fix this.

The vast majority of times that this has occurred is because someone (not necessarily an integration user, and not necessarily a rooftop hobbyist user) is hammering Solcast servers thousands of times an hour (or minute) with an out-of-control process.

If the Solcast team aren't yet aware of it (outside of normal Australian business hours) they may not have had a chance to respond and block that process, so as the message on their website says, please, in the first instance, politely (since you're using a free service), ask them if there are any issues, and provide them with as much information as possible.

For example:

- Last successful update 1:30pm AEST (GMT+10).
- Three failed attempts since (10 retries per attempt over a fifteen-minute period)
- 429 responses received on each call to https://api.solcast.com.au/rooftop_sites/

By the way, the 10 retries per attempt over a fifteen-minute period is exactly how the integration works.

### Q: You asked for DEBUG logs to be provided when raising issues. How do I get these?

We can't usually do anything without them, and it's almost always the first question that will be asked: "Could you provide debug logs, please?"

When set for debug you see all kinds of fascinating stuff about what's going on under the covers. In configuration.yaml:

```
 logger:
   default: warn
   logs:
     custom_components.solcast_solar: debug
```

(Make the default info/warn/whatever, as we don't care. We just want the debug goodness.)

Reviewing logs is quite simple, and can be done from the UI. Go to Settings | System | Logs, where "condensed" logs are shown by default. Select the three dots at the top right of screen and select "Show full logs".

<img width="231" height="170" alt="image" src="https://github.com/user-attachments/assets/1799752a-0bd6-4fc4-9b91-daaed9ad2f82" />

You can't filter for just the Solcast integration in the UI, so it might be a good idea to download the log and filter it by another method (for example the *nix utility `less` "&/" command, or Notepad++ with the Linefilter2 plugin.)

### Q: I don't understand the README, and it's too long. Can it be simplified?

No.

This is a complex integration, and the documentation is extensive. If you want to use some of its advanced features then you're just going to have to slow down, take a deep breath and read. Do not guess nor assume how something works.

Every word has been painstakingly reviewed to ensure clarity and flow.

If the documentation is incorrect or misleading then call it out by contributing a pull request.

### Q: Is submitting debug logging going to expose my API key or location to the world?

No.

All sensitive information, including API keys, and your home address via latitude/longitude are redacted.

### Q: I get a timeout connecting to api.solcast.com.au!!! What the heck is happening? (...raises issue...)

Honestly, it's not us, but you. Please do not raise an issue.

This kind of thing can cause you to tear your hair out, but we might be able to put it back. A timeout is a timeout. We got nothing, so we timeout. Period. We got nothing, so we can't go on. But...

You _have_ to check your networking. It may seem right, but it's not. It may seem solid but...

Try a `curl` from your Home Assistant server first. (This will not use up API call quota.)

```
curl -X GET -H 'content-type: application/json' https://api.solcast.com.au/rooftop_sites?api_key=YOURAPIKEYHERE
```

Do you get an instant, and pleasing response of your sites data? (Or even a 429/Solcast too busy) Then, great! Move on. Because more networking bear traps can be laid... It is possible for the command line `curl` to receive an IPv4 address, and not the address that Home Assistant actually gets from making the same DNS query.

WT?

Check for IPv6 weirdness. Is IPv6 enabled in Home Assistant? If yes, then triple check that HA can _actually_ talk IPv6 to the Internet...  If in doubt, then disable IPv6 in the HA network config. Or triple check your **router** config. This IPv6 stuff is new and scary, but please get your head around it, or disable it if you don't get it.

If that's not the problem, and `curl` works, then I've got nothing without knowing more. But it's a network issue... Try a more generic networking issue Google search relating to Home Assistant.

### Q: I've just had a shiny new PV string attached to my inverter, and I've gone to Solcast, added the new rooftop site details, but it's not being included in the forecast results. What's up?

There is almost certainly a simple fix.

The integration loads a list of all rooftop sites from Solcast on startup. It does not attempt to load these until another startup, because that would just add API load to the Solcast service. They don't like that, and tend to respond with `429/Too busy` responses when heaps of calls come in from hobbyists, so we like to keep the number of calls to just the essential, and not do a 'get sites' call at every forecast update fetch.

Restart the integration, and your new rooftop will almost certainly be found.

But... Potentially further complicating things for you, it is just possible that a restart will not load the new site details. Should a `429/Too busy` be hit at precisely the same moment that you restart to load the new site then the integration will move on, preferring to load cached sites instead. The logs are your friend here, because a `429` gets logged as a warning to tell you that this has happened.

Ugh. Be patient, and persistent if needed.

Restarting near an on-the-fifteen-minute boundary of the hour particularly in the European morning could be to blame. So try, and try again. It will pick up the new site eventually (but only when restarted).

### Q: I just restored Home Assistant from backup, and when it started the Solcast integration updated the forecast! Why?

Auto-update is enabled. The backup that you restored from was prior to the last auto update.

The integration records the date and time of the latest update attempt in `solcast.json`. On start, it calculates the auto-update intervals, plus the date and time of the most recent auto-update. It then compares the most recent auto-update time with that recorded in `solcast.json`, and if the forecast cache is out of date, or "stale" then it will do a forecast update.

It has no way of knowing that you have restored from backup.
 
This is an unusual situation to arise, so we have no plans to alter the integration behaviour. At worst, there will be one instance of API quota exhaustion on update for the day before the next UTC midnight reset of the used count happens.

As an aside, the reason that it does this check is to cover a far more likely scenario. Re-starting Home Assistant.

If HA gets restarted _just before_ a scheduled auto-update is going to happen then that update will be cancelled. If the check for stale forecast data were not done on start then that update would be missed entirely.

So short-term pain on restore from backup. Long-term gain on having auto-update operate reliably for you.

Don't like the behaviour? Send feedback in a discussion, and revert to using an HA automation to update the forecast.

### Q: Does the integration cope with daylight savings / Summer / Winter time transitions?

It does.

If it is logging odd things for you in debug level logs, and you're getting multiple "Sunday" forecasts (if that's your day of transition) then you need to upgrade to at least v4.2.5.

The transition to daylight time results in Solcast varying the number of half-hourly forecast intervals for the day of transition. When transitioning to daylight time there will be only 46 intervals, and not the usual 48. This is because 2AM will no longer exist for that day. When transitioning from daylight time we get a sleep-in, and there are two 2AMs and a total of 50 intervals.

The integration was messing up the UTC time of period start and end, and using a fixed number of 48 intervals. Now it does not.

More recently "Winter time" transition support was added for Ireland (their Summer period is considered "standard" time, and the net time shift is the same, but this gets treated differently by Python code, which the integration is written in).

### Q: Why are certain sensors Watt, while others are Watt-hour or kilo-Watt-hour? Shouldn't these be the same? Why?

The power sensors, with a unit of measurement of Watt represent an instantaneous forecast power at a point in time. Given Solcast forecasts in half-hourly increments these can be thought of as an average power that is expected to be generated for a period (or the value expected half way through each interval).

All values received from Solcast are instantaneous power, or Watts.

The values for Watt-hour/kWh are calculated by the integration from the power numbers, and are power over time, or energy. An example of this is expected solar production for the remainder of the day. For these, the period averages are summed, and then divided by two because the unit is for a whole hour, yet intervals are half-hourly. For some of these, like remaining for the day, a portion of the calculated first period is used because some sensors are updated every five minutes.

@ProphetOfDoom drew up a great annotated representation of an actual forecast chart overlaid with the underlying values that had been received from Solcast.

![image](https://github.com/BJReplay/ha-solcast-solar/assets/37229860/3a42c215-15c0-4285-a6ba-980352554e9e)

### Q: Why have my historical forecasts disappeared from the energy dashboard? I now only see 10/14 days!

At some point, your /config/solcast_solar/solcast.json file has gone missing, and was recreated. This contains the history.

First ask yourself, what use are historic forecasts to me anyway? A dashed line that extends back as far as since this integration was first installed is really only visually pleasing, and not really of value.

What temperature was forecast on the 3rd of December 2021, and was it right? Who cares? We know the actual answer now. Solcast would care about improving forecast accuracy, but I'm pretty sure they would not use history to do so. They would compare the predictions of present and proposed forecast models against actuals over time.

The "good" news is that these forecasts will be retained for a couple of years from here on, so your dashed line will get longer, even if it is of almost zero value.

Or do you really want to fix it?

I hope you have a backup from the day when the history vanished. You do back up, right?

The fix involves "merging" the contents of two solcast.json files, which is not as simple as just concatenating the files.

Inside the json structure there is a `forecasts` key for each rooftop site, which holds an array. What you need to do is get the older values from backup for this array, and _carefully_ (making sure there is the required comma between array elements) insert these forecast elements into the current file. Do this for each rooftop ID, then restart the Solcast integration. (Having duplicates of the timestamped entries won't hurt anything, and they will be cleaned up.) _Please, take a backup of `solcast.json` before attempting this..._

### Q: I have a Solcast API limit of 50 calls. Why is the integration now limiting me to 10?

Solcast removed an API call to get API quota usage, so the answer is because _**you**_ told it to.

To answer a question with a question, is the API quota set correctly in the integration configuration? If not, then set it to 50 or as appropriate, given you may be using calls for estimated actuals or forced updates as well.

### Q: What polls to Solcast happen, when do they happen, and are they important?

When the integration starts for the very first time, several important things happen, and these involve Solcast API calls that are generally metered. Continued use of API calls also occurs.

This FAQ post is way longer than it should be for a mere _three_ API calls, but there be nuances depending on circumstance. The TL>DR? Getting sites data does not use API call quota. Getting a forecast, or a set of estimated actuals does.

1. The rooftop sites information is gathered for each of the solcast API keys specified.

This is **super** important information, and the integration _cannot function_ with out this. The return includes the rooftop ID(s), which are used in subsequent calls, plus other data that isn't used except for populating sensor attributes, like location, azimuth and panel tilt.

This call happens when you are first setting up the integration, and also on _every_ re-load. The "first set up" call is used to verify that your API key is good, and also that you've got sites configured. It also occurs on each load just in case you've changed settings at `solcast.com` and then re-load the integration.

For each re-load if the API call does not work for some reason, then this integration utilises a cache that will recall the data from the last successful call. If the cache doesn't exist yet or has been deleted then the integration won't work, and it will continuously restart until this call succeeds. But do note that if this is your first attempt at setting up the integration and the call fails (i.e. Solcast not available), then you'll be hit with a "Do not pass Go" scenario, and must just follow the instruction: Try again later. You've almost certainly hit a busy API time window. It's not us. It's them... So, try again later. 😅 Five or ten minutes should do.

This call _will not_ use up any precious API call quota, no matter how many times it is called.

2. When "estimated actuals" is not yet available.

This call happens ideally once, and only for a new install or if the `solcast.json` cache file is deleted (which is an action that can be requested via Developer tools, or by directly deleting the file and re-starting).

It can also be called should the integration have been sitting disabled/failed for over a week, where past data gaps would be seen. (The estimated actuals are used to fill gaps where possible.)

This occurs for each rooftop ID, so if you have two Solcast sites defined, then _two_ calls are made.

This will use up API quota for each site defined, then on top of that usage a forecast update will occur using more quota.

3. When a forecast update is requested.

Auto-update is enabled, or an automation is created by you in Home Assistant to trigger how often solar forecasts are gathered, and when this triggers the service `solcast_solar.update_forecasts` it will update all of the rooftop IDs for all of the accounts.

This will use up API quota, and if you have two sites configured for an API key then it'll use up two calls for that key.

Should this call not be successful, then it will be re-tried ten times. (A failure almost always does not use quota. It _may_ if the failure happens due to a bug, but I can't recall that ever happening.) The retry mechanism is designed using a back-off mechanism that will retry at delays of 15, 30, 45, 60 and so on seconds, plus a random number of seconds between zero and fifteen for each retry. You'll see this activity in the log as warnings if it happens.

If all retries are exhausted, then a 429/Solcast too busy error will be logged.

But don't panic and raise an issue. It's almost certainly them, not you or us, and the next forecast acquisition will likely be successful.

4. When "estimated actuals" are updated just past midnight, or when requested to be updated using an action.

This will use up API quota for each site defined if the option to get estimated actuals is enabled. Updates occur by default within fifteen minutes of the midnight local time roll-over, or when requested by an action call.

That's all the API calls there are!

Sometimes the API gets so swamped with requests that it asks users to retry. This is the well seen HTTP 429 response where quota has not yet been reached. It's not an error as such, but more a "we heard you, but go away we're busy, try later" notification. Paying users generally never hit this. Un-paying hobbyist users sometimes often, and fair enough. I think Solcast are super generous to offer such a brilliant (but limited) service for us for free.

This integration does its level best to cooperate with Solcast, and retry in a sensible manner.

### Q: A follow-up question: If I restart the integration will it use API quota?

The integration has a cache of the last successful forecast call response data and the sites data. The sites are loaded on startup if requesting it from Solcast fails. Then the forecast history loads. This does not use API quota. Forecast is only requested, and API usage incremented when auto-update fetches, or _you_ ask the integration to do so, normally with an automation.

So the answer is definitely no. But this becomes a definite maybe as of v4.2.5.

If you have auto-update enabled in v4.2.5+ then some strange things can seem to happen. If you restored Home Assistant from a backup that pre-dated the last auto fetch then the integration will initiate a fetch because stale data. API call(s) used.

And if you re-started HA immediately before an auto-update was scheduled to fire then that update will fire on integration start. API call(s) will be used, but they would have been used anyway, just weren't previously.

So depending on circumstance, the v4.2.5+ answer is possibly, but probably not.

And a final "what the???" API use scenario: If the integration had been in a failed state that has caused forecast history to be aged out beyond one week then "estimated actuals" will be retrieved from Solcast to cover the gap. This is done to support integration scenarios that rely on recent history, so API calls will be used to get history, and a fresh forecast. (But this will likely not be an issue as the integration has not been running and using quota for forecast updates...)

That is _way_ too many words to describe that lot, but I trust it has explained every scenario.