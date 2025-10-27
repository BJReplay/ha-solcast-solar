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

Changes to this file will be detected in near-real time, changing code behaviour. Application of changed behaviour may only be seen at forecast or estimated actuals update, or possibly immediately should "reload_on_advanced_change" be set to `true`.

The impact will vary by advanced option, and the reader is left to decide when the outcome should occur; this is advanced, and _you_ are advanced...

Support for these advanced options will be limited. (Well, "support" for this integration is limited at the best of times. You expect, yet do not pay us, even though there are channels available, and we sometimes respond in kind by ignoring you. Yet, we endeavour not to.)

Understand the implication of setting any of these options before raising any issue, and check set values for 'sanity', and clearly outline the issue faced in detail. (These advanced options are advanced, and modify otherwise predictable behaviour. When your behaviour is no longer predictable then **make sure it is stated well in any issue report**. Or a crystal ball will be required, which will likely not go well.)

Value 'sanity checking' is almost non-existent for this feature. Aside from "is it the expected type" it is as dumb as a bagful of hammers, and will set a 'hammer' of your own making in place to club you forcefully. Do not report in this circumstance. You broke it. You fix your file. No negative values. No 'stupid' settings. What is set generally gets directly injected...

## Contents

1. [Automated dampening](#automated-dampening)
1. [General](#general)

## Automated dampening

**Key: "automated_dampening_delta_adjustment_model"**

Possible values: integer 0 (default 0)

This option presently does nothing. It is reserved to accommodate the addition of alternatives to the present delta logarithmic adjustment of dampening factors where forecast deviates from matching past intervals.

**Key: "automated_dampening_insignificant_factor"**

Possible values: float 0.0-1.0 (default 0.95)

Dampening values modelled as higher than a certain threshold are ignored as insignificant.

**Key: "automated_dampening_minimum_matching_intervals"**

Possible values: integer 1-model_days (default 2)

Dampening modelling will skip intervals where there are a low number of matching past intervals. A low number of matches are generally seen at the beginning and end of each day, and these are ignored by default.

**Key: "automated_dampening_model_days"**

Possible values: integer 0-21 (default 14)

The number of days of past estimated actual generation to use for modelling future dampening.

**Key: "automated_dampening_no_delta_corrections"**

Possible values: boolean true/false (default false)

If delta logarithmic adjustment of dampening factors is not desired then this option may be set to true.

## General

**Key: "reload_on_advanced_change"**

Possible values: boolean true/false (default false)

Setting this option to true will cause the integration to reload whenever any advanced option is added or changed.