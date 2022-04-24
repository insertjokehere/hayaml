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
| `answers` | list of dict | Answers to provide for each step when setting up the configuration. If these change, the integration will be removed and recreated with the new options. See [below](#answers) for tips on figuring out the required values for your integration. Required. |
| `options` | list of dict | Some integrations allow you to adjust some settings after they are set up (the "Configure" button on the integration list) - set the desired values for these options here. Any value not set will be left unchanged. Optional. |
| `recreate_options` | bool | If set, will recreate the integration if the specified options change - see [below](#options) for why you might want this. Defaults to False |

Hayaml keeps track of which `configuration_id`s it has already created, and what answers were provided when it did so. Once Home Assistant has started, hayaml will check each platform definition in turn and:
* If the `configuration_id` hasn't been seen before, enable the integration.
* If the `configuration_id` has been seen before, but with a different configuration, delete the integration and re-enable it with the new config.
* If the `configuration_id` has been seen before, `options` has changed and `recreate_options` is set, delete the integration and re-enable it.
* For any `configuration_id`s that are no longer present in the configuration file are deleted.
* Update the `options` if supported by the integration and `options` has changed (or the integration was newly enabled)

### <a name="options"></a>Recreating when options change

Some integrations (like Android TV) have fairly complex configuration flows to add or remove features. In this case, you need to know what state the integration is in to write a set of answers to give to the configuration flow to get to your desired config - its easier to delete the integration and start from a known state. If you set `recreate_options`, hayaml will manage this for you.

## <a name="answers"></a>Finding the right answers

Each integration requires a different set of `answers`, and supports different `options`. It can be a little tricky to work out what values are required - I'm trying to figure out a way to document these automatically, but in the mean time, try these:

### Read the code

The rules for setting up an integration are defined in the `config_flow.py` file for the component. Look for a class that subclasses `ConfigFlow`, and find its `async_step_user` function. `async_step_user` will make calls to `async_show_form` (possibly via other functions) with a schema to ask for input from the user. Keep in mind that the setup process might involve multiple steps - find the schema for each step and add an entry for each step.

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

### Use the debug tools

Use the network tab of your browsers' developer tools to inspect the network requests being made while you set up the integration manually - the data being sent in the request is the answers for that step.

### Try it and see

If you are missing a required config option, hayaml will return an error when setting up the integration like:

```
ERROR (MainThread) [custom_components.hayaml] Schema error while updating component unifi - required key not provided @ data['username']. Check that your configuration can match {'host': <class 'str'>, 'username': <class 'str'>, 'password': <class 'str'>, 'port': <class 'int'>, 'verify_ssl': <class 'bool'>}
```

This _might_ give you some hints about what values you are missing

## Troubleshooting

### `Integration <X> already configured for given parameters, but not present in lock file`

This usually indicates that you've set up an integration through the Home Assistant dashboard, and are now trying to create it again using hayaml. Delete the integration through the UI and try again.

## Examples

### Android TV

```yaml
- platform: androidtv
  configuration_id: media_room_tv
  recreate_options: true
  answers:
    - host: 192.168.1.1
      device_class: androidtv
      port: 5555
      adbkey: "/var/secrets/adbkey/adbkey"
      name: "Media Room TV"
  options:
    - apps: NewApp
    - app_name: Netflix
      app_id: com.netflix.ninja
    - apps: NewApp
    - app_name: Steam Link
      app_id: com.valvesoftware.steamlink
    - apps: NewApp
    - app_name: Home
      app_id: com.google.android.leanbacklauncher
    - exclude_unnamed_apps: true
      get_sources: true
      screencap: true
      turn_off_command: "input keyevent 223"
      turn_on_command: "input keyevent 26"
```

### Broadlink

```yaml
- platform: "broadlink"
  configuration_id: broadlink_146
  answers:
    - host: "192.168.3.146"
    - name: "Office Broadlink"
```

### CO2 Signal

```yaml
- platform: co2signal
  configuration_id: co2signal
  answers:
    - api_key: !secret CO2_SIGNAL_API_KEY
      location: Specify country code
    - country_code: NZ
```

### ESPHome

```yaml
- configuration_id: esphome-192.168.3.148
  platform: esphome
  answers:
    - host: 192.168.3.148
      port: 6053
    - password: !secret 'ESPHOME_PASSWORD'
```

### Google Travel Time

```yaml
- platform: google_travel_time
  configuration_id: google_travel_time_work
  answers:
    - name: "Travel Time to Work"
      api_key: !secret GAPPS_API_KEY
      origin: "place_id:..."
      destination: "place_id:..."
  options:
    - mode: driving
      units: metric
```

### OpenWeatherMap

```yaml
- platform: openweathermap
  configuration_id: openweathermap
  answers:
    - name: Weather
      latitude: ...
      longitude: ...
      mode: "onecall_hourly"
      language: "en"
      api_key: !secret OPENWEATHERMAP_KEY
  options:
    - mode: "onecall_hourly"
      language: "en"
```

### Unifi

```yaml
- platform: "unifi"
  configuration_id: "unifi"
  answers:
    - host: unifi
      username: homeassistant
      password: !secret UNIFI_PASSWORD
      port: 443
      verify_ssl: true
  options:
    - ssid_filter:
        - MyWiFi
    - {}
    - {}
```