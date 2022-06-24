# prometheus-shelly-exporter
Prometheus Exporter for Shelly devices

**If you want support for another device, or metrics for an existing device are missing,
please open an issue or PR.**
I only implemented for the devices I personally have.

## Help
```
usage: shelly_exporter.py [-h] [-l LISTEN_IP] [-p LISTEN_PORT]
                          [-s STATIC_TARGETS] [-U USERNAME] [-P PASSWORD]
                          [-t TIMEOUT] [-f METRICSFILE]

Prometheus Exporter for Shelly devices.

This exporter will scrape the API endpoints of Shelly devices.
Device-specific metrics are auto-discovered based on the 'type' value of the '/shelly' endpoint.

2 endpoints are provided:
  * The '/probe' endpoint will do a single scrape of the target specified
    with the 'target' URL parameter.
    'username' and 'password' parameters can optionally be added if authentication is required.
    If 'safe' parameter is set to 'true', metrics will aditionally be safed and included in the
    results of the '/metrics' endpoint (Use-case are battery-powered devices that are in sleep mode
    most of the time and wake up to push metrics. Configure /probe URL as URL to push updates to on
    the battery-powered device).
  * The '/metrics' endpoint will scrape all devices specified at startup
    with the '-s|--static-targets' option, and those saved from the '/probe' endpoint.
    Other relevant flags are '-U|--username' and '-P|--password'.

options:
  -h, --help            show this help message and exit
  -l LISTEN_IP, --listen-ip LISTEN_IP
                        IP address for the exporter to listen on. Default:
                        0.0.0.0
  -p LISTEN_PORT, --listen-port LISTEN_PORT
                        Port for the exporter to listen on. Default: 9686
  -s STATIC_TARGETS, --static-targets STATIC_TARGETS
                        Comma-separated list of static targets to scrape when
                        querying /metrics
  -U USERNAME, --username USERNAME
                        Username for the static targets (same for all)
  -P PASSWORD, --password PASSWORD
                        Password for the static targets (same for all)
  -t TIMEOUT, --timeout TIMEOUT
                        Timeout (in seconds) to use when Scraping shelly
                        devices. Default: 5
  -f METRICSFILE, --metricsfile METRICSFILE
                        Pickle file to save metrics too (from
                        /probe?safe=true). Default: metrics.pkl

All parameters can be supplied as env vars in 'SHELLY_<LONG_ARG>' form (e.g. 'SHELLY_LISTEN_PORT')
```
