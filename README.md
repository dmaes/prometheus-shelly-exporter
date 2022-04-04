# prometheus-shelly-exporter
Prometheus Exporter for Shelly devices

**If you want support for another device, or metrics for an existing device are missing,
please open an issue or PR.**
I only implemented for the devices I personally have.

## Help
```
usage: shelly_exporter.py [-h] [-l ADDR] [-p PORT] [-s [STATICS ...]]
                          [-U USERNAME] [-P PASSWORD]

Prometheus Exporter for Shelly devices.

This exporter will scrape the API endpoints of Shelly devices.
Device-specific metrics are auto-discovered based on the 'type' value of the '/shelly' endpoint.

2 endpoints are provided:
  * The '/probe' endpoint will do a single scrape of the target specified
    with the 'target' URL parameter.
    'username' and 'password' parameters can optionally be added if authentication is required.
  * The '/metrics' endpoint will scrape all devices specified at startup
    with the '-s|--static-targets' option.
    Other relevant flags are '-U|--username' and '-P|--password'.

options:
  -h, --help            show this help message and exit
  -l ADDR, --listen-ip ADDR
                        IP address for the exporter to listen on. Default:
                        0.0.0.0
  -p PORT, --listen-port PORT
                        Port for the exporter to listen on. Default: 9686
  -s [STATICS ...], --static-targets [STATICS ...]
                        List of static targets to scrape when querying
                        /metrics
  -U USERNAME, --username USERNAME
                        Username for the static targets (same for all)
  -P PASSWORD, --password PASSWORD
                        Password for the static targets (same for all)
```
