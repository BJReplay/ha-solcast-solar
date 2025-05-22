Hi community!

A Solcast API simulator and unit/integration tests are available for this custom integration. To set up, add these mounts to your HA dev container, adjusting for your local integration fork.

As a custom component (no simulator, no tests):

```
  "mounts": [
    "source=${localEnv:HOME}/Documents/GitHub/ha-solcast-solar/custom_components/solcast_solar,target=${containerWorkspaceFolder}/config/custom_components/solcast_solar,type=bind",
    "source=${localEnv:HOME}/Documents/GitHub/ha-solcast-solar/tests,target=${containerWorkspaceFolder}/tests/components/solcast_solar,type=bind",
  ],
```

As a core component (to run tests the integration must be mounted under core components):

```
  "mounts": [
    "source=${localEnv:HOME}/Documents/GitHub/ha-solcast-solar/custom_components/solcast_solar,target=${containerWorkspaceFolder}/homeassistant/components/solcast_solar,type=bind",
    "source=${localEnv:HOME}/Documents/GitHub/ha-solcast-solar/tests,target=${containerWorkspaceFolder}/tests/components/solcast_solar,type=bind",
  ],
```

Before running as core, set up and start the simulator, then add the integration as a custom component in HA and then modify the mount locations. Things are not set up to be able to add the component as core, but an already added component will use core component code on HA start once the mount is modified.

To get the simulator to work `/etc/hosts` needs to be modified to specify `127.0.0.1 localhost api.solcast.com.au` (use sudo). For a quick start, `cd tests/components/solcast_solar` and execute `python3 -u wsgi_sim.py --limit 5000 --no429`, which gets 5,000 API calls max, and no 'too busy' errors generated on the hour. (`python3 -u wsgi_sim.py --help` for options, or inspect `wsgi_sim.py` for the documentation.) Note that if the integration or simulator has never been started then dependencies will not yet be installed. The simulator will `pip install` missing dependencies and also create a new self-signed certificate. /etc/hosts is inspected for correctness but not modified automatically. To avoid needing `python3 -u` make `wsgi_sim.py` executable.

Re-building the dev container will require `/etc/hosts` to be modified again for the simulator to work.

The tests will show up at `tests/components/solcast_solar`. `cd` to there and execute `pytest` for all, or `pytest test_xxxx.py` for just one test module. To inspect logging, `pytest -o log_cli=true --log-cli-level=DEBUG [module.py ...]`. For a test coverage report, `pytest --cov=homeassistant.components.solcast_solar --cov-report term-missing -v`.

Additional test contributions will be most welcome. In fact, test contributions will be required if your code modifications introduce lines of code that are not properly tested by the current PyTest modules.

PyTest coverage of all modules is 100%. _Every_ line of code is currently exercised, and it is expected that every circumstance is covered by a test. (This may be accomplished by extending an existing test, or by creating a new one.) This is something that should be aspired to for every pull request to this integration, and if test coverage is completely ignored and your pull request is extensive, then it will likely be rejected, even if it appears to work perfectly. (If your test does not hit PyTest 100% coverage then _someone else_ will need to code the test before the code is released. And they won't like that...)

Home Assistant development standards to Platinum level is also a thing here, and non-conformance will also result in PR revisions required, or rejection. A strict type checking standard is maintained. The Home Assistant dev container incorporates much automated checking of code standards to help out, but you will likely need to add PyLance and configure type checking to strict standard. GitHub CoPilot is also pretty neat at calling out inefficient or poorly constructed code, and this can also be used in the dev container.

Welcome! Let's make this an even better integration!
