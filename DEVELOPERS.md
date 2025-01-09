Hi community!

A Solcast API simulator and unit/integration tests are available for this custom integration. To set up, add these mounts to your HA dev container, adjusting for your local integration fork.

As a custom component (no simulator, no tests):

```
  "mounts": [
    "source=${localEnv:HOME}/Documents/GitHub/ha-solcast-solar/custom_components/solcast_solar,target=${containerWorkspaceFolder}/config/custom_components/solcast_solar,type=bind",
    "source=${localEnv:HOME}/Documents/GitHub/ha-solcast-solar/tests,target=${containerWorkspaceFolder}/tests/components/solcast_solar,type=bind",
  ],
```

As a core component (to run tests the integration must be mounted under core components, and this also makes the simulator available):

```
  "mounts": [
    "source=${localEnv:HOME}/Documents/GitHub/ha-solcast-solar/custom_components/solcast_solar,target=${containerWorkspaceFolder}/homeassistant/components/solcast_solar,type=bind",
    "source=${localEnv:HOME}/Documents/GitHub/ha-solcast-solar/tests,target=${containerWorkspaceFolder}/tests/components/solcast_solar,type=bind",
  ],
```

Note that should a folder called `config/custom_components/solcast_solar` exist, even if empty then the core component will not be found. This can happen if a mount to `custom_components` has been done previously, and if that's the case then remove that empty folder.

To get the simulator to work `/etc/hosts` needs to be modified to specify `127.0.0.1 localhost api.solcast.com.au` (use sudo). For a quick start, `cd tests/components/solcast_solar` and execute `python3 -u wsgi_sim.py --limit 5000 --no429`, which gets 5,000 API calls max, and no 'too busy' errors generated on the hour. (`python3 -u wsgi_sim.py --help` for options, or inspect `wsgi_sim.py` for documentation.) Note that if the integration or simulator has never been started then dependencies will not yet be installed. The simulator will `pip install` missing dependencies and also create a new self-signed certificate. /etc/hosts is inspected but not modified automatically. To avoid needing `python3 -u` make `wsgi_sim.py` executable.

The tests will show up at `tests/components/solcast_solar`. `cd` to there and execute `pytest`. To inspect logging, `pytest -o log_cli=true --log-cli-level=DEBUG`. For a test coverage report, `pytest --cov=homeassistant.components.solcast_solar --cov-report term-missing -vv`. Additional test contributions will be most welcome.
