## Bronze
- [X] `config-flow` - Integration needs to be able to be set up via the UI
    - [X] Uses `data_description` to give context to fields
    - [X] Uses `ConfigEntry.data` and `ConfigEntry.options` correctly
- [X] `test-before-configure` - Test a connection in the config flow
- [X] `unique-config-entry` - Don't allow the same device or service to be able to be set up twice
- [X] `config-flow-test-coverage` - Full test coverage for the config flow
- [X] `runtime-data` - Use ConfigEntry.runtime_data to store runtime data
- [X] `test-before-setup` - Check during integration initialization if we are able to set it up correctly
- [X] `appropriate-polling` - If it's a polling integration, set an appropriate polling interval
- [X] `entity-unique-id` - Entities have a unique ID
- [X] `has-entity-name` - Entities use has_entity_name = True
- [N/A] `entity-event-setup` - Entities event setup
- [N/A] `dependency-transparency` - Dependency transparency
- [X] `action-setup` - Service actions are registered in async_setup
- [X] `common-modules` - Place common patterns in common modules
- [X] `docs-high-level-description` - The documentation includes a high-level description of the integration brand, product, or service
- [X] `docs-installation-instructions` - The documentation provides step-by-step installation instructions for the integration, including, if needed, prerequisites
- [ ] `docs-removal-instructions` - The documentation provides removal instructions
- [X] `docs-actions` - The documentation describes the provided service actions that can be used
- [X] `brands` - Has branding assets available for the integration

## Silver
- [X] `config-entry-unloading` - Support config entry unloading
- [N/A] `log-when-unavailable` - If internet/device/service is unavailable, log once when unavailable and once when back connected
- [X] `entity-unavailable` - Mark entity unavailable if appropriate
- [X] `action-exceptions` - Service actions raise exceptions when encountering failures
- [X] `reauthentication-flow` - Reauthentication flow
- [N/A] `parallel-updates` - Set Parallel updates
- [X] `test-coverage` - Above 95% test coverage for all integration modules
- [X] `integration-owner` - Has an integration owner
- [X] `docs-installation-parameters` - The documentation describes all integration installation parameters
- [X] `docs-configuration-parameters` - The documentation describes all integration configuration options

## Gold
- [X] `entity-translations` - Entities have translated names
- [X] `entity-device-class` - Entities use device classes where possible
- [X] `devices` - The integration creates devices
- [X] `entity-category` - Entities are assigned an appropriate EntityCategory
- [X] `entity-disabled-by-default` - Integration disables less popular (or noisy) entities
- [N/A] `discovery` - Can be discovered
- [N/A] `stale-devices` - Clean up stale devices
- [X] `diagnostics` - Implements diagnostics
- [X] `exception-translations` - Exception messages are translatable
- [X] `icon-translations` - Icon translations
- [X] `reconfiguration-flow` - Integrations should have a reconfigure flow
- [N/A] `dynamic-devices` - Devices added after integration setup
- [N/A] `discovery-update-info` - Integration uses discovery info to update network information
- [X] `repair-issues` - Repair issues and repair flows are used when user intervention is needed
- [X] `docs-use-cases` - The documentation describes use cases to illustrate how this integration can be used
- [N/A] `docs-supported-devices` - The documentation describes known supported / unsupported devices
- [X] `docs-supported-functions` - The documentation describes the supported functionality, including entities, and platforms
- [X] `docs-data-update` - The documentation describes how data is updated
- [X] `docs-known-limitations` - The documentation describes known limitations of the integration (not to be confused with bugs)
- [ ] `docs-troubleshooting` - The documentation provides troubleshooting information
- [X] `docs-examples` - The documentation provides automation examples the user can use.

## Platinum
- [N/A] `async-dependency` - Dependency is async
- [N/A] `inject-websession` - The integration dependency supports passing in a websession
- [X] `strict-typing` - Strict typing

## Notes on applicability
- `entity-event-setup`: Entity event are not used by the integration, so there is nothing to set up.
- `dependency-transparency`: The integration does not utilise an externally hosted dependency.
- `log-when-unavailable`: It is not desirable to log once when the Solcast REST API is unavailable and then once more when re-connected. Each interaction is atomic, and a connection is not held open.
- `parallel-updates`: Parallel updates of local devices are not applicable given the nature of the integration.
- `discovery`: Local devices are not used, so discovery of any is irrelevant.
- `stale-devices`: A single device is created for the integration instance. There can only be one instance.
- `dynamic-devices`: A single device is created for the integration instance. There can only be one instance.
- `discovery-update-info`: Local devices are not used, so updating network information is irrelevant.
- `docs-supported-devices`: Local devices are not used, and API variability is irrelevant.
- `async-dependency`: The integration does not utilise an externally hosted dependency.
- `inject-websession`: The integration does not utilise an externally hosted dependency.
