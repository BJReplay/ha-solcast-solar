Hi community!

A Solcast API simulator and unit/integration tests are available for this custom integration. To set up, add these mounts to your HA dev container, adjusting for your local integration fork.

As a custom component (no tests):

```
  "mounts": [
    "source=${localEnv:HOME}/Documents/GitHub/ha-solcast-solar/custom_components/solcast_solar,target=${containerWorkspaceFolder}/config/custom_components/solcast_solar,type=bind"
  ],
```

Or with tests, which is preferred. Mount the integration at `config/custom_components/solcast_solar` as above and the tests at `tests/components/solcast_solar`. HA loads it from there as a custom component, next to any other custom component in `config/custom_components`. The dev container does not build `translations/en.json` from `strings.json` for a custom component, so copy any `strings.json` change to `en.json` by hand.

```
  "mounts": [
    "source=${localEnv:HOME}/Documents/GitHub/ha-solcast-solar/custom_components/solcast_solar,target=${containerWorkspaceFolder}/config/custom_components/solcast_solar,type=bind",
    "source=${localEnv:HOME}/Documents/GitHub/ha-solcast-solar/tests,target=${containerWorkspaceFolder}/tests/components/solcast_solar,type=bind"
  ],
```

Add `PYTHONPATH` to `containerEnv` in `devcontainer.json`, so that `pytest` finds the integration in `config/custom_components`.

```
  "containerEnv": {
    "PYTHONASYNCIODEBUG": "1",
    "PYTHONPATH": "${containerWorkspaceFolder}/config"
  },
```

For VS Code to find the imports as well, add the paths to `.vscode/settings.json` and restart the language server.

```
  "python.analysis.extraPaths": [
    "./config",
    "./config/custom_components"
  ],
```

Mounting a solcast_solar config folder is also recommended.

```
    "source=${localEnv:HOME}/Documents/GitHub/ha-solcast-solar-config,target=${containerWorkspaceFolder}/config/solcast_solar,type=bind"
```

Before running, set up and start the simulator, then add the integration using API key `1`, `2` or both `1, 2`.

To get the WSGI simulator to work an advanced integration option (`solcast_url`) must be set to change the API URL used (or `/etc/hosts` needs to be modified to specify `127.0.0.1 localhost api.solcast.com.au`). For a quick start, `cd tests/components/solcast_solar` and execute `python3 -u wsgi_sim.py --limit 5000`, which gets 5,000 API calls max. (`python3 -u wsgi_sim.py --help` for options, or inspect `wsgi_sim.py` for the documentation.) Note that if the integration or simulator has never been started then dependencies will not yet be installed. The simulator will `pip install` missing dependencies and also create a new self-signed certificate. To avoid needing `python3 -u` make `wsgi_sim.py` executable with `chmod +x wsgi_sim.py`.

Re-building the dev container will require `/etc/hosts` to be modified again if that approach has been used. Using the advanced option persists a re-build, and even more so if a mount of the config folder has been done.

The tests will show up at `tests/components/solcast_solar`. `cd` to there and execute `pytest -n auto` for all, or `pytest test_xxxx.py` for just one test module. To inspect logging, `pytest -o log_cli=true --log-cli-level=DEBUG [module.py ...]`. For a test coverage report, `pytest -n auto --cov=custom_components.solcast_solar --cov-report term-missing -v` using `xdist` parallelism (drop `-n auto` for a serialised run).

Adding `--dist=worksteal` will likely reduce test runtime. Also if running the dev container on Apple silicon then limiting `xdist` to `-n {performance_cores}` will likely yield consistently fast test runtime (e.g. M2 Max use `-n 8`); the Linux test environment has no way of knowing which core is a performance core, so let MacOS work it out, because `-n auto` would choose 12 worker threads and end up running tests on efficiency cores.

Additional test contributions will be most welcome. In fact, test contributions will be required if your code modifications introduce lines of code that are not properly tested by the current PyTest modules.

Present PyTest coverage of all modules is 100%. _Every_ statement of code is currently exercised, and it is expected that every circumstance is covered by a test. (This may be accomplished by extending an existing test, or by creating a new one.) This is something that should be aspired to for every pull request to this integration, and if test coverage is completely ignored and your pull request is extensive, then it will likely be rejected, even if it appears to work perfectly. (If your test does not hit PyTest 100% coverage then _someone else_ will need to code the test properly before the code is released.)

Home Assistant development standards to Platinum level is also a thing here, and non-conformance will also result in PR revisions required, or rejection. A strict type checking standard is maintained. The Home Assistant dev container incorporates much automated checking of code standards to help out, but you will likely need to add PyLance and configure type checking to strict standard. GitHub Copilot is also pretty neat at calling out inefficient or poorly constructed code, and this can also be used in the dev container.

If you're really new to Home Assistant development then to set up the dev container install VSCode, fork homeAssistant-core to your own repo, go to https://developers.home-assistant.io/docs/development_environment/ and
use the forked repo address https://github.com/{myGithubName}/homeAssistant-core/. Commits and PRs are not managed in the dev container unless you are developing core components, so use GitHub Desktop or Git command line instead for this custom component.

Welcome! Let's make this an even better integration!
