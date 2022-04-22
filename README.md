# hayaml - Manage Home Assistant integrations through the config file

This is a custom component for Home Assistant that lets you set up integrations in your config file that would otherwise require you to set them up through the UI.

The Home Assistant developers have [decided](https://www.home-assistant.io/blog/2020/04/14/the-future-of-yaml/) to remove support from using YAML to configure many types of integrations. This component reintroduces support for setting up these integrations by calling the same methods that the Home Assistant front end does when setting up an integration, and supplying it with the answers it expects - instead of prompting the user to fill in the details, it populates them directly from the config file. It follows a "declarative" configuration scheme, where you tell hayaml how you want Home Assistant to be configured, and it does its best make that happen.

Once enabled, it will:
* Enable integrations that you define
* Remove integrations when you remove them from the configuration
* Automatically remove and recreate integrations if the desired configuration changes

## Caveats

This whole thing is very experimental - it uses parts of the Home Assistant API that custom components aren't expected to call, which might change without warning. I make no promises that this will work at all for you, or that it will keep working with future Home Assistant updates. Integrations that require OAuth are untested are very unlikely to work.

## Configuration

Add the component to your `custom_components` directory, then add to your `configuration.yaml` file:

```
hayaml:
  integrations:
    - platform: ...
      configuration_id: ...
      answers:
        ...
      options:
        ...
```

| key | type | description |
| --- | ---- | ---- |
| `integrations` | List of [integration](#integration) | List of integrations to configure |

### <a name="integration"></a>`integration` objects

| key | type | description |
| --- | --- | --- |
| `platform` | string | Platform to configure, eg `unifi`, `broadlink`. Required. |
| `configuration_id` | string | A unique ID used to keep track of which configurations were added or removed. Doesn't matter what it is, as long as it is unique. Required. |
| `answers` | dict | Answers to provide when setting up the configuration. If these change, the integration will be removed and recreated with the new options. See [below](#answers) for tips on figuring out the required values for your integration. Required. |
| `options` | dict | Some integrations allow you to adjust some settings after they are set up (the "Configure" button on the integration list) - set the desired values for these options here. Any value not set will be left unchanged. Optional. |

Hayaml keeps track of which `configuration_id`s it has already created, and what answers were provided when it did so. Once Home Assistant has started, hayaml will check each platform definition in turn and:
* If the `configuration_id` hasn't been seen before, enable the integration.
* If the `configuration_id` has been seen before, but with a different configuration, delete the integration and re-enable it with the new config.
* For any `configuration_id`s that are no longer present in the configuration file are deleted.
* Update the `options` to match (if supported by the integration)

### <a name="answers"></a>Finding the right answers

Each integration requires a different set of `answers`, and supports different `options`. It can be a little tricky to work out what values are required - I'm trying to figure out a way to document these automatically, but in the mean time, try these:

#### Read the code

The rules for setting up an integration are defined in the `config_flow.py` file for the component. Look for a class that subclasses `ConfigFlow`, and find its `async_step_user` function. `async_step_user` will make calls to `async_show_form` (possibly via other functions) with a schema to ask for input from the user. Keep in mind that the setup process might involve multiple steps - find the schema for each step and merge the fields together to come up with the complete list of answers to provide.

Options can be found in a similar process by looking for a class that subclasses `OptionsFlow`, and following the logic from its `async_step_init` function.

For example, the [unifi integration](https://github.com/home-assistant/core/blob/80653463bfcbe29410c95f77f3ae0ceba3c067e8/homeassistant/components/unifi/config_flow.py) shows one screen that [prompts for](https://github.com/home-assistant/core/blob/80653463bfcbe29410c95f77f3ae0ceba3c067e8/homeassistant/components/unifi/config_flow.py#L131-L145) the `host`, `username`, `password`, `port` and `verify_ssl` options, then a second screen that [prompts for](https://github.com/home-assistant/core/blob/80653463bfcbe29410c95f77f3ae0ceba3c067e8/homeassistant/components/unifi/config_flow.py#L187-L193) the `site` (but only if more than one site is configured on the controller). Therefore, the complete list of answers for the `unifi` integration is:

| key | required |
| --- | --- |
| `host` | yes |
| `username` | yes |
| `password` | yes |
| `port` | no |
| `verify_ssl` | no |
| `site` | no |

Similarly, it provides lots of [options](https://github.com/home-assistant/core/blob/80653463bfcbe29410c95f77f3ae0ceba3c067e8/homeassistant/components/unifi/config_flow.py#L248):
* `track_client`
* `track_devices`
* `block_client`
* `ssid_filter`
* `detection_time`
* `ignore_wired_bug`
* `block_client`
* `poe_clients`
* `dpi_restrictions`
* `allow_bandwidth_sensors`
* `allow_uptime_sensors`

#### Try it and see

If you are missing a required config option, hayaml will return an error when setting up the integration like:

```
ERROR (MainThread) [custom_components.hayaml] Schema error while updating component unifi - required key not provided @ data['username']. Check that your configuration can match {'host': <class 'str'>, 'username': <class 'str'>, 'password': <class 'str'>, 'port': <class 'int'>, 'verify_ssl': <class 'bool'>}
```

This _might_ give you some hints about what values you are missing

## Troubleshooting

### `Integration <X> already configured for given parameters, but not present in lock file`

This usually indicates that you've set up an integration through the Home Assistant dashboard, and are now trying to create it again using hayaml. Delete the integration through the UI and try again.