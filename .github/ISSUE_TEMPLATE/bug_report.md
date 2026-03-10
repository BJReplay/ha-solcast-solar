---
name: Bug report
about: Create an issue  when you think you've found a bug in the Solcast integration
title: ''
labels: ''
assignees: ''

---
### Help us help you.

#### Do not create issues for questions on how to use or set up this integration.

Use the discussions for general support.  Only create issues to report geniune suspected bugs in the integration.

#### This issue template requests debug logs.  Please provide them.

Please don't provide just screenshots of logs (they're hard to read), or say "_logs look clean_" or assume they're not needed.  This integration works extremely well except when it fails, and when it fails, unless debug logs are provided - as ` ```back-ticked text``` `, or attachments - our chances of working out why it has failed are close to zero.

Note the instructions for getting debug logs, and follow them.

If you fail  to provide debug logs, you're providing us with permission to ignore you, or, at best, for us to say **_debug logs required_**, and then ignore you until you provide debug logs.

By being lazy and not bothering to fill in **all** of the data requested for an issue (such as the version of the integration you're running, or the type of home assistant installation you're running), you're encouraging us to be lazy and not bother responding.

#### Fill in **all** of the data requested.

Feel free to delete everything above this line.

---

## Describe the bug

A clear and concise description of what the bug is.

## To Reproduce

Steps to reproduce the behaviour:

1. Go to '...'
2. Click on '....'
3. Scroll down to '....'
4. See error

## Expected behaviour

A clear and concise description of what you expected to happen.

## Screenshots

If applicable, add screenshots to help explain your problem.

## AI

I confirm:

- [ ] I have **not used AI** to generate any Home Assistant configuration, automations, or custom components related to this issue, and I believe this is a bug in the Solcast integration itself
- [ ] I **have used AI** but have **read the documentation before raising this issue** and can confirm that the problem is not caused by AI‑generated Home Assistant configuration, automations, or custom components
- [ ] I have included **debug** logs for any AI related issues.

## Logs

I confirm:

- [ ] I have attached **debug** logs
- [ ] I have embedded **debug** logs in the issue description (enclosed in tick marks ``` for proper formatting)
- [ ] Confirmed **debug** logs are not required for this issue

Make sure you include logs from HA listing the output from the Solcast integration showing the error - this is particularly useful in debugging issues and helping to determine whether the issue is with the integration or the Solcast service

To add detailed debug information, add the following to your configuration.yaml and restart HA:

``` yaml
logger:
  default: warn
  logs:
    custom_components.solcast_solar: debug
```

To inspect and collect debug logs examine `/config/home-assistant.log` using File Editor or Visual Studio Code Server.

If you are using docker, it sometimes can be easier to gather logs using `docker compose logs -n 500 -f homeassistant` or similar

## Solcast Integration Version

- Integration Version [e.g. 4.0.29]

## Home Assistant Environment

- Home Assistant Version [e.g. 2026.0]
- Installation method [e.g. Home Assistant OS / Docker / HA Green]
- Home Assistant Core Version [e.g. 2026.3.1]
- Home Assistant Supervisor Version [e.g. 2026.02.3]
- Operating System [e.g. HAOS 17.1 / Linux Ubuntu 24.03]
- Home Assistant Frontend Version [e.g. 20260304.0]

### Desktop (please complete the following information if you encounter the error on your desktop / PC)

- OS and Version: [e.g. Windows 11, macOS 14, Ubuntu 24.04]
- Browser and Version [e.g. chrome 145.0.7632.160 (Official Build) (64-bit), safari]

### Smartphone (please complete the following information if you encounter the error on your phone)

- Device: [e.g. iPhone6]
- OS: [e.g. iOS8.1]
- Browser [e.g. stock browser, safari]
- Version [e.g. 22]

## Additional context

Add any other context about the problem here.
