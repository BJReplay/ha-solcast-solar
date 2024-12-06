Hi community!

A Solcast API simulator and unit tests are available for this custom integration. To set up for both, add these mounts to your HA dev container, adjusting for your local integration fork.

```
  "mounts": [
    "source=${localEnv:HOME}/Documents/GitHub/ha-solcast-solar/custom_components/solcast_solar,target=${containerWorkspaceFolder}/config/custom_components/solcast_solar,type=bind",
    "source=${localEnv:HOME}/Documents/GitHub/ha-solcast-solar/tests,target=${containerWorkspaceFolder}/tests/components/solcast_solar,type=bind",
    "source=${localEnv:HOME}/Documents/GitHub/ha-solcast-solar/sim,target=${containerWorkspaceFolder}/config/custom_components/solcast_solar/sim,type=bind"
  ],
```

To get the simulator to work, the container will need a `pip install flask`, along with modifying `/etc/hosts` to specify `127.0.0.1 localhost api.solcast.com.au`. For a quick start, `cd config/custom_components/solcast_solar/sim` and execute `python3 -u wsgi.py --limit 5000 --no429`, which gets 5,000 API calls max, and no 'too busy' errors generated on the hour. (`python3 -u wsgi.py --help` for options, or inspect `wsgi.py` for doco.) Note that if the integration has never been started in your dev container then dependencies like `isodate` will not yet be installed. Do start the dev container once before trying to execute the simulator, or `pip install` the missing dependencies.

The unit tests will show up at `tests/components/solcast_solar`. `cd` to there and execute `pytest`. Additional test contributions will be most welcome.
