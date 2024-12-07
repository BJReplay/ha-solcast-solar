Hi community!

A Solcast API simulator and unit tests are available for this custom integration. To set up, add these mounts to your HA dev container, adjusting for your local integration fork.

```
  "mounts": [
    "source=${localEnv:HOME}/Documents/GitHub/ha-solcast-solar/custom_components/solcast_solar,target=${containerWorkspaceFolder}/config/custom_components/solcast_solar,type=bind",
    "source=${localEnv:HOME}/Documents/GitHub/ha-solcast-solar/tests,target=${containerWorkspaceFolder}/tests/components/solcast_solar,type=bind",
  ],
```

To get the simulator to work `/etc/hosts` needs to be modified to specify `127.0.0.1 localhost api.solcast.com.au`. For a quick start, `cd config/custom_components/solcast_solar/sim` and execute `python3 -u wsgi.py --limit 5000 --no429`, which gets 5,000 API calls max, and no 'too busy' errors generated on the hour. (`python3 -u wsgi.py --help` for options, or inspect `wsgi.py` for doco.) Note that if the integration or simulator has never been started then dependencies will not yet be installed. The simulator will `pip install` missing dependencies and also create a new self-signed certificate.

The unit tests will show up at `tests/components/solcast_solar`. `cd` to there and execute `pytest`. Additional test contributions will be most welcome.
