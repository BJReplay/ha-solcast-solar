# Advanced options

It is possible to alter the behaviour of some integration functions by creating a file called `solcast-advanced.json` in the Home Assistant configuration directory.

This file has a JSON structure of a dictionary containing key/value pairs.

Example:

```
{
    "option_key_one": value,
    "option_key_two": value
}
```

Changes to this file will be detected in near-real time, changing code behaviour. The impact of that changed behaviour may only be seen at forecast or estimated actuals update. For other changes, setting `reload_on_advanced_change` can be set to `true` (see below), so that things like dampening modelling and entity set up can occur on reload.

The impact of not restarting will vary by advanced option, and you are left to decide when the outcome should occur; this is advanced, and _you_ are expected to be advanced about option application. If you're unsure then just set `reload_on_advanced_change` while testing.

Support for these advanced options will be limited. (Well, "support" for this integration is limited at the best of times. You expect it, yet we are not obliged to provide it; we endeavour to.)

Understand the implication of setting any of these options before reporting any problem, and check that set values are sensible, and if you then need to seek help, clearly outline any problem faced in detail in a discussion. Any value set is logged at `DEBUG` level, so please include that detail.

These options modify otherwise predictable and well-tested behaviour, so you are wandering into poorly tested/test-it-yourself territory, where enabling `DEBUG` logging will likely be essential to see what's going on.

Values are validated for individual sanity, however it is possible to set multiple option values together in an inappropriate way. Do not raise a problem report in this circumstance. You broke it. You fix your config, or revert to defaults and reload, or raise a discussion topic instead.

You are free to raise an issue should a code exception occur after setting an advanced option, and `DEBUG` logging is _mandatory_ in this circumstance. Exceptions should not happen, and there will be no exception to requiring `DEBUG` logs in a raised issue.

## Contents

1. [Automated dampening](#automated-dampening)
1. [Estimated actuals](#estimated-actuals)
1. [Forecasts](#forecasts)
1. [General](#general)

## Automated dampening

**Key: "automated_dampening_delta_adjustment_model"**

Possible values: integer `0` (default `0`)

This option presently does nothing. It is reserved to accommodate the addition of alternatives to the present delta logarithmic adjustment of dampening factors where forecast deviates from matching past intervals.

**Key: "automated_dampening_generation_history_load_days"**

Possible values: integer `1`..`21` (default `7`)

By default, the integration assumes that there will not be generation history available beyond seven days. If Home Assistant is configured with `purge_keep_days` of a longer period for `recorder`, then this option may be used to accelerate the time to accuracy for automated dampening results.

This history load occurs when there is no `solcast-generation.json` present. An integration reload is required after deleting the generation cache file.

**Key: "automated_dampening_ignore_intervals"**

Possible values: list of strings as "HH:MM" (default `[]`)

Certain intervals of the day can be set to be ignored by dampening, at times when there is no possibility of shading.

A possible use case is to avoid situations where there are many matching estimated actual intervals and a small number of lower older generation intervals that lack an export limiting flag. This can only occur when `automated_dampening_no_limiting_consistency` is set to `true`, and may be seen as days get longer towards Summer.

Double quotes are valid JSON format (single quotes are not). Times are specified in local time zone, and must match the format "HH:MM" with one or two digit hour and a minute of either "00" or "30", and be unique in the list.

An example list: `["12:00", "12:30", "13:00", "13:30", "14:00", "14:30", "15:00"]`

**Key: "automated_dampening_insignificant_factor"**

Possible values: float `0.0`..`1.0` (default `0.95`)

Dampening values modelled as higher than a certain threshold are ignored as insignificant.

**Key: "automated_dampening_insignificant_factor_adjusted"**

Possible values: float `0.0`..`1.0` (default `0.95`)

Dampening values adjusted by delta adjustment as higher than a certain threshold are ignored as insignificant.

**Key: "automated_dampening_minimum_matching_generation"**

Possible values: integer `1`..`21` (default `2`)

Dampening modelling will skip intervals where there are a low number of matching generation samples for intervals. This is defaulted at two to get a "peak" generation value, but a value of one is also allowed for experimentation.

Do not set this value higher than the number of past days considered for automated dampening.

**Key: "automated_dampening_minimum_matching_intervals"**

Possible values: integer `1`..`21` (default `2`)

Dampening modelling will skip intervals where there are a low number of matching past intervals. A low number of matches are generally seen at the beginning and end of each day, and these are ignored by default.

Do not set this value higher than the number of past days considered for automated dampening.

**Key: "automated_dampening_model_days"**

Possible values: integer `2`..`21` (default `14`)

The number of days of past estimated actual and generation to use for modelling future dampening.

**Key: "automated_dampening_no_delta_corrections"**

Possible values: boolean `true`/`false` (default `false`)

If delta logarithmic adjustment of dampening factors is not desired then this option may be set to `true`.

**Key: "automated_dampening_no_limiting_consistency"**

Possible values: boolean `true`/`false` (default `false`)

Whenever export limiting of generation is seen (either by export limit detection, or manual limiting by using the entity `solcast_suppress_auto_dampening`) then all intervals of generation will be ignored over the period defined by "automated_dampening_model_days", which is `14` by default.

Said another way, if there is limiting detected for any interval on any day, then that interval will be ignored for every day of the past fourteen days.

Set this option to `true` to prevent this behaviour.

**Key: "automated_dampening_similar_peak"**

Possible values: float `0.0`..`1.0` (default `0.9`)

Estimated actual peaks are compared to find a similar number of "matching" peaks from which to compare maximum generation. By default this is intervals within 0.9 * peak that are considered.

This setting is variable by using this option.

## Estimated actuals

**Key: "estimated_actuals_fetch_delay"**

Possible values: int `0`..`120` (default `0`)

A number of minutes to delay beyond midnight before estimated actuals are retrieved (in addition to a randomised up-to fifteen minute delay). This may be of use should the retrieval of estimated actuals often fail just after midnight local time.

If automated dampening is enabled then modelling of new dampening factors will occur immediately following retrieval.

If Home Assistant is restarted in the period between midnight and estimated actuals being retrieved then retrieval will be rescheduled.

## Forecasts

**Key: "forecast_day_entities"**

Possible values: integer `8`..`14` (default `8`)

The number of forecast day entities to create (plus one). By default seven entities are created. Today, tomorrow, day 3, day 4, day 5, day 6 and day 7. This option enables creation of up to a day 13 entity.

An integration reload is required to vary the number of entities. New entities created will be disabled by default, and if this option is reduced then entities will be cleaned up.

**Key: "forecast_future_days"**

Possible values: integer `8`..`14` (default `14`)

The number of days of forecasts to request from Solcast. Setting this lower than 14 will not remove forecasts already retrieved.

**Key: "forecast_history_max_days"**

Possible values: integer `22`..`3650` (default `730`)

The number of days of history to retain for forecasts (and estimated actuals).

There may be a performance implication when too much history data is retained, depending on the platform used for Home Assistant.

## General

**Key: "entity_logging"**

Possible values: boolean `true`/`false` (default `false`)

By default the value set in entities is not logged. This option enables that at `DEBUG` level.

An integration reload is required.

**Key: "reload_on_advanced_change"**

Possible values: boolean `true`/`false` (default `false`)

Setting this option to `true` will cause the integration to reload whenever any advanced option is added or changed.

**Key: "solcast_url"**

Possible values: string URL (default `"https://api.solcast.com.au"`)

Do not set this option unless you are a developer and want to utilise the Solcast API Simulator.

Do not add a trailing `/`. An integration reload is required.
